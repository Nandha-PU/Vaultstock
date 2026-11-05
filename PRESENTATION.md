# 📊 VaultStock — Project Presentation & Technical Architecture

> **Project Title**: VaultStock — Relational Inventory & Cryptographic Audit Ledger  
> **Domain**: Database Management Systems (DBMS), Information Security & Cryptographic Auditing  
> **Core Principle**: *"Never edit an inventory balance. Record an append-only transaction, and let the database mathematically guarantee historical non-repudiation."*

---

## ⏱️ 1. The 30-Second Elevator Pitch

> *"Most traditional inventory systems update a mutable counter like `UPDATE products SET stock = stock - 5`. This introduces lost-update race conditions, phantom reads, and leaves zero forensic evidence if an insider commits fraud.  
> **VaultStock** solves this through two fundamental database principles:  
> 1. **An Immutable Append-Only Ledger**: Balances are never stored; they are dynamically derived via `SUM(IN) - SUM(OUT)`. Engine-level triggers permanently abort any `UPDATE` or `DELETE` statement.  
> 2. **A Cryptographic Audit Chain**: Every transaction creates an HMAC-SHA256 block bound to the operational row. If any attacker tampers with the SQLite database file directly, the mathematical chain breaks and alerts the system instantly."*

---

## 🔑 2. Demo Credentials & Quick Access

| Role | Username | Default Password | Granted Capabilities |
|---|---|---|---|
| **Admin** | `admin` | `vault-admin-2026` | Create products, record IN/OUT movements, verify audit chain, simulate tampering, reset database |
| **Staff** | `staff` | `vault-staff-2026` | Record IN/OUT movements, view inventory, verify audit chain |

- **Web Frontend**: [http://localhost:3000](http://localhost:3000)
- **Interactive Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Local Dev Server Command**: `python run_dev.py`

---

## 🌟 3. Key Features Matrix

| Feature | Technical Description | DBMS & Security Value |
|---|---|---|
| **Dynamic Balance Derivation** | Zero mutable `stock` columns in `products`. Computed on the fly via `SUM(IN) - SUM(OUT)`. | Eliminates redundant derived data, ensures 3NF/BCNF normalization, and prevents balance desynchronization. |
| **Engine-Level Immutability** | SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers abort write operations on `products`, `movements`, and `audit_log`. | Defense-in-depth: Even if application logic fails or an SQL injection occurs, the database engine itself rejects changes. |
| **Negative Stock Prevention** | `BEFORE INSERT` trigger on `movements` when `NEW.type = 'OUT'` calculates real-time stock and halts with `RAISE(ABORT)` if balance < qty. | Guarantees zero inventory overdrafts at the storage layer under high concurrency. |
| **HMAC-SHA256 Audit Chain** | Sequential blocks linked with `prev_hash` and signed using a secret external key (`VAULTSTOCK_AUDIT_KEY`). | Non-repudiation: Attackers with raw disk access cannot forge valid signatures without the external HMAC key. |
| **5-Point Chain Verification** | Automated mathematical integrity check covering Contiguity, Linkage, HMAC signature, Relational Reconciliation, and External Anchor. | Verifies the entire ledger in sub-second time, catching record edits, deletions, ghost rows, and tail truncations. |
| **Out-of-Band Head Anchor** | Independent checkpoint file (`data/audit_head.json`) synced on every transaction. | Defeats tail-truncation attacks where a malicious actor deletes the latest audit blocks. |
| **Role-Based Access Control** | Stateless HS256 JWT tokens with role separation (`admin` vs `staff`). | Principle of least privilege; restricts catalog creation and administrative simulation tools. |
| **Brute-Force & Timing Protection** | Sliding window rate limiter (5 attempts / 15 min) + dummy verification for non-existent users. | Prevents credential guessing and eliminates side-channel user enumeration. |

---

## 🏛️ 4. Detailed Component & Function Breakdown

### A. Database & Cryptographic Engine (`api/db.py`)

* **`get_connection()`**:
  * Configures SQLite with Write-Ahead Logging (`PRAGMA journal_mode = WAL;`).
  * Enforces foreign key constraints (`PRAGMA foreign_keys = ON;`).
  * Sets a 10-second busy timeout to handle concurrent transactions without deadlocks.
* **`write_tx(conn)`**:
  * Atomic transaction context manager utilizing `BEGIN IMMEDIATE;`.
  * Obtains an exclusive write lock immediately, preventing SQLite read-check-write race conditions.
* **`canonical_json(data)`**:
  * Normalizes dictionaries with sorted keys, no redundant whitespace, and UTF-8 encoding for deterministic HMAC generation.
* **`compute_hash(prev_hash, row_id, action, actor, ref_table, ref_id, payload_json, timestamp)`**:
  * Generates an HMAC-SHA256 signature using the secret key loaded from `data/.audit_key`.
* **`append_audit_entry(conn, action, actor, ref_table, ref_id, payload, details)`**:
  * Retrieves the latest audit row, links `prev_hash`, computes the new `row_hash`, and commits the audit block.
* **`verify_audit_chain()`**:
  * Performs the comprehensive 5-point mathematical scan:
    1. **Contiguity**: Block IDs must strictly follow $1, 2, \dots, N$ without gaps.
    2. **Linkage**: `current_block.prev_hash == previous_block.row_hash`.
    3. **Integrity**: Recomputes HMAC-SHA256 across all fields and compares in constant time.
    4. **Relational Reconciliation**: Cross-examines operational rows in `products` and `movements` against the JSON snapshots in `audit_log` (detects unlogged and ghost rows).
    5. **Anchor Check**: Compares the chain head against the out-of-band `data/audit_head.json`.
* **`tamper_for_demo(block_id, file_level)`**:
  * Bypasses triggers and mutates block #1 with an unkeyed SHA-256 hash to simulate raw disk corruption by an attacker.
* **`reset_demo_db(admin_actor)`**:
  * Drops all tables/triggers, re-initializes schema, and logs a clean `DEMO_RESET` audit block.

---

### B. Security & Authentication (`api/security.py` & `api/config.py`)

* **`hash_password(password)`**:
  * Uses salted PBKDF2 with HMAC-SHA256, 150,000 iterations, and a 16-byte cryptographically secure random salt.
* **`verify_password(password, stored_hash)`**:
  * Extracts iterations, salt, and hash, then executes constant-time verification (`hmac.compare_digest`).
* **`dummy_verify(password)`**:
  * Executes a dummy PBKDF2 computation when a username is not found, equalizing response times and defeating user enumeration timing attacks.
* **`is_login_throttled(key)` & `record_login_failure(key)`**:
  * In-memory thread-safe rate limiter restricting brute-force attacks to 5 failed attempts per 15-minute window.

---

### C. REST API Endpoints (`api/main.py`)

* **`POST /api/login`**: Authenticates user credentials with rate-limiting and issues a signed JWT token.
* **`GET /api/me`**: Returns the active session profile and user permissions.
* **`GET /api/products`**: Returns the catalog alongside real-time derived stock balances (`SUM(IN) - SUM(OUT)`).
* **`POST /api/products`**: *(Admin only)* Inserts a new SKU and creates a `PRODUCT_CREATE` audit block.
* **`GET /api/movements`**: Retrieves historical stock movements with pagination.
* **`POST /api/movements`**: Records an append-only stock movement (`IN` or `OUT`) and seals it with an audit block.
* **`GET /api/audit`**: Returns paginated audit trail blocks with cryptographic hashes and details.
* **`GET /api/audit/verify`**: Executes full mathematical verification of the entire system state.
* **`GET /api/debug/internals`**: Returns live SQLite engine PRAGMAs (`journal_mode`, `foreign_keys`, `busy_timeout`), table row counts, active `sqlite_master` triggers/tables, and anchor comparison data.
* **`POST /api/debug/sql-probe`**: Executes live SQLite diagnostic probes (`EXPLAIN QUERY PLAN` and trigger defense probes) safely inside rolled-back transactions.
* **`POST /api/audit/tamper-demo`**: *(Admin only)* Triggers simulated disk tampering on block #1.
* **`POST /api/reset-demo`**: *(Admin only)* Restores the database to a pristine seed state.

---

### D. Relational Schema & Constraints (`db/schema.sql`)

* **`users` Table**: Authenticated users, hashed passwords, and roles (`admin`, `staff`).
* **`products` Table**: `(id, sku, name, unit_price, created_at)` with strict length and range checks. **No stock column.**
* **`movements` Table**: `(id, product_id, type ['IN'/'OUT'], qty, note, created_by, created_at)` with foreign keys and index on `product_id`.
* **`audit_log` Table**: `(id, action, actor, ref_table, ref_id, payload, details, timestamp, prev_hash, row_hash)` with `UNIQUE(ref_table, ref_id)`.
* **Triggers**:
  * `prevent_product_update` & `prevent_product_delete`
  * `prevent_movement_update` & `prevent_movement_delete`
  * `prevent_audit_update` & `prevent_audit_delete`
  * `prevent_negative_stock` (evaluates dynamic balance on `BEFORE INSERT ON movements WHEN NEW.type = 'OUT'`)

---

### E. Frontend User Interface (`web/app.js`, `web/index.html` & `web/style.css`)

* **Light & Dark Mode Toggle**: Instant theme switcher persisted across sessions (`[data-theme="dark"]`).
* **Clean Inventory Dashboard (`#viewDashboard`)**:
  * **KPI Summary Cards**: Displays total active SKUs, total derived units in stock, real-time inventory valuation, and ledger integrity status.
  * **Product Catalog**: Searchable and filterable product table with instant **`+ Receive`** (`IN`) and **`- Issue`** (`OUT`) action buttons.
  * **Recent Stock Movements**: Clean operational log without cluttering the user view with raw cryptographic hashes.
* **Dedicated SQL & Crypto Debugger Page (`#viewDebug`)**:
  * **5-Point Verification Matrix**: Visual status cards for Contiguity, Linkage, HMAC-SHA256, Reconciliation, and Head Anchor.
  * **SQLite Engine Telemetry Box**: Displays live PRAGMA settings (`WAL`, `foreign_keys`, `busy_timeout`, DB page size) and table row counts.
  * **Interactive SQL Trigger & Query Plan Sandbox**: One-click buttons to run `EXPLAIN QUERY PLAN` and test SQLite triggers (`UPDATE`/`DELETE` on `movements`, `audit_log`, `products`, and overdraft inserts) with a live SQL console.
  * **Anti-Truncation Anchor Comparison**: Side-by-side comparison of the SQLite `audit_log` chain head vs. `data/audit_head.json`.
  * **Cryptographic Hash Chain & Block Inspector**: Full `audit_log` table with an interactive inspector showing 64-character `prev_hash`, `row_hash`, and formatted canonical JSON snapshots.
  * **Live Backend SQL Process Trace & DDL Explorer**: Real-time trace of SQLite transaction pipelines and `sqlite_master` trigger/table DDL definitions.
* **Interactive 6-Step Live Demo Walkthrough Panel**: Built-in presentation runner with **`▶ Auto-Play All Steps`**, **`Next Step →`**, individual **`Run Step 1–6`** buttons, automatic view switching between Dashboard and Debugger, and live speaker prompts.

---

## 📽️ 5. Suggested Slide-by-Slide Presentation Structure

```
[Slide 1] Title: VaultStock — Relational Inventory & Cryptographic Ledger
          • Relational Database Integrity, SQLite Triggers & Cryptographic Non-Repudiation
          • Presented by: [Your Name]

[Slide 2] The Industry Problem
          • Traditional systems use: UPDATE products SET stock = stock - 5
          • Flaws: Lost updates under concurrency, zero forensic history, vulnerable to insider fraud

[Slide 3] VaultStock Solution & Core Architecture
          • 1. Dynamic Attribute Derivation: Balances computed via SUM(IN) - SUM(OUT)
          • 2. Engine-Enforced Immutability: Triggers block UPDATE & DELETE queries
          • 3. Cryptographic Audit Chaining: HMAC-SHA256 block ledger

[Slide 4] Relational Database Engineering (DBMS Concepts)
          • Strict adherence to 3NF & BCNF (no redundant derived attributes)
          • Active DB Triggers: BEFORE INSERT (negative stock guard), BEFORE UPDATE/DELETE
          • Concurrency control: SQLite WAL mode with BEGIN IMMEDIATE write locks

[Slide 5] Cryptographic Verification Architecture
          • 5-Point Verification Scan:
            1. Contiguity (No gap deletions)
            2. Linkage (prev_hash chain)
            3. HMAC Signature (Keyed secret protection)
            4. Relational Reconciliation (Operational rows vs Audit snapshots)
            5. Out-of-band Head Anchor (Anti-truncation defense)

[Slide 6] Security Architecture & Defense-in-Depth
          • Salted PBKDF2-HMAC-SHA256 (150,000 iterations)
          • Constant-time verification & dummy hashing against timing attacks
          • Sliding-window brute force login rate limiting

[Slide 7] Live Demonstration Walkthrough (See Step-by-Step Demo Script)

[Slide 8] Summary & Key Takeaways
          • Security must exist at the database storage layer, not just the application layer
          • Append-only event ledgers eliminate concurrency races and guarantee auditability
```

---

## 🎬 6. Step-by-Step 2-Minute Live Demo Script

| Step | Action on Screen | What to Say to the Evaluator |
|---|---|---|
| **1. Sign In** | Open `http://localhost:3000`. Sign in as `admin` / `vault-admin-2026`. | *"Notice our dashboard interface. The top status panel shows 'Audit Chain Intact' with 100% cryptographic verification across all blocks."* |
| **2. Dynamic Stock** | Click **IN / OUT** on *MacBook Pro 16-inch M3* $\rightarrow$ Select `IN`, Qty: `10`, Note: `"Supplier Batch"`. Click **Submit**. | *"When I receive 10 units, notice that stock increments dynamically from 25 to 35. The database did not update a column; it appended an immutable movement row and sealed an HMAC audit block."* |
| **3. Negative Stock Guard** | Click **IN / OUT** on any product $\rightarrow$ Select `OUT`, Qty: `9999`. Click **Submit**. | *"The system immediately rejects the transaction with 'Insufficient inventory'. The database trigger prevents overdrafts even under concurrent requests."* |
| **4. Tamper Simulation** | Click the red button: **"Simulate Tamper (Block #1)"**. | *"Now imagine an insider or attacker gains direct SQLite access and tampers with historical block #1 behind the application."* |
| **5. Verification Catch** | Click **"Verify Audit Chain"**. | *The banner turns glowing red: `Verification Failed: HMAC mismatch in block #1: data was altered`.*<br>*"The mathematical verification walked the chain and caught the altered payload digest immediately."* |
| **6. Reset Demo** | Click **"Reset DB"** $\rightarrow$ Confirm. | *"A single click restores the database to a pristine, reseeded state with zero anomalies."* |

---

## ❓ 7. Top 8 Viva & Technical Evaluation Questions

### Q1: Why not store a `stock` column directly in the `products` table?
> **Answer**: *"A mutable `stock` column violates 3NF by duplicating data that is mathematically derivable from the movement history. In multi-user systems, mutable counters suffer from lost updates and race conditions. By deriving stock via `SUM(IN) - SUM(OUT)`, our balance is always 100% synchronized with historical reality."*

### Q2: How does VaultStock prevent overselling if two users issue stock simultaneously?
> **Answer**: *"We use two layers of defense:  
> 1. In Python, every transaction opens with `BEGIN IMMEDIATE;` to acquire an exclusive write lock in SQLite WAL mode.  
> 2. Inside the database, a `BEFORE INSERT` trigger calculates current stock and aborts the insert (`RAISE(ABORT)`) if balance would drop below zero."*

### Q3: Why use HMAC-SHA256 instead of simple SHA-256?
> **Answer**: *"Plain SHA-256 is unkeyed. An attacker who gains raw file access could modify an audit block and recalculate plain SHA-256 hashes down the rest of the chain. HMAC-SHA256 requires a secret key (`VAULTSTOCK_AUDIT_KEY`) stored outside the database. Without the key, the attacker cannot forge valid signatures."*

### Q4: What prevents an attacker from deleting the newest audit rows (Tail Truncation)?
> **Answer**: *"If someone deletes the latest blocks, the remaining chain prefix appears mathematically valid. VaultStock defeats this by writing an out-of-band external anchor checkpoint file (`data/audit_head.json`) upon every append. The verifier flags a failure if the database head does not match the anchor."*

### Q5: How do triggers protect against application-level exploits?
> **Answer**: *"Even if an attacker finds an SQL injection vulnerability or bugs in our API endpoints, SQLite triggers (`prevent_movement_update`, `prevent_movement_delete`, `prevent_audit_update`) execute inside the database engine itself and immediately abort any `UPDATE` or `DELETE` statement."*

### Q6: What is 'Relational Reconciliation' in your verification procedure?
> **Answer**: *"Hash chaining only proves the audit log wasn't altered. Relational reconciliation cross-checks the actual operational tables (`products`, `movements`) against the JSON snapshots stored inside the audit blocks. If someone injects a 'ghost' row directly into `movements` without an audit entry, the verifier catches it."*

### Q7: How does your password storage adhere to security standards?
> **Answer**: *"We use salted PBKDF2 with HMAC-SHA256 and 150,000 iterations using a 16-byte cryptographically secure random salt. Comparisons are constant-time (`hmac.compare_digest`), and dummy hash evaluations run for non-existent users to eliminate timing attacks."*

### Q8: How does this design scale to millions of records?
> **Answer**: *"For enterprise scale, the append-only ledger pattern allows periodic balance snapshots. Every month, a snapshot row is created, and balances are computed by summing the snapshot plus subsequent delta movements, maintaining high query speed while preserving immutable history."*
