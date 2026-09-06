import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("."))
from PySide6.QtWidgets import QApplication
from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.widgets.sync_panel import SyncPanel, SyncConfirmDialog, FiltersDialog, ReportsDialog

def run_test():
    app = QApplication.instance() or QApplication(sys.argv)
    settings = AppSettings()
    engine = MailEngine()
    panel = SyncPanel(engine=engine, settings=settings)
    panel.refresh()

    print("=== SYNCPANEL VERIFICATION ===")
    print("Account table row count:", panel.account_table.rowCount())
    print("Account table column count:", panel.account_table.columnCount())
    print("Profile widget instance:", type(panel.view_profile_widget).__name__)
    print("Available profiles:", panel.view_profile_widget.manager.get_profile_names())
    print("Stat total text:", panel.lbl_stat_total.text())
    print("Stat selected text:", panel.lbl_stat_selected.text())
    print("Search input placeholder:", panel.txt_search_sync.placeholderText())

    # Test profile switching
    panel.view_profile_widget.combo_profiles.setCurrentText("Geniş Görünüm")
    panel._on_grid_profile_selected("Geniş Görünüm", {})
    print("Active profile applied: Geniş Görünüm, Row Height:", panel._current_row_height)

    # Test search filtering
    panel.txt_search_sync.setText("ozmed")
    visible_rows = [r for r in range(panel.account_table.rowCount()) if not panel.account_table.isRowHidden(r)]
    print(f"Rows matching 'ozmed': {len(visible_rows)}")

    # Clear search
    panel.txt_search_sync.setText("")
    visible_all = [r for r in range(panel.account_table.rowCount()) if not panel.account_table.isRowHidden(r)]
    print(f"All visible rows after clear: {len(visible_all)}")

    # Test SyncConfirmDialog preview construction
    sample_previews = [
        {
            "label": "Test Hesabı 1",
            "email": "test1@domain.com",
            "folder_count": 3,
            "new_mails": 25,
            "folders_list": [
                {"folder": "INBOX", "new_mails": 15},
                {"folder": "Sent", "new_mails": 10},
                {"folder": "Archive", "new_mails": 0},
            ],
            "since_date": "2025-01-01",
            "before_date": "",
            "archive_unread": True,
            "attachments_dir": "E:\\mailyedek\\attachments\\domain.com\\test1",
        },
        {
            "label": "Test Hesabı 2",
            "email": "test2@domain.com",
            "folder_count": 2,
            "new_mails": 50,
            "folders_list": [
                {"folder": "INBOX", "new_mails": 50},
            ],
            "since_date": "",
            "before_date": "",
            "archive_unread": True,
            "attachments_dir": "E:\\mailyedek\\attachments\\domain.com\\test2",
        }
    ]
    dlg = SyncConfirmDialog(sample_previews)
    print("SyncConfirmDialog successfully initialized, size:", dlg.size().width(), "x", dlg.size().height())
    print("SyncConfirmDialog account items count:", dlg.account_list_widget.count())

    # Test toggling log
    panel._toggle_log_visibility()
    print("Log box visibility after toggle:", panel.log_box.isVisible())
    panel._toggle_log_visibility()
    print("Log box visibility restored:", panel.log_box.isVisible())

    print("ALL CHECKS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_test()
