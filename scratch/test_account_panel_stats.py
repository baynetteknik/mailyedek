import os
import sys
import time
from pathlib import Path

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QCoreApplication
from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.widgets.account_panel import AccountPanel

def test_account_panel():
    app = QApplication.instance() or QApplication(sys.argv)
    engine = MailEngine()
    settings = AppSettings()
    
    panel = AccountPanel(engine=engine, settings=settings)
    
    # Process events until worker finishes and data is loaded
    start_time = time.time()
    while panel._is_refreshing and (time.time() - start_time) < 10:
        app.processEvents()
        time.sleep(0.05)
    
    app.processEvents()
    
    print(f"Total cached accounts: {len(panel._cached_accounts)}")
    print(f"Table row count: {panel.table.rowCount()}")
    print(f"Card accounts text: {panel.lbl_card_accounts.text()}")
    print(f"Card mails text: {panel.lbl_card_mails.text()}")
    print(f"Card size text: {panel.lbl_card_size.text()}")
    print(f"Card status text: {panel.lbl_card_status.text()}")
    print(f"Card compare text: {panel.lbl_card_compare.text()}")
    
    # Verify ozmedmedikal accounts
    ozmed_accounts = [a for a in panel._cached_accounts if "ozmedmedikal.com.tr" in a.get("email", "").lower()]
    print(f"Ozmedmedikal accounts count: {len(ozmed_accounts)}")
    ozmed_total_mails = sum(panel._account_stats.get(a["id"], {}).get("mail_count", 0) for a in ozmed_accounts)
    print(f"Ozmedmedikal total mails: {ozmed_total_mails}")
    assert len(ozmed_accounts) == 11, f"Expected 11 ozmed accounts, got {len(ozmed_accounts)}"
    assert ozmed_total_mails == 23938, f"Expected 23938 mails for ozmed, got {ozmed_total_mails}"
    
    # Test Select All Checkboxes
    panel._select_all_checkboxes()
    print("After Select All - Compare Card:", panel.lbl_card_compare.text())
    assert "Seçilen" in panel.lbl_card_compare.text()
    
    # Test Clear Checkboxes
    panel._clear_all_checkboxes()
    print("After Clear - Compare Card:", panel.lbl_card_compare.text())
    assert "Seçili: 0 Hesap" in panel.lbl_card_compare.text()
    
    # Test Check a few rows
    for r in range(min(3, panel.table.rowCount())):
        panel.table.item(r, 0).setCheckState(Qt.Checked)
    print("After checking 3 rows - Compare Card:", panel.lbl_card_compare.text())
    assert "Seçilen 3 Hesap" in panel.lbl_card_compare.text()
    
    # Test Filter by Domain (e.g. ozmedmedikal.com.tr)
    panel.left_sidebar.get_selected_domain = lambda: "ozmedmedikal.com.tr"
    panel._on_group_filter_changed("ozmedmedikal.com.tr")
    app.processEvents()
    
    print(f"Filtered Table row count for ozmed: {panel.table.rowCount()}")
    print(f"Filtered Card accounts: {panel.lbl_card_accounts.text()}")
    print(f"Filtered Card mails: {panel.lbl_card_mails.text()}")
    print(f"Filtered Card size: {panel.lbl_card_size.text()}")
    
    assert panel.table.rowCount() == 11, f"Expected 11 visible rows for ozmed, got {panel.table.rowCount()}"
    assert "23,938 Mail" in panel.lbl_card_mails.text()
    
    print("\nALL ACCOUNT PANEL STATS & COMPARISON TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_account_panel()
