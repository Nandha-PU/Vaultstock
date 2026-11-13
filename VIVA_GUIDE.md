# VaultStock: Comprehensive DBMS Viva & Presentation Guide

> **Important Mindset for Your Viva:**
> Do **not** present this as just a "web application" or "FastAPI project". To your DBMS professors, present it as a **"Relational Database Architecture & Integrity Engine"**. The web interface is simply a live visual telemetry dashboard for the underlying database kernel.

---

## 1. The 30-Second Elevator Pitch
*(Use this exact opening when the professor asks: "Tell me about your project" or "What is the problem statement?")*

> *"Good morning/afternoon, Professors. Our project is **VaultStock**. 
> 
> In traditional inventory and transaction systems, availability is stored as a mutable counter column—for example, `UPDATE products SET stock = stock - 5`. In database theory, this creates three serious flaws: **lost-update concurrency anomalies**, **loss of historical audit provenance**, and **susceptibility to silent insider tampering**.
> 
> To solve this, VaultStock implements an **Append-Only Relational Ledger** in **Third Normal Form (3NF)**:
> 1. We completely eliminate the mutable `stock` column. Current balances—both global and per-warehouse—are derived dynamically in real time via **compiled SQL views** (`SUM(IN) - SUM(OUT)`).
> 2. Overdrafts and unauthorized changes are blocked directly inside the storage kernel using **7 SQLite `BEFORE` triggers**.
> 3. Concurrent operations and inter-warehouse transfers are serialized using **`BEGIN IMMEDIATE` ACID transactions** under **WAL (Write-Ahead Logging)** mode.
> 4. Every single transaction is cryptographically sealed into an **HMAC-SHA256 audit chain**, backed by an out-of-band external anchor, allowing mathematical tamper detection across the entire database."*

---

## 2. The 5 Core DBMS Pillars You Must Master

You do not need to memorize every line of Python code. You only need to master these 5 DBMS concepts:

### Pillar 1: Schema Design & Third Normal Form (3NF)
- **7 Tables**: `users`, `categories`, `suppliers`, `locations`, `products`, `movements`, `audit_log`.
- **1NF**: All attributes are atomic scalar values (no arrays or comma-separated lists stored in columns); each table has a designated primary key (`id`).
- **2NF**: All non-key attributes are fully functionally dependent on the entire primary key (since every table uses a single-attribute surrogate key `id`, partial key dependency is mathematically impossible).
- **3NF & Elimination of Transitive Dependencies**:
  - Category details live strictly in `categories` (`products.category_id` references `categories.id`).
  - Warehouse names/codes live strictly in `locations` (`movements.location_id` references `locations.id`).
  - Supplier info lives strictly in `suppliers` (`movements.supplier_id` references `suppliers.id`).
  - **The Golden Rule**: *Derived data is never stored.* Storing `current_stock` or `total_valuation` in `products` would violate 3NF and introduce update anomalies. Instead, they are computed dynamically via SQL views.

### Pillar 2: Relational Views (Derived State)
- **Question:** *"If there is no stock column, how do you know how much stock exists?"*
- **Answer:** We use compiled SQL views:
  1. **`v_inventory_summary`**: Computes global stock:
     ```sql
     COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.qty ELSE -m.qty END), 0) AS current_stock
     ```
     Also computes `total_valuation = current_stock * unit_price` and evaluates `is_low_stock` dynamically against `reorder_threshold`.
  2. **`v_location_inventory`**: Uses a `CROSS JOIN locations` and groups by `(product_id, location_id)` with `HAVING current_stock > 0` to report stock per physical warehouse.

### Pillar 3: Storage-Kernel Triggers (Defense-in-Depth)
- **Question:** *"What if someone bypasses your web server and runs SQL directly on the database file?"*
- **Answer:** The application backend is only the first layer of defense. SQLite's internal storage engine enforces 7 triggers:
  1. **`prevent_negative_stock`**: Fires `BEFORE INSERT` on `movements` when `NEW.type = 'OUT'`. It queries the view/subquery. If available balance < `NEW.qty` (either globally or at the specified location), it halts the engine via `RAISE(ABORT, 'SECURITY VIOLATION: Insufficient stock.')`.
  2. **Immutability Triggers**: `BEFORE UPDATE` and `BEFORE DELETE` triggers on `movements`, `products`, and `audit_log` immediately abort any modification or erasure.

### Pillar 4: Concurrency Control & ACID Transactions
- **Question:** *"What happens if two users try to dispatch the last remaining 5 items at the exact same millisecond?"*
- **Answer:**
  - We use **Pessimistic Concurrency Control** via `BEGIN IMMEDIATE` inside `write_tx()`:
    - Normal `BEGIN` in SQLite is deferred (it acquires a read lock and upgrades to a write lock only when writing, creating deadlock or race conditions).
    - `BEGIN IMMEDIATE` immediately acquires a reserved write lock *before* reading the current stock. Other writers must wait up to `busy_timeout = 10000ms`.
  - **Atomic Warehouse Transfers**:
    - When transferring stock from Warehouse A to Warehouse B, four operations occur in one single atomic transaction:
      1. Insert `OUT` movement for Location A.
      2. Seal `STOCK_TRANSFER_OUT` audit block.
      3. Insert `IN` movement for Location B.
      4. Seal `STOCK_TRANSFER_IN` audit block.
    - If any step fails or if Location A has insufficient stock, the trigger aborts and the transaction rolls back completely—satisfying **Atomicity** and **Consistency**.
  - **WAL (Write-Ahead Logging)**: Enabled via `PRAGMA journal_mode = WAL`. Readers do not block writers, and writers do not block readers. Changes are written to a WAL log before being checkpointed to the DB page file, ensuring crash recovery.

### Pillar 5: Cryptographic Tamper Evidence & The 5-Point Verifier
- **Question:** *"What is your audit chain and how does it prove tampering?"*
- **Answer:**
  - Every row in `products` and `movements` is paired with an entry in `audit_log`.
  - Each block stores `row_hash = HMAC_SHA256(prev_hash, id, action, actor, ref_table, ref_id, payload, timestamp)`.
  - The secret key is stored securely on the server (`data/.audit_key`).
  - **The 5 Invariant Checks (`verify_audit_chain()`):**
    1. **Contiguity ($1..N$)**: Blocks must form an unbroken sequence $1, 2, \dots, N$ (catches deleted middle rows).
    2. **Hash Linkage**: Block $N$'s `prev_hash` must equal Block $N-1$'s `row_hash` (catches row reordering).
    3. **HMAC Signature**: Recomputed keyed HMAC must match (catches direct disk edits, since an attacker lacks the secret key).
    4. **Relational Reconciliation**: Canonical JSON of every row in `products` and `movements` is compared 1:1 with `audit_log.payload` (catches direct "ghost" inserts).
    5. **Out-of-Band Head Anchor**: Chain head is checked against `data/audit_head.json` (catches tail-truncation attacks where the attacker deletes the latest block and row together).

---

## 3. The 3-Minute Live Demo Flow

Follow this exact sequence during your demonstration:

1. **Tab 1 — Inventory (Explain Derived State)**:
   - Point to the Stock numbers and warehouse badges (`WH-A1: 25`, `WH-B2: 15`).
   - *Say to Faculty:* "Notice that there is no `stock` column anywhere in the database tables. These numbers are calculated dynamically by our SQL view `v_inventory_summary` by aggregating all past `IN` and `OUT` rows."
2. **Tab 2 — Operations (Demonstrate Ledger & Transfer)**:
   - Go to the **Warehouse Transfer** form. Transfer 5 units of `SKU-LAPTOP-01` from `WH-A1` to `RETAIL-1`. Click Submit.
   - Show the Movement Ledger below: Point out that two append-only rows were inserted (`OUT` from WH-A1 and `IN` to RETAIL-1) in one atomic transaction.
   - Go back to Tab 1: Point out that global laptop stock stayed at 25, but the location badges shifted dynamically.
3. **Tab 4 — ER Diagram & Schema (Demonstrate DBMS Features)**:
   - Show the **Crow's Foot SVG ER Diagram**: Explain that it is generated dynamically using SQLite `PRAGMA foreign_key_list` and `table_info`.
   - Scroll down to **Interactive SQL & Trigger Probes**:
     - Select probe: **"Trigger Defense — Overdraft Prevention Guard"**.
     - Click Execute. Show the red banner: `SECURITY VIOLATION: Insufficient stock.`
     - Select probe: **"Trigger Defense — Block UPDATE on Movements"**.
     - Click Execute. Show that the storage engine rejects updates to ledger entries.
4. **Tab 3 — Audit Chain (Demonstrate Cryptographic Security)**:
   - Point to the **5-Point Verification Bar**: All 5 checks are green (`VERIFIED`).
   - Click **"Simulate Disk Tamper"**:
     - Explain: "This simulates an attacker directly modifying the SQLite `.db` file using a standard hex editor or unkeyed SHA-256."
     - Click **"Verify Chain"**: Show that Check #3 (Integrity) turns RED and flags block #1 as tampered.
   - Click **"Reset Database"** to cleanly restore the 12-block baseline.
5. **The "Ace Card" — Terminal SQLite Shell (`inspect_db.py`)**:
   - If the professor asks: *"Can you show me the database directly without your web UI?"*
   - Open PowerShell in the project folder and type:
     ```powershell
     python inspect_db.py --shell
     ```
   - Run:
     ```sql
     sqlite> .tables
     sqlite> .views
     sqlite> .triggers
     sqlite> SELECT * FROM v_location_inventory;
     ```

---

## 4. Top 10 Viva Questions & Exact Answers

### Q1: Why did you use SQLite instead of MySQL or PostgreSQL?
> **Answer:** *"We chose SQLite because it is an in-process, zero-configuration, ACID-compliant storage engine that stores the entire database in a single file. This allowed us to implement and demonstrate low-level storage primitives—such as custom `BEFORE` triggers that call `RAISE(ABORT)`, WAL mode concurrency, and cryptographic integrity verification down to the page/file level—without relying on heavy database server daemons."*

### Q2: Isn't running `SUM()` dynamically slower than having a `stock` column?
> **Answer:** *"In terms of raw CPU cycles, reading a static column is $O(1)$, while `SUM()` is $O(k)$ where $k$ is the number of movements for that product. However:
> 1. We indexed `movements(product_id)` with a B-Tree index, making row lookups logarithmic.
> 2. More importantly, in financial and inventory accounting, **data integrity trumps microsecond caching**. A mutable counter suffers from lost-update race conditions and zero historical provenance.
> 3. If millions of movements exist, DBMS best practice is to maintain periodic snapshot checkpoints rather than mutating individual rows."*

### Q3: What is the difference between 2NF and 3NF in your schema?
> **Answer:** 
> - *"**2NF** eliminates partial dependencies on a composite primary key. In our schema, every table uses a single-column primary key (`id`), so 2NF is automatically satisfied.
> - **3NF** eliminates transitive functional dependencies ($X \to Y \to Z$). For example, `movements` needs to know the warehouse location. If we stored `location_name` in `movements`, `movement_id \to location_id \to location_name` would be a transitive dependency. If the warehouse were renamed, we would have update anomalies. We decomposed this into a separate `locations` table, referencing only `location_id`."*

### Q4: How does `BEGIN IMMEDIATE` prevent lost updates?
> **Answer:** *"By default, SQLite uses deferred transactions: it starts with a shared READ lock and only attempts to obtain a RESERVED WRITE lock when an `INSERT` or `UPDATE` is issued. If two concurrent threads read balance=5, both see enough stock; when both try to write, one deadlocks or overdraws. `BEGIN IMMEDIATE` forces SQLite to acquire the reserved write lock upfront at the start of the transaction. The second thread must wait until the first commits, ensuring serialized execution."*

### Q5: What is the purpose of `PRAGMA foreign_keys = ON;`?
> **Answer:** *"In SQLite, for historical backward compatibility with SQLite 2, foreign key constraint enforcement is disabled by default. By executing `PRAGMA foreign_keys = ON;` immediately upon opening every connection in `get_connection()`, we ensure that SQLite strictly enforces `REFERENCES` constraints and `ON DELETE RESTRICT` rules."*

### Q6: What is Write-Ahead Logging (WAL) and why did you enable it?
> **Answer:** *"In traditional rollback journal mode, SQLite locks the entire database file during writes—readers block writers, and writers block readers. In WAL mode (`PRAGMA journal_mode = WAL`), changes are appended to a separate `-wal` file. Readers can read committed database pages while a writer appends to the WAL log concurrently, significantly increasing concurrency and throughput."*

### Q7: Why did you use HMAC-SHA256 instead of plain SHA-256 for the audit chain?
> **Answer:** *"Plain SHA-256 is an unkeyed cryptographic hash function. If an attacker gains direct write access to the `.db` file, they could alter a movement quantity, recalculate all subsequent SHA-256 hashes, and the chain would look valid. HMAC-SHA256 incorporates a secret 256-bit key (`data/.audit_key`) known only to the server kernel. An attacker cannot recalculate valid hashes without that key, making disk-level forgery mathematically impossible."*

### Q8: What is a tail-truncation attack and how does your 5th check catch it?
> **Answer:** *"If an attacker deletes the last 3 rows from both `movements` and `audit_log`, contiguity ($1..N$) is preserved, hash linkage is intact, and HMACs are valid because the earlier chain wasn't modified. This is called a **tail-truncation attack**. We prevent this by maintaining an out-of-band external anchor file (`data/audit_head.json`). Our 5th check verifies that the database chain's head matches the external anchor. If rows were truncated, the head ID and hash will mismatch."*

### Q9: Why did you use `ON DELETE RESTRICT` instead of `ON DELETE CASCADE`?
> **Answer:** *"In an audit-compliant ledger, historical records must never be accidentally destroyed. If an administrator attempts to delete a category or supplier that is referenced by past products or movements, `ON DELETE RESTRICT` causes the engine to reject the deletion with an integrity error. Furthermore, our triggers `prevent_product_delete` and `prevent_movement_delete` provide an additional layer of immutability."*

### Q10: How does your schema map to Relational Algebra?
> **Answer:**
> - **Selection ($\sigma$)**: Filtering active stock or alerts (`WHERE is_low_stock = 1`).
> - **Projection ($\pi$)**: Selecting specific attributes in `v_inventory_summary` (SKU, product name, price, stock).
> - **Cartesian Product & Joins ($\times, \bowtie$)**: `CROSS JOIN locations` combined with `LEFT OUTER JOIN movements` in `v_location_inventory` to produce the full location-stock matrix.
> - **Aggregation ($\mathcal{G}$)**: `GROUP BY product_id, location_id` with aggregate functions `SUM()` and `ROUND()`."*

---

## 5. Quick Reference Vocabulary Cheatsheet

| Term | 1-Sentence Definition to Give in Viva |
| :--- | :--- |
| **ACID** | Atomicity (all-or-nothing), Consistency (rules preserved), Isolation (independent transactions), Durability (persisted on disk). |
| **Referential Integrity** | Ensuring every foreign key value matches an existing primary key value in the referenced table. |
| **Lossless Decomposition** | Decomposing a relation $R$ into $R_1$ and $R_2$ such that joining them with a natural join ($R_1 \bowtie R_2$) reconstructs $R$ without spurious tuples. |
| **B-Tree Index** | A self-balancing tree data structure that allows logarithmic ($O(\log N)$) search, insert, and sequential range scans. |
| **Query Execution Plan** | The sequence of steps (SCAN, SEARCH via INDEX, TEMP B-TREE) generated by the DBMS optimizer to execute a query. |
| **Pessimistic Locking** | Locking a resource upfront before reading or updating it (`BEGIN IMMEDIATE`), assuming conflicts are likely. |
| **Non-Repudiation** | Ensuring that an actor cannot deny having performed an action, proven here via HMAC signing of each transaction. |

