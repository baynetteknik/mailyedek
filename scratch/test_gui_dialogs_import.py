"""
test_gui_dialogs_import.py
Verify GUI components import and instantiate properly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.dialogs.account_dialog import AccountDialog
from gui.widgets.sync_panel import SyncPanel, SelectSyncServerDialog

def main():
    app = QApplication.instance() or QApplication(sys.argv)
    settings = AppSettings()
    engine = MailEngine(settings=settings)

    print("Checking AccountDialog...")
    acc_35 = engine.accounts.get(35)
    dlg = AccountDialog(engine=engine, account=acc_35, settings=settings, parent=None)
    assert hasattr(dlg, "btn_test_selected_profile")
    assert hasattr(dlg, "lbl_profile_test_status")
    print("AccountDialog loaded with 'Seçili Sunucuyu Test Et' button!")

    print("Checking SelectSyncServerDialog...")
    profiles = engine.db.get_server_profiles(35)
    sync_dlg = SelectSyncServerDialog(account=acc_35, profiles=profiles, parent=None)
    assert hasattr(sync_dlg, "radio_buttons")
    assert len(sync_dlg.radio_buttons) == 2
    print(f"SelectSyncServerDialog successfully initialized with {len(sync_dlg.radio_buttons)} profile radio options!")

    print("\nAll GUI checks passed cleanly!")

if __name__ == "__main__":
    main()
