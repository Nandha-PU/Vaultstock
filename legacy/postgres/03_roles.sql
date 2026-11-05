-- ============================================================================
-- VaultStock: 03_roles.sql
-- Role-Based Access Control (RBAC) and Defense-in-Depth Permissions
-- ============================================================================

-- Create NOLOGIN role groups
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vs_admin') THEN
        CREATE ROLE vs_admin NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vs_storekeeper') THEN
        CREATE ROLE vs_storekeeper NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vs_purchaser') THEN
        CREATE ROLE vs_purchaser NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vs_auditor') THEN
        CREATE ROLE vs_auditor NOLOGIN;
    END IF;
    -- API Application User (The single connection role used by FastAPI)
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vaultstock_api') THEN
        CREATE ROLE vaultstock_api WITH LOGIN PASSWORD 'CHANGE_ME';
    END IF;
END $$;

-- Permit the API application role to assume any of the 4 contextual roles via SET LOCAL ROLE
GRANT vs_admin TO vaultstock_api;
GRANT vs_storekeeper TO vaultstock_api;
GRANT vs_purchaser TO vaultstock_api;
GRANT vs_auditor TO vaultstock_api;

-- Revoke all default public permissions on schema public
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO vs_admin, vs_storekeeper, vs_purchaser, vs_auditor, vaultstock_api;

-- Universal sequence usage (for tables where INSERT is permitted)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO vs_admin, vs_storekeeper, vs_purchaser;

-- ----------------------------------------------------------------------------
-- 1. vs_admin PERMISSIONS
-- ----------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE ON roles, users, suppliers, locations, products, purchase_orders TO vs_admin;
GRANT SELECT, INSERT ON stock_movements TO vs_admin;
GRANT SELECT ON audit_log TO vs_admin;

-- ----------------------------------------------------------------------------
-- 2. vs_storekeeper PERMISSIONS (LEAST PRIVILEGE)
-- Denied direct access to base suppliers table and raw product costs.
-- Denied all access to audit_log.
-- Can only INSERT movements and view public/masked views.
-- ----------------------------------------------------------------------------
GRANT SELECT ON locations TO vs_storekeeper;
GRANT SELECT, INSERT ON stock_movements TO vs_storekeeper;
-- Note: Storekeeper gets SELECT on masked views defined in 04_views.sql

-- ----------------------------------------------------------------------------
-- 3. vs_purchaser PERMISSIONS
-- Manages catalog pricing and suppliers, but cannot log movements or read audit log.
-- ----------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE ON suppliers, products, purchase_orders TO vs_purchaser;
GRANT SELECT ON locations, stock_movements TO vs_purchaser;

-- ----------------------------------------------------------------------------
-- 4. vs_auditor PERMISSIONS
-- Read-only across everything, including full audit chain and verification function.
-- ----------------------------------------------------------------------------
GRANT SELECT ON roles, users, suppliers, locations, products, stock_movements, purchase_orders, audit_log TO vs_auditor;

-- Explicitly revoke UPDATE / DELETE on immutable tables from EVERYONE
REVOKE UPDATE, DELETE, TRUNCATE ON stock_movements FROM vs_admin, vs_storekeeper, vs_purchaser, vs_auditor, vaultstock_api, PUBLIC;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM vs_admin, vs_storekeeper, vs_purchaser, vs_auditor, vaultstock_api, PUBLIC;
