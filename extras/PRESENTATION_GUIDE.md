# 🎓 VaultStock: Presentation & Viva Guide

> **Project Concept**: Minimalist, Tamper-Evident Inventory Ledger with Relational Integrity and Cryptographic Non-Repudiation.  
> **Core Principle**: *"You never edit an inventory number. You record an append-only event, and the database mathematically guarantees nobody can tamper with history."*

---

## ⏱️ The 30-Second Elevator Pitch

> *"Most traditional inventory systems update a mutable counter like `UPDATE products SET stock = stock - 5`. This causes lost update race conditions, phantom reads, and leaves zero forensic evidence if an insider commits fraud.  
> **VaultStock** solves this through two core database principles:  
> 1. An **immutable append-only ledger**: balances are derived dynamically via `SUM(IN) - SUM(OUT)`. Engine triggers permanently abort any `UPDATE` or `DELETE` query.  
> 2. A **cryptographic audit chain**: every transaction produces an HMAC-SHA256 block cryptographically bound to the referenced row. If any actor alters a past record directly in the SQLite database file, the mathematical chain breaks and sounds an immediate alert."*

---

## 🔑 Demo Credentials

| Role | Username | Password | Capabilities |
|---|---|---|---|
| **Admin** | `admin` | `vault-admin-2026` | Create products, record `IN`/`OUT` stock, verify chain, simulate tampering, reset DB |
| **Staff** | `staff` | `vault-staff-2026` | Record `IN`/`OUT` stock, view movements, verify audit chain |

---

## 🏛️ The 3 DBMS Concepts You Are Demonstrating

### 1. Dynamic Attribute Derivation (Zero Redundant Stored Balances)
- **Concept**: Derived attributes vs. base attributes (Normalization & Concurrency).
- **Implementation**: The `products` table has **no** mutable `stock` column.
- **SQL Query**:
  ```sql
  SELECT p.id, p.sku, p.name, p.unit_price,
         COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.qty ELSE -m.qty END), 0) AS current_stock
  FROM products p
  LEFT JOIN movements m ON p.id = m.product_id
  GROUP BY p.id;
  ```
- **Why it matters**: Zero risk of desynchronization between historical movements and reported balance.

### 2. Database-Enforced Immutability (Triggers & Constraints)
- **Concept**: Active database integrity rules operating below the application layer.
- **Implementation**: SQLite `BEFORE UPDATE` and `BEFORE DELETE` triggers on `movements`, `products`, and `audit_log`:
  ```sql
  CREATE TRIGGER prevent_movement_update
  BEFORE UPDATE ON movements
  BEGIN
      SELECT RAISE(ABORT, 'SECURITY VIOLATION: Ledger entries are immutable and cannot be updated.');
  END;
  ```
- **Negative Stock Trigger**:
  ```sql
  CREATE TRIGGER prevent_negative_stock
  BEFORE INSERT ON movements
  WHEN NEW.type = 'OUT'
  BEGIN
      SELECT RAISE(ABORT, 'SECURITY VIOLATION: Insufficient stock.')
      WHERE (SELECT COALESCE(SUM(CASE WHEN type = 'IN' THEN qty ELSE -qty END), 0)
             FROM movements WHERE product_id = NEW.product_id) < NEW.qty;
  END;
  ```
- **Why it matters**: Even if an application bug or rogue SQL query attempts to overwrite ledger history or oversell inventory, the database engine aborts the transaction.

### 3. Cryptographic Non-Repudiation (HMAC-SHA256 Audit Chain)
- **Concept**: Blockchain-style tamper-evident ledger with keyed message authentication.
- **Formula**:
  $$\text{row\_hash} = \text{HMAC-SHA256}_{K}(\text{canonical\_json}([\text{prev\_hash}, \text{id}, \text{action}, \text{actor}, \text{ref\_table}, \text{ref\_id}, \text{payload}, \text{timestamp}]))$$
- **5-Point Verification Scan (`verify_audit_chain()`):**
  1. **Contiguity:** Block IDs form a strictly continuous sequence ($1, 2, \dots, N$) with zero missing gaps.
  2. **Linkage:** Every block's `prev_hash` equals the preceding block's `row_hash`.
  3. **HMAC Integrity:** Every block's recomputed HMAC-SHA256 matches its stored signature.
  4. **Relational Reconciliation:** Every product and movement row exactly matches its audited JSON snapshot.
  5. **Anchor Check:** The latest chain head matches an out-of-band anchor file (`data/audit_head.json`).

---

## 🎬 The 2-Minute Live Demo Script (Step-by-Step)

Follow this sequence during your project evaluation:

| Step | Action on Screen | What to Say to the Evaluator |
|---|---|---|
| **1. Sign In** | Open [http://localhost:3000](http://localhost:3000). Sign in as `admin` / `vault-admin-2026`. | *"Notice our clean interface. The top status panel shows 'Audit Chain Intact' with 100% cryptographic verification."* |
| **2. Dynamic Stock** | Click **IN / OUT** on *MacBook Pro 16-inch M3* $\rightarrow$ Type: `IN`, Qty: `10`, Note: `"Supplier Batch"`. Click **Submit**. | *"When I receive 10 units, notice that stock increments dynamically from 25 to 35, a new row is appended to the ledger, and an HMAC audit block is generated."* |
| **3. Negative Stock Guard** | Click **IN / OUT** on any product $\rightarrow$ Type: `OUT`, Qty: `9999`. Click **Submit**. | *"The system immediately aborts the transaction with 'Insufficient inventory'. The database trigger prevents overdrafts even under concurrent requests."* |
| **4. The Wow Moment: Tamper Simulation** | Click the red button: **"Simulate Tamper (Block #1)"**. | *"Now, imagine a rogue attacker gains direct database access or uses a raw SQLite client to alter historical row #1 behind the scenes."* |
| **5. Verification Catch** | Click **"Verify Audit Chain"**. | *The banner turns glowing red with an alert: `Verification Failed: HMAC mismatch in block #1: data was altered`.*<br>*"The mathematical verification walked the chain and caught the altered payload digest immediately."* |
| **6. Reset Demo** | Click **"Reset DB"** $\rightarrow$ Confirm. | *"A single click restores the database to a pristine, reseeded state with zero anomalies."* |

---

## ❓ Top 8 Viva / Oral Exam Questions & Sharp Answers

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
> **Answer**: *"Hash chaining only proves the audit log wasn't altered. Relational reconciliation cross-checks the actual operational tables (`products`, `movements`) against the JSON payloads stored inside the audit blocks. If someone injects a 'ghost' row directly into `movements` without an audit entry, the verifier catches it."*

### Q7: How does your password storage adhere to security standards?
> **Answer**: *"We use salted PBKDF2 with HMAC-SHA256 and 150,000 iterations using a 16-byte cryptographically secure random salt. Comparisons are constant-time (`hmac.compare_digest`), and dummy hash evaluations run for non-existent users to eliminate timing attacks."*

### Q8: How does this design scale to millions of records?
> **Answer**: *"For enterprise scale, the append-only ledger pattern allows periodic balance snapshots. Every month, a snapshot row is created, and balances are computed by summing the snapshot plus subsequent delta movements, maintaining high query speed while preserving immutable history."*
