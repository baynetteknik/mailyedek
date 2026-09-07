import sys
sys.path.insert(0, '.')
import json
import sqlite3
from pathlib import Path
from core.settings import AppSettings

main_db_path = Path("E:/mailyedek/mail_archive.db")
local_db_path = Path("data/mail_archive.db")

if main_db_path.exists():
    conn_main = sqlite3.connect(str(main_db_path))
    conn_main.row_factory = sqlite3.Row
    rows = conn_main.execute("SELECT * FROM accounts").fetchall()
    print(f"Read {len(rows)} accounts from main database.")
    
    conn_local = sqlite3.connect(str(local_db_path))
    conn_local.row_factory = sqlite3.Row
    c = conn_local.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            label           TEXT NOT NULL,
            email           TEXT NOT NULL,
            imap_host       TEXT NOT NULL,
            imap_port       INTEGER NOT NULL DEFAULT 993,
            use_ssl         INTEGER NOT NULL DEFAULT 1,
            username_enc    TEXT NOT NULL,
            password_enc    TEXT NOT NULL,
            is_active       INTEGER NOT NULL DEFAULT 1,
            export_subfolder TEXT DEFAULT '',
            account_group   TEXT DEFAULT '',
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    
    for r in rows:
        cols = [k for k in r.keys()]
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        update_str = ", ".join([f"{k}=excluded.{k}" for k in cols if k != "id"])
        sql = f"INSERT INTO accounts ({col_names}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {update_str}"
        c.execute(sql, [r[k] for k in cols])
        
    conn_local.commit()
    cnt = c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    print(f"Local database data/mail_archive.db now has {cnt} accounts!")
    conn_local.close()
    conn_main.close()

