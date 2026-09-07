import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from core.mail_engine import MailEngine

engine = MailEngine()
print(f"Using DB: {engine.db._db_path}")

# Test search for ozmed accounts
with engine.db.get_conn() as conn:
    ozmed_mails = conn.execute(
        "SELECT id, account_id, subject, sender, recipients, date FROM mail_metadata "
        "WHERE account_id IN (SELECT id FROM accounts WHERE email LIKE '%ozmedmedikal%') "
        "LIMIT 5"
    ).fetchall()
    print(f"Sample Ozmed mails in DB ({len(ozmed_mails)} found):")
    for m in ozmed_mails:
        print(f" - [{m['date']}] Acc {m['account_id']} | From: {m['sender'][:30]} | Subj: {m['subject'][:40]}")

print("Search verification complete.")
