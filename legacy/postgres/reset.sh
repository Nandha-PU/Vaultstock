#!/usr/bin/env bash
# ============================================================================
# VaultStock: reset.sh
# Drop and rebuild database from scratch
# ============================================================================

set -e

DB_NAME="${DB_NAME:-vaultstock}"
DB_USER="${DB_USER:-postgres}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ">>> Resetting database '${DB_NAME}' on ${DB_HOST}:${DB_PORT}..."
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -c "DROP DATABASE IF EXISTS ${DB_NAME} WITH (FORCE); CREATE DATABASE ${DB_NAME};"

echo ">>> Executing DDL and triggers..."
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -f "${DIR}/01_schema.sql"
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -f "${DIR}/02_triggers.sql"
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -f "${DIR}/03_roles.sql"
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -f "${DIR}/04_views.sql"
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -f "${DIR}/05_seed.sql"

echo ">>> Verifying audit chain:"
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -c "SELECT * FROM verify_audit_chain();"

echo ">>> VaultStock database reset complete."
