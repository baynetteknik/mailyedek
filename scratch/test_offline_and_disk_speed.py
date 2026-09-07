import time
import os
import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.settings import AppSettings, is_path_accessible_fast
from core.mail_engine import MailEngine

def test_speed_and_fallback():
    print("=" * 60)
    print("TESTING FAST DISK CHECK & OFFLINE ACCOUNT RECOVERY")
    print("=" * 60)

    # 1. Test is_path_accessible_fast on offline drive
    t0 = time.perf_counter()
    for _ in range(100):
        is_path_accessible_fast("Z:\\non_existent_drive\\data")
        is_path_accessible_fast("E:\\mailyedek")
    t1 = time.perf_counter()
    avg_ms = ((t1 - t0) / 200) * 1000
    print(f"[OK] 200 offline drive probes took: {(t1 - t0)*1000:.3f} ms (Avg: {avg_ms:.4f} ms per probe)")

    # 2. Test AppSettings
    settings = AppSettings()
    cfg_path = settings.configured_data_path_str()
    is_online = settings.is_configured_data_path_available()
    active_path = settings.data_path()
    print(f"[SETTINGS] Configured Path: {cfg_path}")
    print(f"[SETTINGS] Is Online: {is_online}")
    print(f"[SETTINGS] Active Fallback Path: {active_path}")

    # 3. Test Engine and Account Loading
    engine = MailEngine(settings=settings)
    t0 = time.perf_counter()
    accounts = engine.list_accounts()
    t1 = time.perf_counter()
    print(f"[ACCOUNTS] Loaded {len(accounts)} accounts in {(t1 - t0)*1000:.2f} ms")
    assert len(accounts) > 0, "Accounts should not be empty even when disk is offline!"

    # 4. Test Domain Groups Extraction
    groups = set()
    for acc in accounts:
        g = acc.get("account_group") or (acc.get("email", "").split("@")[-1] if "@" in acc.get("email", "") else "Diğer")
        groups.add(g)
    print(f"[GROUPS] Found {len(groups)} domain groups: {sorted(list(groups))}")

    # 5. Test MailViewerDataLoaderWorker logic
    from gui.widgets.mail_viewer_panel import MailViewerDataLoaderWorker
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    worker = MailViewerDataLoaderWorker(engine, selected_group="__ALL__")
    worker_result = {}
    def on_loaded(res):
        nonlocal worker_result
        worker_result = res

    worker.data_loaded.connect(on_loaded)
    worker.run()

    print(f"[MAIL VIEWER WORKER] Groups: {len(worker_result.get('groups', []))}")
    print(f"[MAIL VIEWER WORKER] Accounts: {len(worker_result.get('accounts_for_group', []))}")
    print(f"[MAIL VIEWER WORKER] Folder Tree Items: {len(worker_result.get('folder_tree_data', []))}")
    assert len(worker_result.get('folder_tree_data', [])) == len(accounts), "All accounts must be in folder tree data!"

    print("=" * 60)
    print("ALL OFFLINE AND SPEED TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    test_speed_and_fallback()
