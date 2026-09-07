import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from core.mail_engine import MailEngine
from core.settings import AppSettings

engine = MailEngine()
accounts = engine.list_accounts()
print(f"Engine db path: {engine.db._db_path}")
print(f"Total accounts from engine: {len(accounts)}")

stats_map = {}
with engine.db.get_conn() as conn:
    rows = conn.execute(
        "SELECT account_id, COUNT(*) as mail_count, SUM(size_bytes) as total_size "
        "FROM mail_metadata WHERE is_deleted = 0 GROUP BY account_id"
    ).fetchall()
    for r in rows:
        stats_map[r["account_id"]] = {
            "mail_count": r["mail_count"],
            "total_size": r["total_size"] or 0
        }

print(f"Total accounts with stats: {len(stats_map)}")
ozmed_accs = [a for a in accounts if "ozmed" in a.get("email", "").lower()]
print(f"Ozmed accounts: {len(ozmed_accs)}")
for a in ozmed_accs:
    st = stats_map.get(a["id"], {})
    print(f"ID {a['id']}: {a['email']} -> {st.get('mail_count', 0)} mails, {st.get('total_size', 0)} bytes")
