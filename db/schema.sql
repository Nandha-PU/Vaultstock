-- ============================================================================
-- VaultStock: Core Minimal Hardened Schema
-- Design: Immutable Ledger + Cryptographic Audit Chain with HMAC Binding
-- ============================================================================

-- 1. USERS: Authentication & role control
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'staff')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. PRODUCTS: Catalog definition with validation checks
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE CHECK(length(sku) BETWEEN 3 AND 32),
    name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 120),
    unit_price REAL NOT NULL CHECK(unit_price > 0 AND unit_price <= 10000000),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Product catalog immutability triggers
CREATE TRIGGER IF NOT EXISTS prevent_product_update
BEFORE UPDATE ON products
BEGIN
    SELECT RAISE(ABORT, 'SECURITY VIOLATION: Products are immutable; create a new SKU.');
END;

CREATE TRIGGER IF NOT EXISTS prevent_product_delete
BEFORE DELETE ON products
BEGIN
    SELECT RAISE(ABORT, 'SECURITY VIOLATION: Products cannot be deleted.');
END;

-- 3. MOVEMENTS: The append-only stock ledger
CREATE TABLE IF NOT EXISTS movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    type TEXT NOT NULL CHECK(type IN ('IN', 'OUT')),
    qty INTEGER NOT NULL CHECK(typeof(qty) = 'integer' AND qty BETWEEN 1 AND 1000000),
    note TEXT CHECK(note IS NULL OR length(note) <= 200),
    created_by TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Performance index for derived balance calculations & foreign key joins
CREATE INDEX IF NOT EXISTS idx_movements_product_id ON movements(product_id);

-- Negative-stock guard at the DB layer (defense-in-depth for concurrency control)
CREATE TRIGGER IF NOT EXISTS prevent_negative_stock
BEFORE INSERT ON movements
WHEN NEW.type = 'OUT'
BEGIN
    SELECT RAISE(ABORT, 'SECURITY VIOLATION: Insufficient stock.')
    WHERE (SELECT COALESCE(SUM(CASE WHEN type = 'IN' THEN qty ELSE -qty END), 0)
           FROM movements WHERE product_id = NEW.product_id) < NEW.qty;
END;

-- Movement ledger immutability triggers
CREATE TRIGGER IF NOT EXISTS prevent_movement_update
BEFORE UPDATE ON movements
BEGIN
    SELECT RAISE(ABORT, 'SECURITY VIOLATION: Ledger entries are immutable and cannot be updated.');
END;

CREATE TRIGGER IF NOT EXISTS prevent_movement_delete
BEFORE DELETE ON movements
BEGIN
    SELECT RAISE(ABORT, 'SECURITY VIOLATION: Ledger entries are immutable and cannot be deleted.');
END;

-- 4. AUDIT LOG: Cryptographically chained tamper-evident ledger
-- Bound directly to referenced table and row payload
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    ref_table TEXT,
    ref_id INTEGER,
    payload TEXT NOT NULL,
    details TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    UNIQUE(ref_table, ref_id)
);

-- Audit log immutability triggers
CREATE TRIGGER IF NOT EXISTS prevent_audit_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'SECURITY VIOLATION: Audit log is immutable.');
END;

CREATE TRIGGER IF NOT EXISTS prevent_audit_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'SECURITY VIOLATION: Audit log is immutable.');
END;
