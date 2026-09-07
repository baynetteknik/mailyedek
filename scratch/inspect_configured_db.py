import sys
sys.path.insert(0, '.')
from core.settings import AppSettings
import sqlite3

settings = AppSettings()
db_p = settings.db_path()
print("Configured DB Path:", db_p)

conn = sqlite3.connect(str(db_p))
print("\nmail_metadata server_hosts:")
for r in conn.execute("SELECT server_host, COUNT(*) FROM mail_metadata GROUP BY server_host"):
    print(" ", r)

print("\nsync_state server_hosts:")
for r in conn.execute("SELECT server_host, COUNT(*) FROM sync_state GROUP BY server_host"):
    print(" ", r)

print("\naccount 35 (muhasebe@ozmedmedikal.com.tr) mails count:", conn.execute("SELECT COUNT(*) FROM mail_metadata WHERE account_id=35").fetchone()[0])
for r in conn.execute("SELECT folder, server_host, uid, subject FROM mail_metadata WHERE account_id=35 LIMIT 10"):
    print(" ", r)
