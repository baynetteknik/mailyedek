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

print("=== Checking Atlas and Ozmed on Disk ===")
data_dir = s.data_path()
for item in data_dir.iterdir():
    if item.is_dir():
        # count files inside
        subfiles = list(item.glob("**/*"))
        file_count = sum(1 for f in subfiles if f.is_file())
        print(f"Folder: {item.name:25s} | File count: {file_count}")

print("\n=== Checking Account 14 (Atlas) in DB ===")
with e.db.get_conn() as conn:
    acc14 = conn.execute("SELECT * FROM accounts WHERE id = 14").fetchone()
    print("Account 14 row:", dict(acc14) if acc14 else "Not found")
    mails14 = conn.execute("SELECT COUNT(*) FROM mail_metadata WHERE account_id = 14").fetchone()[0]
    print(f"Mails for account 14 in DB: {mails14}")

    # Check all accounts with atlas or ebter in email or sender
    atlas_mails = conn.execute("SELECT id, account_id, sender, recipients, subject, date, folder FROM mail_metadata WHERE sender LIKE '%atlas%' OR recipients LIKE '%atlas%' OR sender LIKE '%ebter%' LIMIT 10").fetchall()
    print(f"Mails matching 'atlas' in sender/recipients: {len(atlas_mails)}")
    for m in atlas_mails:
        print("  -", dict(m))

    # Check sync_state table for all accounts
    sync_states = conn.execute("SELECT s.account_id, a.email, a.account_group, s.folder, s.total_synced FROM sync_state s LEFT JOIN accounts a ON s.account_id = a.id").fetchall()
    print(f"\nTotal sync_state rows: {len(sync_states)}")
    for ss in sync_states:
        print("  - Sync state:", dict(ss))
