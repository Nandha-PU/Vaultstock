-- ============================================================================
-- VaultStock: 01_schema.sql
-- Core Schema Definition with Strict Integrity Constraints
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Clean drop for idempotency in reset script
DROP TABLE IF EXISTS audit_log CASCADE;
DROP TABLE IF EXISTS stock_movements CASCADE;
DROP TABLE IF EXISTS purchase_orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS locations CASCADE;
DROP TABLE IF EXISTS suppliers CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS roles CASCADE;

-- ----------------------------------------------------------------------------
-- 1. ROLES TABLE
-- ----------------------------------------------------------------------------
CREATE TABLE roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(32) NOT NULL UNIQUE,
    description TEXT
);

-- ----------------------------------------------------------------------------
-- 2. USERS TABLE
-- Passwords stored as salted bcrypt/argon2 hashes, never plaintext.
-- Soft delete via is_active flag to preserve audit references.
-- ----------------------------------------------------------------------------
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role_id INT NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
    full_name VARCHAR(128) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_username ON users(username);

-- ----------------------------------------------------------------------------
-- 3. SUPPLIERS TABLE
-- Contains commercially sensitive financial margins and unit costs.
-- ----------------------------------------------------------------------------
CREATE TABLE suppliers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL UNIQUE,
    contact_email VARCHAR(128) NOT NULL,
    phone VARCHAR(32),
    contract_margin NUMERIC(5, 2) NOT NULL DEFAULT 0.00 CHECK (contract_margin >= 0.00),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 4. LOCATIONS TABLE
-- Warehouses, bays, or store rooms.
-- ----------------------------------------------------------------------------
CREATE TABLE locations (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    address TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- ----------------------------------------------------------------------------
-- 5. PRODUCTS TABLE
-- Sensitive unit_cost field masked for storekeepers.
-- Soft deleted via is_active; ON DELETE RESTRICT prevents orphan historical rows.
-- ----------------------------------------------------------------------------
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    unit_cost NUMERIC(12, 2) NOT NULL CHECK (unit_cost > 0),
    reorder_level INT NOT NULL DEFAULT 10 CHECK (reorder_level >= 0),
    supplier_id INT NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_products_sku ON products(sku);
CREATE INDEX idx_products_supplier ON products(supplier_id);

-- ----------------------------------------------------------------------------
-- 6. STOCK MOVEMENTS (THE IMMUTABLE LEDGER)
-- There is NO 'quantity' column in the products table!
-- All balances are dynamically derived from this append-only ledger.
-- ----------------------------------------------------------------------------
CREATE TABLE stock_movements (
    id BIGSERIAL PRIMARY KEY,
    product_id INT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    location_id INT NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    movement_type VARCHAR(16) NOT NULL CHECK (movement_type IN ('RECEIVE', 'ISSUE', 'ADJUST')),
    qty_delta INT NOT NULL CHECK (qty_delta <> 0),
    reason TEXT,
    created_by INT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Business logic constraints:
    -- RECEIVE must add stock (positive delta)
    -- ISSUE must deduct stock (negative delta)
    -- ADJUST requires an explicit audit explanation
    CONSTRAINT chk_receive_positive CHECK (movement_type <> 'RECEIVE' OR qty_delta > 0),
    CONSTRAINT chk_issue_negative CHECK (movement_type <> 'ISSUE' OR qty_delta < 0),
    CONSTRAINT chk_adjust_reason CHECK (movement_type <> 'ADJUST' OR (reason IS NOT NULL AND length(trim(reason)) > 0))
);

CREATE INDEX idx_movements_prod_loc ON stock_movements(product_id, location_id);
CREATE INDEX idx_movements_created_at ON stock_movements(created_at);

-- ----------------------------------------------------------------------------
-- 7. PURCHASE ORDERS (Minimal KISS module)
-- ----------------------------------------------------------------------------
CREATE TABLE purchase_orders (
    id SERIAL PRIMARY KEY,
    supplier_id INT NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'RECEIVED', 'CANCELLED')),
    created_by INT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (total_amount >= 0),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 8. AUDIT LOG (THE HASH CHAIN)
-- Append-only record of every critical change.
-- row_hash = SHA256(prev_hash || id || user_id || action || table_name || record_id || old_val || new_val || created_at)
-- ----------------------------------------------------------------------------
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE RESTRICT,
    action VARCHAR(16) NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
    table_name VARCHAR(64) NOT NULL,
    record_id BIGINT NOT NULL,
    old_value JSONB,
    new_value JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    prev_hash VARCHAR(64) NOT NULL,
    row_hash VARCHAR(64) NOT NULL
);

CREATE INDEX idx_audit_log_record ON audit_log(table_name, record_id);
CREATE INDEX idx_audit_log_created_at ON audit_log(created_at);
