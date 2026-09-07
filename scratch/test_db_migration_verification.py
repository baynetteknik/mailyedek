import sys
sys.path.insert(0, '.')
from core.settings import AppSettings
from core.database import DatabaseManager
import sqlite3

settings = AppSettings()
db_path = settings.db_path()
print("Connecting to configured database:", db_path)

# Initialize DatabaseManager which runs _init_schema and self-healing migrations
db = DatabaseManager(db_path=db_path)

conn = sqlite3.connect(str(db_path))

print("\n=== mail_metadata sql ===")
row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='mail_metadata'").fetchone()
print(row[0])

print("\n=== sync_state sql ===")
row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='sync_state'").fetchone()
print(row[0])

print("\n=== mail_metadata total count ===")
cnt = conn.execute("SELECT COUNT(*) FROM mail_metadata").fetchone()[0]
print("Total mails in DB:", cnt)

print("\n=== Server host distribution in mail_metadata ===")
for r in conn.execute("SELECT server_host, COUNT(*) FROM mail_metadata GROUP BY server_host"):
    print(" ", r)

print("\n=== Server host distribution in sync_state ===")
for r in conn.execute("SELECT server_host, COUNT(*) FROM sync_state GROUP BY server_host"):
    print(" ", r)

# Test inserting UID 1 from Cenuta and UID 1 from Yandex for a test account or verification
print("\n=== Testing multi-server duplicate UID insert ===")
try:
    with db.transaction() as c:
        # Test upserting
        mid1 = db.upsert_mail_metadata(
            account_id=35, folder="Sent", uid=1, subject="Test Sent 1 Cenuta", server_host="srv10.cenuta.email"
        )
        mid2 = db.upsert_mail_metadata(
            account_id=35, folder="Sent", uid=1, subject="Test Sent 1 Yandex", server_host="imap.yandex.com"
        )
        print(f"SUCCESS! Both inserted without constraint collision: Cenuta ID={mid1}, Yandex ID={mid2}")
except Exception as e:
    print(f"FAILED: {e}")
