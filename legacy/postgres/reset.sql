-- ============================================================================
-- VaultStock: reset.sql
-- Master DDL & Reset Script
-- Drops and rebuilds all schemas, tables, triggers, views, roles, and seed data.
-- ============================================================================

\echo '>>> [1/5] Loading Schema Definition...'
\i 01_schema.sql

\echo '>>> [2/5] Loading Integrity Triggers & Hash Chain...'
\i 02_triggers.sql

\echo '>>> [3/5] Setting up Roles & Permissions...'
\i 03_roles.sql

\echo '>>> [4/5] Creating Dynamic Stock & Masked Views...'
\i 04_views.sql

\echo '>>> [5/5] Inserting Seed Data...'
\i 05_seed.sql

\echo '>>> Testing Hash Chain Verification...'
SELECT * FROM verify_audit_chain();

\echo '>>> VaultStock Database Initialized Successfully!'
