import sys
sys.path.insert(0, '.')
import json
from pathlib import Path
from core.settings import AppSettings
from core.database import DatabaseManager

s = AppSettings()
print("Settings data_path:", s._data.get("data_path"))
print("is_configured_data_path_available:", s.is_configured_data_path_available())
cached = s.load_account_cache()
print("Cached accounts count:", len(cached))
if cached:
    print("Sample cached account:", cached[0].get("email"), cached[0].get("label"))

# Check all potential databases
db_files = list(Path(".").glob("**/*.db"))
for db_file in db_files:
    try:
        db = DatabaseManager(db_path=db_file)
        accs = db.list_accounts()
        print(f"DB {db_file}: {len(accs)} accounts")
    except Exception as e:
        print(f"DB {db_file} error: {e}")
