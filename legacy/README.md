# VaultStock Legacy Archive 🗄️

This directory stores archived, obsolete, and reference artifacts that are **no longer used** by the active VaultStock application:

1. **`postgres/`**:
   - Earlier architectural prototype files using PostgreSQL (`01_schema.sql` through `05_seed.sql`, reset scripts).
   - The production system runs entirely on self-contained SQLite + FastAPI with cryptographic HMAC-SHA256 audit chaining.

2. **`dev.bat` & `dev.ps1`**:
   - Deprecated platform launcher scripts containing user-specific machine paths.
   - Replaced by the universal cross-platform entrypoint: `python run_dev.py`.

3. **`SECURITY_PATCH_PLAN.md`**:
   - Completed red-team security sprint implementation document from earlier phases.
   - All proposed security patches and integrity triggers have already been baked into `api/` and `db/schema.sql`.

