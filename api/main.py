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
    get_connection,
    get_db_debug_info,
    get_full_database_dump,
    init_db,
    inspect_table_or_view,
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
    description="Relational Inventory Management & Tamper-Evident Audit Ledger",
    version="3.0.0",
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
    category_id: int = Field(default=1, gt=0, le=2_147_483_647)
    unit_price: float = Field(gt=0, le=10_000_000, allow_inf_nan=False)
    reorder_threshold: int = Field(default=10, ge=0, le=100_000)

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
    supplier_id: Optional[int] = Field(default=None, gt=0, le=2_147_483_647)
    location_id: Optional[int] = Field(default=1, gt=0, le=2_147_483_647)
    type: Literal["IN", "OUT"]
    qty: int = Field(gt=0, le=1_000_000)
    reference_doc: Optional[str] = Field(default=None, max_length=60)
    note: str = Field(default="Standard inventory operation", max_length=200)

    @field_validator("note", "reference_doc")
    @classmethod
    def sanitize_text(cls, v: Optional[str]) -> Optional[str]:
        if v and any(ord(c) < 32 for c in v):
            raise ValueError("Control characters are not permitted")
        return v

class SqlProbeRequest(_Strict):
    probe_type: Literal[
        "explain_stock",
        "trigger_movement_update",
        "trigger_movement_delete",
        "trigger_audit_update",
        "trigger_product_delete",
        "trigger_product_update",
        "trigger_negative_stock",
    ]

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
# 1. AUTHENTICATION & CONFIG
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
        "version": "3.0.0",
        "app_title": "VaultStock Inventory",
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
# 2. RELATIONAL LOOKUPS (CATEGORIES, SUPPLIERS, LOCATIONS)
# -----------------------------------------------------------------------------
@app.get("/api/categories")
def list_categories(user: dict = Depends(require_any)):
    """Returns all product classification categories."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, code, name, description FROM categories ORDER BY id ASC;")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

@app.get("/api/suppliers")
def list_suppliers(user: dict = Depends(require_any)):
    """Returns all approved inventory suppliers."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, contact_email, phone FROM suppliers ORDER BY id ASC;")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

@app.get("/api/locations")
def list_locations(user: dict = Depends(require_any)):
    """Returns all storage warehouses and retail sections."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, code, name FROM locations ORDER BY id ASC;")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

# -----------------------------------------------------------------------------
# 3. INVENTORY & DYNAMIC STOCK (VIEWS & TRANSACTIONS)
# -----------------------------------------------------------------------------
@app.get("/api/products")
def list_products(user: dict = Depends(require_any)):
    """Retrieves all products alongside dynamic stock balances derived from view v_inventory_summary."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                product_id AS id,
                product_id,
                sku,
                product_name AS name,
                product_name,
                category_id,
                category_name,
                category_code,
                unit_price,
                reorder_threshold,
                current_stock,
                total_valuation,
                is_low_stock,
                created_at
            FROM v_inventory_summary
            ORDER BY product_id ASC;
        """)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()

@app.get("/api/inventory/alerts")
def list_low_stock_alerts(user: dict = Depends(require_any)):
    """Retrieves products that have reached or dropped below reorder threshold."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT product_id AS id, sku, product_name AS name, category_name, unit_price, reorder_threshold, current_stock
            FROM v_low_stock_alerts
            ORDER BY current_stock ASC;
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
            # Verify category exists
            cur.execute("SELECT id, name FROM categories WHERE id = ?;", (prod.category_id,))
            cat = cur.fetchone()
            if not cat:
                raise HTTPException(status_code=400, detail="Specified category does not exist")

            cur.execute(
                """
                INSERT INTO products (sku, name, category_id, unit_price, reorder_threshold)
                VALUES (?, ?, ?, ?, ?);
                """,
                (prod.sku, prod.name, prod.category_id, prod.unit_price, prod.reorder_threshold),
            )
            product_id = cur.lastrowid
            payload = {
                "category_id": prod.category_id,
                "id": product_id,
                "name": prod.name,
                "reorder_threshold": prod.reorder_threshold,
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
                details=f"Created product '{prod.name}' ({prod.sku}) in category '{cat['name']}'",
            )
        sync_anchor_to_latest(conn)
    except HTTPException:
        raise
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
# 4. STOCK MOVEMENTS (IMMUTABLE LEDGER)
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

            # 2. Relational & Business Logic validation
            if move.type == "OUT":
                if move.supplier_id is not None:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid movement: supplier_id cannot be assigned to OUT dispatches.",
                    )
                effective_supplier_id = None
                if item["balance"] < move.qty:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Insufficient inventory! Current balance is {item['balance']}, cannot issue {move.qty} units.",
                    )
            else:
                effective_supplier_id = move.supplier_id
                if effective_supplier_id is not None:
                    cur.execute("SELECT id FROM suppliers WHERE id = ?;", (effective_supplier_id,))
                    if not cur.fetchone():
                        raise HTTPException(status_code=400, detail="Invalid supplier_id: Supplier does not exist.")

            effective_location_id = move.location_id or 1
            cur.execute("SELECT id FROM locations WHERE id = ?;", (effective_location_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=400, detail="Invalid location_id: Location does not exist.")

            # 3. Insert append-only movement
            cur.execute("""
                INSERT INTO movements (product_id, supplier_id, location_id, type, qty, reference_doc, note, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                move.product_id,
                effective_supplier_id,
                effective_location_id,
                move.type,
                move.qty,
                move.reference_doc,
                move.note,
                user["username"],
            ))
            m_id = cur.lastrowid

            # 4. Seal in cryptographic audit chain
            action_name = "STOCK_RECEIVE" if move.type == "IN" else "STOCK_ISSUE"
            payload = {
                "created_by": user["username"],
                "id": m_id,
                "location_id": effective_location_id,
                "note": move.note,
                "product_id": move.product_id,
                "qty": move.qty,
                "reference_doc": move.reference_doc,
                "supplier_id": effective_supplier_id,
                "type": move.type,
            }
            ref_info = f" [Ref: {move.reference_doc}]" if move.reference_doc else ""
            append_audit_entry(
                conn=conn,
                action=action_name,
                actor=user["username"],
                ref_table="movements",
                ref_id=m_id,
                payload=payload,
                details=f"{move.type} {move.qty} units of '{item['name']}' (Operator: {user['username']}){ref_info}",
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
    """Retrieves chronological stock movements joined via v_ledger_history view."""
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                movement_id AS id,
                movement_id,
                created_at,
                type,
                qty,
                product_id,
                sku,
                product_name,
                category_name,
                supplier_name,
                location_name,
                location_code,
                reference_doc,
                note,
                created_by
            FROM v_ledger_history
            LIMIT ? OFFSET ?;
        """, (safe_limit, safe_offset))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

# -----------------------------------------------------------------------------
# 5. AUDIT & CRYPTOGRAPHIC VERIFICATION
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

# -----------------------------------------------------------------------------
# 6. ENGINE DIAGNOSTICS, FULL SCHEMA DUMP & PROBES
# -----------------------------------------------------------------------------
@app.get("/api/debug/internals")
def debug_internals(user: dict = Depends(require_any)):
    """Returns SQLite engine PRAGMAs, row counts, active triggers, and views."""
    return get_db_debug_info()

@app.get("/api/debug/full-schema")
def debug_full_schema(limit: int = 50, user: dict = Depends(require_any)):
    """Returns all tables, views, column definitions, foreign keys, DDL, and raw rows."""
    return get_full_database_dump(limit=limit)

@app.post("/api/debug/sql-probe")
def debug_sql_probe(req: SqlProbeRequest, user: dict = Depends(require_any)):
    """Executes a read-only or safely rolled-back SQLite engine trigger/query-plan probe."""
    return run_sql_probe(req.probe_type)

@app.get("/api/debug/table/{object_name}")
def debug_inspect_table(object_name: str, limit: int = 50, user: dict = Depends(require_any)):
    """Returns table/view schema (columns, data types, PK/FK constraints, DDL) and raw DB rows."""
    try:
        return inspect_table_or_view(object_name, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# -----------------------------------------------------------------------------
# 7. DEMO CONTROL ENDPOINTS (Conditional on DEMO_MODE)
# -----------------------------------------------------------------------------
if DEMO_MODE:
    @app.post("/api/audit/tamper-demo")
    def simulate_tamper(user: dict = Depends(require_admin)):
        result = tamper_for_demo(1)
        return {
            "message": "Simulated rogue DB file-level tampering on block #1. Run verify now to observe detection.",
            "tamper_info": result,
        }

    @app.post("/api/reset-demo")
    def reset_database(user: dict = Depends(require_admin)):
        reset_demo_db()
        return {"message": "Database reset to pristine relational state with zero anomalies."}
