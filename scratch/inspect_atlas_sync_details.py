import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from core.mail_engine import MailEngine

engine = MailEngine()
acc14 = engine.accounts.get(14)
print("Account ID 14:", acc14)

with engine.db.get_conn() as conn:
    sync_states = conn.execute("SELECT * FROM sync_state WHERE account_id = 14").fetchall()
    print("Sync states for account 14:", [dict(s) for s in sync_states])
    
    mail_cnt = conn.execute("SELECT COUNT(*) FROM mail_metadata WHERE account_id = 14").fetchone()[0]
    print(f"Total mails in DB for account 14: {mail_cnt}")

# Check files on drive E:
atlas_paths = [
    Path(r"E:\mailyedek\atlas"),
    Path(r"E:\mailyedek\atlasgrup.com.tr"),
    Path(r"E:\mailyedek\mehmetebter_atlasgrup.com.tr"),
    Path(r"E:\mailyedek\atlas\mehmetebter_atlasgrup.com.tr"),
]

for p in atlas_paths:
    if p.exists():
        emls = list(p.rglob("*.eml"))
        all_files = list(p.rglob("*"))
        print(f"Path exists: {p} (Total files: {len(all_files)}, EML files: {len(emls)})")
    else:
        print(f"Path does NOT exist: {p}")
