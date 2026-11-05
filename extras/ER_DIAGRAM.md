# VaultStock: Entity-Relationship (ER) Diagram 📐

```mermaid
erDiagram
    PRODUCTS ||--o{ MOVEMENTS : "tracks"
    PRODUCTS ||--o| AUDIT_LOG : "audited by"
    MOVEMENTS ||--o| AUDIT_LOG : "audited by"
    USERS ||--o{ MOVEMENTS : "executes"
    USERS ||--o{ AUDIT_LOG : "attributed in"

    USERS {
        integer id PK
        text username UK
        text password_hash
        text role "admin | staff"
        datetime created_at
    }

    PRODUCTS {
        integer id PK
        text sku UK "length 3..32"
        text name "length 1..120"
        real unit_price "> 0"
        datetime created_at
    }

    MOVEMENTS {
        integer id PK
        integer product_id FK
        text type "IN | OUT"
        integer qty "1..1000000"
        text note "max 200 chars"
        text created_by "operator username"
        datetime created_at
    }

    AUDIT_LOG {
        integer id PK "sequential 1..N"
        text action "PRODUCT_CREATE | STOCK_RECEIVE | STOCK_ISSUE | DEMO_RESET"
        text actor "username or system"
        text ref_table "products | movements | NULL"
        integer ref_id "target row ID"
        text payload "canonical JSON snapshot"
        text details "human readable note"
        text timestamp "ISO 8601 UTC"
        text prev_hash "parent block HMAC-SHA256"
        text row_hash "current block HMAC-SHA256"
    }
```

---

## Relational Cardinalities & Constraints

### 1. `PRODUCTS` to `MOVEMENTS` (1 : N)
- **Cardinality:** One catalog product has zero or many historical movement entries.
- **Foreign Key:** `movements.product_id REFERENCES products(id)`.
- **Integrity Rule:** `products` cannot be deleted (`prevent_product_delete` trigger), ensuring historical movement references are permanently referentially intact.

### 2. `MOVEMENTS` to `AUDIT_LOG` (1 : 1 Polymorphic Reference)
- **Constraint:** `UNIQUE(ref_table, ref_id)` on `audit_log`.
- **Integrity Rule:** Every movement row inserted into `movements` is paired with exactly one corresponding entry in `audit_log` where `ref_table = 'movements'` and `ref_id = movements.id`.

### 3. `PRODUCTS` to `AUDIT_LOG` (1 : 1 Polymorphic Reference)
- **Constraint:** `UNIQUE(ref_table, ref_id)` on `audit_log`.
- **Integrity Rule:** Every product created is paired with an audit block where `ref_table = 'products'` and `ref_id = products.id`.

### 4. `USERS` to `MOVEMENTS` & `AUDIT_LOG` (Logical Attribution)
- Every transaction captures the authenticated username (`created_by`, `actor`) from the decoded JWT payload.

### 5. `AUDIT_LOG` to `AUDIT_LOG` (Self-Referential Cryptographic Chaining)
- Block $\#k$ embeds `prev_hash` equal to `row_hash` of block $\#(k-1)$.
- Block $\#1$ (Genesis) sets `prev_hash = "0000000000000000000000000000000000000000000000000000000000000000"`.
- Guaranteed continuous sequence without gaps via contiguity verification ($id = 1 \dots N$).

---

## Design Decision: Derived Balances vs. Mutable Quantity

| Attribute | Traditional Approach (Anti-pattern) | VaultStock Architecture |
|---|---|---|
| **Stock Storage** | Stored in `products.stock` as an integer. | **Derived attribute:** Computed on demand via `SUM(IN) - SUM(OUT)` from `movements`. |
| **Updates** | Direct `UPDATE products SET stock = stock - ?`. | **Append-only:** `INSERT INTO movements (type, qty, ...)` followed by trigger validation. |
| **Auditability** | Lost history; cannot trace when, why, or who altered quantities. | Complete chronological paper trail of every physical unit entering or leaving the vault. |
| **Concurrency Anomaly** | Lost updates, race condition oversells, phantom counts. | Serialized atomic writes (`BEGIN IMMEDIATE`), database trigger guards against negative balances. |
