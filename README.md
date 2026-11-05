# VaultStock
### Relational Inventory & Tamper-Evident Audit Ledger

VaultStock is a minimalist, tamper-evident inventory control system built to demonstrate relational database integrity, SQLite triggers, and cryptographic audit chaining without feature bloat.

---

## Core Design

Traditional inventory tables update a mutable counter (`UPDATE products SET stock = stock - 5`), which loses history and allows silent manipulation.

VaultStock enforces two core database guarantees:
1. **Immutable Append-Only Ledger (`movements`)**:
   - The `products` table has no `quantity` column.
   - Stock balances are computed dynamically via `SUM(IN) - SUM(OUT)`.
   - Database triggers (`BEFORE UPDATE`, `BEFORE DELETE`, `BEFORE INSERT`) block negative balances and reject any attempt to edit or delete historical rows.
2. **Cryptographic Audit Chain (`audit_log`)**:
   - Every product creation and stock movement is recorded in an append-only audit table.
   - Each block stores an **HMAC-SHA256** digest over `(prev_hash, id, action, actor, ref_table, ref_id, payload, timestamp)`.
   - `verify_audit_chain()` checks block contiguity (`1..N`), `prev_hash` linkage, HMAC digests, row-to-payload reconciliation, and an external head anchor (`data/audit_head.json`).

---

## Quick Start

```powershell
python run_dev.py
```

- **Frontend UI**: [http://localhost:3000](http://localhost:3000)
- **Swagger API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Demo Accounts

| Role | Username | Default Demo Password | Capabilities |
|---|---|---|---|
| **Admin** | `admin` | `vault-admin-2026` | Add products, record `IN`/`OUT` movements, verify chain, simulate tamper, reset DB |
| **Staff** | `staff` | `vault-staff-2026` | Record `IN`/`OUT` movements, view inventory and audit chain, verify integrity |

---

## Repository Layout

```
vaultstock/
├── api/                  # FastAPI backend, JWT auth & cryptographic engine
│   ├── config.py         # Centralized configuration & environment loader
│   ├── db.py             # SQLite WAL transactions, HMAC chain & verifier
│   ├── main.py           # REST endpoints, RBAC dependencies & security headers
│   └── security.py       # Salted PBKDF2-HMAC-SHA256 password hashing
├── db/                   # Database definition
│   └── schema.sql        # 4 core tables, CHECK constraints & immutability triggers
├── web/                  # Browser dashboard (HTML/CSS/JS single-page app)
│   ├── index.html        # Tabular ledger interface & modal dialogs
│   ├── style.css         # Dark-mode utilitarian styling
│   └── app.js            # Client logic, live tamper simulation & verification
├── extras/               # Supplementary docs, viva guides & automated test suite
│   ├── DATA_DICTIONARY.md # Column-level table schema definitions
│   ├── ER_DIAGRAM.md      # Entity-Relationship diagram & cardinality rules
│   ├── NORMALIZATION.md   # 1NF, 2NF, 3NF normalization proofs
│   ├── PRESENTATION_GUIDE.md # 2-minute demo script & top viva answers
│   ├── TEST_CASES.md      # Security & functional test matrix
│   ├── THREAT_MODEL.md    # STRIDE threat model & attack analysis
│   ├── test_suite.py      # Automated 26-step verification suite
│   └── README.md          # Guide to extra documentation
├── legacy/               # Archived / unused designs (PostgreSQL prototypes, old scripts)
│   ├── postgres/          # Earlier PostgreSQL reference design scripts
│   ├── dev.bat            # Deprecated batch launcher
│   ├── dev.ps1            # Deprecated PowerShell launcher
│   ├── SECURITY_PATCH_PLAN.md # Completed red-team sprint documentation
│   └── README.md          # Legacy archive manifest
├── data/                 # Local database storage & HMAC keys (auto-generated)
│   ├── .audit_key
│   ├── audit_head.json
│   └── vaultstock.db
├── requirements.txt      # Python dependencies
├── .env.example          # Environment variable reference
├── .gitignore            # Git exclusions
└── run_dev.py            # Universal development server launcher
```
