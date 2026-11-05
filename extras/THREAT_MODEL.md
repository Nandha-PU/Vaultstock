# VaultStock: Threat Model & Security Architecture 🛡️

> **Stack:** SQLite 3 (WAL Journal Mode, Engine Triggers) + FastAPI (Python 3.13) + Vanilla JS / CSS Frontend.  
> **Security Philosophy:** Defense-in-Depth combining engine-level database triggers, cryptographic HMAC chaining, and out-of-band external anchoring.

---

## 1. Threat Actors & Capabilities

| Threat Actor | Profile | Objective |
|---|---|---|
| **Malicious Insider (Staff)** | Authenticated user with operational permissions to record inventory movements. | Divert inventory, falsify movement quantities, edit historical prices, or attempt to oversell stock. |
| **External Attacker** | Unauthenticated network adversary targeting web, API endpoints, and session mechanisms. | Stored XSS, privilege escalation, token forgery, parameter tampering, brute-forcing credentials, or DoS. |
| **File-Level Attacker / Host Intruder** | Rogue operator with read/write access to the `.db` SQLite file or server filesystem. | Directly alter records in SQLite, drop triggers, inject ghost rows, or truncate audit records. |

---

## 2. Threat Mitigation Matrix

| Threat ID | Threat Vector | Technical Mitigation in VaultStock | Enforcement Layer |
|---|---|---|---|
| **T-01** | **Direct Inventory Balance Manipulation** | Products table contains no mutable quantity column. Balances are derived dynamically from `movements`: `SUM(IN) - SUM(OUT)`. Immutability triggers on `movements` and `products` reject `UPDATE` and `DELETE`. | Database Layer (Triggers) |
| **T-02** | **Race Condition / Overselling / Chain Fork** | Parallel `OUT` requests or simultaneous writes. Mitigated by `BEGIN IMMEDIATE` SQLite write transactions in WAL mode, serializing balance validation, movement insertion, and audit ledger append atomically. | Database Concurrency Control |
| **T-03** | **Stored XSS & Injection** | Injected script tags in product names or notes (`<img onerror=...>`). Defeated by strict context-aware HTML escaping (`esc()`), elimination of inline `onclick` attributes in favor of event delegation, and Pydantic v2 strict input sanitization. | Frontend + API |
| **T-04** | **Privilege Escalation & Token Forgery** | Tampered JWT claims or staff invoking admin routes. Tokens use short TTL, non-guessable secrets (`VAULTSTOCK_JWT_SECRET`), and only contain the subject identifier (`sub`). User identity and active role are re-verified against the database on every request. | API Auth / RBAC |
| **T-05** | **Covert Audit Log Alteration** | Malicious updates to historical audit records. SQLite triggers (`prevent_audit_update`, `prevent_audit_delete`) reject application-level modifications. Cryptographic HMAC-SHA256 digests keyed by `VAULTSTOCK_AUDIT_KEY` ensure unauthorized alterations cannot be re-signed without the secret key. | Cryptographic Chain + Triggers |
| **T-06** | **Ghost / Unaudited Inventory Injections** | Attacker inserting movement rows directly into SQLite. The cryptographic audit block binds directly to `ref_table`, `ref_id`, and a canonical JSON snapshot of the row. Verification performs bidirectional reconciliation; unaudited or mismatched rows trigger immediate verification failure. | Relational Reconciliation |
| **T-07** | **Tail Truncation / Block Deletion** | Deleting newest audit blocks and movements. Verification checks contiguity ($1 \dots N$) and validates the database head against an external out-of-band anchor (`data/audit_head.json`). | External Anchoring |
| **T-08** | **Credential Harvesting & Brute Force** | Leaked hashes or password guessing. Passwords are salted with 16 random bytes and hashed using PBKDF2-HMAC-SHA256 (150,000 iterations). Login endpoint enforces sliding-window rate limiting (5 attempts per 15 minutes) and dummy verification to prevent timing attacks. | Authentication / Security |
| **T-09** | **Session Hijacking & Framing** | Theft of stored tokens or clickjacking. Tokens are maintained strictly in-memory (never in `localStorage` or ambient cookies). Cross-Origin requests are restricted via strict CORS and framing is blocked (`X-Frame-Options: DENY`, CSP `frame-ancestors: 'none'`). | Browser / HTTP Headers |

---

## 3. Defense Boundaries & Architectural Mitigations

### 1. SQLite Security Boundary vs File-Level Attackers
- **Challenge:** SQLite is an in-process library without operating-system user privilege separation. Any process with file system access to `data/vaultstock.db` can drop triggers or execute raw SQL updates.
- **Mitigation:** While database triggers protect against application-level exploits, **cryptographic HMAC verification and relational reconciliation** detect file-level attackers. Because the HMAC key (`data/.audit_key`) is stored separately from the database, file-level attackers cannot recompute valid HMAC signatures.

### 2. Tail Truncation Defense
- **Challenge:** Truncating both the tail of `movements` and `audit_log` leaves a mathematically unbroken hash prefix.
- **Mitigation:** VaultStock implements an **out-of-band anchor file** (`data/audit_head.json`). On every committed transaction, the newest block ID and HMAC digest are recorded to this anchor file atomically. The verification engine detects any disparity between the database head and the anchor checkpoint.
