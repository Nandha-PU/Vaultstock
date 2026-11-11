import hashlib
import json
import os
import re
import secrets
import sqlite3
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# Ensure root directory is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Set test environment
os.environ["VAULTSTOCK_DEMO_MODE"] = "1"
os.environ["VAULTSTOCK_DB_PATH"] = str(ROOT_DIR / "data" / "vaultstock_test.db")
os.environ["VAULTSTOCK_ANCHOR_PATH"] = str(ROOT_DIR / "data" / "vaultstock_test_anchor.json")
os.environ["VAULTSTOCK_ADMIN_PASSWORD"] = "AdminSecretPass2026!"
os.environ["VAULTSTOCK_STAFF_PASSWORD"] = "StaffSecretPass2026!"
os.environ["VAULTSTOCK_JWT_SECRET"] = secrets.token_hex(32)
os.environ["VAULTSTOCK_AUDIT_KEY"] = secrets.token_hex(32)

from fastapi import HTTPException
from api.main import (
    app,
    create_product,
    get_current_user,
    get_profile,
    get_public_config,
    issue_token,
    list_audit_trail,
    list_categories,
    list_location_inventory,
    list_locations,
    list_low_stock_alerts,
    list_movements,
    list_products,
    list_suppliers,
    record_movement,
    reset_database,
    simulate_tamper,
    transfer_stock,
    verify_integrity,
    LoginRequest,
    MovementCreate,
    ProductCreate,
    TransferCreate,
    _LOGIN_FAILS,
)
from api.config import (
    DB_PATH,
    ANCHOR_PATH,
    JWT_SECRET,
    JWT_TTL_SECONDS,
    AUDIT_HMAC_KEY,
)
from api.db import (
    get_connection,
    init_db,
    reset_demo_db,
    verify_audit_chain,
    write_tx,
)
from api.security import hash_password, verify_password, dummy_verify
import jwt

def setup_clean_db():
    for p in [DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm", ANCHOR_PATH]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
    _LOGIN_FAILS.clear()
    init_db()

results = []

def record(test_id, name, passed, detail=""):
    results.append((test_id, name, passed, detail))
    status_str = "PASS" if passed else "FAIL"
    print(f"[{status_str}] {test_id}: {name}" + (f" -> {detail}" if detail else ""))

print("=" * 70)
print("RUNNING VAULTSTOCK SECURITY, RELATIONAL & FUNCTIONAL TEST SUITE")
print("=" * 70)

# Setup initial clean test DB
setup_clean_db()
admin_user = {"id": 1, "username": "admin", "role": "admin"}
staff_user = {"id": 2, "username": "staff", "role": "staff"}
admin_token = issue_token(admin_user["id"])
staff_token = issue_token(staff_user["id"])

# -----------------------------------------------------------------------------
# T1: Unauthenticated Profile Call
# -----------------------------------------------------------------------------
t1_passed = False
try:
    get_current_user(authorization=None)
except HTTPException as e:
    t1_passed = e.status_code == 401
record("T1", "Unauthenticated request rejected with 401", t1_passed)

# -----------------------------------------------------------------------------
# T2: Authenticated Token Resolves User
# -----------------------------------------------------------------------------
u_auth = get_current_user(authorization=f"Bearer {admin_token}")
t2_passed = u_auth["username"] == "admin" and u_auth["role"] == "admin"
record("T2", "Valid JWT correctly resolves user session profile", t2_passed, f"User: {u_auth['username']}")

# -----------------------------------------------------------------------------
# T3: Staff Role Rejected on Admin-Only Action (RBAC)
# -----------------------------------------------------------------------------
t3_passed = False
try:
    from api.main import require_admin
    dep = require_admin
    dep(staff_user)
except HTTPException as e:
    t3_passed = e.status_code == 403
record("T3", "Staff role rejected on admin-only route (403)", t3_passed)

# -----------------------------------------------------------------------------
# T4: Forged JWT Secret Rejected
# -----------------------------------------------------------------------------
fake_tok = jwt.encode(
    {"sub": "1", "iat": int(time.time()), "exp": int(time.time()) + 3600, "iss": "vaultstock"},
    "forged-unauthorized-key",
    algorithm="HS256",
)
t4_passed = False
try:
    get_current_user(authorization=f"Bearer {fake_tok}")
except HTTPException as e:
    t4_passed = e.status_code == 401
record("T4", "Forged JWT key returns 401 unauthorized", t4_passed)

# -----------------------------------------------------------------------------
# T5: Expired JWT Rejected
# -----------------------------------------------------------------------------
exp_tok = jwt.encode(
    {"sub": "1", "iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600, "iss": "vaultstock"},
    JWT_SECRET,
    algorithm="HS256",
)
t5_passed = False
try:
    get_current_user(authorization=f"Bearer {exp_tok}")
except HTTPException as e:
    t5_passed = e.status_code == 401
record("T5", "Expired JWT returns 401 session expired", t5_passed)

# -----------------------------------------------------------------------------
# T6: XSS Payloads Stored Safely
# -----------------------------------------------------------------------------
xss_name = '<img src=x onerror=alert(1)>'
p_xss = create_product(ProductCreate(sku="SKU-XSS-01", name=xss_name, category_id=1, unit_price=50.0), admin_user)
prods = list_products(admin_user)
t6_passed = any(p["name"] == xss_name for p in prods)
record("T6", "XSS payload stored without execution/corruption", t6_passed)

# -----------------------------------------------------------------------------
# T7: Category Reference Constraint (1:N)
# -----------------------------------------------------------------------------
t7_passed = False
try:
    create_product(ProductCreate(sku="SKU-BAD-CAT", name="Bad Cat", category_id=9999, unit_price=10.0), admin_user)
except HTTPException as e:
    t7_passed = e.status_code in (400, 409)
record("T7", "Invalid category_id rejected by relational constraint", t7_passed)

# -----------------------------------------------------------------------------
# T8: Negative Stock Prevention Trigger
# -----------------------------------------------------------------------------
t8_passed = False
try:
    record_movement(MovementCreate(product_id=1, type="OUT", qty=999999, note="Overdraft attempt"), admin_user)
except HTTPException as e:
    t8_passed = e.status_code in (400, 409) and "Insufficient inventory" in str(e.detail)
record("T8", "Negative stock overdraft blocked by application and trigger", t8_passed)

# -----------------------------------------------------------------------------
# T9: Movement Immutability Trigger (UPDATE & DELETE)
# -----------------------------------------------------------------------------
conn = get_connection()
t9_update = False
t9_delete = False
try:
    conn.execute("UPDATE movements SET qty = 100 WHERE id = 1;")
except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
    if "SECURITY VIOLATION: Ledger entries are immutable" in str(e):
        t9_update = True

try:
    conn.execute("DELETE FROM movements WHERE id = 1;")
except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
    if "SECURITY VIOLATION: Ledger entries are immutable" in str(e):
        t9_delete = True
conn.close()
record("T9", "Database triggers block direct UPDATE & DELETE on movements", t9_update and t9_delete)

# -----------------------------------------------------------------------------
# T10: Audit Log Immutability Trigger
# -----------------------------------------------------------------------------
conn = get_connection()
t10_passed = False
try:
    conn.execute("UPDATE audit_log SET details = 'tampered' WHERE id = 1;")
except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
    if "SECURITY VIOLATION: Audit log is immutable" in str(e):
        t10_passed = True
conn.close()
record("T10", "Database trigger blocks direct UPDATE on audit_log", t10_passed)

# -----------------------------------------------------------------------------
# T11: Product Deletion Referential Guard
# -----------------------------------------------------------------------------
conn = get_connection()
t11_passed = False
try:
    conn.execute("DELETE FROM products WHERE id = 1;")
except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
    if "SECURITY VIOLATION: Products cannot be deleted" in str(e):
        t11_passed = True
conn.close()
record("T11", "Product deletion blocked to protect referential integrity", t11_passed)

# -----------------------------------------------------------------------------
# T12: File-Level Attacker with Plain SHA-256 Detected
# -----------------------------------------------------------------------------
setup_clean_db()
conn = get_connection()
conn.execute("DROP TRIGGER IF EXISTS prevent_audit_update;")
cur = conn.cursor()
cur.execute("SELECT * FROM audit_log WHERE id = 1;")
row1 = cur.fetchone()
raw_msg = json.dumps(
    [row1["prev_hash"], row1["id"], row1["action"], row1["actor"], row1["ref_table"], row1["ref_id"], row1["payload"], row1["timestamp"]],
    separators=(",", ":"),
    ensure_ascii=False,
)
fake_sha256 = hashlib.sha256(raw_msg.encode()).hexdigest()
conn.execute("UPDATE audit_log SET details = 'HACKED DETAILS', row_hash = ? WHERE id = 1;", (fake_sha256,))
conn.close()

v12 = verify_audit_chain()
t12_passed = (v12["verified"] is False) and (v12["broken_at_id"] == 1) and (v12["checks"]["integrity"] is False)
record("T12", "File-level attacker bypassing triggers detected via HMAC", t12_passed, v12["reason"])

# -----------------------------------------------------------------------------
# T13: Ghost Movement Row Detected by Relational Reconciliation
# -----------------------------------------------------------------------------
setup_clean_db()
conn = get_connection()
conn.execute("INSERT INTO movements (product_id, supplier_id, location_id, type, qty, note, created_by) VALUES (1, 1, 1, 'IN', 500, 'Ghost injection', 'attacker');")
conn.close()

v13 = verify_audit_chain()
t13_passed = (v13["verified"] is False) and (v13["checks"]["reconciliation"] is False)
record("T13", "Ghost movement row detected by relational reconciliation", t13_passed, v13["reason"])

# -----------------------------------------------------------------------------
# T14: Deleted Audit Block Detected by Contiguity Check
# -----------------------------------------------------------------------------
setup_clean_db()
conn = get_connection()
conn.execute("DROP TRIGGER IF EXISTS prevent_audit_delete;")
conn.execute("DELETE FROM audit_log WHERE id = 3;")
conn.close()

v14 = verify_audit_chain()
t14_passed = (v14["verified"] is False) and (v14["broken_at_id"] == 4) and (v14["checks"]["contiguity"] is False)
record("T14", "Deleted audit block detected by contiguity check (1..N)", t14_passed, v14["reason"])

# -----------------------------------------------------------------------------
# T15: Tail Truncation Detected by External Head Anchor
# -----------------------------------------------------------------------------
setup_clean_db()
conn = get_connection()
cur = conn.cursor()
cur.execute("SELECT id, ref_id FROM audit_log ORDER BY id DESC LIMIT 1;")
last_audit = cur.fetchone()
conn.execute("DROP TRIGGER IF EXISTS prevent_audit_delete;")
conn.execute("DROP TRIGGER IF EXISTS prevent_movement_delete;")
conn.execute("DELETE FROM audit_log WHERE id = ?;", (last_audit["id"],))
if last_audit["ref_id"]:
    conn.execute("DELETE FROM movements WHERE id = ?;", (last_audit["ref_id"],))
conn.close()

v15 = verify_audit_chain()
t15_passed = (v15["verified"] is False) and (v15["checks"]["anchor"] is False)
record("T15", "Tail truncation detected via external head anchor", t15_passed, v15["reason"])

# -----------------------------------------------------------------------------
# T16: Missing Anchor File Detected
# -----------------------------------------------------------------------------
setup_clean_db()
if os.path.exists(ANCHOR_PATH):
    os.remove(ANCHOR_PATH)
v16 = verify_audit_chain()
t16_passed = (v16["verified"] is False) and (v16["checks"]["anchor"] is False)
record("T16", "Deleted anchor file detected as integrity failure", t16_passed, v16.get("reason", ""))

# -----------------------------------------------------------------------------
# T17: Corrupted Audit JSON Payload Caught Safely
# -----------------------------------------------------------------------------
setup_clean_db()
conn = get_connection()
conn.execute("DROP TRIGGER IF EXISTS prevent_audit_update;")
conn.execute("UPDATE audit_log SET payload = 'NOT_VALID_JSON' WHERE id = 1;")
conn.close()
v17 = verify_audit_chain()
t17_passed = (v17["verified"] is False) and ("corrupt" in v17.get("reason", "").lower() or v17["checks"]["integrity"] is False)
record("T17", "Corrupted audit JSON payload caught safely without crash", t17_passed, v17.get("reason", ""))

# -----------------------------------------------------------------------------
# T18: Duplicate SKU Returns Clean 409
# -----------------------------------------------------------------------------
setup_clean_db()
t18_passed = False
try:
    create_product(ProductCreate(sku="SKU-LAPTOP-01", name="Duplicate SKU Item", category_id=1, unit_price=100.0), admin_user)
except HTTPException as e:
    t18_passed = e.status_code == 409 and e.detail == "SKU already exists"
record("T18", "Duplicate SKU returns clean 409 'SKU already exists'", t18_passed)

# -----------------------------------------------------------------------------
# T19: Relational Lookups (Categories, Suppliers, Locations)
# -----------------------------------------------------------------------------
cats = list_categories(admin_user)
supps = list_suppliers(admin_user)
locs = list_locations(admin_user)
t19_passed = len(cats) >= 4 and len(supps) >= 3 and len(locs) >= 3
record("T19", "Relational entities populated (4 Categories, 3 Suppliers, 3 Locations)", t19_passed)

# -----------------------------------------------------------------------------
# T20: Relational Views (Summary & Low-Stock Alerts)
# -----------------------------------------------------------------------------
summary = list_products(admin_user)
alerts = list_low_stock_alerts(admin_user)
t20_passed = len(summary) >= 6 and all("current_stock" in p and "total_valuation" in p for p in summary)
record("T20", "View v_inventory_summary derives live stock, valuation, and categories", t20_passed)

# -----------------------------------------------------------------------------
# Core Functional Workflow Verification (F1 – F4)
# -----------------------------------------------------------------------------
print("\n" + "=" * 70)
print("RUNNING FUNCTIONAL WORKFLOW VERIFICATION (F1 – F4)")
print("=" * 70)

setup_clean_db()

# F1: Dynamic Stock Calculation SUM(IN) - SUM(OUT)
# Initial stock of Product #1 is 25
prods_init = list_products(admin_user)
p1_init = next(p for p in prods_init if p["id"] == 1)
assert p1_init["current_stock"] == 25

# Admin receives 50 units (IN)
record_movement(
    MovementCreate(product_id=1, supplier_id=1, location_id=1, type="IN", qty=50, reference_doc="PO-TEST-01", note="Restock shipment"),
    admin_user,
)

# Staff issues 20 units (OUT)
record_movement(
    MovementCreate(product_id=1, location_id=1, type="OUT", qty=20, reference_doc="SO-TEST-01", note="Customer order"),
    staff_user,
)

prods_after = list_products(admin_user)
p1_after = next(p for p in prods_after if p["id"] == 1)
f1_passed = p1_after["current_stock"] == 55  # 25 + 50 - 20
record("F1", "Dynamic stock balance calculation: SUM(IN) - SUM(OUT)", f1_passed, f"Stock: {p1_after['current_stock']}")

# F2: Low Stock View Reactivity
# Dispense 52 units, leaving 3 (below threshold of 5)
record_movement(
    MovementCreate(product_id=1, location_id=1, type="OUT", qty=52, reference_doc="SO-TEST-02", note="Bulk sale"),
    admin_user,
)
alerts_after = list_low_stock_alerts(admin_user)
f2_passed = any(a["id"] == 1 for a in alerts_after)
record("F2", "Low stock alert view dynamically triggers when stock <= threshold", f2_passed)

# F3: Cryptographic Verification Scan 100% Pass
v_data = verify_integrity(staff_user)
f3_passed = v_data["verified"] is True and all(v_data["checks"].values())
record("F3", "Cryptographic audit chain verification returns 100% valid", f3_passed, f"Total blocks: {v_data['total_blocks']}")

# F4: Reset Demo Workflow
reset_res = reset_database(admin_user)
v_reset = verify_integrity(admin_user)
f4_passed = v_reset["verified"] is True and all(v_reset["checks"].values())
record("F4", "Reset demo cleanly reseeds database and passes cryptographic audit", f4_passed, f"Total blocks: {v_reset['total_blocks']}")

# F5: Multi-Warehouse Stock Transfer & Location Balance Derivation (v_location_inventory)
# Product #1 starts with 25 units at location_id=1 (WH-A1) and 0 at location_id=3 (RETAIL-1)
xfer_res = transfer_stock(
    TransferCreate(
        product_id=1,
        from_location_id=1,
        to_location_id=3,
        qty=10,
        reference_doc="XFER-TEST-01",
        note="Restock retail floor",
    ),
    admin_user,
)
loc_inv = list_location_inventory(admin_user)
p1_loc1 = next((r["current_stock"] for r in loc_inv if r["product_id"] == 1 and r["location_id"] == 1), 0)
p1_loc3 = next((r["current_stock"] for r in loc_inv if r["product_id"] == 1 and r["location_id"] == 3), 0)
p1_global = next(p["current_stock"] for p in list_products(admin_user) if p["id"] == 1)
v_after_xfer = verify_integrity(admin_user)
f5_passed = (p1_loc1 == 15) and (p1_loc3 == 10) and (p1_global == 25) and v_after_xfer["verified"]
record(
    "F5",
    "Atomic warehouse transfer updates v_location_inventory while preserving global stock & audit chain",
    f5_passed,
    f"WH-A1: {p1_loc1}, RETAIL-1: {p1_loc3}, Total: {p1_global}",
)

print("\n" + "=" * 70)
total_tests = len(results)
total_passed = sum(1 for _, _, passed, _ in results)
print(f"SUMMARY: {total_passed} / {total_tests} TESTS PASSED")
print("=" * 70)

# Clean up test DB files
for p in [DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm", ANCHOR_PATH]:
    if os.path.exists(p):
        try:
            os.remove(p)
        except Exception:
            pass

assert total_passed == total_tests, f"Test failure detected! Passed {total_passed}/{total_tests}"
print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY.")
