-- ============================================================================
-- VaultStock: 04_views.sql
-- Stock Computation, Low-Stock Alerts, and Data Masking Views
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. CURRENT STOCK PER PRODUCT AND LOCATION (DERIVED LEDGER VIEW)
-- No direct quantity column: calculated on-the-fly from the immutable movements.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_stock AS
SELECT 
    p.id AS product_id,
    p.sku,
    p.name AS product_name,
    l.id AS location_id,
    l.code AS location_code,
    l.name AS location_name,
    COALESCE(SUM(sm.qty_delta), 0)::BIGINT AS quantity,
    p.reorder_level,
    CASE 
        WHEN COALESCE(SUM(sm.qty_delta), 0) <= p.reorder_level THEN TRUE 
        ELSE FALSE 
    END AS is_low_stock
FROM products p
CROSS JOIN locations l
LEFT JOIN stock_movements sm 
    ON sm.product_id = p.id 
   AND sm.location_id = l.id
WHERE p.is_active = TRUE 
  AND l.is_active = TRUE
GROUP BY p.id, p.sku, p.name, l.id, l.code, l.name, p.reorder_level;

-- ----------------------------------------------------------------------------
-- 2. TOTAL PRODUCT STOCK SUMMARY (AGGREGATED ACROSS ALL LOCATIONS)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_stock_summary AS
SELECT 
    p.id AS product_id,
    p.sku,
    p.name AS product_name,
    p.reorder_level,
    p.unit_cost,
    COALESCE(SUM(sm.qty_delta), 0)::BIGINT AS total_quantity,
    (COALESCE(SUM(sm.qty_delta), 0) * p.unit_cost)::NUMERIC(14,2) AS total_inventory_value,
    CASE 
        WHEN COALESCE(SUM(sm.qty_delta), 0) <= p.reorder_level THEN TRUE 
        ELSE FALSE 
    END AS is_low_stock
FROM products p
LEFT JOIN stock_movements sm ON sm.product_id = p.id
WHERE p.is_active = TRUE
GROUP BY p.id, p.sku, p.name, p.reorder_level, p.unit_cost;

-- ----------------------------------------------------------------------------
-- 3. LOW STOCK MONITORING VIEW
-- Identifies products at or below their defined safety reorder thresholds.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_low_stock AS
SELECT * 
FROM v_stock_summary
WHERE is_low_stock = TRUE;

-- ----------------------------------------------------------------------------
-- 4. DATA MASKING: PUBLIC PRODUCTS VIEW (FOR STOREKEEPERS)
-- Hides proprietary unit_cost column to prevent commercial insider leakage.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW products_public AS
SELECT 
    id,
    sku,
    name,
    description,
    reorder_level,
    supplier_id,
    is_active,
    created_at
FROM products;

-- ----------------------------------------------------------------------------
-- 5. DATA MASKING: PUBLIC SUPPLIERS VIEW (FOR STOREKEEPERS)
-- Strips out contract margins and negotiations.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW suppliers_public AS
SELECT 
    id,
    name,
    contact_email,
    phone,
    is_active,
    created_at
FROM suppliers;

-- ----------------------------------------------------------------------------
-- PERMISSION GRANTS ON VIEWS
-- ----------------------------------------------------------------------------
GRANT SELECT ON v_stock, v_stock_summary, v_low_stock TO vs_admin, vs_storekeeper, vs_purchaser, vs_auditor;
GRANT SELECT ON products_public, suppliers_public TO vs_storekeeper;
GRANT SELECT ON products, suppliers TO vs_admin, vs_purchaser, vs_auditor;
