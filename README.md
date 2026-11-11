# VaultStock
### Relational Inventory Management & Cryptographic Audit Ledger

VaultStock is a textbook-grade relational inventory management and loss-prevention system built to demonstrate **Third Normal Form (3NF) relational database design**, **SQLite trigger-level immutability**, and **cryptographic HMAC-SHA256 audit chaining** without feature bloat.

---

## Core Database Design

Traditional inventory tables update a mutable counter (`UPDATE products SET stock = stock - 5`), which loses historical context, invites lost-update race conditions, and allows silent insider fraud.

VaultStock enforces strict database guarantees:
1. **Dynamic Stock Derivation & 3NF Normalization**:
   - The `products` table has **no `quantity` column**.
   - Global stock and valuations are computed in real time via `v_inventory_summary`, per-warehouse balances via `v_location_inventory` (`SUM(IN) - SUM(OUT)`), and reorder alerts via `v_low_stock_alerts`.
2. **Immutable Append-Only Movement Ledger (`movements`) & Atomic Transfers**:
   - Every inward receipt (`IN`), outward dispatch (`OUT`), and inter-warehouse transfer (`OUT` + `IN`) is an immutable transaction linked to `suppliers` and `locations`.
   - SQLite triggers (`BEFORE UPDATE`, `BEFORE DELETE`) permanently abort any attempt to edit or delete historical rows.
   - The `prevent_negative_stock` trigger rejects any issue or transfer that exceeds available global or location balance at the storage layer.
3. **Cryptographic Audit Chain (`audit_log`)**:
   - Every product creation and movement is signed into an append-only audit log chained like **Git commits** using HMAC-SHA256.
   - The 5-Point Verifier checks **Contiguity** ($1..N$), **Linkage** (`prev_hash`), **HMAC Integrity**, **Relational Reconciliation**, and an out-of-band **Head Anchor** (`data/audit_head.json`).

---

## Quick Start

```powershell
python run_dev.py
```

- **Unified Web Dashboard**: [http://localhost:3000](http://localhost:3000)
- **Interactive Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Direct Interactive SQLite Terminal**: `python inspect_db.py --shell`
- **Full CLI Database Dump**: `python inspect_db.py`
- **Run Automated Test Suite**: `python extras/test_suite.py`

---

## Demo Accounts

| Role | Username | Default Password | Capabilities |
|---|---|---|---|
| **Admin** | `admin` | `vault-admin-2026` | Create products, record IN/OUT movements, view diagnostics, simulate disk tamper, reset DB |
| **Staff** | `staff` | `vault-staff-2026` | Record IN/OUT movements, view inventory & audit chain, run integrity verification |

---

## Repository Layout

```
vaultstock/
├── api/                     # FastAPI backend, JWT auth & cryptographic engine
│   ├── config.py            # Environment loader & security configuration
│   ├── db.py                # SQLite WAL transactions, seed data & HMAC verifier
│   ├── main.py              # REST API endpoints, Pydantic v2 models & RBAC
│   └── security.py          # Salted PBKDF2-HMAC-SHA256 password hashing
├── db/                      # Database definition
│   └── schema.sql           # 3NF schema, indexes, views & immutability triggers
├── web/                     # Unified Single-Page Application (SPA)
│   ├── index.html           # Unified 4-tab dashboard interface
│   ├── style.css            # Responsive design system (Light & Dark modes)
│   ├── app.js               # Reactive client logic, transfers, flowchart & diagnostics
│   └── theme.js             # Theme initialization script
├── extras/                  # Supplementary documentation & tests
│   ├── ER_DIAGRAM.md        # Entity-Relationship diagram & cardinality rules
│   ├── NORMALIZATION.md     # 1NF, 2NF, 3NF normalization proofs
│   ├── test_suite.py        # Automated 25-step verification test suite
│   └── ...
├── data/                    # SQLite database & HMAC keys (auto-generated)
├── inspect_db.py            # CLI database inspector & query tool
├── PROJECT_REPORT.md        # Comprehensive technical report & documentation
├── requirements.txt         # Python dependencies
└── run_dev.py               # Universal development server launcher
```
