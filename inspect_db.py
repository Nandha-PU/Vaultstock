#!/usr/bin/env python3
"""
VaultStock — Interactive Backend & SQLite Shell (inspect_db.py / inspect-db.py)
Directly inspect, query, modify, and test the backend SQLite database and
cryptographic audit engine from the terminal during a DBMS viva or evaluation.

Usage:
  python inspect_db.py                 # Shows DB status & launches interactive shell
  python inspect_db.py --shell         # Launches the interactive SQL & backend shell
  python inspect_db.py --dump          # Prints full schema & rows for all tables/views
  python inspect_db.py products        # Prints schema & rows for a specific table/view
  python inspect_db.py -c "SELECT ..." # Runs a one-off SQL statement from CLI
"""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure demo mode defaults match run_dev.py so .reset preserves demo credentials
os.environ.setdefault("VAULTSTOCK_DEMO_MODE", "1")

from api.config import ANCHOR_PATH, DB_PATH
from api.db import (
    _split_sql_statements,
    append_audit_entry,
    execute_interactive_sql,
    get_anchor,
    get_connection,
    get_db_debug_info,
    get_triggers_status,
    init_db,
    reset_demo_db,
    set_storage_triggers,
    sync_anchor_to_latest,
    tamper_for_demo,
    verify_audit_chain,
    write_tx,
)


def print_ascii_table(headers: list[str], rows: list[list], max_col_width: int = 40) -> None:
    if not headers:
        return
    col_widths = [len(str(h)) for h in headers]
    formatted_rows = []
    for r in rows:
        fmt_row = []
        for idx, val in enumerate(r):
            s = "NULL" if val is None else str(val)
            if len(s) > max_col_width:
                s = s[: max_col_width - 3] + "..."
            fmt_row.append(s)
            if idx < len(col_widths):
                col_widths[idx] = max(col_widths[idx], len(s))
        formatted_rows.append(fmt_row)

    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    header_line = "| " + " | ".join(str(headers[i]).ljust(col_widths[i]) for i in range(len(headers))) + " |"

    print(sep)
    print(header_line)
    print(sep)
    for r in formatted_rows:
        print("| " + " | ".join(r[i].ljust(col_widths[i]) for i in range(len(headers))) + " |")
    print(sep)


def inspect_object(conn: sqlite3.Connection, name: str) -> None:
    cur = conn.cursor()
    cur.execute("SELECT type, sql FROM sqlite_master WHERE name = ?;", (name,))
    meta = cur.fetchone()
    if not meta:
        print(f"[!] Object '{name}' not found in database.")
        return

    obj_type = meta["type"].upper()
    safe_name = name.replace('"', '""')
    print("\n" + "=" * 84)
    print(f" {obj_type}: {name}")
    print("=" * 84)

    # 1. Column info
    cur.execute(f'PRAGMA table_info("{safe_name}");')
    cols = cur.fetchall()
    fks = {}
    if obj_type == "TABLE":
        cur.execute(f'PRAGMA foreign_key_list("{safe_name}");')
        fks = {fk["from"]: fk for fk in cur.fetchall()}

    col_rows = []
    for c in cols:
        key_info = ""
        if c["pk"]:
            key_info = "PRIMARY KEY"
        elif c["name"] in fks:
            fk = fks[c["name"]]
            key_info = f"FK -> {fk['table']}({fk['to']}) [ON DELETE {fk['on_delete']}]"
        col_rows.append([
            c["cid"],
            c["name"],
            c["type"] or "VIEW COL",
            "NOT NULL" if c["notnull"] else "NULLABLE",
            c["dflt_value"],
            key_info,
        ])

    print("\n[Schema / Columns]:")
    print_ascii_table(["#", "Column", "Type", "Nullable", "Default", "Constraint"], col_rows, max_col_width=45)

    # 2. Raw Rows
    total = cur.execute(f'SELECT COUNT(*) FROM "{safe_name}";').fetchone()[0]
    cur.execute(f'SELECT * FROM "{safe_name}" LIMIT 50;')
    raw = cur.fetchall()
    col_names = [c["name"] for c in cols]
    data_rows = []
    for r in raw:
        row_data = []
        for c in col_names:
            val = r[c]
            if c == "password_hash" and val:
                val = "pbkdf2_sha256$150000$***REDACTED***"
            row_data.append(val)
        data_rows.append(row_data)

    print(f"\n[Raw Data Rows (Showing {len(data_rows)} of {total} total rows)]:")
    if data_rows:
        print_ascii_table(col_names, data_rows, max_col_width=34)
    else:
        print("  (Empty table)")


def dump_all_objects(conn: sqlite3.Connection) -> None:
    print("=" * 84)
    print(f" VAULTSTOCK FULL DATABASE DUMP — {DB_PATH}")
    print("=" * 84)
    ordered_objects = [
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
    ]
    for obj in ordered_objects:
        inspect_object(conn, obj)


def print_audit_report() -> None:
    res = verify_audit_chain()
    anchor = get_anchor()
    status_str = "100% VERIFIED (INTACT)" if res["verified"] else f"TAMPER DETECTED (Broken at Block #{res['broken_at_id']})"
    print("\n" + "=" * 84)
    print(f" 5-POINT CRYPTOGRAPHIC AUDIT VERIFICATION : {status_str}")
    print("=" * 84)
    checks = res.get("checks", {})
    check_rows = [
        ["01. Contiguity", "PASS" if checks.get("contiguity") else "FAIL", "Strict 1..N block sequence without gaps"],
        ["02. Hash Linkage", "PASS" if checks.get("linkage") else "FAIL", "Each block prev_hash == parent row_hash"],
        ["03. HMAC-SHA256", "PASS" if checks.get("integrity") else "FAIL", "Keyed cryptographic signature verification"],
        ["04. Reconciliation", "PASS" if checks.get("reconciliation") else "FAIL", "1:1 match between tables & audit JSON snapshots"],
        ["05. Head Anchor", "PASS" if checks.get("anchor") else "FAIL", f"Matches external anchor ({ANCHOR_PATH})"],
    ]
    print_ascii_table(["Invariant Check", "Status", "Verification Rule"], check_rows, max_col_width=52)
    print(f" Total Audit Blocks : {res['total_blocks']}")
    if anchor:
        print(f" External Anchor    : Block #{anchor.get('id')} | Hash: {str(anchor.get('row_hash', ''))[:24]}...")
    else:
        print(" External Anchor    : MISSING")
    print(f" Diagnostic Summary : {res['reason']}")
    print("=" * 84)


def print_status_overview(conn: sqlite3.Connection) -> None:
    info = get_db_debug_info()
    trig = get_triggers_status(conn)
    audit = verify_audit_chain()

    trig_label = (
        f"ACTIVE ({trig['active_count']}/{trig['expected_count']} triggers enforced)"
        if trig["triggers_enabled"]
        else f"BYPASSED ({trig['active_count']}/{trig['expected_count']} active — Direct Modify Mode)"
    )
    audit_label = (
        f"VERIFIED ({audit['total_blocks']} blocks intact)"
        if audit["verified"]
        else f"TAMPERED! ({audit['reason']})"
    )

    print("\n" + "=" * 84)
    print(" VAULTSTOCK BACKEND & DATABASE STATUS OVERVIEW")
    print("=" * 84)
    print(f" Database File   : {DB_PATH} ({info['pragmas']['db_size_bytes'] / 1024:.1f} KB)")
    print(f" SQLite Engine   : v{info['sqlite_version']} | Journal: {info['pragmas']['journal_mode']} | Foreign Keys: {'ON' if info['pragmas']['foreign_keys'] else 'OFF'}")
    print(f" Storage Triggers: {trig_label}")
    print(f" Audit Chain     : {audit_label}")
    print("-" * 84)

    cur = conn.cursor()
    cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY type, name;")
    summary_rows = []
    for r in cur.fetchall():
        safe_n = r["name"].replace('"', '""')
        cnt = cur.execute(f'SELECT COUNT(*) FROM "{safe_n}";').fetchone()[0]
        summary_rows.append([r["name"], r["type"].upper(), cnt])
    print_ascii_table(["Object Name", "Type", "Live Row Count"], summary_rows)


def print_help_menu() -> None:
    print("\n" + "=" * 84)
    print(" INTERACTIVE SHELL COMMAND REFERENCE")
    print("=" * 84)
    print(" [1] DIRECT SQL EXECUTION (Read & Write):")
    print("     Type any SQL query directly (SELECT, INSERT, UPDATE, DELETE, PRAGMA, EXPLAIN):")
    print("       SELECT * FROM v_inventory_summary;")
    print("       SELECT * FROM v_location_inventory;")
    print("       INSERT INTO categories (code, name, description) VALUES ('LAB', 'Lab Gear', 'Test');")
    print("       UPDATE products SET unit_price = 0.01 WHERE id = 1;")
    print("")
    print(" [2] TRIGGER & DIRECT DB TAMPERING CONTROLS:")
    print("     .triggers             Show active SQLite storage triggers and status")
    print("     .triggers off         Disable all 7 immutability/overdraft triggers (allow direct UPDATE/DELETE)")
    print("     .triggers on          Re-enable all 7 storage-layer protection triggers")
    print("     .bypass <SQL>         Execute a SQL statement with triggers temporarily bypassed")
    print("     .tamper [1-5]         Simulate a specific database tamper attack to test the verifier:")
    print("                             1 = Forged unkeyed SHA-256 on Audit Block #1 (breaks Check #3 HMAC)")
    print("                             2 = Direct SQL price edit on Product #1 (breaks Check #4 Reconciliation)")
    print("                             3 = Unlogged ghost movement row injection (breaks Check #4 Reconciliation)")
    print("                             4 = Delete Audit Block #3 (breaks Check #1 Contiguity 1..N)")
    print("                             5 = Tail-truncate latest movement & block (breaks Check #5 Head Anchor)")
    print("     .verify               Run the 5-point cryptographic audit chain verifier")
    print("     .reset                Wipe, vacuum, and reseed the database to clean 12-block baseline")
    print("")
    print(" [3] BACKEND APPLICATION ENGINE COMMANDS (Seals valid HMAC-SHA256 blocks):")
    print("     .receive <pid> <qty> [loc_id] [supp_id]   Record inward stock receipt via backend engine")
    print("     .dispatch <pid> <qty> [loc_id]            Record outward stock issue via backend engine")
    print("     .transfer <pid> <from_loc> <to_loc> <qty> Atomic warehouse transfer via backend engine")
    print("     .add-product <sku> <price> <cat_id> <name> Create a new catalog SKU via backend engine")
    print("")
    print(" [4] SCHEMA & DATA INSPECTION COMMANDS:")
    print("     .status               Show live engine PRAGMAs, trigger status, row counts & audit state")
    print("     .tables               List all 7 physical 3NF tables and row counts")
    print("     .views                List all 4 compiled relational views")
    print("     .schema [name]        Show CREATE TABLE / VIEW / TRIGGER DDL statements")
    print("     .dump [name]          Inspect columns, foreign keys, and rows of a table/view (or all)")
    print("     exit / .quit          Close the interactive shell")
    print("=" * 84)


def handle_tamper_command(conn: sqlite3.Connection, arg: str) -> None:
    choice = arg.strip().lower()
    if not choice:
        print("\nSelect a tamper scenario to execute:")
        print("  .tamper 1   [HMAC Integrity]    Rewrite Audit Block #1 with unkeyed SHA-256 hash")
        print("  .tamper 2   [Reconciliation]    Bypass triggers & change Product #1 unit_price to $0.01")
        print("  .tamper 3   [Ghost Injection]   Insert unlogged +500 movement row without audit block")
        print("  .tamper 4   [Contiguity Gap]    Bypass triggers & delete Audit Block #3")
        print("  .tamper 5   [Tail Truncation]   Bypass triggers & delete latest movement + audit block")
        return

    if choice in ("1", "hmac"):
        res = tamper_for_demo(1)
        print(f"[+] Tamper #1 executed: Rewrote Audit Block #1 with unkeyed SHA-256 ({res.get('fake_hash', '')[:20]}...).")
    elif choice in ("2", "price"):
        res = execute_interactive_sql("UPDATE products SET unit_price = 0.01 WHERE id = 1;", bypass_triggers=True)
        print(f"[+] Tamper #2 executed: {res['message']}")
    elif choice in ("3", "ghost"):
        res = execute_interactive_sql(
            "INSERT INTO movements (product_id, supplier_id, location_id, type, qty, reference_doc, note, created_by) "
            "VALUES (1, 1, 1, 'IN', 500, 'GHOST-PO-999', 'Unlogged direct SQL injection', 'rogue_dba');",
            bypass_triggers=False,
        )
        print(f"[+] Tamper #3 executed: {res['message']}")
    elif choice in ("4", "gap", "contiguity"):
        res = execute_interactive_sql("DELETE FROM audit_log WHERE id = 3;", bypass_triggers=True)
        print(f"[+] Tamper #4 executed: {res['message']}")
    elif choice in ("5", "truncate", "anchor"):
        cur = conn.cursor()
        last = cur.execute("SELECT id, ref_table, ref_id FROM audit_log ORDER BY id DESC LIMIT 1;").fetchone()
        if not last:
            print("[!] Audit log is empty.")
            return
        sql = f"DELETE FROM audit_log WHERE id = {last['id']};"
        if last["ref_table"] in ("movements", "products"):
            sql += f" DELETE FROM {last['ref_table']} WHERE id = {last['ref_id']};"
        res = execute_interactive_sql(sql, bypass_triggers=True)
        print(f"[+] Tamper #5 executed (Tail Truncation of Block #{last['id']} & {last['ref_table']} #{last['ref_id']}): {res['message']}")
    else:
        print(f"[!] Unknown tamper option '{choice}'. Use .tamper 1..5")
        return

    print_audit_report()


def handle_backend_command(conn: sqlite3.Connection, cmd: str, args_str: str) -> None:
    parts = args_str.split()
    try:
        if cmd == ".receive":
            if len(parts) < 2:
                print("Usage: .receive <product_id> <qty> [location_id=1] [supplier_id=1]")
                return
            pid = int(parts[0])
            qty = int(parts[1])
            loc_id = int(parts[2]) if len(parts) >= 3 else 1
            supp_id = int(parts[3]) if len(parts) >= 4 else 1

            with write_tx(conn):
                cur = conn.cursor()
                prod = cur.execute("SELECT id, name, sku FROM products WHERE id = ?;", (pid,)).fetchone()
                if not prod:
                    print(f"[!] Product #{pid} not found.")
                    return
                ref_doc = f"CLI-PO-{int(time.time()) % 100000}"
                note = "CLI interactive backend stock receipt"
                cur.execute(
                    "INSERT INTO movements (product_id, supplier_id, location_id, type, qty, reference_doc, note, created_by) "
                    "VALUES (?, ?, ?, 'IN', ?, ?, ?, 'cli_admin');",
                    (pid, supp_id, loc_id, qty, ref_doc, note),
                )
                m_id = cur.lastrowid
                payload = {
                    "created_by": "cli_admin",
                    "id": m_id,
                    "location_id": loc_id,
                    "note": note,
                    "product_id": pid,
                    "qty": qty,
                    "reference_doc": ref_doc,
                    "supplier_id": supp_id,
                    "type": "IN",
                }
                row_hash = append_audit_entry(
                    conn,
                    "STOCK_RECEIVE",
                    "cli_admin",
                    "movements",
                    m_id,
                    payload,
                    f"IN {qty} units of '{prod['name']}' (Operator: cli_admin) [Ref: {ref_doc}]",
                )
            sync_anchor_to_latest(conn)
            print(f"[+] Backend IN Receipt committed! Movement #{m_id} | Sealed HMAC: {row_hash[:20]}...")

        elif cmd == ".dispatch":
            if len(parts) < 2:
                print("Usage: .dispatch <product_id> <qty> [location_id=1]")
                return
            pid = int(parts[0])
            qty = int(parts[1])
            loc_id = int(parts[2]) if len(parts) >= 3 else 1

            with write_tx(conn):
                cur = conn.cursor()
                prod = cur.execute("SELECT id, name, sku FROM products WHERE id = ?;", (pid,)).fetchone()
                if not prod:
                    print(f"[!] Product #{pid} not found.")
                    return
                ref_doc = f"CLI-SO-{int(time.time()) % 100000}"
                note = "CLI interactive backend stock dispatch"
                cur.execute(
                    "INSERT INTO movements (product_id, supplier_id, location_id, type, qty, reference_doc, note, created_by) "
                    "VALUES (?, NULL, ?, 'OUT', ?, ?, ?, 'cli_admin');",
                    (pid, loc_id, qty, ref_doc, note),
                )
                m_id = cur.lastrowid
                payload = {
                    "created_by": "cli_admin",
                    "id": m_id,
                    "location_id": loc_id,
                    "note": note,
                    "product_id": pid,
                    "qty": qty,
                    "reference_doc": ref_doc,
                    "supplier_id": None,
                    "type": "OUT",
                }
                row_hash = append_audit_entry(
                    conn,
                    "STOCK_ISSUE",
                    "cli_admin",
                    "movements",
                    m_id,
                    payload,
                    f"OUT {qty} units of '{prod['name']}' (Operator: cli_admin) [Ref: {ref_doc}]",
                )
            sync_anchor_to_latest(conn)
            print(f"[+] Backend OUT Dispatch committed! Movement #{m_id} | Sealed HMAC: {row_hash[:20]}...")

        elif cmd == ".transfer":
            if len(parts) < 4:
                print("Usage: .transfer <product_id> <from_location_id> <to_location_id> <qty>")
                return
            pid, from_loc, to_loc, qty = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            if from_loc == to_loc:
                print("[!] Source and destination locations must be different.")
                return
            with write_tx(conn):
                cur = conn.cursor()
                prod = cur.execute("SELECT id, name FROM products WHERE id = ?;", (pid,)).fetchone()
                f_row = cur.execute("SELECT id, code FROM locations WHERE id = ?;", (from_loc,)).fetchone()
                t_row = cur.execute("SELECT id, code FROM locations WHERE id = ?;", (to_loc,)).fetchone()
                if not prod or not f_row or not t_row:
                    print("[!] Invalid product_id or location_id.")
                    return
                ref_doc = f"XFER-{f_row['code']}-{t_row['code']}"
                out_note = f"CLI transfer (Transfer OUT to {t_row['code']})"
                in_note = f"CLI transfer (Transfer IN from {f_row['code']})"

                cur.execute(
                    "INSERT INTO movements (product_id, supplier_id, location_id, type, qty, reference_doc, note, created_by) "
                    "VALUES (?, NULL, ?, 'OUT', ?, ?, ?, 'cli_admin');",
                    (pid, from_loc, qty, ref_doc, out_note),
                )
                out_id = cur.lastrowid
                append_audit_entry(
                    conn,
                    "STOCK_TRANSFER_OUT",
                    "cli_admin",
                    "movements",
                    out_id,
                    {
                        "created_by": "cli_admin",
                        "id": out_id,
                        "location_id": from_loc,
                        "note": out_note,
                        "product_id": pid,
                        "qty": qty,
                        "reference_doc": ref_doc,
                        "supplier_id": None,
                        "type": "OUT",
                    },
                    f"Transfer OUT: {qty} units of '{prod['name']}' from {f_row['code']} -> {t_row['code']}",
                )

                cur.execute(
                    "INSERT INTO movements (product_id, supplier_id, location_id, type, qty, reference_doc, note, created_by) "
                    "VALUES (?, NULL, ?, 'IN', ?, ?, ?, 'cli_admin');",
                    (pid, to_loc, qty, ref_doc, in_note),
                )
                in_id = cur.lastrowid
                row_hash = append_audit_entry(
                    conn,
                    "STOCK_TRANSFER_IN",
                    "cli_admin",
                    "movements",
                    in_id,
                    {
                        "created_by": "cli_admin",
                        "id": in_id,
                        "location_id": to_loc,
                        "note": in_note,
                        "product_id": pid,
                        "qty": qty,
                        "reference_doc": ref_doc,
                        "supplier_id": None,
                        "type": "IN",
                    },
                    f"Transfer IN: {qty} units of '{prod['name']}' into {t_row['code']} from {f_row['code']}",
                )
            sync_anchor_to_latest(conn)
            print(f"[+] Atomic Warehouse Transfer committed! Movements #{out_id} (OUT) & #{in_id} (IN) | Head HMAC: {row_hash[:20]}...")

        elif cmd == ".add-product":
            if len(parts) < 4:
                print("Usage: .add-product <SKU> <unit_price> <category_id> <Product Name...>")
                return
            sku = parts[0].upper()
            price = float(parts[1])
            cat_id = int(parts[2])
            name = " ".join(parts[3:])
            with write_tx(conn):
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO products (sku, name, category_id, unit_price, reorder_threshold) VALUES (?, ?, ?, ?, 10);",
                    (sku, name, cat_id, price),
                )
                pid = cur.lastrowid
                payload = {
                    "category_id": cat_id,
                    "id": pid,
                    "name": name,
                    "reorder_threshold": 10,
                    "sku": sku,
                    "unit_price": price,
                }
                row_hash = append_audit_entry(
                    conn,
                    "PRODUCT_CREATE",
                    "cli_admin",
                    "products",
                    pid,
                    payload,
                    f"Created product '{name}' ({sku}) via CLI shell",
                )
            sync_anchor_to_latest(conn)
            print(f"[+] Product #{pid} ('{name}') created and sealed! HMAC: {row_hash[:20]}...")

    except Exception as e:
        print(f"[Backend Engine Error]: {e}")


def execute_and_print_sql(sql: str, bypass_triggers: bool = False) -> None:
    res = execute_interactive_sql(sql, bypass_triggers=bypass_triggers, max_rows=200)
    if res["status"] == "SUCCESS":
        if res["is_query"]:
            cols = res["columns"]
            rows = [[r.get(c) for c in cols] for r in res["rows"]]
            if rows:
                print_ascii_table(cols, rows, max_col_width=42)
            else:
                print("  (0 rows returned)")
            print(f"({res['row_count']} row(s) returned in {res['execution_time_ms']:.2f} ms)")
        else:
            print(f"[+] {res['message']}")
            audit = res.get("audit_status", {})
            if audit.get("verified"):
                print(f"    [Audit Chain Status: 100% VERIFIED ({audit.get('total_blocks', 0)} blocks intact)]")
            else:
                failed_checks = [k for k, v in (audit.get("checks") or {}).items() if not v]
                print(f"    [!] AUDIT ALERT: Chain verification FAILED ({', '.join(failed_checks)}) -> {audit.get('reason')}")
    elif res["status"] == "INTERCEPTED":
        print(f"[SQLite Storage Trigger Intercepted ({res['execution_time_ms']:.2f} ms)]: {res['message']}")
        print("  -> Tip: Use '.triggers off' or '.bypass <SQL>' to bypass triggers and modify the table directly.")
    else:
        print(f"[SQLite Engine Error ({res['execution_time_ms']:.2f} ms)]: {res['message']}")


def interactive_shell(conn: sqlite3.Connection) -> None:
    print("\n" + "=" * 84)
    print(" VaultStock — Interactive SQLite & Backend Control Shell")
    print(f" Database File : {DB_PATH}")
    print("-" * 84)
    print(" Quick Commands: .help | .status | .tables | .views | .triggers [on|off] | .verify")
    print(" Modify / Test : .bypass <SQL> | .tamper [1-5] | .receive | .dispatch | .transfer | .reset")
    print(" Raw SQL       : Type any SQL statement (SELECT, INSERT, UPDATE, DELETE, PRAGMA, EXPLAIN)")
    print("=" * 84)

    cur = conn.cursor()
    while True:
        trig_state = get_triggers_status(conn)
        prompt_label = "sqlite> " if trig_state["triggers_enabled"] else "sqlite [TRIGGERS-OFF]> "
        try:
            query = input(f"\n{prompt_label}").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting interactive SQL shell.")
            break

        if not query:
            continue

        lower_q = query.lower()
        if lower_q in ("exit", "quit", ".exit", ".quit"):
            print("Closing VaultStock shell.")
            break

        if lower_q in (".help", "help"):
            print_help_menu()
            continue

        if lower_q == ".status":
            print_status_overview(conn)
            continue

        if lower_q == ".verify":
            print_audit_report()
            continue

        if lower_q == ".reset":
            conn.close()
            reset_demo_db()
            conn = get_connection()
            cur = conn.cursor()
            print("[+] Database cleanly reset to pristine 12-block baseline (all 7 triggers active).")
            print_audit_report()
            continue

        if lower_q == ".tables":
            cur.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
            t_names = [r["name"] for r in cur.fetchall()]
            rows = []
            for t in t_names:
                safe_t = t.replace('"', '""')
                cnt = cur.execute(f'SELECT COUNT(*) FROM "{safe_t}";').fetchone()[0]
                rows.append([t, "TABLE", cnt])
            print_ascii_table(["Table Name", "Type", "Row Count"], rows)
            continue

        if lower_q == ".views":
            cur.execute("SELECT name, sql FROM sqlite_master WHERE type = 'view' ORDER BY name;")
            v_rows = [[r["name"], "VIEW", (r["sql"] or "").replace("\n", " ")] for r in cur.fetchall()]
            print_ascii_table(["View Name", "Type", "Definition"], v_rows, max_col_width=54)
            continue

        if lower_q.startswith(".triggers"):
            parts = query.split(maxsplit=1)
            if len(parts) > 1:
                sub = parts[1].strip().lower()
                if sub in ("off", "disable", "0", "false"):
                    st = set_storage_triggers(False, conn)
                    print(f"[!] Storage-layer triggers DISABLED ({st['active_count']}/{st['expected_count']} active).")
                    print("    You can now execute direct UPDATE / DELETE statements on products, movements, and audit_log.")
                    continue
                elif sub in ("on", "enable", "1", "true"):
                    st = set_storage_triggers(True, conn)
                    print(f"[+] Storage-layer triggers ENABLED ({st['active_count']}/{st['expected_count']} active).")
                    continue
                else:
                    print("Usage: .triggers [on | off]")
                    continue

            st = get_triggers_status(conn)
            print(f"Trigger Enforcement: {'ACTIVE' if st['triggers_enabled'] else 'BYPASSED'} ({st['active_count']}/{st['expected_count']})")
            cur.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY tbl_name, name;")
            t_rows = [[r["name"], r["tbl_name"], (r["sql"] or "").replace("\n", " ")] for r in cur.fetchall()]
            if t_rows:
                print_ascii_table(["Trigger Name", "Target Table", "DDL"], t_rows, max_col_width=48)
            else:
                print("  (All storage triggers are currently disabled. Run '.triggers on' to restore them.)")
            continue

        if lower_q.startswith(".bypass ") or lower_q.startswith(".force "):
            sql_part = query.split(maxsplit=1)[1] if len(query.split(maxsplit=1)) > 1 else ""
            if not sql_part:
                print("Usage: .bypass <SQL statement>")
                continue
            execute_and_print_sql(sql_part, bypass_triggers=True)
            continue

        if lower_q.startswith(".tamper"):
            arg_part = query.split(maxsplit=1)[1] if len(query.split(maxsplit=1)) > 1 else ""
            handle_tamper_command(conn, arg_part)
            continue

        if lower_q.startswith((".receive", ".dispatch", ".transfer", ".add-product")):
            parts = query.split(maxsplit=1)
            cmd_name = parts[0].lower()
            arg_str = parts[1] if len(parts) > 1 else ""
            handle_backend_command(conn, cmd_name, arg_str)
            continue

        if lower_q.startswith(".schema"):
            parts = query.split(maxsplit=1)
            if len(parts) > 1:
                cur.execute("SELECT type, name, sql FROM sqlite_master WHERE name = ?;", (parts[1].strip(";"),))
            else:
                cur.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type, name;")
            items = cur.fetchall()
            if not items:
                print("[!] No matching schema object found.")
            for item in items:
                print(f"\n-- {item['type'].upper()}: {item['name']}\n{item['sql']};")
            continue

        if lower_q.startswith(".dump"):
            parts = query.split(maxsplit=1)
            if len(parts) > 1:
                inspect_object(conn, parts[1].strip(";"))
            else:
                dump_all_objects(conn)
            continue

        # Multi-line SQL continuation if statement is incomplete and user is in interactive tty
        full_sql = query
        while not sqlite3.complete_statement(full_sql) and ";" not in full_sql and sys.stdin.isatty():
            # Allow single-line queries without trailing semicolon to execute immediately
            break

        execute_and_print_sql(full_sql, bypass_triggers=False)


def main() -> None:
    if not Path(DB_PATH).exists():
        init_db()

    conn = get_connection()
    try:
        args = sys.argv[1:]
        if "--shell" in args or "-s" in args:
            print_status_overview(conn)
            interactive_shell(conn)
            return

        if "--dump" in args or "-d" in args:
            dump_all_objects(conn)
            return

        if len(args) >= 2 and args[0] in ("-c", "--cmd"):
            sql_cmd = " ".join(args[1:])
            execute_and_print_sql(sql_cmd, bypass_triggers=False)
            return

        if args:
            for target in args:
                inspect_object(conn, target)
            return

        # Default behavior when run with no arguments:
        # Show status overview and drop directly into the interactive shell if in a terminal
        print_status_overview(conn)
        if sys.stdin.isatty():
            interactive_shell(conn)
        else:
            dump_all_objects(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
