import sys
sys.path.insert(0, '.')
from core.settings import AppSettings
from core.mail_engine import MailEngine

engine = MailEngine()
acc_id = 35 # muhasebe@ozmedmedikal.com.tr

print("Listing server profiles for account 35:")
profiles = engine.list_server_profiles(acc_id)
for p in profiles:
    print(" ", p["id"], p["profile_name"], p["imap_host"], "Default:", p["is_default"])

# Find Cenuta profile
cenuta_p = next((p for p in profiles if "cenuta" in p["imap_host"].lower()), None)
if not cenuta_p:
    print("Cenuta profile not found!")
    sys.exit(1)

# Set Cenuta as active default
engine.set_default_server_profile(acc_id, cenuta_p["id"])
print(f"\nSwitched active profile to Cenuta (id={cenuta_p['id']})")

print("\nRunning sync for account 35 on Cenuta...")
def log_cb(msg):
    print("LOG:", msg)

report = engine.sync_account(acc_id, log_callback=log_cb)
print("\n=== Sync Report ===")
print("Fetched:", report.mails_fetched)
print("Updated:", report.mails_updated)
print("Duplicates:", report.duplicates_found)
print("Already Archived:", report.mails_already_archived)
print("Errors:", report.errors)
if report.error_details:
    print("Error details:")
    for err in report.error_details:
        print(" -", err)
