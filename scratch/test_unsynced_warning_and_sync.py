import os
import sys
import time
from pathlib import Path

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.widgets.account_panel import AccountPanel
from gui.widgets.search_panel import SearchPanel

def test_unsynced_warning():
    app = QApplication.instance() or QApplication(sys.argv)
    engine = MailEngine()
    settings = AppSettings()

    # 1. Test AccountPanel unsynced badge
    account_panel = AccountPanel(engine=engine, settings=settings)
    
    # Process events for loading
    start = time.time()
    while account_panel._is_refreshing and (time.time() - start) < 5:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()

    # Find account ID 14 (atlasgrup)
    atlas_row = -1
    for r in range(account_panel.table.rowCount()):
        aid = account_panel._get_row_account_id(r)
        if aid == 14:
            atlas_row = r
            break

    print(f"Atlasgrup (ID 14) row in AccountPanel: {atlas_row}")
    assert atlas_row >= 0, "Account ID 14 not found in table"
    
    mail_item = account_panel.table.item(atlas_row, 8)
    print(f"Atlasgrup Toplam Mail column text: {mail_item.text()}")
    assert "Senkronize Edilmedi" in mail_item.text(), "Expected unsynced warning in mail column"

    # 2. Test SearchPanel unsynced account detection
    search_panel = SearchPanel(engine=engine)
    start = time.time()
    while search_panel._loader_worker and search_panel._loader_worker.isRunning() and (time.time() - start) < 5:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()

    print(f"SearchPanel loaded accounts: {len(search_panel._all_accounts)}")
    print(f"SearchPanel mail counts: {len(search_panel._account_mail_counts)}")
    atlas_mail_cnt = search_panel._account_mail_counts.get(14, 0)
    print(f"Atlasgrup mail count in SearchPanel: {atlas_mail_cnt}")
    assert atlas_mail_cnt == 0, f"Expected 0 mails for atlasgrup, got {atlas_mail_cnt}"

    # Verify combo_account text for ID 14
    idx14 = search_panel.combo_account.findData(14)
    if idx14 >= 0:
        item_text = search_panel.combo_account.itemText(idx14)
        print(f"SearchPanel combo_account item text for ID 14: {item_text}")
        assert "Senkronize Edilmedi" in item_text

    print("\nALL UNSYNCED WARNING & PROMPT TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_unsynced_warning()
