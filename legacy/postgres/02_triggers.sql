-- ============================================================================
-- VaultStock: 02_triggers.sql
-- Database-Enforced Integrity, Advisory Locks, Ledger Immutability,
-- and Cryptographic Audit Hash Chaining (SHA-256)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. NO NEGATIVE STOCK TRIGGER WITH ADVISORY LOCKS
-- Prevents overselling / race conditions under concurrent orders.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_check_negative_stock()
RETURNS TRIGGER AS $$
DECLARE
    current_balance BIGINT;
    new_balance BIGINT;
BEGIN
    -- Take a transaction-scoped exclusive advisory lock keyed on (product_id, location_id).
    -- This guarantees concurrent transactions attempting to issue stock for the same
    -- product at the same location serialize their check and balance calculation.
    PERFORM pg_advisory_xact_lock(NEW.product_id, NEW.location_id);

    -- Calculate current balance directly from the ledger
    SELECT COALESCE(SUM(qty_delta), 0)
    INTO current_balance
    FROM stock_movements
    WHERE product_id = NEW.product_id
      AND location_id = NEW.location_id;

    new_balance := current_balance + NEW.qty_delta;

    IF new_balance < 0 THEN
        RAISE EXCEPTION 'NegativeStockException: Insufficient stock for product ID % at location ID %. Current balance: %, requested delta: %, resulting balance: %',
            NEW.product_id, NEW.location_id, current_balance, NEW.qty_delta, new_balance
            USING ERRCODE = '23514'; -- check_violation
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_stock_movements_before_insert ON stock_movements;
CREATE TRIGGER trg_stock_movements_before_insert
    BEFORE INSERT ON stock_movements
    FOR EACH ROW
    EXECUTE FUNCTION trg_check_negative_stock();

-- ----------------------------------------------------------------------------
-- 2. IMMUTABLE LEDGER TRIGGER
-- Rejects any UPDATE or DELETE on stock_movements.
-- Corrections must be recorded as compensatory reversing entries.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_prevent_ledger_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'ImmutableLedgerException: Stock ledger entries cannot be updated or deleted. Recorded movements are permanent. Create an ADJUST or reversing movement instead.'
        USING ERRCODE = '23505';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_stock_movements_immutable ON stock_movements;
CREATE TRIGGER trg_stock_movements_immutable
    BEFORE UPDATE OR DELETE ON stock_movements
    FOR EACH ROW
    EXECUTE FUNCTION trg_prevent_ledger_modification();

-- ----------------------------------------------------------------------------
-- 3. IMMUTABLE AUDIT LOG TRIGGER
-- Blocks all UPDATE or DELETE queries on the audit_log table.
-- Even database superusers cannot run ad-hoc updates without disabling the trigger.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'ImmutableAuditException: Audit log rows are cryptographically sealed and append-only. Modification or deletion is strictly forbidden.'
        USING ERRCODE = '42501';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_log;
CREATE TRIGGER trg_audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW
    EXECUTE FUNCTION trg_prevent_audit_modification();

-- ----------------------------------------------------------------------------
-- 4. HASH-CHAINED AUDIT LOG TRIGGER
-- Computes SHA-256 over (prev_hash, record details, timestamp, app.user_id)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_log_audit_event()
RETURNS TRIGGER AS $$
DECLARE
    v_user_id INT;
    v_record_id BIGINT;
    v_prev_hash VARCHAR(64);
    v_new_hash VARCHAR(64);
    v_old_val JSONB := NULL;
    v_new_val JSONB := NULL;
    v_genesis_hash CONSTANT VARCHAR(64) := '0000000000000000000000000000000000000000000000000000000000000000';
    v_payload TEXT;
    v_created_at TIMESTAMPTZ := clock_timestamp();
    v_next_id BIGINT;
BEGIN
    -- Serialize audit log inserts via advisory lock to avoid race conditions on prev_hash
    PERFORM pg_advisory_xact_lock(hashtext('vaultstock_audit_lock'));

    -- Retrieve active authenticated user set by the API layer in this transaction
    BEGIN
        v_user_id := NULLIF(current_setting('app.user_id', true), '')::INT;
    EXCEPTION WHEN OTHERS THEN
        v_user_id := NULL;
    END;

    -- Extract record ID and JSON representations
    IF TG_OP = 'INSERT' THEN
        v_record_id := NEW.id;
        v_new_val := to_jsonb(NEW);
    ELSIF TG_OP = 'UPDATE' THEN
        v_record_id := NEW.id;
        v_old_val := to_jsonb(OLD);
        v_new_val := to_jsonb(NEW);
    ELSIF TG_OP = 'DELETE' THEN
        v_record_id := OLD.id;
        v_old_val := to_jsonb(OLD);
    END IF;

    -- Fetch the previous row's hash from the chain (or genesis hash for row #1)
    SELECT row_hash
    INTO v_prev_hash
    FROM audit_log
    ORDER BY id DESC
    LIMIT 1;

    IF v_prev_hash IS NULL THEN
        v_prev_hash := v_genesis_hash;
    END IF;

    -- Determine next ID for audit_log to include deterministically in the hash
    SELECT COALESCE(max(id), 0) + 1 INTO v_next_id FROM audit_log;

    -- Construct deterministic canonical string for hashing:
    -- prev_hash | id | user_id | action | table_name | record_id | old_value | new_value | created_at
    v_payload := concat_ws('|',
        v_prev_hash,
        v_next_id,
        COALESCE(v_user_id::text, '0'),
        TG_OP,
        TG_TABLE_NAME,
        v_record_id,
        COALESCE(v_old_val::text, ''),
        COALESCE(v_new_val::text, ''),
        to_char(v_created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
    );

    -- Calculate SHA-256 digest
    v_new_hash := encode(digest(v_payload, 'sha256'), 'hex');

    -- Insert append-only audit row
    INSERT INTO audit_log (
        id,
        user_id,
        action,
        table_name,
        record_id,
        old_value,
        new_value,
        created_at,
        prev_hash,
        row_hash
    ) VALUES (
        v_next_id,
        v_user_id,
        TG_OP,
        TG_TABLE_NAME,
        v_record_id,
        v_old_val,
        v_new_val,
        v_created_at,
        v_prev_hash,
        v_new_hash
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSE
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Attach audit trigger to auditable operational tables
DROP TRIGGER IF EXISTS trg_audit_products ON products;
CREATE TRIGGER trg_audit_products
    AFTER INSERT OR UPDATE ON products
    FOR EACH ROW
    EXECUTE FUNCTION trg_log_audit_event();

DROP TRIGGER IF EXISTS trg_audit_stock_movements ON stock_movements;
CREATE TRIGGER trg_audit_stock_movements
    AFTER INSERT ON stock_movements
    FOR EACH ROW
    EXECUTE FUNCTION trg_log_audit_event();

DROP TRIGGER IF EXISTS trg_audit_users ON users;
CREATE TRIGGER trg_audit_users
    AFTER INSERT OR UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION trg_log_audit_event();

-- ----------------------------------------------------------------------------
-- 5. AUDIT CHAIN VERIFICATION FUNCTION
-- Iterates sequentially across the entire audit log, recomputing hashes.
-- Returns whether the chain is intact, or precisely where it was broken.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION verify_audit_chain()
RETURNS TABLE (
    is_valid BOOLEAN,
    broken_at_id BIGINT,
    total_verified BIGINT,
    message TEXT
) AS $$
DECLARE
    r RECORD;
    v_expected_prev VARCHAR(64) := '0000000000000000000000000000000000000000000000000000000000000000';
    v_computed_hash VARCHAR(64);
    v_payload TEXT;
    v_count BIGINT := 0;
BEGIN
    FOR r IN (SELECT * FROM audit_log ORDER BY id ASC) LOOP
        v_count := v_count + 1;

        -- 1. Check prev_hash linkage
        IF r.prev_hash <> v_expected_prev THEN
            RETURN QUERY SELECT
                FALSE,
                r.id,
                v_count,
                format('Hash chain broken at row ID %s: previous hash linkage mismatch (expected %s, found %s)',
                       r.id, v_expected_prev, r.prev_hash);
            RETURN;
        END IF;

        -- 2. Recompute the expected hash for this row
        v_payload := concat_ws('|',
            r.prev_hash,
            r.id,
            COALESCE(r.user_id::text, '0'),
            r.action,
            r.table_name,
            r.record_id,
            COALESCE(r.old_value::text, ''),
            COALESCE(r.new_value::text, ''),
            to_char(r.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
        );

        v_computed_hash := encode(digest(v_payload, 'sha256'), 'hex');

        -- 3. Verify computed hash matches stored hash
        IF r.row_hash <> v_computed_hash THEN
            RETURN QUERY SELECT
                FALSE,
                r.id,
                v_count,
                format('Hash chain corrupted at row ID %s: data tampering detected (computed %s, stored %s)',
                       r.id, v_computed_hash, r.row_hash);
            RETURN;
        END IF;

        -- Advance expected prev_hash to current row's hash
        v_expected_prev := r.row_hash;
    END LOOP;

    RETURN QUERY SELECT
        TRUE,
        NULL::BIGINT,
        v_count,
        format('Audit chain fully intact. %s row(s) cryptographically verified.', v_count);
END;
$$ LANGUAGE plpgsql;
