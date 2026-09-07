import sys
import os
import sqlite3
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.settings import AppSettings

settings = AppSettings()
print(f"Current configured data_path: {settings.data_path()}")
print(f"Current settings data: {settings._data}")

# Search for all .db files in c:\mail_yedek and data path
for root, dirs, files in os.walk(str(Path("c:/mail_yedek"))):
    for f in files:
        if f.endswith(".db"):
            fp = Path(root) / f
            try:
                conn = sqlite3.connect(fp)
                cur = conn.cursor()
                tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                mail_cnt = 0
                acc_cnt = 0
                if "mail_metadata" in tables:
                    mail_cnt = cur.execute("SELECT COUNT(*) FROM mail_metadata").fetchone()[0]
                if "accounts" in tables:
                    acc_cnt = cur.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
                print(f"DB: {fp} | Size: {fp.stat().st_size:,} bytes | accounts: {acc_cnt} | mails: {mail_cnt} | tables: {len(tables)}")
                conn.close()
            except Exception as e:
                print(f"DB: {fp} | Error: {e}")

# Also search on other drives if any (e.g. D:, E:)
for d in ["D:\\", "E:\\", "F:\\", "G:\\"]:
    if os.path.exists(d):
        print(f"Scanning drive {d}...")
        for root, dirs, files in os.walk(d):
            # Limit depth
            if len(Path(root).parts) > 4:
                continue
            for f in files:
                if f.endswith("metadata.db") or f.endswith("backup.db"):
                    fp = Path(root) / f
                    print(f"Found DB on {d}: {fp} ({fp.stat().st_size:,} bytes)")
