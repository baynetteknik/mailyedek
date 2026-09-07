import sys
import os
import sqlite3
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.settings import AppSettings
from core.mail_engine import MailEngine

s = AppSettings()
e = MailEngine(db_path=s.db_path(), settings=s)

print(f"DB Path: {e.db._db_path}")

with e.db.get_conn() as conn:
    print("\n--- ACCOUNTS SUMMARY BY GROUP ---")
    acc_rows = conn.execute("SELECT id, email, label, account_group, export_subfolder, is_active FROM accounts ORDER BY account_group, id").fetchall()
    
    # Mail counts
    mail_counts = dict(conn.execute("SELECT account_id, COUNT(*) FROM mail_metadata GROUP BY account_id").fetchall())
    
    for r in acc_rows:
        aid = r["id"]
        cnt = mail_counts.get(aid, 0)
        print(f"ID: {aid:2d} | Group: {r['account_group']:20s} | Subfolder: {str(r['export_subfolder']):15s} | Email: {r['email']:35s} | Label: {r['label']:20s} | Mails: {cnt}")

    print("\n--- SYNC STATE TABLE ---")
    syncs = conn.execute("SELECT account_id, folder, last_uid, total_synced, last_sync_time FROM sync_state").fetchall()
    for sy in syncs:
        print(f"Account {sy['account_id']:2d} | Folder: {sy['folder']:20s} | Total Synced: {sy['total_synced']} | Last Sync: {sy['last_sync_time']}")
