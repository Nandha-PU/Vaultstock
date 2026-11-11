import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
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
    ref_table: str,
    ref_id: int,
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


_ANCHOR_LOCK = threading.Lock()


def update_anchor(head_id: int, head_hash: str, timestamp: str) -> None:
    """Writes the latest audit block head to an external checkpoint file."""
    anchor_file = Path(ANCHOR_PATH)
    anchor_file.parent.mkdir(parents=True, exist_ok=True)
    with _ANCHOR_LOCK:
        tmp_file = anchor_file.with_name(f"{anchor_file.name}.{secrets.token_hex(4)}.tmp")
        try:
            tmp_file.write_text(
                json.dumps({"id": head_id, "row_hash": head_hash, "timestamp": timestamp}, indent=2),
                encoding="utf-8",
            )
            tmp_file.replace(anchor_file)
        finally:
            tmp_file.unlink(missing_ok=True)


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
    ref_table: str,
    ref_id: int,
    payload: dict,
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
            "category_id": row["category_id"],
            "id": row["id"],
            "name": row["name"],
            "reorder_threshold": row["reorder_threshold"],
            "sku": row["sku"],
            "unit_price": row["unit_price"],
        })
    return canonical_json({
        "created_by": row["created_by"],
        "id": row["id"],
        "location_id": row["location_id"],
        "note": row["note"],
        "product_id": row["product_id"],
        "qty": row["qty"],
        "reference_doc": row["reference_doc"],
        "supplier_id": row["supplier_id"],
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


def tamper_for_demo(block_id: int = 1) -> dict:
    """
    Simulates disk-level database tampering for presentation demonstrations:
    bypasses the SQLite trigger and rewrites block #1 with an unkeyed SHA-256
    hash (simulating a direct disk edit without the secret HMAC key).
    """
    conn = get_connection()
    try:
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
            (target["details"] + " [TAMPERED - UNKEYED HASH]", fake_hash, block_id),
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
    """Initializes schema, triggers, demo users, and realistic relational seed data."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))

        with write_tx(conn):
            cur = conn.cursor()

            # 1. Seed demo users
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
                for uname, pw in (("admin", admin_pw), ("staff", staff_pw)):
                    cur.execute("SELECT password_hash FROM users WHERE username = ?;", (uname,))
                    row = cur.fetchone()
                    if row and not verify_password(pw, row["password_hash"]):
                        cur.execute(
                            "UPDATE users SET password_hash = ? WHERE username = ?;",
                            (hash_password(pw), uname),
                        )

            # 2. Seed Categories
            cur.execute("SELECT COUNT(*) as cnt FROM categories;")
            if cur.fetchone()["cnt"] == 0:
                categories = [
                    ("COMP", "Computer Hardware & Peripherals", "Laptops, workstations, displays, and high-performance peripherals"),
                    ("NET", "Networking Equipment", "Enterprise routers, managed switches, and Wi-Fi 6 access points"),
                    ("OFF", "Office Supplies & Paper", "Toner, ergonomic accessories, and warehouse packaging supplies"),
                    ("PWR", "Power & Electrical Tools", "Cordless drills, testing equipment, and industrial battery packs"),
                ]
                cur.executemany(
                    "INSERT INTO categories (code, name, description) VALUES (?, ?, ?);",
                    categories,
                )

            # 3. Seed Suppliers
            cur.execute("SELECT COUNT(*) as cnt FROM suppliers;")
            if cur.fetchone()["cnt"] == 0:
                suppliers = [
                    ("Apex Global Electronics", "dispatch@apexelectronics.com", "+1-800-555-0144"),
                    ("LogiTech Wholesale", "supply@logitechwholesale.com", "+1-800-555-0288"),
                    ("Prime Industrial Supply", "orders@primeindustrialsupply.com", "+1-800-555-0399"),
                ]
                cur.executemany(
                    "INSERT INTO suppliers (name, contact_email, phone) VALUES (?, ?, ?);",
                    suppliers,
                )

            # 4. Seed Storage Locations
            cur.execute("SELECT COUNT(*) as cnt FROM locations;")
            if cur.fetchone()["cnt"] == 0:
                locations = [
                    ("WH-A1", "Main Warehouse Section A"),
                    ("WH-B2", "Secondary Storage Depot B"),
                    ("RETAIL-1", "Storefront Retail Floor"),
                ]
                cur.executemany(
                    "INSERT INTO locations (code, name) VALUES (?, ?);",
                    locations,
                )

            # 5. Seed Catalog Products & Initial Movements
            cur.execute("SELECT COUNT(*) as cnt FROM products;")
            if cur.fetchone()["cnt"] == 0:
                seed_products = [
                    ("SKU-LAPTOP-01", "MacBook Pro 16-inch M3", 1, 2499.00, 5, 25, 1, 1, "PO-2026-001"),
                    ("SKU-KBD-02", "Mechanical Wireless Keyboard", 1, 149.00, 10, 40, 2, 1, "PO-2026-002"),
                    ("SKU-DISP-03", "4K Ultra-Wide Monitor 34-inch", 1, 799.00, 8, 15, 1, 2, "PO-2026-003"),
                    ("SKU-ROUTER-04", "Enterprise WiFi-6 Mesh Router", 2, 349.00, 6, 20, 2, 2, "PO-2026-004"),
                    ("SKU-TONER-05", "High-Yield Laser Toner Cartridge", 3, 89.00, 15, 30, 3, 1, "PO-2026-005"),
                    ("SKU-DRILL-06", "Cordless Brushless Hammer Drill 20V", 4, 189.00, 8, 18, 3, 3, "PO-2026-006"),
                ]
                for sku, name, cat_id, price, threshold, initial_qty, supp_id, loc_id, po_ref in seed_products:
                    cur.execute(
                        """
                        INSERT INTO products (sku, name, category_id, unit_price, reorder_threshold)
                        VALUES (?, ?, ?, ?, ?);
                        """,
                        (sku, name, cat_id, price, threshold),
                    )
                    p_id = cur.lastrowid
                    p_payload = {
                        "category_id": cat_id,
                        "id": p_id,
                        "name": name,
                        "reorder_threshold": threshold,
                        "sku": sku,
                        "unit_price": price,
                    }
                    append_audit_entry(
                        conn,
                        "PRODUCT_CREATE",
                        "system",
                        "products",
                        p_id,
                        p_payload,
                        f"Created product '{name}' ({sku}) under category #{cat_id}",
                    )

                    cur.execute(
                        """
                        INSERT INTO movements (product_id, supplier_id, location_id, type, qty, reference_doc, note, created_by)
                        VALUES (?, ?, ?, 'IN', ?, ?, 'Initial inventory stock receipt', 'system');
                        """,
                        (p_id, supp_id, loc_id, initial_qty, po_ref),
                    )
                    m_id = cur.lastrowid
                    m_payload = {
                        "created_by": "system",
                        "id": m_id,
                        "location_id": loc_id,
                        "note": "Initial inventory stock receipt",
                        "product_id": p_id,
                        "qty": initial_qty,
                        "reference_doc": po_ref,
                        "supplier_id": supp_id,
                        "type": "IN",
                    }
                    append_audit_entry(
                        conn,
                        "STOCK_RECEIVE",
                        "system",
                        "movements",
                        m_id,
                        m_payload,
                        f"Initial receipt: {initial_qty} units of '{name}' via {po_ref}",
                    )
            sync_anchor_to_latest(conn)
    finally:
        conn.close()


def reset_demo_db() -> None:
    """Drops all tables, views, and triggers, compacts storage, and cleanly reseeds initial data."""
    conn = get_connection()
    try:
        conn.executescript(
            """
            DROP VIEW IF EXISTS v_location_inventory;
            DROP VIEW IF EXISTS v_ledger_history;
            DROP VIEW IF EXISTS v_low_stock_alerts;
            DROP VIEW IF EXISTS v_inventory_summary;
            DROP TRIGGER IF EXISTS prevent_negative_stock;
            DROP TRIGGER IF EXISTS prevent_movement_update;
            DROP TRIGGER IF EXISTS prevent_movement_delete;
            DROP TRIGGER IF EXISTS prevent_product_delete;
            DROP TRIGGER IF EXISTS prevent_product_update;
            DROP TRIGGER IF EXISTS prevent_audit_update;
            DROP TRIGGER IF EXISTS prevent_audit_delete;
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS movements;
            DROP TABLE IF EXISTS products;
            DROP TABLE IF EXISTS locations;
            DROP TABLE IF EXISTS suppliers;
            DROP TABLE IF EXISTS categories;
            DROP TABLE IF EXISTS users;
            DELETE FROM sqlite_sequence;
            VACUUM;
            """
        )
    finally:
        conn.close()

    Path(ANCHOR_PATH).unlink(missing_ok=True)
    init_db()


def get_db_debug_info() -> dict:
    """Returns live SQLite engine telemetry, active PRAGMAs, row counts, triggers, and views."""
    conn = get_connection()
    try:
        cur = conn.cursor()

        journal_mode = cur.execute("PRAGMA journal_mode;").fetchone()[0]
        foreign_keys = cur.execute("PRAGMA foreign_keys;").fetchone()[0]
        busy_timeout = cur.execute("PRAGMA busy_timeout;").fetchone()[0]
        page_size = cur.execute("PRAGMA page_size;").fetchone()[0]
        page_count = cur.execute("PRAGMA page_count;").fetchone()[0]

        counts = {}
        for tbl in ("users", "categories", "suppliers", "locations", "products", "movements", "audit_log"):
            try:
                counts[tbl] = cur.execute(f"SELECT COUNT(*) FROM {tbl};").fetchone()[0]
            except sqlite3.OperationalError:
                counts[tbl] = 0

        cur.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY tbl_name, name;"
        )
        triggers = [dict(r) for r in cur.fetchall()]

        cur.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'view' ORDER BY name;"
        )
        views = [dict(r) for r in cur.fetchall()]

        return {
            "sqlite_version": sqlite3.sqlite_version,
            "pragmas": {
                "journal_mode": str(journal_mode).upper(),
                "foreign_keys": bool(foreign_keys),
                "busy_timeout_ms": int(busy_timeout),
                "page_size_bytes": int(page_size),
                "db_size_bytes": int(page_size) * int(page_count),
            },
            "row_counts": counts,
            "triggers": triggers,
            "views": views,
        }
    finally:
        conn.close()


ALLOWED_DB_OBJECTS = {
    "categories",
    "suppliers",
    "locations",
    "products",
    "movements",
    "audit_log",
    "users",
    "v_inventory_summary",
    "v_low_stock_alerts",
    "v_ledger_history",
    "v_location_inventory",
}


def inspect_table_or_view(name: str, limit: int = 50) -> dict:
    """
    Returns full relational metadata (columns, data types, PK/FK constraints, DDL SQL)
    and live raw rows for a given table or view so faculty/evaluators can inspect the actual DB.
    """
    if name not in ALLOWED_DB_OBJECTS:
        raise ValueError(f"Object '{name}' is not an inspectable database table or view.")

    safe_limit = max(1, min(limit, 200))
    conn = get_connection()
    try:
        cur = conn.cursor()

        # 1. Object type & DDL SQL from sqlite_master
        cur.execute("SELECT type, sql FROM sqlite_master WHERE name = ?;", (name,))
        meta = cur.fetchone()
        obj_type = meta["type"].upper() if meta else "TABLE"
        ddl_sql = meta["sql"] if meta else ""

        # 2. Column metadata via PRAGMA table_info
        cur.execute(f"PRAGMA table_info({name});")
        columns = []
        for col in cur.fetchall():
            columns.append({
                "cid": col["cid"],
                "name": col["name"],
                "type": col["type"] or "DYNAMIC (VIEW)",
                "notnull": bool(col["notnull"]),
                "default_value": col["dflt_value"],
                "is_pk": bool(col["pk"]),
            })

        # 3. Foreign key metadata via PRAGMA foreign_key_list
        foreign_keys = []
        if obj_type == "TABLE":
            cur.execute(f"PRAGMA foreign_key_list({name});")
            for fk in cur.fetchall():
                foreign_keys.append({
                    "column": fk["from"],
                    "references_table": fk["table"],
                    "references_column": fk["to"],
                    "on_delete": fk["on_delete"],
                    "on_update": fk["on_update"],
                })

        # 4. Total row count & raw rows
        total_rows = cur.execute(f"SELECT COUNT(*) FROM {name};").fetchone()[0]
        cur.execute(f"SELECT * FROM {name} LIMIT ?;", (safe_limit,))
        raw_rows = [dict(r) for r in cur.fetchall()]
        for r in raw_rows:
            if "password_hash" in r and r["password_hash"]:
                r["password_hash"] = "pbkdf2_sha256$150000$***REDACTED***"

        return {
            "name": name,
            "object_type": obj_type,
            "ddl_sql": ddl_sql,
            "total_rows": total_rows,
            "columns": columns,
            "foreign_keys": foreign_keys,
            "rows": raw_rows,
        }
    finally:
        conn.close()


def get_full_database_dump(limit: int = 50) -> dict:
    """
    Returns the entire database schema, all tables, all views, foreign key metadata,
    and raw rows in a single payload for the Full DB & Visual ER Diagram view.
    """
    table_names = [
        "categories",
        "suppliers",
        "locations",
        "products",
        "movements",
        "audit_log",
        "users",
    ]
    view_names = [
        "v_inventory_summary",
        "v_low_stock_alerts",
        "v_ledger_history",
        "v_location_inventory",
    ]

    return {
        "tables": [inspect_table_or_view(t, limit=limit) for t in table_names],
        "views": [inspect_table_or_view(v, limit=limit) for v in view_names],
    }


def run_sql_probe(probe_type: str) -> dict:
    """
    Executes a safe diagnostic SQL probe against SQLite to demonstrate triggers,
    constraints, and query execution plans in real time.
    """
    import time as _time

    probes = {
        "explain_stock": {
            "title": "EXPLAIN QUERY PLAN — Relational Stock Derivation View",
            "sql": (
                "EXPLAIN QUERY PLAN\n"
                "SELECT * FROM v_inventory_summary;"
            ),
            "mode": "explain",
            "process_steps": [
                "1. Client accesses relational view 'v_inventory_summary'.",
                "2. SQLite parser builds execution tree: SCAN table 'products' in PK order.",
                "3. SQLite performs SEARCH on 'categories' using PRIMARY KEY (id).",
                "4. SQLite executes SEARCH on 'movements' via index 'idx_movements_product_id' for each product.",
                "5. Aggregates SUM(IN) - SUM(OUT) in memory and evaluates 'stock <= reorder_threshold' to set low-stock flag.",
                "6. Normalization: Zero mutable stock counter — guarantees non-repudiation and eliminates lost-update anomalies."
            ],
        },
        "trigger_negative_stock": {
            "title": "Trigger Defense — Overdraft Prevention Guard",
            "sql": "INSERT INTO movements (product_id, type, qty, note, created_by) VALUES (1, 'OUT', 999999, 'Direct SQL overdraft attempt', 'probe_actor');",
            "mode": "trigger",
            "process_steps": [
                "1. Application initiates write transaction with immediate write lock (BEGIN IMMEDIATE).",
                "2. SQLite fires trigger 'prevent_negative_stock' BEFORE INSERT WHEN NEW.type = 'OUT'.",
                "3. Trigger evaluates subquery: (SELECT COALESCE(SUM(IN) - SUM(OUT), 0) FROM movements WHERE product_id = 1) < 999999.",
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
            "sql": "UPDATE audit_log SET details = 'manipulated' WHERE id = 1;",
            "mode": "trigger",
            "process_steps": [
                "1. Process attempts direct SQL UPDATE on cryptographic audit_log block #1.",
                "2. SQLite storage engine intercepts query with BEFORE UPDATE trigger 'prevent_audit_update'.",
                "3. Trigger calls RAISE(ABORT, 'SECURITY VIOLATION: Audit log is immutable.').",
                "4. Direct modification fails instantly at the database kernel level."
            ],
        },
        "trigger_product_delete": {
            "title": "Referential Guard — Block DELETE on Products",
            "sql": "DELETE FROM products WHERE id = 1;",
            "mode": "trigger",
            "process_steps": [
                "1. User attempts to DELETE product #1 from catalog.",
                "2. Engine intercepts with 'prevent_product_delete' BEFORE DELETE trigger.",
                "3. Aborts with RAISE(ABORT, 'SECURITY VIOLATION: Products cannot be deleted; historical ledger requires referential integrity.').",
                "4. Eliminates orphaned rows in movements and preserves audit trail."
            ],
        },
        "trigger_product_update": {
            "title": "Referential Guard — Block UPDATE on Products",
            "sql": "UPDATE products SET unit_price = 0.01 WHERE id = 1;",
            "mode": "trigger",
            "process_steps": [
                "1. User or rogue script attempts to UPDATE product #1 catalog record.",
                "2. Engine intercepts with 'prevent_product_update' BEFORE UPDATE trigger.",
                "3. Aborts with RAISE(ABORT, 'SECURITY VIOLATION: Products cannot be updated; catalog records are immutable.').",
                "4. Protects historic valuation, prevents catalog tampering, and enforces non-repudiation."
            ],
        },
    }

    if probe_type not in probes:
        return {"error": f"Unknown probe type: {probe_type}"}

    cfg = probes[probe_type]
    t0 = _time.perf_counter()
    conn = get_connection()
    try:
        cur = conn.cursor()
        if cfg["mode"] == "explain":
            cur.execute(cfg["sql"])
            rows = [dict(r) for r in cur.fetchall()]
            elapsed_ms = (_time.perf_counter() - t0) * 1000
            return {
                "probe": probe_type,
                "title": cfg["title"],
                "sql": cfg["sql"],
                "status": "EXPLAINED",
                "result": "Query plan generated successfully.",
                "plan_rows": rows,
                "process_steps": cfg["process_steps"],
                "execution_time_ms": round(elapsed_ms, 3),
            }
        else:
            try:
                with write_tx(conn):
                    cur.execute(cfg["sql"])
                elapsed_ms = (_time.perf_counter() - t0) * 1000
                return {
                    "probe": probe_type,
                    "title": cfg["title"],
                    "sql": cfg["sql"],
                    "status": "UNEXPECTED_SUCCESS",
                    "result": "Query succeeded unexpectedly.",
                    "process_steps": cfg["process_steps"],
                    "execution_time_ms": round(elapsed_ms, 3),
                }
            except (sqlite3.IntegrityError, sqlite3.OperationalError) as err:
                elapsed_ms = (_time.perf_counter() - t0) * 1000
                err_str = str(err)
                intercepted = "SECURITY VIOLATION" in err_str
                return {
                    "probe": probe_type,
                    "title": cfg["title"],
                    "sql": cfg["sql"],
                    "status": "INTERCEPTED" if intercepted else "ERROR",
                    "result": err_str,
                    "process_steps": cfg["process_steps"],
                    "execution_time_ms": round(elapsed_ms, 3),
                }
    finally:
        conn.close()
