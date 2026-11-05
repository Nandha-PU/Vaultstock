# VaultStock: Entity-Relationship (ER) Diagram 📐

```mermaid
erDiagram
    CATEGORIES ||--o{ PRODUCTS : "classifies (1:N)"
    SUPPLIERS ||--o{ MOVEMENTS : "supplies (1:N)"
    LOCATIONS ||--o{ MOVEMENTS : "stores (1:N)"
    PRODUCTS ||--o{ MOVEMENTS : "tracks (1:N)"
    PRODUCTS ||--o| AUDIT_LOG : "audited by (1:1)"
    MOVEMENTS ||--o| AUDIT_LOG : "audited by (1:1)"
    USERS ||--o{ MOVEMENTS : "authorizes"
    USERS ||--o{ AUDIT_LOG : "attributed in"

    USERS {
        integer id PK
        text username UK
        text password_hash
        text role "admin | staff"
        datetime created_at
    }

    CATEGORIES {
        integer id PK
        text code UK "2..16 chars"
        text name "1..80 chars"
        text description
        datetime created_at
    }

    SUPPLIERS {
        integer id PK
        text name UK "2..100 chars"
        text contact_email
        text phone
        datetime created_at
    }

    LOCATIONS {
        integer id PK
        text code UK "e.g. WH-A1"
        text name "1..80 chars"
        datetime created_at
    }

    PRODUCTS {
        integer id PK
        text sku UK "length 3..32"
        text name "length 1..120"
        integer category_id FK
        real unit_price "> 0"
        integer reorder_threshold ">= 0"
        datetime created_at
    }

    MOVEMENTS {
        integer id PK
        integer product_id FK
        integer supplier_id FK "Nullable (for IN receipts)"
        integer location_id FK
        text type "IN | OUT"
        integer qty "1..1000000"
        text reference_doc "PO / Dispatch Slip"
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

### 1. `CATEGORIES` to `PRODUCTS` (1 : N)
- **Cardinality:** One product category classifies one or more catalog products.
- **Foreign Key:** `products.category_id REFERENCES categories(id) ON DELETE RESTRICT`.

### 2. `SUPPLIERS` to `MOVEMENTS` (1 : N)
- **Cardinality:** One supplier can fulfill zero or multiple inward stock receipts (`IN`).
- **Foreign Key:** `movements.supplier_id REFERENCES suppliers(id) ON DELETE RESTRICT`.

### 3. `LOCATIONS` to `MOVEMENTS` (1 : N)
- **Cardinality:** One warehouse/retail location holds multiple stock movement transactions.
- **Foreign Key:** `movements.location_id REFERENCES locations(id) ON DELETE RESTRICT`.

### 4. `PRODUCTS` to `MOVEMENTS` (1 : N)
- **Cardinality:** One catalog product has multiple historical ledger entries.
- **Foreign Key:** `movements.product_id REFERENCES products(id) ON DELETE RESTRICT`.
- **Integrity Rule:** `products` cannot be deleted (`prevent_product_delete` trigger) to ensure referential integrity for historical movements.

### 5. `MOVEMENTS` & `PRODUCTS` to `AUDIT_LOG` (1 : 1 Polymorphic Reference)
- **Constraint:** `UNIQUE(ref_table, ref_id)` on `audit_log`.
- **Integrity Rule:** Every product creation and movement insertion is paired with exactly one cryptographic audit block.

### 6. `AUDIT_LOG` to `AUDIT_LOG` (Self-Referential Cryptographic Chaining)
- Block $\#k$ stores `prev_hash` equal to `row_hash` of block $\#(k-1)$.
- Block $\#1$ (Genesis) sets `prev_hash = "0000000000000000000000000000000000000000000000000000000000000000"`.
- Guaranteed continuous sequence without gaps via contiguity verification ($id = 1 \dots N$).
