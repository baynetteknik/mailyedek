import sys
sys.path.insert(0, '.')
import sqlite3
from pathlib import Path
from core.settings import AppSettings

s = AppSettings()
print("Configured data_path in settings:", s._data.get("data_path"))
cache = s.load_account_cache()
print("Account cache count:", len(cache))

for p in [Path("data/mail_archive.db"), Path("E:/mailyedek/mail_archive.db"), Path("data/account_cache.json")]:
    print(f"Path {p}: exists={p.exists()}")
    if p.suffix == ".db" and p.exists():
        conn = sqlite3.connect(str(p))
        c = conn.cursor()
        try:
            cnt = c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            print(f"  -> accounts count in {p}: {cnt}")
        except Exception as e:
            print(f"  -> error in {p}: {e}")
        conn.close()
