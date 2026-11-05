# VaultStock: Relational Normalization & Functional Dependencies 🔬

This document provides formal mathematical and relational proofs demonstrating that the VaultStock database schema adheres strictly to **Third Normal Form (3NF)** and **Boyce-Codd Normal Form (BCNF)**.

---

## 1. First Normal Form (1NF)

A relation $R$ satisfies 1NF if and only if:
1. Every attribute contains only atomic (indivisible) scalar values.
2. There are no repeating groups, multivalue arrays, or comma-separated lists.
3. A unique primary key exists for every tuple.

### Verification by Table:
- **`users`**: All attributes (`id`, `username`, `password_hash`, `role`, `created_at`) are atomic scalar values.
- **`products`**: `sku`, `name`, and `unit_price` are single scalar values.
- **`movements`**: Each movement records one discrete atomic stock event (`IN` or `OUT`) for a specific product.
- **`audit_log`**: The `payload` field contains a serialized canonical JSON object representing the immutable state snapshot of an entity at a point in time; it is treated as an indivisible cryptographic digest input rather than queried for decomposed attributes.
- **Conclusion:** All relations strictly satisfy **1NF**.

---

## 2. Second Normal Form (2NF)

A relation $R$ is in 2NF if:
1. It is in 1NF.
2. No non-prime attribute is partially functionally dependent on any proper subset of any candidate key.

### Verification by Candidate Keys:
- **`users`**: Candidate keys are `{id}` and `{username}` (both are single-attribute keys).
- **`products`**: Candidate keys are `{id}` and `{sku}` (both are single-attribute keys).
- **`movements`**: Candidate key is `{id}` (single-attribute key).
- **`audit_log`**: Candidate keys are `{id}` and composite candidate key `{ref_table, ref_id}` for audited entity rows.

### Theorem on Single-Attribute Keys:
> *If all candidate keys of a relation $R$ consist of a single attribute, then no partial functional dependency can mathematically exist, and $R$ is automatically in 2NF.*

For composite key `{ref_table, ref_id}` in `audit_log`:
- Neither `ref_table` alone nor `ref_id` alone determines any non-prime attribute (an ID alone without a table is ambiguous; a table name alone does not determine any row's payload or details).
- All non-prime attributes depend on the complete key `{ref_table, ref_id}` as well as the primary key `{id}`.

**Conclusion:** All relations strictly satisfy **2NF**.

---

## 3. Third Normal Form (3NF) & Boyce-Codd Normal Form (BCNF)

A relation $R$ is in **3NF** if, for every non-trivial functional dependency $X \to Y$:
- $X$ is a superkey of $R$, **OR**
- $Y$ is a prime attribute (part of a candidate key).

A relation $R$ is in **BCNF** if, for every non-trivial functional dependency $X \to Y$, $X$ is a superkey.

---

### Detailed Entity Analysis

#### 1. Relation: `users`
- **Attributes:** $\{ \text{id}, \text{username}, \text{password\_hash}, \text{role}, \text{created\_at} \}$
- **Candidate Keys:** $CK_1 = \{ \text{id} \}$, $CK_2 = \{ \text{username} \}$
- **Functional Dependencies:**
  1. $\text{id} \to \{ \text{username}, \text{password\_hash}, \text{role}, \text{created\_at} \}$
  2. $\text{username} \to \{ \text{id}, \text{password\_hash}, \text{role}, \text{created\_at} \}$
- **Evaluation:** Every determinant ($\text{id}$ and $\text{username}$) is a candidate key (and therefore a superkey). There are no transitive dependencies ($A \to B \to C$).
- **Status:** **3NF and BCNF Satisfied.**

---

#### 2. Relation: `products`
- **Attributes:** $\{ \text{id}, \text{sku}, \text{name}, \text{unit\_price}, \text{created\_at} \}$
- **Candidate Keys:** $CK_1 = \{ \text{id} \}$, $CK_2 = \{ \text{sku} \}$
- **Functional Dependencies:**
  1. $\text{id} \to \{ \text{sku}, \text{name}, \text{unit\_price}, \text{created\_at} \}$
  2. $\text{sku} \to \{ \text{id}, \text{name}, \text{unit\_price}, \text{created\_at} \}$
- **Evaluation:** Both determinants are superkeys. No transitive dependencies exist between non-prime attributes.
- **Normalization Architectural Decision (Derived Attribute):**
  - Storing a `current_stock` column inside `products` would introduce redundant, mutable state:
    $$\text{current\_stock} = \sum_{\text{movements}} \text{qty}_{\text{IN}} - \sum_{\text{movements}} \text{qty}_{\text{OUT}}$$
  - Storing this calculated value in `products` would violate normalization by duplicating state already determined by `movements`, causing update anomalies and lost updates under concurrency.
  - Omission of the redundant attribute preserves pure 3NF/BCNF.
- **Status:** **3NF and BCNF Satisfied.**

---

#### 3. Relation: `movements`
- **Attributes:** $\{ \text{id}, \text{product\_id}, \text{type}, \text{qty}, \text{note}, \text{created\_by}, \text{created\_at} \}$
- **Candidate Keys:** $CK = \{ \text{id} \}$
- **Functional Dependencies:**
  1. $\text{id} \to \{ \text{product\_id}, \text{type}, \text{qty}, \text{note}, \text{created\_by}, \text{created\_at} \}$
- **Foreign Keys:**
  - $\text{product\_id} \to \text{products}(\text{id})$
- **Evaluation:**
  - The relation does not embed product metadata (e.g. `product_name`, `unit_price`, `sku`); it references only `product_id`. Storing `product_name` in `movements` would create a transitive dependency ($\text{id} \to \text{product\_id} \to \text{product\_name}$), violating 3NF.
  - The determinant ($\text{id}$) is a superkey.
- **Status:** **3NF and BCNF Satisfied.**

---

#### 4. Relation: `audit_log`
- **Attributes:** $\{ \text{id}, \text{action}, \text{actor}, \text{ref\_table}, \text{ref\_id}, \text{payload}, \text{details}, \text{timestamp}, \text{prev\_hash}, \text{row\_hash} \}$
- **Candidate Keys:**
  1. $CK_1 = \{ \text{id} \}$
  2. $CK_2 = \{ \text{ref\_table}, \text{ref\_id} \}$ (for rows referencing entity records)
- **Functional Dependencies:**
  1. $\text{id} \to \{ \text{action}, \text{actor}, \text{ref\_table}, \text{ref\_id}, \text{payload}, \text{details}, \text{timestamp}, \text{prev\_hash}, \text{row\_hash} \}$
  2. $\{ \text{ref\_table}, \text{ref\_id} \} \to \{ \text{id}, \text{action}, \text{actor}, \text{payload}, \text{details}, \text{timestamp}, \text{prev\_hash}, \text{row\_hash} \}$
- **Evaluation:**
  - Because `audit_log` is an append-only cryptographic ledger, each block represents an immutable historical record.
  - Every determinant is a candidate key.
- **Status:** **3NF and BCNF Satisfied.**

---

## Summary of Normalization Analysis

| Table | 1NF | 2NF | 3NF | BCNF | Key Justification |
|---|:---:|:---:|:---:|:---:|---|
| `users` | ✅ | ✅ | ✅ | ✅ | Single-attribute candidate keys (`id`, `username`); no transitive dependencies. |
| `products` | ✅ | ✅ | ✅ | ✅ | Redundant running balance omitted; derived dynamically from ledger. |
| `movements` | ✅ | ✅ | ✅ | ✅ | No duplicated catalog attributes; references normalized `product_id`. |
| `audit_log` | ✅ | ✅ | ✅ | ✅ | Immutable ledger with strict $1 \dots N$ sequence and candidate key parity. |
