import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("."))
from PySide6.QtWidgets import QApplication
from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.widgets.export_panel import ExportPanel, ExportConfigDialog, ExportConfirmDialog, ExportReportsDialog

def run_test():
    app = QApplication.instance() or QApplication(sys.argv)
    settings = AppSettings()
    engine = MailEngine()
    panel = ExportPanel(engine=engine)
    panel.show()
    panel.refresh()

    print("=== EXPORTPANEL VERIFICATION ===")
    print("Account table row count:", panel.account_table.rowCount())
    print("Account table column count:", panel.account_table.columnCount())
    print("Default Row Height:", panel._current_row_height)
    assert panel._current_row_height == 88, f"Expected 88, got {panel._current_row_height}"
    
    print("Stat total text:", panel.lbl_stat_total.text())
    print("Stat selected text:", panel.lbl_stat_selected.text())
    print("Search input placeholder:", panel.txt_search_export.placeholderText())

    # Test row height adjustments
    panel.set_row_height(40)
    print("Applied Row Height 40px:", panel._current_row_height)
    assert panel._current_row_height == 40
    panel.set_row_height(88)
    print("Reset Row Height 88px:", panel._current_row_height)
    assert panel._current_row_height == 88

    # Test search filtering
    panel.txt_search_export.setText("a")
    visible_rows = [r for r in range(panel.account_table.rowCount()) if not panel.account_table.isRowHidden(r)]
    print(f"Rows matching 'a': {len(visible_rows)}")

    # Clear search
    panel.txt_search_export.setText("")
    visible_all = [r for r in range(panel.account_table.rowCount()) if not panel.account_table.isRowHidden(r)]
    print(f"All visible rows after clear: {len(visible_all)}")

    # Test preview dialog
    previews = panel._get_export_stats_for_checked(list(panel._accounts_ui.keys())[:2])
    confirm_dlg = ExportConfirmDialog(previews)
    print(f"ExportConfirmDialog created successfully with {len(previews)} account(s).")

    # Test reports dialog
    reports = [{
        "account_label": "Test Account",
        "format": "ZIP",
        "exported": 50,
        "errors": 0,
        "total_bytes": 524288,
        "duration_seconds": 1.5
    }]
    rep_dlg = ExportReportsDialog(reports)
    print(f"ExportReportsDialog created successfully.")

    # Test log box toggle
    assert not panel.log_box.isHidden()
    panel._toggle_log_visibility()
    assert panel.log_box.isHidden()
    panel._toggle_log_visibility()
    assert not panel.log_box.isHidden()

    print("ALL EXPORT PANEL VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_test()
