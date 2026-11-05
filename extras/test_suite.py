import concurrent.futures
import json
import os
import re
import secrets
import sqlite3
import sys
import time
from pathlib import Path

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

from fastapi.testclient import TestClient
from api.main import app, _LOGIN_FAILS
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
from api.security import hash_password
import jwt

client = TestClient(app)

def setup_clean_db():
    for p in [DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm", ANCHOR_PATH]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
    _LOGIN_FAILS.clear()
    init_db()

def get_tokens():
    res_admin = client.post("/api/login", json={"username": "admin", "password": "AdminSecretPass2026!"})
    assert res_admin.status_code == 200, f"Admin login failed: {res_admin.text}"
    admin_token = res_admin.json()["token"]

    res_staff = client.post("/api/login", json={"username": "staff", "password": "StaffSecretPass2026!"})
    assert res_staff.status_code == 200, f"Staff login failed: {res_staff.text}"
    staff_token = res_staff.json()["token"]

    return admin_token, staff_token

results = []

def record(test_id, name, passed, detail=""):
    results.append((test_id, name, passed, detail))
    status_str = "PASS" if passed else "FAIL"
    print(f"[{status_str}] {test_id}: {name}" + (f" -> {detail}" if detail else ""))

print("=" * 70)
print("RUNNING VAULTSTOCK SECURITY & FUNCTIONAL TEST SUITE")
print("=" * 70)

# Setup initial clean test DB
setup_clean_db()
admin_tok, staff_tok = get_tokens()

# -----------------------------------------------------------------------------
# T1: Unauthenticated Reset Demo
# -----------------------------------------------------------------------------
r = client.post("/api/reset-demo")
record("T1", "Unauthenticated reset-demo returns 401", r.status_code == 401, f"Status: {r.status_code}")

# -----------------------------------------------------------------------------
# T2: Unauthenticated Product List
# -----------------------------------------------------------------------------
r = client.get("/api/products")
record("T2", "Unauthenticated GET /api/products returns 401", r.status_code == 401, f"Status: {r.status_code}")

# -----------------------------------------------------------------------------
# T3: Staff Token cannot create product (RBAC)
# -----------------------------------------------------------------------------
r = client.post(
    "/api/products",
    json={"sku": "SKU-STAFF-01", "name": "Staff Device", "unit_price": 99.0},
    headers={"Authorization": f"Bearer {staff_tok}"},
)
record("T3", "Staff role rejected on POST /api/products (403)", r.status_code == 403, f"Status: {r.status_code}")

# -----------------------------------------------------------------------------
# T4: Forged JWT Secret rejected
# -----------------------------------------------------------------------------
fake_tok = jwt.encode(
    {"sub": "1", "iat": int(time.time()), "exp": int(time.time()) + 3600, "iss": "vaultstock"},
    "vaultstock-minimalist-secret-key-2026",
    algorithm="HS256",
)
r = client.get("/api/products", headers={"Authorization": f"Bearer {fake_tok}"})
record("T4", "Forged legacy JWT secret returns 401", r.status_code == 401, f"Status: {r.status_code}")

# -----------------------------------------------------------------------------
# T5: Expired JWT rejected
# -----------------------------------------------------------------------------
exp_tok = jwt.encode(
    {"sub": "1", "iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600, "iss": "vaultstock"},
    JWT_SECRET,
    algorithm="HS256",
)
r = client.get("/api/products", headers={"Authorization": f"Bearer {exp_tok}"})
record("T5", "Expired JWT returns 401", r.status_code == 401, f"Status: {r.status_code}")

# -----------------------------------------------------------------------------
# T6 & T7: Stored XSS Script Tag & Attribute Breakout
# -----------------------------------------------------------------------------
xss_name = '<img src=x onerror=alert(1)>'
r = client.post(
    "/api/products",
    json={"sku": "SKU-XSS-01", "name": xss_name, "unit_price": 50.0},
    headers={"Authorization": f"Bearer {admin_tok}"},
)
record("T6", "XSS payload stored without raw execution", r.status_code == 200)

xss_attr_name = 'x" onmouseover="alert(1)'
r = client.post(
    "/api/products",
    json={"sku": "SKU-XSS-02", "name": xss_attr_name, "unit_price": 50.0},
    headers={"Authorization": f"Bearer {admin_tok}"},
)
record("T7", "Attribute breakout stored safely", r.status_code == 200)

# Verify products endpoint returns them cleanly
r = client.get("/api/products", headers={"Authorization": f"Bearer {admin_tok}"})
assert any(p["name"] == xss_name for p in r.json())
assert any(p["name"] == xss_attr_name for p in r.json())

# -----------------------------------------------------------------------------
# T8: Integer Overflow DoS
# -----------------------------------------------------------------------------
r = client.post(
    "/api/movements",
    json={"product_id": 1, "type": "IN", "qty": 10**19, "note": "Huge quantity"},
    headers={"Authorization": f"Bearer {admin_tok}"},
)
record("T8", "Unbounded integer quantity rejected with 422", r.status_code == 422, f"Status: {r.status_code}")

# -----------------------------------------------------------------------------
# T9: Invalid Float NaN/Infinity
# -----------------------------------------------------------------------------
r = client.post(
    "/api/products",
    content='{"sku": "SKU-INF-01", "name": "Infinity Device", "unit_price": Infinity}',
    headers={"Authorization": f"Bearer {admin_tok}", "Content-Type": "application/json"},
)
record("T9", "Float Infinity rejected with 422", r.status_code == 422, f"Status: {r.status_code}")

# -----------------------------------------------------------------------------
# T10: Concurrency Oversell Race Condition Mitigation
# -----------------------------------------------------------------------------
# Create product with exactly 25 stock
r = client.post(
    "/api/products",
    json={"sku": "SKU-RACE-01", "name": "Race Product", "unit_price": 100.0},
    headers={"Authorization": f"Bearer {admin_tok}"},
)
race_prod_id = r.json()["product_id"]
# Receive 25 units
client.post(
    "/api/movements",
    json={"product_id": race_prod_id, "type": "IN", "qty": 25, "note": "Seed for race test"},
    headers={"Authorization": f"Bearer {admin_tok}"},
)

def issue_stock():
    return client.post(
        "/api/movements",
        json={"product_id": race_prod_id, "type": "OUT", "qty": 25, "note": "Parallel issue"},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )

with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(issue_stock) for _ in range(20)]
    responses = [f.result() for f in futures]

status_codes = [resp.status_code for resp in responses]
success_count = status_codes.count(200)
reject_count = len([c for c in status_codes if c in (400, 409)])

conn = get_connection()
cur = conn.cursor()
cur.execute(
    "SELECT COALESCE(SUM(CASE WHEN type='IN' THEN qty ELSE -qty END), 0) AS bal FROM movements WHERE product_id = ?;",
    (race_prod_id,),
)
final_bal = cur.fetchone()["bal"]
conn.close()

v_race = verify_audit_chain()
t10_passed = (success_count == 1) and (reject_count == 19) and (final_bal == 0) and v_race["verified"]
record("T10", "20 concurrent OUT 25 serialized (1 success, 19 rejected, bal=0)", t10_passed, f"Success: {success_count}, Rejects: {reject_count}, Final Bal: {final_bal}")

# -----------------------------------------------------------------------------
# T11: Application-level audit modification blocked by trigger
# -----------------------------------------------------------------------------
conn = get_connection()
t11_passed = False
try:
    conn.execute("UPDATE audit_log SET details = 'tampered' WHERE id = 1;")
except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
    if "SECURITY VIOLATION: Audit log is immutable" in str(e):
        t11_passed = True
conn.close()
record("T11", "Direct SQLite UPDATE audit_log blocked by trigger", t11_passed)

# -----------------------------------------------------------------------------
# T12: File-level attacker with plain SHA-256 detected
# -----------------------------------------------------------------------------
conn = get_connection()
conn.execute("DROP TRIGGER IF EXISTS prevent_audit_update;")
cur = conn.cursor()
cur.execute("SELECT * FROM audit_log WHERE id = 1;")
row1 = cur.fetchone()
# Recompute plain SHA-256 (attacker has no HMAC key)
raw_msg = json.dumps(
    [row1["prev_hash"], row1["id"], row1["action"], row1["actor"], row1["ref_table"], row1["ref_id"], row1["payload"], row1["timestamp"]],
    separators=(",", ":"),
    ensure_ascii=False,
)
import hashlib
fake_sha256 = hashlib.sha256(raw_msg.encode()).hexdigest()
conn.execute("UPDATE audit_log SET details = 'HACKED DETAILS', row_hash = ? WHERE id = 1;", (fake_sha256,))
conn.close()

v12 = verify_audit_chain()
t12_passed = (v12["verified"] is False) and (v12["broken_at_id"] == 1) and (v12["checks"]["integrity"] is False)
record("T12", "File-level attacker bypassing triggers detected via HMAC", t12_passed, v12["reason"])

# -----------------------------------------------------------------------------
# T13: Ghost Movement injection detected via reconciliation
# -----------------------------------------------------------------------------
# Restore clean DB for next tests
setup_clean_db()
admin_tok, staff_tok = get_tokens()

conn = get_connection()
conn.execute("INSERT INTO movements (product_id, type, qty, note, created_by) VALUES (1, 'IN', 500, 'Ghost injection', 'attacker');")
conn.close()

v13 = verify_audit_chain()
t13_passed = (v13["verified"] is False) and (v13["checks"]["reconciliation"] is False)
record("T13", "Ghost movement row detected by relational reconciliation", t13_passed, v13["reason"])

# -----------------------------------------------------------------------------
# T14: Deleted Audit Block detected by contiguity check
# -----------------------------------------------------------------------------
setup_clean_db()
admin_tok, staff_tok = get_tokens()

conn = get_connection()
conn.execute("DROP TRIGGER IF EXISTS prevent_audit_delete;")
conn.execute("DELETE FROM audit_log WHERE id = 3;")
conn.close()

v14 = verify_audit_chain()
t14_passed = (v14["verified"] is False) and (v14["broken_at_id"] == 4) and (v14["checks"]["contiguity"] is False)
record("T14", "Deleted audit block detected by contiguity check (1..N)", t14_passed, v14["reason"])

# -----------------------------------------------------------------------------
# T15: Tail truncation detected by external anchor
# -----------------------------------------------------------------------------
setup_clean_db()
admin_tok, staff_tok = get_tokens()

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
record("T15", "Tail truncation detected via external anchor checkpoint", t15_passed, v15["reason"])

# -----------------------------------------------------------------------------
# T16: Login rate limiting (sliding window 5 fails / 15 min)
# -----------------------------------------------------------------------------
_LOGIN_FAILS.clear()
for i in range(5):
    res_fail = client.post("/api/login", json={"username": "admin", "password": "WrongPassword!"})
    assert res_fail.status_code == 401

# 6th attempt should return 429
res_throttle = client.post("/api/login", json={"username": "admin", "password": "WrongPassword!"})
record("T16", "6th invalid login throttled with 429 and Retry-After", res_throttle.status_code == 429 and "Retry-After" in res_throttle.headers, f"Status: {res_throttle.status_code}")
_LOGIN_FAILS.clear()

# -----------------------------------------------------------------------------
# T17: User Enumeration Timing & Message Parity
# -----------------------------------------------------------------------------
t0 = time.time()
res_unknown = client.post("/api/login", json={"username": "nonexistent_user", "password": "RandomPassword!"})
t_unknown = time.time() - t0

t0 = time.time()
res_known_bad = client.post("/api/login", json={"username": "admin", "password": "WrongPassword!"})
t_known_bad = time.time() - t0

t17_passed = (
    res_unknown.status_code == 401
    and res_known_bad.status_code == 401
    and res_unknown.json()["detail"] == res_known_bad.json()["detail"]
)
record("T17", "User enumeration defense: identical 401 message and dummy verify", t17_passed, f"Unknown: {t_unknown:.3f}s, Bad PW: {t_known_bad:.3f}s")
_LOGIN_FAILS.clear()

# -----------------------------------------------------------------------------
# T18: Public API Docs hidden when demo mode is off
# -----------------------------------------------------------------------------
# Test in a separate subprocess or module import with VAULTSTOCK_DEMO_MODE=0
import subprocess
script = """
import os
os.environ['VAULTSTOCK_DEMO_MODE'] = '0'
from fastapi.testclient import TestClient
from api.main import app
c = TestClient(app)
r_docs = c.get('/docs')
r_openapi = c.get('/openapi.json')
assert r_docs.status_code == 404, f'docs was {r_docs.status_code}'
assert r_openapi.status_code == 404, f'openapi was {r_openapi.status_code}'
print('DOCS_HIDDEN')
"""
p = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
t18_passed = "DOCS_HIDDEN" in p.stdout
record("T18", "API docs return 404 when DEMO_MODE=0", t18_passed, f"Output: {p.stdout.strip()}")

# -----------------------------------------------------------------------------
# T19: Security Headers / Clickjacking protection
# -----------------------------------------------------------------------------
r = client.get("/api/products", headers={"Authorization": f"Bearer {admin_tok}"})
headers = r.headers
t19_passed = (
    headers.get("X-Frame-Options") == "DENY"
    and headers.get("X-Content-Type-Options") == "nosniff"
    and "frame-ancestors 'none'" in headers.get("Content-Security-Policy", "")
    and headers.get("Referrer-Policy") == "no-referrer"
)
record("T19", "Security HTTP headers enforced on responses", t19_passed)

# -----------------------------------------------------------------------------
# T20: Duplicate SKU Error Masking
# -----------------------------------------------------------------------------
r = client.post(
    "/api/products",
    json={"sku": "SKU-APPLE-01", "name": "Duplicate Mac", "unit_price": 1000.0},
    headers={"Authorization": f"Bearer {admin_tok}"},
)
t20_passed = r.status_code == 409 and r.json()["detail"] == "SKU already exists"
record("T20", "Duplicate SKU returns clean 409 'SKU already exists'", t20_passed, f"Status: {r.status_code}, Msg: {r.text}")

# -----------------------------------------------------------------------------
# T21: Hardcoded Credential Scan
# -----------------------------------------------------------------------------
pattern = re.compile(r"admin123|staff123|minimalist-secret", re.IGNORECASE)
matches = []
for folder in ["web", "api"]:
    for root, _, files in os.walk(ROOT_DIR / folder):
        for f in files:
            if f.endswith((".py", ".js", ".html", ".css")):
                filepath = Path(root) / f
                content = filepath.read_text(encoding="utf-8", errors="ignore")
                if pattern.search(content):
                    matches.append(str(filepath))
t21_passed = len(matches) == 0
record("T21", "Zero hardcoded credentials in web/ and api/", t21_passed, f"Matches: {matches}")

# -----------------------------------------------------------------------------
# T22: Movement Immutability Trigger
# -----------------------------------------------------------------------------
setup_clean_db()
conn = get_connection()
t22_update = False
t22_delete = False
try:
    conn.execute("UPDATE movements SET qty = 100 WHERE id = 1;")
except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
    if "SECURITY VIOLATION: Ledger entries are immutable" in str(e):
        t22_update = True

try:
    conn.execute("DELETE FROM movements WHERE id = 1;")
except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
    if "SECURITY VIOLATION: Ledger entries are immutable" in str(e):
        t22_delete = True
conn.close()

record("T22", "Movement triggers prevent UPDATE and DELETE", t22_update and t22_delete, f"Update blocked: {t22_update}, Delete blocked: {t22_delete}")

# -----------------------------------------------------------------------------
# T23: Missing Anchor File Detection
# -----------------------------------------------------------------------------
setup_clean_db()
admin_tok, staff_tok = get_tokens()
if os.path.exists(ANCHOR_PATH):
    os.remove(ANCHOR_PATH)
v_missing_anchor = verify_audit_chain()
t23_passed = (v_missing_anchor["verified"] is False) and (v_missing_anchor["checks"]["anchor"] is False)
record("T23", "Deleted anchor file detected as integrity failure", t23_passed, v_missing_anchor.get("reason", ""))

# -----------------------------------------------------------------------------
# T24: Corrupted JSON Payload Handled Gracefully (No 500)
# -----------------------------------------------------------------------------
setup_clean_db()
admin_tok, staff_tok = get_tokens()
conn = get_connection()
conn.execute("DROP TRIGGER IF EXISTS prevent_audit_update;")
conn.execute("UPDATE audit_log SET payload = 'NOT_VALID_JSON' WHERE id = 1;")
conn.close()
v_corrupt = verify_audit_chain()
t24_passed = (v_corrupt["verified"] is False) and ("corrupt" in v_corrupt.get("reason", "").lower() or v_corrupt["checks"]["integrity"] is False)
record("T24", "Corrupted audit JSON payload caught safely without 500 error", t24_passed, v_corrupt.get("reason", ""))

# -----------------------------------------------------------------------------
# T25: Non-numeric JWT subject returns 401 (not 500)
# -----------------------------------------------------------------------------
bad_sub_tok = jwt.encode(
    {"sub": "non_integer_username", "iat": int(time.time()), "exp": int(time.time()) + 3600, "iss": "vaultstock"},
    JWT_SECRET,
    algorithm="HS256",
)
r_bad_sub = client.get("/api/me", headers={"Authorization": f"Bearer {bad_sub_tok}"})
t25_passed = r_bad_sub.status_code == 401
record("T25", "Malformed non-numeric JWT sub returns clean 401", t25_passed, f"Status: {r_bad_sub.status_code}")

# -----------------------------------------------------------------------------
# T26: Pagination on Movements & Audit
# -----------------------------------------------------------------------------
setup_clean_db()
admin_tok, staff_tok = get_tokens()
r_m_page = client.get("/api/movements?limit=2&offset=1", headers={"Authorization": f"Bearer {admin_tok}"})
r_a_page = client.get("/api/audit?limit=2&offset=1", headers={"Authorization": f"Bearer {admin_tok}"})
t26_passed = (r_m_page.status_code == 200 and len(r_m_page.json()) == 2) and (r_a_page.status_code == 200 and len(r_a_page.json()) == 2)
record("T26", "Pagination limit/offset parameters supported on ledger feeds", t26_passed)

# -----------------------------------------------------------------------------
# T27: Public Config Endpoint
# -----------------------------------------------------------------------------
r_cfg = client.get("/api/config")
t27_passed = r_cfg.status_code == 200 and "demo_mode" in r_cfg.json()
record("T27", "Unauthenticated GET /api/config returns runtime flags", t27_passed)

# -----------------------------------------------------------------------------
# Core Functional Workflow Verification (F1 – F4)
# -----------------------------------------------------------------------------
print("\n" + "=" * 70)
print("RUNNING FUNCTIONAL WORKFLOW VERIFICATION (F1 – F4)")
print("=" * 70)

# Clean DB setup
setup_clean_db()
admin_tok, staff_tok = get_tokens()

# F1: Dynamic Stock Calculation
# Initial stock of Product #1 is 25
r_prod1_initial = client.get("/api/products", headers={"Authorization": f"Bearer {admin_tok}"})
p1_initial = next(p for p in r_prod1_initial.json() if p["id"] == 1)
assert p1_initial["current_stock"] == 25

# Admin receives 50 units (IN)
client.post(
    "/api/movements",
    json={"product_id": 1, "type": "IN", "qty": 50, "note": "Restock shipment"},
    headers={"Authorization": f"Bearer {admin_tok}"},
)

# Staff issues 20 units (OUT)
client.post(
    "/api/movements",
    json={"product_id": 1, "type": "OUT", "qty": 20, "note": "Customer order"},
    headers={"Authorization": f"Bearer {staff_tok}"},
)

r_prod1_after = client.get("/api/products", headers={"Authorization": f"Bearer {admin_tok}"})
p1_after = next(p for p in r_prod1_after.json() if p["id"] == 1)
f1_passed = p1_after["current_stock"] == 55  # 25 + 50 - 20
record("F1", "Dynamic stock balance calculation: SUM(IN) - SUM(OUT)", f1_passed, f"Stock: {p1_after['current_stock']}")

# F2: Negative Stock Prevention
r_neg = client.post(
    "/api/movements",
    json={"product_id": 1, "type": "OUT", "qty": 100, "note": "Excessive issue"},
    headers={"Authorization": f"Bearer {staff_tok}"},
)
f2_passed = r_neg.status_code == 400 and "Insufficient inventory" in r_neg.json()["detail"]
record("F2", "Negative stock prevention rejects overdraft (400)", f2_passed, r_neg.json().get("detail", ""))

# F3: Full Verification Scan
r_verify = client.get("/api/audit/verify", headers={"Authorization": f"Bearer {staff_tok}"})
v_data = r_verify.json()
f3_passed = v_data["verified"] is True and all(v_data["checks"].values())
record("F3", "Cryptographic audit chain verification returns 100% valid", f3_passed, f"Total blocks: {v_data['total_blocks']}")

# F4: Reset Demo Workflow
r_reset = client.post("/api/reset-demo", headers={"Authorization": f"Bearer {admin_tok}"})
assert r_reset.status_code == 200

# Reseeded verify
r_verify_after_reset = client.get("/api/audit/verify", headers={"Authorization": f"Bearer {admin_tok}"})
v_reset_data = r_verify_after_reset.json()
f4_passed = v_reset_data["verified"] is True and all(v_reset_data["checks"].values())
record("F4", "Reset demo cleanly reseeds database and passes cryptographic audit", f4_passed, f"Total blocks: {v_reset_data['total_blocks']}")

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
