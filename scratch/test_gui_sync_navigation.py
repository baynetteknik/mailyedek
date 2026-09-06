import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("."))
from PySide6.QtWidgets import QApplication
from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.main_window import MainWindow

def test_main_window_sync():
    app = QApplication.instance() or QApplication(sys.argv)
    settings = AppSettings()
    engine = MailEngine()
    
    win = MainWindow(engine=engine, settings=settings)
    print("MainWindow initialized.")
    
    # Navigate to sync panel
    win._navigate("sync")
    print("Navigated to sync panel successfully.")
    
    sync_panel = win.panels.get("sync")
    assert sync_panel is not None, "Sync panel should be instantiated"
    
    print("Sync panel account table rows:", sync_panel.account_table.rowCount())
    print("Sync panel action buttons bar visible:", sync_panel.btn_sync.isVisible())
    print("Top total stat:", sync_panel.lbl_stat_total.text())
    
    # Test group filter change
    sync_panel._on_group_filter_changed("__ALL__")
    print("Group filter changed to __ALL__ cleanly.")
    
    # Test select all
    sync_panel._toggle_select_all()
    print("Toggle select all executed:", sync_panel.lbl_stat_selected.text())
    sync_panel._toggle_select_all()
    print("Toggle deselect all executed:", sync_panel.lbl_stat_selected.text())
    
    print("ALL MAIN WINDOW SYNC TESTS PASSED!")

if __name__ == "__main__":
    test_main_window_sync()
