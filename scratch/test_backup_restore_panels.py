"""
test_backup_restore_panels.py — Automated verification for Backup & Restore modernized panels,
NumericStepperWidget, CloudAccountDialog, and AppSettings multi-cloud account management.
"""

import sys
import os
import time
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.widgets.numeric_stepper import NumericStepperWidget
from gui.widgets.cloud_account_dialog import CloudAccountDialog
from gui.widgets.backup_right_sidebar_widget import BackupRightSidebarWidget
from gui.widgets.restore_right_sidebar_widget import RestoreRightSidebarWidget
from gui.widgets.backup_panel import BackupPanel
from gui.widgets.restore_panel import RestorePanel


def test_numeric_stepper():
    print("Testing NumericStepperWidget...")
    stepper = NumericStepperWidget(value=10, minimum=1, maximum=100, suffix="adet")
    assert stepper.value() == 10, f"Expected 10, got {stepper.value()}"
    assert stepper.suffix() == "adet"
    assert stepper.line_edit.text() == "10"

    # Test plus
    stepper.btn_plus.click()
    assert stepper.value() == 11, f"Expected 11, got {stepper.value()}"

    # Test minus
    stepper.btn_minus.click()
    assert stepper.value() == 10, f"Expected 10, got {stepper.value()}"

    # Test direct typing / text editing
    stepper.line_edit.setText("25")
    stepper._on_text_edited("25")
    assert stepper.value() == 25, f"Expected 25, got {stepper.value()}"

    # Test setSuffix
    stepper.setSuffix("gün")
    assert stepper.lbl_suffix.text() == "gün"

    print("✅ NumericStepperWidget tests passed successfully.")


def test_app_settings_cloud_accounts():
    print("Testing AppSettings multi-cloud accounts...")
    settings = AppSettings(settings_dir=Path("scratch/test_data"))

    # Clear old test cloud accounts
    settings.set("cloud_storage_accounts", [])
    settings.save()

    # Add S3 account 1
    s3_1 = {
        "name": "AWS Production",
        "provider": "s3",
        "bucket": "prod-mail-archive",
        "region": "eu-central-1",
        "access_key": "AKIA_PROD",
        "secret_key": "SECRET_PROD",
        "is_default": True
    }
    id1 = settings.save_cloud_account(s3_1)
    assert id1.startswith("s3_"), f"Unexpected ID {id1}"

    # Add S3 account 2
    s3_2 = {
        "name": "AWS Cold Storage",
        "provider": "s3",
        "bucket": "glacier-mail-archive",
        "region": "us-east-1",
        "is_default": False
    }
    id2 = settings.save_cloud_account(s3_2)

    # Add Google Drive account
    gd_1 = {
        "name": "Company Google Drive",
        "provider": "gdrive",
        "credentials_path": "C:/keys/gdrive_creds.json",
        "is_default": True
    }
    id3 = settings.save_cloud_account(gd_1)

    # Test query
    all_accs = settings.cloud_accounts()
    assert len(all_accs) == 3, f"Expected 3, got {len(all_accs)}"

    s3_accs = settings.cloud_accounts("s3")
    assert len(s3_accs) == 2, f"Expected 2 S3 accounts, got {len(s3_accs)}"

    gd_accs = settings.cloud_accounts("gdrive")
    assert len(gd_accs) == 1, f"Expected 1 GDrive account, got {len(gd_accs)}"

    # Test set default
    settings.set_default_cloud_account(id2)
    s3_accs_updated = settings.cloud_accounts("s3")
    acc2 = next(a for a in s3_accs_updated if a["id"] == id2)
    acc1 = next(a for a in s3_accs_updated if a["id"] == id1)
    assert acc2["is_default"] is True
    assert acc1["is_default"] is False

    # Test remove
    settings.remove_cloud_account(id2)
    assert len(settings.cloud_accounts("s3")) == 1

    print("✅ AppSettings multi-cloud accounts tests passed successfully.")


def test_backup_panel_and_right_sidebar(app: QApplication):
    print("Testing BackupPanel & BackupRightSidebarWidget...")
    test_db = Path("scratch/test_data/mail_archive.db")
    test_db.parent.mkdir(parents=True, exist_ok=True)
    engine = MailEngine(db_path=test_db)
    engine.settings = AppSettings(settings_dir=Path("scratch/test_data"))

    backup_panel = BackupPanel(engine=engine)
    assert backup_panel.grid_table.columnCount() == 4
    assert backup_panel._current_row_height in (40, 60, 88, 110)

    # Process events to allow async lazy loading
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()

    # Test category switching
    backup_panel._on_category_selected("s3")
    assert backup_panel._active_category == "s3"

    backup_panel._on_category_selected("all")
    assert backup_panel._active_category == "all"

    # Test row height adjustment
    backup_panel._set_row_height(88)
    assert backup_panel.grid_table.verticalHeader().defaultSectionSize() == 88

    backup_panel._set_row_height(60)
    assert backup_panel._current_row_height == 60

    print("✅ BackupPanel tests passed successfully.")


def test_restore_panel_and_right_sidebar(app: QApplication):
    print("Testing RestorePanel & RestoreRightSidebarWidget...")
    test_db = Path("scratch/test_data/mail_archive.db")
    engine = MailEngine(db_path=test_db)
    engine.settings = AppSettings(settings_dir=Path("scratch/test_data"))

    restore_panel = RestorePanel(engine=engine)
    assert restore_panel.grid_table.columnCount() == 4

    app.processEvents()
    time.sleep(0.3)
    app.processEvents()

    # Test category switching
    restore_panel._on_category_selected("gdrive")
    assert restore_panel._active_category == "gdrive"

    restore_panel._on_category_selected("all")
    assert restore_panel._active_category == "all"

    # Test row height adjustment
    restore_panel._set_row_height(88)
    assert restore_panel._current_row_height == 88

    print("✅ RestorePanel tests passed successfully.")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    test_numeric_stepper()
    test_app_settings_cloud_accounts()
    test_backup_panel_and_right_sidebar(app)
    test_restore_panel_and_right_sidebar(app)
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! 🎉")


if __name__ == "__main__":
    main()
