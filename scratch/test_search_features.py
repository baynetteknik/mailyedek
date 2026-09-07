import sys
import os
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.widgets.search_panel import SearchPanel

def run_test():
    app = QApplication.instance() or QApplication(sys.argv)
    settings = AppSettings()
    engine = MailEngine(settings.data_path() / "metadata.db", settings=settings)

    print("Creating SearchPanel...")
    panel = SearchPanel(engine)
    panel.resize(1400, 800)
    panel.show()
    app.processEvents()

    # Wait a moment for loader worker
    if panel._loader_worker:
        panel._loader_worker.wait(3000)
    app.processEvents()

    # 1. Test Domain Selection -> Account Combo Filtering
    print("\n--- 1. Testing Domain -> Account Combo Filtering ---")
    total_acc_count = len(panel._all_accounts)
    print(f"Total accounts in DB: {total_acc_count}")
    print(f"Initial combo_domain count: {panel.combo_domain.count()}")
    print(f"Initial combo_account count: {panel.combo_account.count()}")
    assert panel.combo_account.count() == total_acc_count + 1  # 1 'All' + all accounts

    # Select '4umedical.com.tr'
    idx_4u = panel.combo_domain.findData("4umedical.com.tr")
    assert idx_4u >= 0, "4umedical.com.tr not found in combo_domain!"
    print(f"Selecting 4umedical.com.tr (index {idx_4u})...")
    panel.combo_domain.setCurrentIndex(idx_4u)
    app.processEvents()

    print(f"Accounts in combo_account for 4umedical.com.tr: {panel.combo_account.count()}")
    # Item 0 is '👤 Tüm Hesaplar (5)', then 5 accounts
    assert panel.combo_account.count() == 6, f"Expected 6 items (1 header + 5 accounts), got {panel.combo_account.count()}"
    account_labels = [panel.combo_account.itemText(i) for i in range(panel.combo_account.count())]
    print(f"Items: {account_labels}")
    for lbl in account_labels[1:]:
        assert "@4umedical.com.tr" in lbl, f"Non-4umedical account found: {lbl}"
    assert "👤 Tüm Hesaplar (5)" in account_labels[0]
    print("✅ Domain '4umedical.com.tr' correctly filters combo_account to exactly 5 accounts!")

    # Select 'acsgroup.com.tr'
    idx_acs = panel.combo_domain.findData("acsgroup.com.tr")
    if idx_acs >= 0:
        print(f"Selecting acsgroup.com.tr (index {idx_acs})...")
        panel.combo_domain.setCurrentIndex(idx_acs)
        app.processEvents()
        print(f"Accounts in combo_account for acsgroup.com.tr: {panel.combo_account.count()}")
        for i in range(1, panel.combo_account.count()):
            lbl = panel.combo_account.itemText(i)
            assert "@acsgroup.com.tr" in lbl, f"Non-acsgroup account found: {lbl}"
        print("✅ Domain 'acsgroup.com.tr' correctly filters combo_account!")

    # Select 'Tüm Domainler'
    panel.combo_domain.setCurrentIndex(0)
    app.processEvents()
    assert panel.combo_account.count() == total_acc_count + 1
    print("✅ Selecting 'Tüm Domainler' restores all accounts in combo_account.")

    # 2. Test Column Filter Inputs
    print("\n--- 2. Testing Column Filter Inputs ---")
    fb = panel.db_grid.filter_bar
    assert len(fb.line_edits) == 8, f"Expected 8 column filter edits, got {len(fb.line_edits)}"
    
    expected_cols = ["Tarih", "Hesap", "Kimden", "Alıcı", "Konu", "Klasör", "Boyut", "Ek"]
    for i, col_name in enumerate(expected_cols):
        assert i in fb.line_edits, f"Missing filter line edit for column {i} ({col_name})"
        placeholder = fb.line_edits[i].placeholderText()
        print(f"Column {i} ({col_name}): placeholder = '{placeholder}', width = {fb.line_edits[i].width()}, visible = {fb.line_edits[i].isVisible()}")
        assert col_name in placeholder, f"Column name '{col_name}' not in placeholder '{placeholder}'"
        assert fb.line_edits[i].isVisible(), f"Column {i} ({col_name}) is not visible!"

    # 3. Test filtering functionality on column search
    print("\n--- 3. Testing Column Search Filtering ---")
    if panel._search_worker and panel._search_worker.isRunning():
        panel._search_worker.wait(3000)
    app.processEvents()
    mock_results = [
        {"id": 1, "account_id": 3, "date": "2026-03-01 10:00:00", "sender": "ali@gmail.com", "recipients": "kalite@4umedical.com.tr", "subject": "Acil Siparis", "folder": "INBOX", "size_bytes": 1024, "has_attachments": 1},
        {"id": 2, "account_id": 17, "date": "2026-03-02 11:00:00", "sender": "veli@gmail.com", "recipients": "aaksan@acsgroup.com.tr", "subject": "Fatura Bilgisi", "folder": "Sent", "size_bytes": 2048, "has_attachments": 0},
        {"id": 3, "account_id": 4, "date": "2026-03-03 12:00:00", "sender": "mehmet@gmail.com", "recipients": "ozdenali@4umedical.com.tr", "subject": "Toplanti Notlari", "folder": "INBOX", "size_bytes": 4096, "has_attachments": 1},
    ]
    panel._on_search_results_ready(mock_results)
    app.processEvents()
    assert panel.table.rowCount() == 3

    # Filter Col 4 (Konu) with "Siparis"
    fb._on_text_changed(4, "siparis")
    app.processEvents()
    visible_cnt = sum(1 for r in range(panel.table.rowCount()) if not panel.table.isRowHidden(r))
    assert visible_cnt == 1, f"Expected 1 visible row for 'siparis', got {visible_cnt}"
    print("✅ Filter on column 4 (Konu) correctly matched 1 row.")

    # Filter Col 1 (Hesap) with "4u"
    fb._on_text_changed(4, "")
    fb._on_text_changed(1, "4u")
    app.processEvents()
    visible_cnt_4u = sum(1 for r in range(panel.table.rowCount()) if not panel.table.isRowHidden(r))
    assert visible_cnt_4u == 2, f"Expected 2 visible rows for '4u', got {visible_cnt_4u}"
    print("✅ Filter on column 1 (Hesap) correctly matched 2 rows.")

    # Reset all filters
    fb.clear_all_filters()
    app.processEvents()
    visible_cnt_all = sum(1 for r in range(panel.table.rowCount()) if not panel.table.isRowHidden(r))
    assert visible_cnt_all == 3
    print("✅ clear_all_filters() restored all rows.")

    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! 🎉\n")

if __name__ == "__main__":
    run_test()
