import logging
import sqlite3
import threading
import time
from collections import deque
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.config import (
    ALLOWED_ORIGINS,
    DEMO_MODE,
    JWT_SECRET,
    JWT_TTL_SECONDS,
)
from api.db import (
    append_audit_entry,
    canonical_json,
    get_anchor,
    get_connection,
    get_db_debug_info,
    init_db,
    reset_demo_db,
    run_sql_probe,
    sync_anchor_to_latest,
    tamper_for_demo,
    verify_audit_chain,
    write_tx,
)
from api.security import dummy_verify, verify_password
import jwt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vaultstock")

# App instance with documentation conditionally hidden in production
app = FastAPI(
    title="VaultStock",
    description="Minimalist Tamper-Evident Inventory Control System",
    version="2.1.0",
    docs_url="/docs" if DEMO_MODE else None,
    redoc_url=None,
    openapi_url="/openapi.json" if DEMO_MODE else None,
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Sanitizes validation errors to ensure non-JSON numbers (inf/nan) don't crash response rendering."""
    clean_errors = []
    for err in exc.errors():
        err_copy = dict(err)
        val = err_copy.get("input")
        if isinstance(val, float) and (val != val or val == float("inf") or val == float("-inf")):
            err_copy["input"] = str(val)
        clean_errors.append(err_copy)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(clean_errors)})

# Security HTTP headers middleware
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update({
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    })
    return response

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# Thread-safe in-memory sliding-window rate limiter for login attempts with auto-pruning
_LIMITER_LOCK = threading.Lock()
_LOGIN_FAILS: dict[str, deque] = {}
MAX_LOGIN_FAILS = 5
LOGIN_WINDOW_SECONDS = 900  # 15 minutes

def is_login_throttled(key: str) -> bool:
    now = time.time()
    with _LIMITER_LOCK:
        q = _LOGIN_FAILS.get(key)
        if not q:
            return False
        while q and now - q[0] > LOGIN_WINDOW_SECONDS:
            q.popleft()
        if not q:
            _LOGIN_FAILS.pop(key, None)
            return False
        return len(q) >= MAX_LOGIN_FAILS

def record_login_failure(key: str) -> None:
    now = time.time()
    with _LIMITER_LOCK:
        if key not in _LOGIN_FAILS:
            _LOGIN_FAILS[key] = deque()
        _LOGIN_FAILS[key].append(now)
        while len(_LOGIN_FAILS[key]) > MAX_LOGIN_FAILS * 2:
            _LOGIN_FAILS[key].popleft()

def clear_login_failures(key: str) -> None:
    with _LIMITER_LOCK:
        _LOGIN_FAILS.pop(key, None)

# Initialize DB on startup
@app.on_event("startup")
def startup():
    init_db()

# -----------------------------------------------------------------------------
# Data Models (Pydantic v2 strict)
# -----------------------------------------------------------------------------
class _Strict(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

class LoginRequest(_Strict):
    username: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128)

class ProductCreate(_Strict):
    sku: str = Field(min_length=3, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9_-]*$")
    name: str = Field(min_length=1, max_length=120)
    unit_price: float = Field(gt=0, le=10_000_000, allow_inf_nan=False)

    @field_validator("sku", mode="before")
    @classmethod
    def format_sku(cls, v):
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        if any(ord(c) < 32 for c in v):
            raise ValueError("Control characters are not permitted")
        return v

class MovementCreate(_Strict):
    product_id: int = Field(gt=0, le=2_147_483_647)
    type: Literal["IN", "OUT"]
    qty: int = Field(gt=0, le=1_000_000)
    note: str = Field(default="Standard stock operation", max_length=200)

    @field_validator("note")
    @classmethod
    def sanitize_note(cls, v: str) -> str:
        if any(ord(c) < 32 for c in v):
            raise ValueError("Control characters are not permitted")
        return v

# -----------------------------------------------------------------------------
# Authentication & RBAC Dependencies
# -----------------------------------------------------------------------------
def issue_token(user_id: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "iat": now,
            "nbf": now,
            "exp": now + JWT_TTL_SECONDS,
            "iss": "vaultstock",
        },
        JWT_SECRET,
        algorithm="HS256",
    )

def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization[7:].strip()
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            issuer="vaultstock",
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Session expired or token invalid")

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, username, role FROM users WHERE id = ?;", (user_id,))
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return dict(row)

def require_role(*roles: str):
    def dep(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Insufficient privileges")
        return user
    return dep

require_admin = require_role("admin")
require_any = require_role("admin", "staff")

# -----------------------------------------------------------------------------
# 1. AUTHENTICATION & USER PROFILE
# -----------------------------------------------------------------------------
@app.post("/api/login")
def login(req: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    throttle_key = f"{client_ip}:{req.username.lower()}"

    if is_login_throttled(throttle_key):
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Please retry later.",
            headers={"Retry-After": str(LOGIN_WINDOW_SECONDS)},
        )

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, username, password_hash, role FROM users WHERE username = ?;", (req.username,))
        user = cur.fetchone()
    finally:
        conn.close()

    if not user or not verify_password(req.password, user["password_hash"]):
        dummy_verify(req.password)
        record_login_failure(throttle_key)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    clear_login_failures(throttle_key)
    token = issue_token(user["id"])
    return {
        "token": token,
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "demo_mode": DEMO_MODE,
    }

@app.get("/api/config")
def get_public_config():
    """Returns non-sensitive public runtime configuration for frontend adaptation."""
    return {
        "demo_mode": DEMO_MODE,
        "version": "2.1.0",
    }

@app.get("/api/me")
def get_profile(user: dict = Depends(require_any)):
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "demo_mode": DEMO_MODE,
    }

# -----------------------------------------------------------------------------
# 2. INVENTORY & DYNAMIC STOCK
# -----------------------------------------------------------------------------
@app.get("/api/products")
def list_products(user: dict = Depends(require_any)):
    """Retrieves all products alongside their dynamically computed stock balance."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                p.id, 
                p.sku, 
                p.name, 
                p.unit_price,
                COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.qty ELSE -m.qty END), 0) AS current_stock
            FROM products p
            LEFT JOIN movements m ON p.id = m.product_id
            GROUP BY p.id
            ORDER BY p.id ASC;
        """)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

@app.post("/api/products")
def create_product(prod: ProductCreate, user: dict = Depends(require_admin)):
    conn = get_connection()
    product_id = None
    try:
        with write_tx(conn):
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO products (sku, name, unit_price) VALUES (?, ?, ?);",
                (prod.sku, prod.name, prod.unit_price),
            )
            product_id = cur.lastrowid
            payload = {
                "id": product_id,
                "name": prod.name,
                "sku": prod.sku,
                "unit_price": prod.unit_price,
            }
            append_audit_entry(
                conn=conn,
                action="PRODUCT_CREATE",
                actor=user["username"],
                ref_table="products",
                ref_id=product_id,
                payload=payload,
                details=f"Created product '{prod.name}' (SKU: {prod.sku}) by {user['username']}",
            )
        sync_anchor_to_latest(conn)
    except sqlite3.IntegrityError as e:
        logger.warning("Product creation integrity error: %s", str(e))
        if "UNIQUE" in str(e).upper() and "SKU" in str(e).upper():
            raise HTTPException(status_code=409, detail="SKU already exists")
        raise HTTPException(status_code=409, detail="Constraint violation on product creation")
    except Exception:
        logger.exception("Unexpected error creating product")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()

    return {"message": "Product created successfully", "product_id": product_id}

# -----------------------------------------------------------------------------
# 3. STOCK MOVEMENTS (IMMUTABLE LEDGER)
# -----------------------------------------------------------------------------
@app.post("/api/movements")
def record_movement(move: MovementCreate, user: dict = Depends(require_any)):
    conn = get_connection()
    try:
        with write_tx(conn):
            cur = conn.cursor()

            # 1. Verify Product exists and compute current balance
            cur.execute("""
                SELECT p.name, COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.qty ELSE -m.qty END), 0) AS balance
                FROM products p
                LEFT JOIN movements m ON p.id = m.product_id
                WHERE p.id = ?
                GROUP BY p.id;
            """, (move.product_id,))
            item = cur.fetchone()
            if not item:
                raise HTTPException(status_code=404, detail="Product not found")

            # 2. Application-level check
            if move.type == "OUT" and item["balance"] < move.qty:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient inventory! Current balance is {item['balance']}, cannot issue {move.qty} units.",
                )

            # 3. Insert append-only movement
            cur.execute("""
                INSERT INTO movements (product_id, type, qty, note, created_by)
                VALUES (?, ?, ?, ?, ?);
            """, (move.product_id, move.type, move.qty, move.note, user["username"]))
            m_id = cur.lastrowid

            # 4. Seal in cryptographic audit chain
            action_name = "STOCK_RECEIVE" if move.type == "IN" else "STOCK_ISSUE"
            payload = {
                "created_by": user["username"],
                "id": m_id,
                "note": move.note,
                "product_id": move.product_id,
                "qty": move.qty,
                "type": move.type,
            }
            append_audit_entry(
                conn=conn,
                action=action_name,
                actor=user["username"],
                ref_table="movements",
                ref_id=m_id,
                payload=payload,
                details=f"{move.type} {move.qty} units of '{item['name']}' (Operator: {user['username']})",
            )
        sync_anchor_to_latest(conn)
    except HTTPException:
        raise
    except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
        logger.warning("Database constraint violation during movement: %s", str(e))
        err_msg = str(e)
        if "SECURITY VIOLATION" in err_msg:
            clean_msg = err_msg.split("SECURITY VIOLATION:")[-1].strip()
            raise HTTPException(status_code=409, detail=f"Security violation: {clean_msg}")
        raise HTTPException(status_code=409, detail="Transaction rejected by database integrity rules")
    except Exception:
        logger.exception("Unexpected error recording movement")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()

    return {"message": f"Recorded stock {move.type} successfully"}

@app.get("/api/movements")
def list_movements(
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(require_any),
):
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT m.id, p.name as product_name, p.sku, m.type, m.qty, m.note, m.created_by, m.created_at
            FROM movements m
            JOIN products p ON m.product_id = p.id
            ORDER BY m.id DESC LIMIT ? OFFSET ?;
        """, (safe_limit, safe_offset))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

# -----------------------------------------------------------------------------
# 4. AUDIT & CRYPTOGRAPHIC VERIFICATION
# -----------------------------------------------------------------------------
@app.get("/api/audit")
def list_audit_trail(
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(require_any),
):
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, action, actor, ref_table, ref_id, payload, details, timestamp, prev_hash, row_hash 
            FROM audit_log 
            ORDER BY id DESC LIMIT ? OFFSET ?;
        """, (safe_limit, safe_offset))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

@app.get("/api/audit/verify")
def verify_integrity(user: dict = Depends(require_any)):
    """Performs mathematical audit verification scan across HMAC-SHA256 chain and relational state."""
    return verify_audit_chain()

@app.get("/api/audit/head")
def get_audit_head(user: dict = Depends(require_admin)):
    """Returns the external anchor checkpoint for offline verification."""
    anchor = get_anchor()
    if not anchor:
        raise HTTPException(status_code=404, detail="Anchor not found")
    return anchor


class SqlProbeRequest(_Strict):
    probe_type: Literal[
        "explain_stock",
        "trigger_movement_update",
        "trigger_movement_delete",
        "trigger_audit_update",
        "trigger_audit_delete",
        "trigger_product_delete",
        "trigger_negative_stock",
    ]


@app.get("/api/debug/internals")
def debug_internals(user: dict = Depends(require_admin)):
    """Returns SQLite engine PRAGMAs, row counts, active triggers, and anchor state."""
    return get_db_debug_info()


@app.post("/api/debug/sql-probe")
def debug_sql_probe(req: SqlProbeRequest, user: dict = Depends(require_admin)):
    """Executes a read-only or safely rolled-back SQLite engine trigger/query-plan probe."""
    return run_sql_probe(req.probe_type)

# -----------------------------------------------------------------------------
# 5. DEMO CONTROL ENDPOINTS (Conditional on DEMO_MODE)
# -----------------------------------------------------------------------------
if DEMO_MODE:
    @app.post("/api/audit/tamper-demo")
    def simulate_tamper(user: dict = Depends(require_admin)):
        result = tamper_for_demo(1, file_level=True)
        return {
            "message": "Simulated rogue DB file-level tampering on block #1. Run verify now to observe detection.",
            "tamper_info": result,
        }

    @app.post("/api/reset-demo")
    def reset_database(user: dict = Depends(require_admin)):
        reset_demo_db(admin_actor=user["username"])
        return {"message": "Database reset to pristine state with zero anomalies."}
