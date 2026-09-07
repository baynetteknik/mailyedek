import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3
from core.settings import AppSettings

s = AppSettings()
for db_p in [s.db_path(), s.data_path() / "metadata.db"]:
    if db_p.exists():
        conn = sqlite3.connect(db_p)
        cur = conn.cursor()
        cur.execute("UPDATE accounts SET account_group = 'atlasgrup.com.tr' WHERE id = 14")
        conn.commit()
        print(f"Updated account 14 in {db_p}: {cur.rowcount} rows updated.")
        conn.close()
