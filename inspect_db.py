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
    print(f" VaultStock Interactive SQLite Shell")
    print(f" Connected to: {DB_PATH}")
    print(" Type any SQL query (e.g. SELECT * FROM products;) or 'exit' to quit.")
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
        if query.lower() in ("exit", "quit", ".exit", ".quit"):
            break
        if query.lower() == ".tables":
            query = "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%';"
        try:
            cur.execute(query)
            if cur.description:
                headers = [d[0] for d in cur.description]
                rows = cur.fetchall()
                print_ascii_table(headers, [list(r) for r in rows], max_col_width=40)
                print(f"({len(rows)} rows returned)")
            else:
                if conn.isolation_level is not None:
                    conn.commit()
                print(f"Query executed successfully. Rows affected: {cur.rowcount}")
        except Exception as e:
            print(f"[SQL Error]: {e}")


def main() -> None:
    if not Path(DB_PATH).exists():
        init_db()

    conn = get_connection()
    try:
        args = sys.argv[1:]
        if "--shell" in args or "-s" in args:
            interactive_shell(conn)
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
        ]
        for obj in ordered_objects:
            inspect_object(conn, obj)

        print("\nTip: Run 'python inspect_db.py --shell' to open an interactive SQL query prompt!")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
