-- ============================================================================
-- VaultStock: Relational Inventory Management & Audit Ledger Schema
-- Design: 3NF Normalized Relational Schema + Immutable Ledger + Cryptographic Audit Chain
-- ============================================================================

-- 1. USERS: Authentication & role control
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'staff')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. CATEGORIES: Product classifications (1:N with products)
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE CHECK(length(code) BETWEEN 2 AND 16),
    name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 80),
    description TEXT CHECK(description IS NULL OR length(description) <= 255),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 3. SUPPLIERS: External vendors for stock replenishment (1:N with movements)
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE CHECK(length(trim(name)) BETWEEN 2 AND 100),
    contact_email TEXT CHECK(contact_email IS NULL OR length(contact_email) <= 120),
    phone TEXT CHECK(phone IS NULL OR length(phone) <= 30),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 4. LOCATIONS: Warehouses, storage rooms, and retail sections (1:N with movements)
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE CHECK(length(code) BETWEEN 2 AND 20),
    name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 80),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 5. PRODUCTS: Catalog definition with category references and reorder thresholds
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE CHECK(length(sku) BETWEEN 3 AND 32),
    name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 120),
    category_id INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
    unit_price REAL NOT NULL CHECK(unit_price > 0 AND unit_price <= 10000000),
    reorder_threshold INTEGER NOT NULL DEFAULT 10 CHECK(reorder_threshold >= 0 AND reorder_threshold <= 100000),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_products_category_id ON products(category_id);

-- Referential safeguard: products cannot be deleted to preserve historic ledger integrity
CREATE TRIGGER IF NOT EXISTS prevent_product_delete
BEFORE DELETE ON products
BEGIN
    SELECT RAISE(ABORT, 'SECURITY VIOLATION: Products cannot be deleted; historical ledger requires referential integrity.');
END;

-- Referential safeguard: products cannot be updated; catalog records are immutable
CREATE TRIGGER IF NOT EXISTS prevent_product_update
BEFORE UPDATE ON products
BEGIN
    SELECT RAISE(ABORT, 'SECURITY VIOLATION: Products cannot be updated; catalog records are immutable.');
END;

-- 6. MOVEMENTS: The append-only stock ledger
CREATE TABLE IF NOT EXISTS movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE RESTRICT,
    location_id INTEGER REFERENCES locations(id) ON DELETE RESTRICT,
    type TEXT NOT NULL CHECK(type IN ('IN', 'OUT')),
    qty INTEGER NOT NULL CHECK(typeof(qty) = 'integer' AND qty BETWEEN 1 AND 1000000),
    reference_doc TEXT CHECK(reference_doc IS NULL OR length(reference_doc) <= 60),
    note TEXT CHECK(note IS NULL OR length(note) <= 200),
    created_by TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Performance indexes for derived balance calculations & relational joins
CREATE INDEX IF NOT EXISTS idx_movements_product_id ON movements(product_id);
CREATE INDEX IF NOT EXISTS idx_movements_supplier_id ON movements(supplier_id);
CREATE INDEX IF NOT EXISTS idx_movements_location_id ON movements(location_id);

-- Negative-stock guard at the DB layer (defense-in-depth against global and per-location overdrafts)
DROP TRIGGER IF EXISTS prevent_negative_stock;
CREATE TRIGGER IF NOT EXISTS prevent_negative_stock
BEFORE INSERT ON movements
WHEN NEW.type = 'OUT'
BEGIN
    SELECT RAISE(ABORT, 'SECURITY VIOLATION: Insufficient stock.')
    WHERE (SELECT COALESCE(SUM(CASE WHEN type = 'IN' THEN qty ELSE -qty END), 0)
           FROM movements WHERE product_id = NEW.product_id) < NEW.qty
       OR (NEW.location_id IS NOT NULL AND
           (SELECT COALESCE(SUM(CASE WHEN type = 'IN' THEN qty ELSE -qty END), 0)
            FROM movements WHERE product_id = NEW.product_id AND location_id = NEW.location_id) < NEW.qty);
END;

-- Movement ledger immutability triggers (strictly append-only)
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

-- 7. AUDIT LOG: Cryptographically chained tamper-evident ledger
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    ref_table TEXT NOT NULL CHECK(ref_table IN ('products', 'movements')),
    ref_id INTEGER NOT NULL,
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

-- 8. RELATIONAL VIEWS: Advanced SQL analytics and derived stock calculation
-- View 1: Real-time dynamic stock summary with category attribution and low-stock flagging
CREATE VIEW IF NOT EXISTS v_inventory_summary AS
SELECT
    p.id AS product_id,
    p.sku,
    p.name AS product_name,
    c.id AS category_id,
    COALESCE(c.name, 'Uncategorized') AS category_name,
    COALESCE(c.code, 'N/A') AS category_code,
    p.unit_price,
    p.reorder_threshold,
    COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.qty ELSE -m.qty END), 0) AS current_stock,
    ROUND(COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.qty ELSE -m.qty END), 0) * p.unit_price, 2) AS total_valuation,
    CASE
        WHEN COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.qty ELSE -m.qty END), 0) <= p.reorder_threshold THEN 1
        ELSE 0
    END AS is_low_stock,
    p.created_at
FROM products p
LEFT JOIN categories c ON p.category_id = c.id
LEFT JOIN movements m ON p.id = m.product_id
GROUP BY p.id;

-- View 2: Reorder alerts view for low stock items
CREATE VIEW IF NOT EXISTS v_low_stock_alerts AS
SELECT * FROM v_inventory_summary WHERE is_low_stock = 1;

-- View 3: Complete enriched movement ledger history with joined relations
CREATE VIEW IF NOT EXISTS v_ledger_history AS
SELECT
    m.id AS movement_id,
    m.created_at,
    m.type,
    m.qty,
    p.id AS product_id,
    p.sku,
    p.name AS product_name,
    COALESCE(c.name, 'Uncategorized') AS category_name,
    COALESCE(s.name, 'Direct Intake') AS supplier_name,
    COALESCE(l.name, 'General Storage') AS location_name,
    COALESCE(l.code, 'GEN') AS location_code,
    COALESCE(m.reference_doc, '-') AS reference_doc,
    COALESCE(m.note, '-') AS note,
    m.created_by
FROM movements m
JOIN products p ON m.product_id = p.id
LEFT JOIN categories c ON p.category_id = c.id
LEFT JOIN suppliers s ON m.supplier_id = s.id
LEFT JOIN locations l ON m.location_id = l.id
ORDER BY m.id DESC;

-- View 4: Per-location warehouse stock balance (derived via SUM(IN) - SUM(OUT))
CREATE VIEW IF NOT EXISTS v_location_inventory AS
SELECT
    p.id AS product_id,
    p.sku,
    p.name AS product_name,
    l.id AS location_id,
    l.code AS location_code,
    l.name AS location_name,
    COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.qty ELSE -m.qty END), 0) AS current_stock
FROM products p
CROSS JOIN locations l
LEFT JOIN movements m ON m.product_id = p.id AND m.location_id = l.id
GROUP BY p.id, l.id
HAVING current_stock > 0;
