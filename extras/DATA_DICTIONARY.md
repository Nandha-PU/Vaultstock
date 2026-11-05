# VaultStock: Comprehensive Data Dictionary 📖

> **Database Engine:** SQLite 3 (WAL Journal Mode, `PRAGMA foreign_keys = ON`)  
> **Schema Design:** Hardened 4-Table Minimalist Architecture with Engine Triggers and HMAC Cryptographic Auditing.

---

## 1. Table: `users`
Stores user identities, authorization credentials, and system roles for RBAC.

| Column | Data Type | Nullable | Constraints & Defaults | Description |
|---|---|---|---|---|
| `id` | `INTEGER` | NO | `PRIMARY KEY AUTOINCREMENT` | Unique monotonic user identifier. |
| `username` | `TEXT` | NO | `UNIQUE` | Case-sensitive account name (e.g., `admin`, `staff`). |
| `password_hash` | `TEXT` | NO | - | Salted `PBKDF2-HMAC-SHA256` digest (150,000 iterations, 16-byte random salt). |
| `role` | `TEXT` | NO | `CHECK(role IN ('admin', 'staff'))` | Role-based authorization tier. |
| `created_at` | `DATETIME` | YES | `DEFAULT CURRENT_TIMESTAMP` | UTC timestamp of account registration. |

### Integrity & Security Notes:
- Passwords are never stored in plaintext. Hashes follow format `pbkdf2_sha256$150000$<salt_hex>$<dk_hex>`.
- Constant-time verification (`hmac.compare_digest`) and dummy evaluations prevent timing-based user enumeration.

---

## 2. Table: `products`
Master catalog containing product metadata and unit pricing.

> **Design Principle:** There is **NO mutable quantity column**. Physical inventory balances are never stored as a mutable integer; balances are calculated dynamically from `movements`.

| Column | Data Type | Nullable | Constraints & Defaults | Description |
|---|---|---|---|---|
| `id` | `INTEGER` | NO | `PRIMARY KEY AUTOINCREMENT` | Monotonic product identifier. |
| `sku` | `TEXT` | NO | `UNIQUE CHECK(length(sku) BETWEEN 3 AND 32)` | Alphanumeric Stock Keeping Unit (e.g., `SKU-APPLE-01`). |
| `name` | `TEXT` | NO | `CHECK(length(trim(name)) BETWEEN 1 AND 120)` | Product commercial description. |
| `unit_price` | `REAL` | NO | `CHECK(unit_price > 0 AND unit_price <= 10000000)` | Unit selling price in USD (must be strictly positive). |
| `created_at` | `DATETIME` | YES | `DEFAULT CURRENT_TIMESTAMP` | UTC timestamp of catalog entry creation. |

### Database Triggers on `products`:
1. **`prevent_product_update`** (`BEFORE UPDATE ON products`):
   - Aborts query with `'SECURITY VIOLATION: Products are immutable; create a new SKU.'`.
   - Prevents retroactive price alterations or covert tampering with existing product lines.
2. **`prevent_product_delete`** (`BEFORE DELETE ON products`):
   - Aborts query with `'SECURITY VIOLATION: Products cannot be deleted.'`.
   - Guarantees historical movements will never reference an orphaned product ID.

---

## 3. Table: `movements` (The Immutable Ledger)
Append-only transactional ledger tracking every receipt (`IN`) and issuance (`OUT`) of stock.

| Column | Data Type | Nullable | Constraints & Defaults | Description |
|---|---|---|---|---|
| `id` | `INTEGER` | NO | `PRIMARY KEY AUTOINCREMENT` | Sequential transaction receipt number. |
| `product_id` | `INTEGER` | NO | `REFERENCES products(id)` | Foreign key linking movement to catalog product. |
| `type` | `TEXT` | NO | `CHECK(type IN ('IN', 'OUT'))` | Stock direction: `IN` (receive) or `OUT` (issue). |
| `qty` | `INTEGER` | NO | `CHECK(typeof(qty) = 'integer' AND qty BETWEEN 1 AND 1000000)` | Quantity transacted (strictly positive integer). |
| `note` | `TEXT` | YES | `CHECK(note IS NULL OR length(note) <= 200)` | Optional operational reason or manifest identifier. |
| `created_by` | `TEXT` | NO | - | Username of the authenticated operator who recorded the transaction. |
| `created_at` | `DATETIME` | YES | `DEFAULT CURRENT_TIMESTAMP` | UTC timestamp of ledger entry. |

### Derived Attribute:
- Current available inventory balance is computed on demand:
  ```sql
  SELECT p.id, p.sku, p.name, p.unit_price,
         COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.qty ELSE -m.qty END), 0) AS current_stock
  FROM products p
  LEFT JOIN movements m ON p.id = m.product_id
  GROUP BY p.id;
  ```

### Database Triggers on `movements`:
1. **`prevent_negative_stock`** (`BEFORE INSERT ON movements WHEN NEW.type = 'OUT'`):
   - Computes current stock and aborts with `'SECURITY VIOLATION: Insufficient stock.'` if available balance is strictly less than `NEW.qty`.
   - Engine-level defense-in-depth against race-condition overdrafts.
2. **`prevent_movement_update`** (`BEFORE UPDATE ON movements`):
   - Aborts with `'SECURITY VIOLATION: Ledger entries are immutable and cannot be updated.'`.
3. **`prevent_movement_delete`** (`BEFORE DELETE ON movements`):
   - Aborts with `'SECURITY VIOLATION: Ledger entries are immutable and cannot be deleted.'`.

---

## 4. Table: `audit_log` (The Cryptographic Audit Chain)
Cryptographically chained, tamper-evident log capturing all state changes with HMAC-SHA256 digests.

| Column | Data Type | Nullable | Constraints & Defaults | Description |
|---|---|---|---|---|
| `id` | `INTEGER` | NO | `PRIMARY KEY` | Strictly monotonic block height ($1 \dots N$). |
| `action` | `TEXT` | NO | - | Event type (`PRODUCT_CREATE`, `STOCK_RECEIVE`, `STOCK_ISSUE`, `DEMO_RESET`). |
| `actor` | `TEXT` | NO | - | Username or `system` responsible for triggering the action. |
| `ref_table` | `TEXT` | YES | - | Entity table linked to this block (`products`, `movements`, or `NULL`). |
| `ref_id` | `INTEGER` | YES | - | Primary key ID of the entity row in `ref_table`. |
| `payload` | `TEXT` | NO | - | Sorted canonical JSON snapshot of the underlying table row. |
| `details` | `TEXT` | NO | - | Human-readable audit narrative. |
| `timestamp` | `TEXT` | NO | - | High-precision ISO 8601 UTC timestamp. |
| `prev_hash` | `TEXT` | NO | - | 64-character hex digest of block $\#(id - 1)$ (`0` * 64 for genesis block #1). |
| `row_hash` | `TEXT` | NO | - | HMAC-SHA256 signature calculated over all block fields using `VAULTSTOCK_AUDIT_KEY`. |

### Constraints:
- `UNIQUE(ref_table, ref_id)`: Enforces exact 1-to-1 relationship between relational database entities and audit blocks.
- **`prevent_audit_update`** (`BEFORE UPDATE ON audit_log`): Aborts with `'SECURITY VIOLATION: Audit log is immutable.'`.
- **`prevent_audit_delete`** (`BEFORE DELETE ON audit_log`): Aborts with `'SECURITY VIOLATION: Audit log is immutable.'`.

### Cryptographic Hash Construction:
$$\text{row\_hash} = \text{HMAC-SHA256}_{K}(\text{canonical\_json}([\text{prev\_hash}, \text{id}, \text{action}, \text{actor}, \text{ref\_table}, \text{ref\_id}, \text{payload}, \text{timestamp}]))$$
where $K$ is the secret key loaded from `data/.audit_key` or `VAULTSTOCK_AUDIT_KEY`.
