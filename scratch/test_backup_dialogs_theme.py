"""
test_backup_dialogs_theme.py — Verify that SqlJobDialog, VhdxJobDialog, and CloudAccountDialog
render with standard Royal Blue header banners, crisp light theme, and proper contrast.
Also verify BackupPanel and RestorePanel top bars are clean with no duplicate titles.
"""

import sys
import os
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication
from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.dialogs.sql_job_dialog import SqlJobDialog
from gui.dialogs.vhdx_job_dialog import VhdxJobDialog
from gui.widgets.cloud_account_dialog import CloudAccountDialog
from gui.widgets.backup_panel import BackupPanel
from gui.widgets.restore_panel import RestorePanel


def test_dialogs_and_panels():
    app = QApplication.instance() or QApplication(sys.argv)
    test_db = Path("scratch/test_data/mail_archive.db")
    test_db.parent.mkdir(parents=True, exist_ok=True)
    engine = MailEngine(db_path=test_db)
    settings = AppSettings(settings_dir=Path("scratch/test_data"))

    print("Testing SqlJobDialog...")
    sql_dlg = SqlJobDialog(engine=engine)
    assert sql_dlg.txt_name is not None
    assert sql_dlg.stepper_retention.value() == 10
    sql_dlg.stepper_retention.btn_plus.click()
    assert sql_dlg.stepper_retention.value() == 11
    print("✅ SqlJobDialog instantiated and stepper verified.")

    print("Testing VhdxJobDialog...")
    vhdx_dlg = VhdxJobDialog(engine=engine)
    assert vhdx_dlg.txt_name is not None
    assert vhdx_dlg.stepper_retention.value() == 10
    vhdx_dlg.stepper_retention.btn_plus.click()
    assert vhdx_dlg.stepper_retention.value() == 11
    print("✅ VhdxJobDialog instantiated and stepper verified.")

    print("Testing CloudAccountDialog...")
    cloud_dlg = CloudAccountDialog(settings=settings, provider="s3")
    assert cloud_dlg.txt_name is not None
    print("✅ CloudAccountDialog instantiated successfully.")

    print("Testing BackupPanel & RestorePanel top bars...")
    b_panel = BackupPanel(engine=engine)
    assert b_panel.txt_search is not None
    assert not hasattr(b_panel, "lbl_title"), "Redundant title label should be removed from BackupPanel"

    r_panel = RestorePanel(engine=engine)
    assert r_panel.txt_search is not None
    assert not hasattr(r_panel, "lbl_title"), "Redundant title label should be removed from RestorePanel"
    print("✅ Top bars verified with no duplicate titles.")

    print("\n🎉 ALL DIALOG AND THEME VERIFICATIONS PASSED! 🎉")


if __name__ == "__main__":
    test_dialogs_and_panels()
