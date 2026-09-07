import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from core.mail_engine import MailEngine

engine = MailEngine()
accounts = engine.list_accounts()
muhasebe_acc = None
for acc in accounts:
    if "muhasebe@ozmedmedikal.com.tr" in acc.get("email", "").lower():
        muhasebe_acc = acc
        break

print("Muhasebe Account in accounts repo:", muhasebe_acc)

if muhasebe_acc:
    aid = muhasebe_acc["id"]
    with engine.db.get_conn() as conn:
        raw_acc = conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
        print("\nRaw DB row in accounts:")
        for k in raw_acc.keys():
            print(f"  {k}: {raw_acc[k]}")
        
        profiles = conn.execute("SELECT * FROM account_server_profiles WHERE account_id = ?", (aid,)).fetchall()
        print(f"\nServer profiles in DB ({len(profiles)} found):")
        for p in profiles:
            p_dict = dict(p)
            try:
                p_dict["username_dec"] = engine.crypto.decrypt(p_dict.get("username_enc", ""))
            except Exception as e:
                p_dict["username_dec"] = f"(error: {e})"
            try:
                p_dict["password_dec"] = engine.crypto.decrypt(p_dict.get("password_enc", ""))
            except Exception as e:
                p_dict["password_dec"] = f"(error: {e})"
            print(" ", p_dict)

    # Decrypt main account credentials
    try:
        u_dec = engine.crypto.decrypt(raw_acc["username_enc"])
        p_dec = engine.crypto.decrypt(raw_acc["password_enc"])
        print(f"\nDecrypted credentials: user='{u_dec}', password_len={len(p_dec)}")
    except Exception as ex:
        print(f"Decryption error: {ex}")
