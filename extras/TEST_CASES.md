# VaultStock: Test Cases & Security Regression Matrix 🧪

This document specifies the complete test matrix implemented in [`extras/test_suite.py`](file:///d:/DBMS%20Project/vaultstock/extras/test_suite.py).

---

## 1. Security Regression Matrix (T1 – T22)

The 22 security checks verify resilience against attacks identified in the threat model:

| # | Test Case | Target / Input | Expected Result | Layer |
|---|---|---|---|---|
| **T1** | Unauthenticated Reset Demo | `POST /api/reset-demo` without Bearer token | `401 Unauthorized` | API Auth |
| **T2** | Unauthenticated Product List | `GET /api/products` without token | `401 Unauthorized` | API Auth |
| **T3** | Unauthorized Product Creation | Staff token sent to `POST /api/products` | `403 Forbidden` (`Insufficient privileges`) | RBAC |
| **T4** | Forged JWT Secret | Token forged using old default key | `401 Unauthorized` | JWT Verification |
| **T5** | Expired JWT | Token with `exp` in the past | `401 Unauthorized` (`Session expired or token invalid`) | JWT Expiry |
| **T6** | Stored XSS Script Tag | Product name: `<img src=x onerror=alert(1)>` | Stored safely, rendered strictly escaped in client | Input Validation |
| **T7** | Stored XSS Attribute Breakout | Product name: `x" onmouseover="alert(1)` | Safely escaped; no attribute breakout | HTML Sanitization |
| **T8** | Integer Overflow DoS | Movement `qty = 10^19` | `422 Unprocessable Entity` (Pydantic range reject) | API Validation |
| **T9** | Invalid Float NaN/Infinity | Product unit_price `Infinity` | `422 Unprocessable Entity` (Strict float validator) | API Validation |
| **T10** | Concurrency Oversell Race | 20 parallel `OUT 25` requests on stock balance of 25 | Exactly 1 succeeds (200), 19 rejected (400), final bal = 0 | Concurrency Control |
| **T11** | App-Level Audit Tampering | Direct SQLite `UPDATE audit_log SET details='x' WHERE id=1` | Trigger `prevent_audit_update` aborts with `SECURITY VIOLATION` | DB Trigger |
| **T12** | File-Level Attacker with SHA-256 | Drop trigger, modify block #1, recompute plain SHA-256 | `verify` detects HMAC failure on block #1 | HMAC Signature |
| **T13** | Ghost Movement Injection | Direct SQLite `INSERT INTO movements` without audit block | `verify` detects reconciliation failure (unaudited row) | Reconciliation |
| **T14** | Deleted Audit Block (Gap) | Drop trigger, `DELETE FROM audit_log WHERE id = 3` | `verify` detects contiguity gap (missing #3) | Contiguity Check |
| **T15** | Tail Truncation Attack | Drop trigger, delete latest block + its movement | `verify` detects mismatch with external anchor file | Anchor Check |
| **T16** | Login Brute Force Throttling | 6 consecutive invalid passwords within 15 minutes | 6th attempt returns `429 Too Many Requests` + `Retry-After` | Rate Limiter |
| **T17** | User Enumeration Timing | Login with unknown username vs wrong password | Identical 401 error message and dummy PBKDF2 hash time | Auth Timing |
| **T18** | Public API Docs Exposure | `GET /docs` and `GET /openapi.json` with `DEMO_MODE=0` | `404 Not Found` | Production Hardening |
| **T19** | Clickjacking / Frame Defense | Load API inside an `<iframe>` on foreign origin | Blocked by `X-Frame-Options: DENY` & CSP `frame-ancestors: 'none'` | Security Headers |
| **T20** | Duplicate SKU Error Masking | Create product with existing SKU code | `409 Conflict: SKU already exists` (clean error) | DB Exception Masking |
| **T21** | Hardcoded Credential Scan | Source code scan for legacy hardcoded passwords | Zero occurrences across `web/` and `api/` | Secrets Hygiene |
| **T22** | Movement Immutability Trigger | Direct `UPDATE` or `DELETE` on `movements` table | Triggers `prevent_movement_update` / `delete` abort | DB Trigger |
| **T23** | Missing Anchor File Detection | Delete external anchor file while ledger has records | `verify` detects anchor failure | Anchor Validation |
| **T24** | Corrupted JSON Payload | Corrupt block payload text in SQLite | Handled gracefully by `verify` without 500 error | Exception Hardening |
| **T25** | Malformed JWT Subject | Non-numeric `sub` claim in valid signature | `401 Unauthorized` (not 500 error) | Auth Hardening |
| **T26** | Feed Pagination | `GET /api/movements` and `/api/audit` with `limit`/`offset` | Subsets returned matching requested window | API Capabilities |
| **T27** | Public Config Endpoint | `GET /api/config` without token | Returns `200 OK` with `demo_mode` boolean | Client Adaptability |

---

## 2. Core Functional Workflows (F1 – F4)

| ID | Test Case | Target / Action | Expected Result |
|---|---|---|---|
| **F1** | Dynamic Stock Calculation | Perform multiple `IN` and `OUT` movements | Stock matches `SUM(IN) - SUM(OUT)` without stored balance |
| **F2** | Negative Stock Prevention | Issue movement `OUT` greater than current balance | Rejected with HTTP 400 (`Insufficient inventory`) |
| **F3** | Full Verification Workflow | Execute `verify_audit_chain()` on pristine database | Returns `verified = true`, all 5 check categories valid |
| **F4** | Reset Demo Workflow | Admin invokes `POST /api/reset-demo` | Drops/reseeds tables, recreates demo accounts, syncs anchor |

---

## 3. Running the Test Suite

```powershell
python extras/test_suite.py
```
*(Requires `fastapi`, `httpx`, `pyjwt`, `pydantic` installed as listed in `requirements.txt`)*
