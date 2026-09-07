import time
import os
import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.widgets.account_panel import AccountDataLoaderWorker
from gui.widgets.mail_viewer_panel import MailViewerDataLoaderWorker

def test_simulated_offline():
    print("=" * 60)
    print("SIMULATING OFFLINE DISK (DRIVE Z:\\ DISCONNECTED)")
    print("=" * 60)

    # Force settings data_path to a missing drive
    settings = AppSettings()
    settings._data["data_path"] = "Z:\\non_existent_drive\\mailyedek"
    
    is_online = settings.is_configured_data_path_available()
    active_path = settings.data_path()
    print(f"[OFFLINE CHECK] is_configured_data_path_available: {is_online} (Expected: False)")
    print(f"[OFFLINE CHECK] fallback data_path: {active_path} (Expected: data)")
    assert not is_online, "Should report offline!"
    assert str(active_path) == "data", "Should fall back to local 'data'!"

    engine = MailEngine(settings=settings)
    
    t0 = time.perf_counter()
    accounts = engine.list_accounts()
    t1 = time.perf_counter()
    print(f"[OFFLINE ENGINE] Loaded {len(accounts)} accounts in {(t1 - t0)*1000:.2f} ms")
    assert len(accounts) == 44, f"Expected 44 accounts, got {len(accounts)}"

    # Test AccountDataLoaderWorker
    acc_worker = AccountDataLoaderWorker(engine)
    acc_result = []
    acc_worker.data_loaded.connect(lambda res: acc_result.extend(res))
    acc_worker.run()
    print(f"[OFFLINE ACCOUNT WORKER] Loaded {len(acc_result)} accounts")
    assert len(acc_result) == 44

    # Test MailViewerDataLoaderWorker
    mail_worker = MailViewerDataLoaderWorker(engine, selected_group="__ALL__")
    mail_result = {}
    mail_worker.data_loaded.connect(lambda res: mail_result.update(res))
    mail_worker.run()
    print(f"[OFFLINE MAIL VIEWER] Groups: {len(mail_result.get('groups', []))}, Accounts: {len(mail_result.get('accounts_for_group', []))}, Tree: {len(mail_result.get('folder_tree_data', []))}")
    assert len(mail_result.get('folder_tree_data', [])) == 44

    print("=" * 60)
    print("OFFLINE SIMULATION TEST PASSED 100% PERFECTLY!")
    print("=" * 60)

if __name__ == "__main__":
    test_simulated_offline()
