import sys
sys.path.insert(0, '.')
from core.settings import AppSettings
import sqlite3

settings = AppSettings()
db_path = settings.db_path()
conn = sqlite3.connect(str(db_path))

print(f"=== Mail Breakdown for muhasebe@ozmedmedikal.com.tr (ID: 35) ===")
rows = conn.execute("""
    SELECT server_host, folder, COUNT(*) as mail_count, MIN(uid) as min_uid, MAX(uid) as max_uid
    FROM mail_metadata 
    WHERE account_id = 35 
    GROUP BY server_host, folder
    ORDER BY server_host, folder
""").fetchall()

total = 0
for r in rows:
    print(f"Host: {r[0]:20} | Folder: {r[1]:20} | Count: {r[2]:5} | UIDs: {r[3]}..{r[4]}")
    total += r[2]

print(f"\nTotal Mails Archived for account 35: {total}")
