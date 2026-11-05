import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from api.config import (
    ADMIN_PASSWORD,
    ANCHOR_PATH,
    AUDIT_HMAC_KEY,
    DB_PATH,
    DEMO_MODE,
    STAFF_PASSWORD,
)
from api.security import hash_password, verify_password

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def get_connection() -> sqlite3.Connection:
    """Returns a SQLite connection with WAL mode and foreign key constraints enabled."""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 10000;")
    return conn


@contextmanager
def write_tx(conn: sqlite3.Connection):
    """Acquires an immediate write lock for atomic read-check-write transactions."""
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield conn
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise


def canonical_json(data: dict | list | None) -> str:
    """Serializes a dictionary into sorted, compact JSON for deterministic hashing."""
    if data is None:
        return "{}"
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(
    prev_hash: str,
    row_id: int,
    action: str,
    actor: str,
    ref_table: str | None,
    ref_id: int | None,
    payload_json: str,
    timestamp: str,
) -> str:
    """Computes an HMAC-SHA256 digest over the audit block fields."""
    message = json.dumps(
        [prev_hash, row_id, action, actor, ref_table, ref_id, payload_json, timestamp],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hmac.new(AUDIT_HMAC_KEY, message.encode("utf-8"), hashlib.sha256).hexdigest()


def update_anchor(head_id: int, head_hash: str, timestamp: str) -> None:
    """Writes the latest audit block head to an external checkpoint file."""
    anchor_file = Path(ANCHOR_PATH)
    anchor_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = anchor_file.with_suffix(".tmp")
    tmp_file.write_text(
        json.dumps({"id": head_id, "row_hash": head_hash, "timestamp": timestamp}, indent=2),
        encoding="utf-8",
    )
    tmp_file.replace(anchor_file)


def get_anchor() -> dict | None:
    """Reads the external audit head checkpoint file if present."""
    anchor_file = Path(ANCHOR_PATH)
    if not anchor_file.exists():
        return None
    try:
        return json.loads(anchor_file.read_text(encoding="utf-8"))
    except Exception:
        return None


def sync_anchor_to_latest(conn: sqlite3.Connection | None = None) -> None:
    """Queries the latest committed audit block and syncs the external anchor file."""
    own_conn = False
    if conn is None:
        conn = get_connection()
        own_conn = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, row_hash, timestamp FROM audit_log ORDER BY id DESC LIMIT 1;")
        last = cur.fetchone()
        if last:
            update_anchor(last["id"], last["row_hash"], last["timestamp"])
    finally:
        if own_conn:
            conn.close()


def append_audit_entry(
    conn: sqlite3.Connection,
    action: str,
    actor: str,
    ref_table: str | None,
    ref_id: int | None,
    payload: dict | None,
    details: str,
) -> str:
    """Appends a chained HMAC-SHA256 block to audit_log. Anchor file is synced post-commit."""
    cur = conn.cursor()
    cur.execute("SELECT id, row_hash FROM audit_log ORDER BY id DESC LIMIT 1;")
    last = cur.fetchone()

    prev_hash = last["row_hash"] if last else ("0" * 64)
    next_id = (last["id"] + 1) if last else 1
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload_str = canonical_json(payload)

    row_hash = compute_hash(
        prev_hash, next_id, action, actor, ref_table, ref_id, payload_str, now
    )

    cur.execute(
        """
        INSERT INTO audit_log
            (id, action, actor, ref_table, ref_id, payload, details, timestamp, prev_hash, row_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (next_id, action, actor, ref_table, ref_id, payload_str, details, now, prev_hash, row_hash),
    )
    return row_hash


def _expected_table_payload(table: str, row: sqlite3.Row) -> str:
    """Builds the canonical JSON snapshot expected for a product or movement row."""
    if table == "products":
        return canonical_json({
            "id": row["id"],
            "name": row["name"],
            "sku": row["sku"],
            "unit_price": row["unit_price"],
        })
    return canonical_json({
        "created_by": row["created_by"],
        "id": row["id"],
        "note": row["note"],
        "product_id": row["product_id"],
        "qty": row["qty"],
        "type": row["type"],
    })


def verify_audit_chain() -> dict:
    """
    Verifies the integrity of the audit ledger across 5 dimensions:
      1. Contiguity: block IDs are strictly 1..N with no deleted gaps.
      2. Linkage: each block's prev_hash equals the previous block's row_hash.
      3. Integrity: each block's recomputed HMAC-SHA256 matches its stored row_hash.
      4. Reconciliation: every product and movement row matches its audit snapshot.
      5. Anchor: the latest block matches the external checkpoint file.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM audit_log ORDER BY id ASC;")
        records = cur.fetchall()
        total = len(records)
        checks = {
            "contiguity": True,
            "linkage": True,
            "integrity": True,
            "reconciliation": True,
            "anchor": True,
        }

        def fail(check_name: str, broken_id: int | None, reason: str) -> dict:
            checks[check_name] = False
            return {
                "verified": False,
                "broken_at_id": broken_id,
                "reason": reason,
                "total_blocks": total,
                "checks": checks,
            }

        # 1–3. Walk the chain and verify contiguity, prev_hash linkage, and HMAC
        expected_prev = "0" * 64
        for idx, row in enumerate(records, start=1):
            if row["id"] != idx:
                return fail("contiguity", row["id"], f"Missing block: expected #{idx}, found #{row['id']}.")
            if row["prev_hash"] != expected_prev:
                return fail("linkage", row["id"], f"Broken prev_hash link at block #{row['id']}.")

            recomputed = compute_hash(
                row["prev_hash"],
                row["id"],
                row["action"],
                row["actor"],
                row["ref_table"],
                row["ref_id"],
                row["payload"],
                row["timestamp"],
            )
            if not hmac.compare_digest(recomputed, row["row_hash"]):
                return fail("integrity", row["id"], f"HMAC mismatch in block #{row['id']}: data was altered.")

            expected_prev = row["row_hash"]

        # 4. Reconcile relational tables against audit snapshots
        for table in ("movements", "products"):
            cur.execute(f"SELECT * FROM {table} ORDER BY id ASC;")
            for item in cur.fetchall():
                cur.execute(
                    "SELECT * FROM audit_log WHERE ref_table = ? AND ref_id = ?;",
                    (table, item["id"]),
                )
                matches = cur.fetchall()
                if len(matches) != 1:
                    return fail(
                        "reconciliation",
                        None,
                        f"Unlogged {table} row #{item['id']} (found {len(matches)} audit entries).",
                    )
                audit_row = matches[0]
                try:
                    payload_obj = json.loads(audit_row["payload"])
                except (json.JSONDecodeError, TypeError):
                    return fail(
                        "integrity",
                        audit_row["id"],
                        f"Audit block #{audit_row['id']} contains corrupted, unparseable JSON payload.",
                    )
                if canonical_json(payload_obj) != _expected_table_payload(table, item):
                    return fail(
                        "reconciliation",
                        audit_row["id"],
                        f"Audit block #{audit_row['id']} payload does not match {table} row #{item['id']}.",
                    )

            cur.execute("SELECT id, ref_id FROM audit_log WHERE ref_table = ?;", (table,))
            for audit_row in cur.fetchall():
                cur.execute(f"SELECT id FROM {table} WHERE id = ?;", (audit_row["ref_id"],))
                if not cur.fetchone():
                    return fail(
                        "reconciliation",
                        audit_row["id"],
                        f"Audit block #{audit_row['id']} references missing {table} row #{audit_row['ref_id']}.",
                    )

        # 5. Compare chain head against external anchor
        anchor = get_anchor()
        if records:
            if not anchor:
                return fail(
                    "anchor",
                    records[-1]["id"],
                    "External anchor file is missing; cannot verify ledger against out-of-band checkpoint.",
                )
            head_id = records[-1]["id"]
            head_hash = records[-1]["row_hash"]
            if head_id != anchor.get("id") or head_hash != anchor.get("row_hash"):
                return fail(
                    "anchor",
                    head_id,
                    f"Chain head (#{head_id}) does not match external anchor (#{anchor.get('id')}).",
                )
        elif anchor and anchor.get("id", 0) != 0:
            return fail(
                "anchor",
                0,
                f"Database has 0 blocks but external anchor references block #{anchor.get('id')}.",
            )

        return {
            "verified": True,
            "broken_at_id": None,
            "reason": "All audit blocks verified.",
            "total_blocks": total,
            "checks": checks,
        }
    finally:
        conn.close()


def tamper_for_demo(block_id: int = 1, file_level: bool = True) -> dict:
    """
    Simulates database tampering for presentation demonstrations:
      - file_level=False: runs a normal SQL UPDATE (blocked immediately by SQLite trigger).
      - file_level=True: bypasses the trigger and rewrites block #1 with an unkeyed SHA-256
        hash (simulating a direct disk edit without the secret HMAC key).
    """
    conn = get_connection()
    try:
        if not file_level:
            conn.execute(
                "UPDATE audit_log SET details = details || ' [TAMPERED]' WHERE id = ?;",
                (block_id,),
            )
            return {"status": "tampered", "type": "app_level"}

        cur = conn.cursor()
        cur.execute("DROP TRIGGER IF EXISTS prevent_audit_update;")
        cur.execute("SELECT * FROM audit_log WHERE id = ?;", (block_id,))
        target = cur.fetchone()
        if not target:
            return {"status": "error", "message": f"Block #{block_id} not found"}

        fake_msg = json.dumps(
            [
                target["prev_hash"],
                target["id"],
                target["action"],
                target["actor"],
                target["ref_table"],
                target["ref_id"],
                target["payload"],
                target["timestamp"],
            ],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        fake_hash = hashlib.sha256(fake_msg.encode("utf-8")).hexdigest()

        cur.execute(
            "UPDATE audit_log SET details = ?, row_hash = ? WHERE id = ?;",
            (target["details"] + " [TAMPERED]", fake_hash, block_id),
        )
        cur.execute(
            """
            CREATE TRIGGER IF NOT EXISTS prevent_audit_update
            BEFORE UPDATE ON audit_log
            BEGIN
                SELECT RAISE(ABORT, 'SECURITY VIOLATION: Audit log is immutable.');
            END;
            """
        )
        return {"status": "tampered", "type": "file_level", "fake_hash": fake_hash}
    finally:
        conn.close()


def init_db() -> None:
    """Initializes schema, triggers, demo users, and initial catalog seed data."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))

        with write_tx(conn):
            cur = conn.cursor()

            default_admin_pw = "vault-admin-2026" if DEMO_MODE else secrets.token_urlsafe(12)
            default_staff_pw = "vault-staff-2026" if DEMO_MODE else secrets.token_urlsafe(12)
            admin_pw = ADMIN_PASSWORD or default_admin_pw
            staff_pw = STAFF_PASSWORD or default_staff_pw

            cur.execute("SELECT COUNT(*) as cnt FROM users;")
            if cur.fetchone()["cnt"] == 0:
                print(f"[*] Seeded users -> admin: {admin_pw} | staff: {staff_pw}")
                cur.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?);",
                    ("admin", hash_password(admin_pw), "admin"),
                )
                cur.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?);",
                    ("staff", hash_password(staff_pw), "staff"),
                )
            elif ADMIN_PASSWORD or STAFF_PASSWORD or DEMO_MODE:
                # Ensure configured or demo passwords stay active across restarts
                for uname, pw in (("admin", admin_pw), ("staff", staff_pw)):
                    cur.execute("SELECT password_hash FROM users WHERE username = ?;", (uname,))
                    row = cur.fetchone()
                    if row and not verify_password(pw, row["password_hash"]):
                        cur.execute(
                            "UPDATE users SET password_hash = ? WHERE username = ?;",
                            (hash_password(pw), uname),
                        )

            cur.execute("SELECT COUNT(*) as cnt FROM products;")
            if cur.fetchone()["cnt"] == 0:
                seed_items = [
                    ("SKU-APPLE-01", "MacBook Pro 16-inch M3", 2499.00),
                    ("SKU-APPLE-02", "Magic Keyboard with Touch ID", 199.00),
                    ("SKU-APPLE-03", "Studio Display 27-inch 5K", 1599.00),
                    ("SKU-APPLE-04", "AirPods Pro 2nd Gen", 249.00),
                ]
                for sku, name, price in seed_items:
                    cur.execute(
                        "INSERT INTO products (sku, name, unit_price) VALUES (?, ?, ?);",
                        (sku, name, price),
                    )
                    p_id = cur.lastrowid
                    append_audit_entry(
                        conn,
                        "PRODUCT_CREATE",
                        "system",
                        "products",
                        p_id,
                        {"id": p_id, "name": name, "sku": sku, "unit_price": price},
                        f"Created product '{name}' ({sku})",
                    )

                    cur.execute(
                        """
                        INSERT INTO movements (product_id, type, qty, note, created_by)
                        VALUES (?, 'IN', 25, 'Initial stock shipment received', 'system');
                        """,
                        (p_id,),
                    )
                    m_id = cur.lastrowid
                    append_audit_entry(
                        conn,
                        "STOCK_RECEIVE",
                        "system",
                        "movements",
                        m_id,
                        {
                            "created_by": "system",
                            "id": m_id,
                            "note": "Initial stock shipment received",
                            "product_id": p_id,
                            "qty": 25,
                            "type": "IN",
                        },
                        f"Initial stock IN: 25 units for product #{p_id}",
                    )
            sync_anchor_to_latest(conn)
    finally:
        conn.close()


def reset_demo_db(admin_actor: str = "admin") -> None:
    """Drops all tables and triggers, re-seeds initial data, and logs DEMO_RESET."""
    conn = get_connection()
    try:
        conn.executescript(
            """
            DROP TRIGGER IF EXISTS prevent_negative_stock;
            DROP TRIGGER IF EXISTS prevent_movement_update;
            DROP TRIGGER IF EXISTS prevent_movement_delete;
            DROP TRIGGER IF EXISTS prevent_product_update;
            DROP TRIGGER IF EXISTS prevent_product_delete;
            DROP TRIGGER IF EXISTS prevent_audit_update;
            DROP TRIGGER IF EXISTS prevent_audit_delete;
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS movements;
            DROP TABLE IF EXISTS products;
            DROP TABLE IF EXISTS users;
            """
        )
    finally:
        conn.close()

    Path(ANCHOR_PATH).unlink(missing_ok=True)
    init_db()

    conn = get_connection()
    try:
        with write_tx(conn):
            append_audit_entry(
                conn,
                "DEMO_RESET",
                admin_actor,
                None,
                None,
                {"action": "DEMO_RESET", "reset_by": admin_actor},
                f"Database reset to initial seed state by {admin_actor}",
            )
        sync_anchor_to_latest(conn)
    finally:
        conn.close()


def get_db_debug_info() -> dict:
    """Returns live SQLite engine telemetry, active PRAGMAs, triggers, indices, and head state."""
    conn = get_connection()
    try:
        cur = conn.cursor()

        journal_mode = cur.execute("PRAGMA journal_mode;").fetchone()[0]
        foreign_keys = cur.execute("PRAGMA foreign_keys;").fetchone()[0]
        busy_timeout = cur.execute("PRAGMA busy_timeout;").fetchone()[0]
        synchronous = cur.execute("PRAGMA synchronous;").fetchone()[0]
        page_size = cur.execute("PRAGMA page_size;").fetchone()[0]
        page_count = cur.execute("PRAGMA page_count;").fetchone()[0]

        counts = {}
        for tbl in ("users", "products", "movements", "audit_log"):
            counts[tbl] = cur.execute(f"SELECT COUNT(*) FROM {tbl};").fetchone()[0]

        cur.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY tbl_name, name;"
        )
        triggers = [dict(r) for r in cur.fetchall()]

        cur.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        )
        tables = [dict(r) for r in cur.fetchall()]

        cur.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL ORDER BY name;"
        )
        indices = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT id, action, row_hash, prev_hash, timestamp FROM audit_log ORDER BY id DESC LIMIT 1;")
        db_head = cur.fetchone()

        return {
            "sqlite_version": sqlite3.sqlite_version,
            "pragmas": {
                "journal_mode": str(journal_mode).upper(),
                "foreign_keys": bool(foreign_keys),
                "busy_timeout_ms": int(busy_timeout),
                "synchronous": int(synchronous),
                "page_size_bytes": int(page_size),
                "db_size_bytes": int(page_size) * int(page_count),
            },
            "row_counts": counts,
            "triggers": triggers,
            "tables": tables,
            "indices": indices,
            "db_head": dict(db_head) if db_head else None,
            "external_anchor": get_anchor(),
        }
    finally:
        conn.close()


def run_sql_probe(probe_type: str) -> dict:
    """
    Executes a safe diagnostic SQL probe against SQLite to demonstrate triggers,
    constraints, and query execution plans in real time.
    """
    import time as _time

    probes = {
        "explain_stock": {
            "title": "EXPLAIN QUERY PLAN — Dynamic Stock Derivation",
            "sql": (
                "EXPLAIN QUERY PLAN\n"
                "SELECT p.id, p.sku, p.name,\n"
                "       COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.qty ELSE -m.qty END), 0) AS current_stock\n"
                "FROM products p\n"
                "LEFT JOIN movements m ON p.id = m.product_id\n"
                "GROUP BY p.id ORDER BY p.id ASC;"
            ),
            "mode": "explain",
            "process_steps": [
                "1. Client issues balance query with SUM(IN) - SUM(OUT) aggregation.",
                "2. SQLite parser builds execution tree: SCAN table 'products' in primary key order.",
                "3. SQLite executes SEARCH on 'movements' via index 'idx_movements_product_id' for each product.",
                "4. Correlated aggregation computes non-persisted real-time stock balance in memory.",
                "5. Zero mutable counter column exists — guarantees 100% historical accuracy and 3NF/BCNF normalization."
            ],
        },
        "trigger_negative_stock": {
            "title": "Trigger Defense — Overdraft Prevention Guard",
            "sql": "INSERT INTO movements (product_id, type, qty, note, created_by) VALUES (1, 'OUT', 999999, 'Direct SQL overdraft', 'debug_probe');",
            "mode": "trigger",
            "process_steps": [
                "1. Application opens write transaction with exclusive write lock (BEGIN IMMEDIATE).",
                "2. SQLite fires trigger 'prevent_negative_stock' BEFORE INSERT WHEN NEW.type = 'OUT'.",
                "3. Trigger evaluates subquery: (SELECT COALESCE(SUM(IN) - SUM(OUT), 0) FROM movements) < NEW.qty.",
                "4. Available balance is less than 999,999 -> Trigger executes RAISE(ABORT, 'SECURITY VIOLATION: Insufficient stock.').",
                "5. SQLite halts statement immediately and rolls back; inventory never drops below zero."
            ],
        },
        "trigger_movement_update": {
            "title": "Trigger Defense — Block UPDATE on Movements",
            "sql": "UPDATE movements SET qty = 9999 WHERE id = 1;",
            "mode": "trigger",
            "process_steps": [
                "1. Process attempts direct SQL UPDATE on historical movement row #1.",
                "2. SQLite storage engine intercepts query with BEFORE UPDATE trigger 'prevent_movement_update'.",
                "3. Trigger unconditionally calls RAISE(ABORT, 'SECURITY VIOLATION: Ledger entries are immutable and cannot be updated.').",
                "4. Database write is rejected at the storage layer, defending against SQL injections or rogue application code.",
                "5. Movement table remains strictly append-only."
            ],
        },
        "trigger_movement_delete": {
            "title": "Trigger Defense — Block DELETE on Movements",
            "sql": "DELETE FROM movements WHERE id = 1;",
            "mode": "trigger",
            "process_steps": [
                "1. Process attempts direct SQL DELETE on historical movement row #1.",
                "2. SQLite storage engine intercepts query with BEFORE DELETE trigger 'prevent_movement_delete'.",
                "3. Trigger calls RAISE(ABORT, 'SECURITY VIOLATION: Ledger entries are immutable and cannot be deleted.').",
                "4. Row is preserved; historical audit records cannot be erased by any user."
            ],
        },
        "trigger_audit_update": {
            "title": "Trigger Defense — Block UPDATE on Audit Log",
            "sql": "UPDATE audit_log SET details = 'Forged entry' WHERE id = 1;",
            "mode": "trigger",
            "process_steps": [
                "1. Attacker attempts to modify historical audit block #1.",
                "2. SQLite storage engine intercepts with BEFORE UPDATE trigger 'prevent_audit_update'.",
                "3. Trigger unconditionally aborts with RAISE(ABORT, 'SECURITY VIOLATION: Audit log is immutable.').",
                "4. Cryptographic record and HMAC signature are protected from unauthorized modification."
            ],
        },
        "trigger_audit_delete": {
            "title": "Trigger Defense — Block DELETE on Audit Log",
            "sql": "DELETE FROM audit_log WHERE id = 1;",
            "mode": "trigger",
            "process_steps": [
                "1. Attacker attempts to delete audit block #1 to hide evidence.",
                "2. SQLite storage engine intercepts with BEFORE DELETE trigger 'prevent_audit_delete'.",
                "3. Trigger aborts with RAISE(ABORT, 'SECURITY VIOLATION: Audit log is immutable.').",
                "4. Continuous 1..N block contiguity is guaranteed."
            ],
        },
        "trigger_product_delete": {
            "title": "Trigger Defense — Block DELETE on Products",
            "sql": "DELETE FROM products WHERE id = 1;",
            "mode": "trigger",
            "process_steps": [
                "1. Attacker attempts to drop product row #1.",
                "2. SQLite storage engine intercepts with BEFORE DELETE trigger 'prevent_product_delete'.",
                "3. Trigger aborts with RAISE(ABORT, 'SECURITY VIOLATION: Products cannot be deleted.').",
                "4. Product catalog remains immutable; orphaned movement references are impossible."
            ],
        },
    }

    if probe_type not in probes:
        return {"status": "error", "message": f"Unknown probe: {probe_type}"}

    spec = probes[probe_type]
    conn = get_connection()
    t0 = _time.perf_counter()
    try:
        cur = conn.cursor()
        if spec["mode"] == "explain":
            cur.execute(spec["sql"])
            rows = [dict(r) for r in cur.fetchall()]
            elapsed_ms = round((_time.perf_counter() - t0) * 1000, 3)
            plan_lines = [f"[{r.get('id', idx)}] {r.get('detail', '')}" for idx, r in enumerate(rows)]
            return {
                "probe": probe_type,
                "title": spec["title"],
                "sql": spec["sql"],
                "outcome": "QUERY PLAN GENERATED",
                "blocked_by_trigger": False,
                "elapsed_ms": elapsed_ms,
                "engine_output": "\n".join(plan_lines) if plan_lines else "SCAN products / SEARCH movements",
                "process_steps": spec.get("process_steps", []),
            }
        else:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                cur.execute(spec["sql"])
                conn.execute("ROLLBACK;")
                elapsed_ms = round((_time.perf_counter() - t0) * 1000, 3)
                return {
                    "probe": probe_type,
                    "title": spec["title"],
                    "sql": spec["sql"],
                    "outcome": "UNEXPECTEDLY ALLOWED (ROLLED BACK)",
                    "blocked_by_trigger": False,
                    "elapsed_ms": elapsed_ms,
                    "engine_output": "Statement did not trigger an abort (rolled back safely).",
                    "process_steps": spec.get("process_steps", []),
                }
            except (sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
                conn.execute("ROLLBACK;")
                elapsed_ms = round((_time.perf_counter() - t0) * 1000, 3)
                return {
                    "probe": probe_type,
                    "title": spec["title"],
                    "sql": spec["sql"],
                    "outcome": "ABORTED BY SQLITE ENGINE TRIGGER",
                    "blocked_by_trigger": True,
                    "elapsed_ms": elapsed_ms,
                    "engine_output": f"sqlite3.IntegrityError: {str(exc)}",
                    "process_steps": spec.get("process_steps", []),
                }
    finally:
        conn.close()
