import sys
import os
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.settings import AppSettings
from core.mail_engine import MailEngine

s = AppSettings()
e = MailEngine(s.data_path() / "metadata.db", settings=s)
accs = e.list_accounts()
print(f"Total accounts in DB: {len(accs)}\n")

with e.db.get_conn() as conn:
    # Check mail counts per account in mail_metadata
    mail_counts = dict(conn.execute("SELECT account_id, COUNT(*) as cnt, SUM(size_bytes) as total_size FROM mail_metadata WHERE is_deleted = 0 GROUP BY account_id").fetchall())
    
    print("--- ALL ACCOUNTS IN DB ---")
    for a in accs:
        aid = a["id"]
        cnt = mail_counts.get(aid, 0)
        email = a.get("email", "")
        group = a.get("account_group", "")
        # Also check domain parsing
        dom_from_email = email.split("@")[-1].strip().lower() if "@" in email else ""
        print(f"ID {aid:2d} | Email: {email:35s} | Group: {group:20s} | EmailDom: {dom_from_email:20s} | Mails in DB: {cnt}")

    print("\n--- DISTINCT DOMAINS IN ACCOUNTS ---")
    email_domains = set()
    group_domains = set()
    for a in accs:
        email = a.get("email", "")
        if "@" in email:
            email_domains.add(email.split("@")[-1].strip().lower())
        grp = a.get("account_group", "").strip()
        if grp:
            group_domains.add(grp.lower())
    print("Domains from email address:", sorted(email_domains))
    print("Domains from account_group: ", sorted(group_domains))

    # Check ozmedmedikal accounts specifically
    ozmed_email = [a for a in accs if "ozmed" in a.get("email", "").lower()]
    ozmed_group = [a for a in accs if "ozmed" in a.get("account_group", "").lower()]
    print(f"\nOzmed accounts by email: {len(ozmed_email)}")
    print(f"Ozmed accounts by group: {len(ozmed_group)}")
    for a in ozmed_email:
        print("  -", a["id"], a["email"], "Group:", a.get("account_group"), "Mails:", mail_counts.get(a["id"], 0))

    # Check atlasgrup accounts specifically
    atlas_email = [a for a in accs if "atlas" in a.get("email", "").lower()]
    atlas_group = [a for a in accs if "atlas" in a.get("account_group", "").lower()]
    print(f"\nAtlas accounts by email: {len(atlas_email)}")
    print(f"Atlas accounts by group: {len(atlas_group)}")
    for a in atlas_email:
        print("  -", a["id"], a["email"], "Group:", a.get("account_group"), "Mails:", mail_counts.get(a["id"], 0))
    for a in atlas_group:
        if a not in atlas_email:
            print("  - [group only]", a["id"], a["email"], "Group:", a.get("account_group"), "Mails:", mail_counts.get(a["id"], 0))

    # Check FTS5 index counts
    try:
        fts_cnt = conn.execute("SELECT COUNT(*) FROM mail_fts").fetchone()[0]
        print(f"\nTotal rows in FTS5 mail_fts index: {fts_cnt}")
    except Exception as exc:
        print(f"\nFTS query error: {exc}")
