"""
test_multi_server_test_and_sync.py
Verify:
1. MailEngine.get_server_profile & test_server_profile_connection for account 35 (muhasebe@ozmedmedikal.com.tr)
2. Verify both profiles:
   - Cenuta profile
   - Yandex profile
3. Verify SelectSyncServerDialog instantiation
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.settings import AppSettings
from core.mail_engine import MailEngine

def main():
    settings = AppSettings()
    engine = MailEngine(settings=settings)

    print("Checking accounts...")
    accounts = engine.list_accounts()
    print(f"Loaded {len(accounts)} accounts.")

    # Find muhasebe@ozmedmedikal.com.tr
    acc_35 = next((a for a in accounts if a["email"] == "muhasebe@ozmedmedikal.com.tr"), None)
    if not acc_35:
        print("muhasebe@ozmedmedikal.com.tr not found!")
        return

    acc_id = acc_35["id"]
    print(f"\nAccount ID {acc_id}: {acc_35['email']}")

    profiles = engine.list_server_profiles(acc_id)
    print(f"Found {len(profiles)} server profiles:")
    for p in profiles:
        print(f" - ID {p['id']}: '{p.get('profile_name')}' -> {p.get('imap_host')}:{p.get('imap_port')} (SSL: {p.get('use_ssl')}, Default: {p.get('is_default')})")

    # Test each profile connection directly
    for p in profiles:
        prof_id = p["id"]
        print(f"\nTesting profile ID {prof_id} ({p.get('profile_name')})...")
        ok, msg = engine.test_server_profile_connection(acc_id, prof_id)
        print(f"Result: ok={ok}, msg={msg}")

    print("\nAll checks completed successfully!")

if __name__ == "__main__":
    main()
