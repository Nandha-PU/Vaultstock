# 🎓 VaultStock — Viva Defense & Teammate Presentation Guide

> **Project Title**: VaultStock — Relational Inventory Management & Cryptographic Audit Ledger<br>
> **Course Domain**: Database Management Systems (DBMS), Relational Database Design & Information Security<br>
> **Target Audience**: Evaluation Committee, External Examiners, and Course Professors

---

## ⚡ 1. The 30-Second Elevator Pitch
*(Memorize this word-for-word. Anyone on the team can use this as an opening statement)*

> *"Traditional inventory systems store a mutable counter like `UPDATE products SET stock = stock - 5`. This introduces lost-update race conditions, leaves no forensic evidence if an employee covers up theft, and violates 3NF normalization.<br>
> **VaultStock** solves this through two core engineering principles:<br>
> 1. **An Immutable Append-Only Ledger**: We never store a stock quantity. Balances are dynamically calculated via SQL aggregation `SUM(IN) - SUM(OUT)`, and database triggers permanently block `UPDATE` and `DELETE` queries.<br>
> 2. **A Cryptographic Audit Chain**: Every transaction is sealed into an HMAC-SHA256 audit block chained to the previous block—**exactly like Git commits**. If an unauthorized DBA or insider edits the SQLite file directly on disk, the mathematical chain breaks and alerts the system instantly."*

---

## 💡 2. The Git Commit Analogy (How to explain the security in 15 seconds)

If the professor asks: *"Why do you have HMAC hashes in a database project?"*

**Answer:**
> *"Think of our audit log like **Git commits**. Each commit stores the commit hash of its parent. In VaultStock, every stock transaction stores the hash of the previous transaction (`prev_hash`).<br>
> If an attacker tampers with transaction #1, row #1's hash changes. Immediately, row #2's `prev_hash` no longer matches, and the system flags the database as corrupted. It gives our database mathematical **non-repudiation**."*

---

## 👥 3. Three-Member Team Role Distribution
*(Assign these exact roles to your teammates so everyone has an impressive, clearly defined contribution)*

### 🗣️ Speaker 1: Relational Schema & Normalization (2 Minutes)
* **What you explain**:
  1. **The 3NF Normalized Schema**: Show the ER diagram. Point out `categories`, `suppliers`, `locations`, `products`, and `movements`.
  2. **Elimination of Derived Data**: Explain that the `products` table intentionally has **no `quantity` column**. Storing derived data causes update anomalies. Instead, we use the relational view `v_inventory_summary` to derive live stock and total inventory valuation (`stock * unit_price`).
  3. **Foreign Keys & Referential Actions**: Explain that `category_id`, `supplier_id`, and `location_id` maintain referential integrity with `ON DELETE RESTRICT` so historical references cannot be orphaned.

### 🗣️ Speaker 2: Business Rules, Triggers & Views (2 Minutes)
* **What you explain**:
  1. **Negative Stock Guard (`prevent_negative_stock`)**: Show the `BEFORE INSERT` trigger on `movements`. When an outward dispatch is attempted (`type = 'OUT'`), the trigger executes a subquery calculating current stock. If stock is insufficient, the trigger executes `RAISE(ABORT)`, guaranteeing that inventory can never drop below zero even under concurrent requests.
  2. **Append-Only Immutability**: Explain that historical movements and audit logs can never be altered or deleted. The triggers `prevent_movement_update` and `prevent_movement_delete` intercept any rogue SQL query.
  3. **Reorder Alert View (`v_low_stock_alerts`)**: Explain how the SQL view dynamically detects items where `current_stock <= reorder_threshold`, driving the low-stock warning banner in the UI.

### 🗣️ Speaker 3: Security Architecture & Live Demo (2 Minutes)
* **What you demonstrate**:
  1. **Walkthrough of Dashboard**: Open `http://localhost:3000`. Show the Inventory tab with real-time stock balances and valuation.
  2. **Record a Transaction**: Go to **Stock Operations**. Record a stock receipt from a supplier, then record an outward dispatch.
  3. **The Live Tamper Demonstration**:
     * Switch to the **Audit & Tamper Demo** tab. Show the green `100% VERIFIED` status.
     * Click **"Simulate File Tamper"**: Explain that this simulates an attacker editing the raw database file on disk, bypassing database triggers.
     * Click **"Run 5-Point Integrity Scan"**: The banner immediately turns **RED** (`TAMPER DETECTED at Block #1`), showing that the HMAC signature check failed.
     * Click **"Reset Database"** to show it returns to clean green baseline.

---

## 🎯 4. Top 10 Tough Professor Questions & Exact Answers

#### Q1: "Why did you use SQLite instead of MySQL or PostgreSQL?"
> **Answer**: *"SQLite provides engine-level ACID compliance, Write-Ahead Logging (`WAL`), and trigger execution in a self-contained, zero-configuration engine. More importantly, SQLite allows us to demonstrate disk-level physical file tampering simulations that would otherwise require root server access in a client-server RDBMS."*

#### Q2: "Isn't calculating stock dynamically with `SUM(IN) - SUM(OUT)` slow for large databases?"
> **Answer**: *"In VaultStock, we created a B-Tree index on `movements(product_id)`. The SQLite query planner performs an indexed search on each product rather than a full table scan. In enterprise high-volume systems, this is paired with periodic checkpoint snapshots (materialized views), while keeping the ledger append-only."*

#### Q3: "What prevents an admin from updating the `audit_log` directly?"
> **Answer**: *"Two layers of defense: First, engine triggers `prevent_audit_update` and `prevent_audit_delete` abort any SQL query. Second, if a rogue administrator bypasses the triggers directly on the disk file, they don't possess the secret external HMAC key (`.audit_key`). Any recalculated hash will fail our constant-time HMAC verification scan."*

#### Q4: "What normal form is your database in?"
> **Answer**: *"It is in **Third Normal Form (3NF)**.<br>
> • **1NF**: All attributes are atomic; no repeating groups.<br>
> • **2NF**: No partial functional dependencies (all non-key attributes depend on the entire primary key).<br>
> • **3NF**: No transitive dependencies. Category descriptions and supplier contact details are factored out into their own normalized tables rather than residing in products or movements."*

#### Q5: "What is the purpose of the out-of-band anchor file (`audit_head.json`)?"
> **Answer**: *"It prevents **Tail-Truncation attacks**. If an attacker deletes the most recent 5 transactions from the SQLite database file, the remaining blocks would still have unbroken links! But because our external anchor file stores the head block ID and hash, the system detects that the database head does not match the external anchor."*

#### Q6: "Why don't you allow updating product names or prices in the `products` table?"
> **Answer**: *"To prevent retroactive audit distortion. In loss-prevention auditing, if an item's price or SKU changes retroactively, historical order totals become invalid. Our referential guard trigger `prevent_product_delete` ensures movements can never point to a deleted product."*

#### Q7: "What happens if two users try to dispatch the last unit of stock at the exact same millisecond?"
> **Answer**: *"We use atomic `BEGIN IMMEDIATE;` write transactions in SQLite WAL mode. This acquires an immediate exclusive reservation lock on the database before reading the balance, serializing the operations. The first transaction succeeds; the second transaction is rejected by the `prevent_negative_stock` trigger."*

#### Q8: "How does your system prevent SQL Injection?"
> **Answer**: *"100% of our SQL statements use parameterized queries (`?` placeholders) with strict Pydantic v2 input sanitization. String concatenation is never used to build queries."*

#### Q9: "Why did you create relational views like `v_inventory_summary`?"
> **Answer**: *"Views encapsulate complex business logic (dynamic balance aggregation, category joins, valuation computation, and low-stock threshold evaluation) directly within the database engine. This prevents code duplication and keeps application code clean."*

#### Q10: "What does the 5-Point Integrity Scan actually check?"
> **Answer**:
> 1. **Contiguity**: Block IDs are strictly $1, 2, \dots, N$ without missing numbers.
> 2. **Linkage**: Every block's `prev_hash` matches the prior block's `row_hash`.
> 3. **HMAC Signature**: Recomputed HMAC-SHA256 matches the stored digest.
> 4. **Relational Reconciliation**: Products and movements match their audit JSON snapshots (catches unlogged ghost rows).
> 5. **Anchor Check**: Database head matches `data/audit_head.json` (catches tail truncation).

---

## 🖥️ 5. Two-Minute Live Presentation Script

1. **Step 1: Sign in**:
   * Open `http://localhost:3000`. Click **"Sign in as Admin"**.
2. **Step 2: Show Inventory Tab**:
   * Point out the 4 KPI cards (Catalog Products, Units in Stock, Total Valuation, Reorder Alerts).
   * Show that each row has Category, Unit Price, Stock, Valuation, and Status.
3. **Step 3: Show Stock Operations Tab**:
   * Receive 10 units of an item from a supplier with reference doc `PO-2026-DEMO`.
   * Issue 2 units with note `Client dispatch`.
   * Show the updated Enriched Movement Ledger below.
4. **Step 4: Show Engine Diagnostics Tab**:
   * Show the active SQLite PRAGMAs (WAL mode, Foreign Keys ON).
   * Click **"EXPLAIN Stock Query Plan"** to show SQLite's execution tree.
   * Click **"Test Overdraft Trigger"** to show the real-time interception (`SECURITY VIOLATION: Insufficient stock`).
5. **Step 5: The Climax — Tamper Detection**:
   * Switch to **Audit & Tamper Demo**.
   * Show the 5 green checkmarks.
   * Click **"Simulate File Tamper"**.
   * Click **"Run 5-Point Integrity Scan"** $\rightarrow$ **Massive Red Alert!** Point to the failed checkmark and the exact block identified.
   * Click **"Reset Database"** $\rightarrow$ Restores clean state.
