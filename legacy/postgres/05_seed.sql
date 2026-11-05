-- ============================================================================
-- VaultStock: 05_seed.sql
-- Seed Data for Users, Roles, Suppliers, Locations, Products, and Ledger
-- ============================================================================

-- Temporary enable superuser context for seeding
SET search_path = public;

-- 1. SEED ROLES
INSERT INTO roles (id, name, description) VALUES
(1, 'admin', 'Full administrative authority over database and system operations'),
(2, 'storekeeper', 'Warehouse floor staff: logs stock receipts and issues, views masked catalogs'),
(3, 'purchaser', 'Procurement staff: manages supplier relationships, product catalog, and costs'),
(4, 'auditor', 'Independent inspector: read-only access to records, hash-chain verification')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description;

SELECT setval('roles_id_seq', (SELECT max(id) FROM roles));

-- 2. SEED USERS
-- Default password for all seed accounts is: password123
-- Hash generated via bcrypt (cost factor 12):
-- $2b$12$Jpt2NqKd47IPAnSJO2oUCef81GNAitraxtsIcdCv0M.0aHoFSPN7u
INSERT INTO users (id, username, password_hash, role_id, full_name, is_active) VALUES
(1, 'admin', '$2b$12$Jpt2NqKd47IPAnSJO2oUCef81GNAitraxtsIcdCv0M.0aHoFSPN7u', 1, 'Sarah Chen (System Administrator)', TRUE),
(2, 'storekeeper', '$2b$12$Jpt2NqKd47IPAnSJO2oUCef81GNAitraxtsIcdCv0M.0aHoFSPN7u', 2, 'Marcus Vance (Warehouse Lead)', TRUE),
(3, 'purchaser', '$2b$12$Jpt2NqKd47IPAnSJO2oUCef81GNAitraxtsIcdCv0M.0aHoFSPN7u', 3, 'Elena Rostova (Head of Procurement)', TRUE),
(4, 'auditor', '$2b$12$Jpt2NqKd47IPAnSJO2oUCef81GNAitraxtsIcdCv0M.0aHoFSPN7u', 4, 'David Sterling (Internal Compliance Auditor)', TRUE)
ON CONFLICT (id) DO NOTHING;

SELECT setval('users_id_seq', (SELECT max(id) FROM users));

-- 3. SEED SUPPLIERS (Sensitive margin details)
INSERT INTO suppliers (id, name, contact_email, phone, contract_margin, is_active) VALUES
(1, 'Apex Industrial Hardware', 'orders@apexindustrial.com', '+1-555-0101', 18.50, TRUE),
(2, 'Titan Microelectronics Corp', 'b2b@titanmicro.com', '+1-555-0102', 24.00, TRUE),
(3, 'Nordic Precision Fasteners', 'supply@nordicfasteners.com', '+1-555-0103', 12.75, TRUE),
(4, 'Vantage Chemical & Polymers', 'ops@vantagechem.com', '+1-555-0104', 31.20, TRUE)
ON CONFLICT (id) DO NOTHING;

SELECT setval('suppliers_id_seq', (SELECT max(id) FROM suppliers));

-- 4. SEED LOCATIONS
INSERT INTO locations (id, code, name, address, is_active) VALUES
(1, 'WH-MAIN', 'Main Distribution Center - Bay 1', '400 Industrial Parkway, Section A', TRUE),
(2, 'SEC-VAULT', 'High-Value Security Cage - Vault B', '400 Industrial Parkway, Vault B', TRUE),
(3, 'REMOTE-NORTH', 'North Regional Depot', '88 Logistics Way, Dock 4', TRUE)
ON CONFLICT (id) DO NOTHING;

SELECT setval('locations_id_seq', (SELECT max(id) FROM locations));

-- 5. SEED PRODUCTS
-- Attributes include unit_cost and reorder safety stock levels
INSERT INTO products (id, sku, name, description, unit_cost, reorder_level, supplier_id, is_active) VALUES
(1, 'SKU-TITAN-001', 'ARM Cortex-M4 Industrial MCU', '32-bit RISC microcontroller, 120MHz, 512KB Flash', 14.50, 50, 2, TRUE),
(2, 'SKU-TITAN-002', 'High-Speed Optocoupler IC', '10Mbps logic gate optocoupler in SOIC-8 packaging', 3.25, 100, 2, TRUE),
(3, 'SKU-APEX-101', 'Heavy Duty Servo Actuator', 'Brushless DC high-torque servo actuator 24V', 185.00, 10, 1, TRUE),
(4, 'SKU-APEX-102', 'Optical Rotary Encoder 1024-PPR', 'Quadrature industrial rotary encoder with shielded lead', 62.00, 15, 1, TRUE),
(5, 'SKU-NORD-501', 'M8 Grade 8.8 Hex Flange Bolts (100pk)', 'Zinc-plated hardened carbon steel fastener pack', 22.40, 30, 3, TRUE),
(6, 'SKU-NORD-502', 'Viton Industrial O-Ring Seal Kit', 'Fluorocarbon elastomeric high-temp seal assortment', 45.00, 20, 3, TRUE),
(7, 'SKU-VANT-901', 'Thermal Conductive Paste 500g', 'Silicone-free 8.5 W/mK thermal interface compound', 38.00, 25, 4, TRUE),
(8, 'SKU-VANT-902', 'Precision Contact Cleaner 400ml', 'Fast-evaporating residue-free dielectric spray', 11.50, 40, 4, TRUE),
(9, 'SKU-TITAN-003', 'FPGA Spartan-7 XC7S50 Evaluation Board', 'Entry-level embedded development board with PCIe', 249.99, 5, 2, TRUE),
(10, 'SKU-APEX-103', 'Pneumatic Control Solenoid Valve', '5/2-way pilot operated directional spool valve 24VDC', 74.50, 12, 1, TRUE)
ON CONFLICT (id) DO NOTHING;

SELECT setval('products_id_seq', (SELECT max(id) FROM products));

-- 6. SEED STOCK MOVEMENTS (THE INITIAL LEDGER)
-- Set app.user_id = 1 (admin) in session context so the audit trigger attributes correctly
SELECT set_config('app.user_id', '1', true);

-- Initial intake of inventory (RECEIVE)
INSERT INTO stock_movements (product_id, location_id, movement_type, qty_delta, reason, created_by) VALUES
(1, 1, 'RECEIVE', 250, 'Initial supplier delivery PO-2026-001', 1),
(1, 2, 'RECEIVE', 50,  'Security reserve stock transfer', 1),
(2, 1, 'RECEIVE', 600, 'Bulk component intake from Titan Micro', 1),
(3, 1, 'RECEIVE', 40,  'Consignment delivery Apex', 1),
(4, 1, 'RECEIVE', 50,  'Q1 stocking order', 1),
(5, 1, 'RECEIVE', 120, 'Standard fasteners restock', 1),
(6, 1, 'RECEIVE', 80,  'O-ring kits delivery', 1),
(7, 1, 'RECEIVE', 100, 'Thermal compound shipment', 1),
(8, 1, 'RECEIVE', 150, 'Cleaners bulk purchase', 1),
(9, 2, 'RECEIVE', 15,  'High-value FPGA dev kits into vault', 1),
(10, 1, 'RECEIVE', 35, 'Pneumatic valves lot 44', 1);

-- Storekeeper issues items to production (ISSUE - negative deltas)
SELECT set_config('app.user_id', '2', true);

INSERT INTO stock_movements (product_id, location_id, movement_type, qty_delta, reason, created_by) VALUES
(1, 1, 'ISSUE', -30, 'Production dispatch for Line 3', 2),
(2, 1, 'ISSUE', -150, 'Batch assembly allocation', 2),
(3, 1, 'ISSUE', -5,  'Maintenance replacement motor', 2),
(5, 1, 'ISSUE', -25, 'Line 1 fastener requisition', 2),
(8, 1, 'ISSUE', -20, 'Toolroom daily consumption', 2);

-- Storekeeper attempts adjustment (Adjust requires mandatory audit note)
SELECT set_config('app.user_id', '1', true); -- adjustments require admin approval in policy

INSERT INTO stock_movements (product_id, location_id, movement_type, qty_delta, reason, created_by) VALUES
(6, 1, 'ADJUST', -2, 'Damaged carton discovered during cycle count - written off', 1);
