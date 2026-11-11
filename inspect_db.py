#!/usr/bin/env python3
"""
VaultStock — Terminal Database Inspector & Interactive SQL Shell
Run this during a viva if faculty asks to see the raw SQLite database tables,
column schemas, foreign keys, views, triggers, or run ad-hoc SQL queries!

Usage:
  python inspect_db.py                 # Prints all tables, schemas, and rows
  python inspect_db.py products        # Prints schema & rows for a specific table/view
  python inspect_db.py --shell         # Opens an interactive SQL prompt (sqlite>)
"""

import sys
import time
import sqlite3
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from api.db import get_connection, init_db
from api.config import DB_PATH


def print_ascii_table(headers: list[str], rows: list[list[str]], max_col_width: int = 38) -> None:
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
    print("\n" + "=" * 80)
    print(f" {obj_type}: {name}")
    print("=" * 80)

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
    cur.execute(f'SELECT * FROM "{safe_name}" LIMIT 25;')
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
        print_ascii_table(col_names, data_rows, max_col_width=32)
    else:
        print("  (Empty table)")


def interactive_shell(conn: sqlite3.Connection) -> None:
    print("=" * 80)
    print(" VaultStock — Direct SQLite Terminal Shell")
    print(f" Database File : {DB_PATH}")
    print(" Engine State  : WAL Mode | PRAGMA foreign_keys = ON | Triggers = ACTIVE")
    print("-" * 80)
    print(" Dot Commands  : .help | .tables | .views | .triggers | .schema [name] | .dump [name] | exit")
    print(" Raw SQL       : Type any SQL statement (SELECT, INSERT, UPDATE, DELETE, PRAGMA, EXPLAIN)")
    print("=" * 80)
    cur = conn.cursor()
    while True:
        try:
            query = input("\nsqlite> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting SQL shell.")
            break
        if not query:
            continue
        lower_q = query.lower()
        if lower_q in ("exit", "quit", ".exit", ".quit"):
            break
        if lower_q == ".help":
            print("  .tables          List all physical 3NF tables and row counts")
            print("  .views           List all compiled relational views")
            print("  .triggers        List all active SQLite storage triggers")
            print("  .schema [name]   Show CREATE TABLE / VIEW / TRIGGER DDL statements")
            print("  .dump <name>     Inspect columns, foreign keys, and rows of a table/view")
            print("  exit / .quit     Close the interactive SQL shell")
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
            print_ascii_table(["View Name", "Type", "Definition"], v_rows, max_col_width=52)
            continue
        if lower_q == ".triggers":
            cur.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY tbl_name, name;")
            t_rows = [[r["name"], r["tbl_name"], (r["sql"] or "").replace("\n", " ")] for r in cur.fetchall()]
            print_ascii_table(["Trigger Name", "Target Table", "DDL"], t_rows, max_col_width=46)
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
                print("Usage: .dump <table_or_view_name>")
            continue

        t0 = time.perf_counter()
        try:
            cur.execute(query)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if cur.description:
                headers = [d[0] for d in cur.description]
                rows = cur.fetchall()
                print_ascii_table(headers, [list(r) for r in rows], max_col_width=42)
                print(f"({len(rows)} row(s) returned in {elapsed_ms:.2f} ms)")
            else:
                if conn.isolation_level is not None:
                    conn.commit()
                print(f"Statement executed successfully ({elapsed_ms:.2f} ms). Rows affected: {cur.rowcount}")
        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            print(f"[SQLite Engine Error ({elapsed_ms:.2f} ms)]: {e}")


def main() -> None:
    if not Path(DB_PATH).exists():
        init_db()

    conn = get_connection()
    try:
        args = sys.argv[1:]
        if "--shell" in args or "-s" in args:
            interactive_shell(conn)
            return

        if len(args) >= 2 and args[0] in ("-c", "--cmd"):
            sql_cmd = " ".join(args[1:])
            cur = conn.cursor()
            t0 = time.perf_counter()
            try:
                cur.execute(sql_cmd)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                if cur.description:
                    headers = [d[0] for d in cur.description]
                    rows = cur.fetchall()
                    print_ascii_table(headers, [list(r) for r in rows], max_col_width=42)
                    print(f"({len(rows)} row(s) in {elapsed_ms:.2f} ms)")
                else:
                    print(f"Executed ({elapsed_ms:.2f} ms). Rows affected: {cur.rowcount}")
            except Exception as e:
                print(f"[SQLite Engine Error]: {e}")
            return

        if args:
            for target in args:
                inspect_object(conn, target)
            return

        print("=" * 80)
        print(f" VAULTSTOCK DATABASE DUMP — {DB_PATH}")
        print("=" * 80)

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

        print("\nTip: Run 'python inspect_db.py --shell' to open the direct interactive SQL terminal!")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
