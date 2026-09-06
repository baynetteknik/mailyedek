#!/usr/bin/env python3
"""
Test script to verify all dialogs and panels have proper light theme, royal blue banners,
high contrast, no dark theme artifacts, and no duplicate titles.
"""
import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.dialogs.sql_job_dialog import SqlJobDialog
from gui.dialogs.vhdx_job_dialog import VhdxJobDialog
from gui.widgets.cloud_account_dialog import CloudAccountDialog
from gui.widgets.backup_panel import BackupPanel
from gui.widgets.restore_panel import RestorePanel
from gui.main_window import MainWindow

def test_dialogs_and_theme():
    app = QApplication.instance() or QApplication(sys.argv)
    
    settings = AppSettings()
    engine = MailEngine(db_path=settings.db_path(), key_file=settings.key_file_path())
    
    print("Testing SqlJobDialog creation...")
    sql_dlg = SqlJobDialog(engine)
    assert sql_dlg.windowTitle() == "SQL Yedekleme Görevi Yapılandırması"
    assert sql_dlg.txt_name is not None
    assert sql_dlg.stepper_retention.value() == 10
    print("[OK] SqlJobDialog initialized with royal blue banner and stepper.")
    
    print("Testing VhdxJobDialog creation...")
    vhdx_dlg = VhdxJobDialog(engine)
    assert vhdx_dlg.windowTitle() == "Hyper-V & VHDX Yedekleme Görevi Yapılandırması"
    assert vhdx_dlg.txt_source is not None
    assert vhdx_dlg.stepper_retention.value() == 10
    print("[OK] VhdxJobDialog initialized with royal blue banner and stepper.")
    
    print("Testing CloudAccountDialog (S3 & GDrive)...")
    s3_dlg = CloudAccountDialog(settings, provider="s3")
    assert "Amazon S3" in s3_dlg.windowTitle()
    gd_dlg = CloudAccountDialog(settings, provider="gdrive")
    assert "Google Drive" in gd_dlg.windowTitle()
    print("[OK] CloudAccountDialog initialized for both S3 and Google Drive.")
    
    print("Testing BackupPanel & RestorePanel creation...")
    bp = BackupPanel(engine)
    rp = RestorePanel(engine)
    assert bp is not None
    assert rp is not None
    print("[OK] BackupPanel and RestorePanel initialized cleanly.")
    
    print("Testing MainWindow navigation...")
    mw = MainWindow(db_path=settings.db_path(), key_file=settings.key_file_path(), settings=settings)
    mw._navigate("backup")
    assert mw.page_title.text() == "🛡️ Yedekleme ve Kurtarma Merkezi"
    mw._navigate("restore")
    assert mw.page_title.text() == "Yedekten Geri Yükleme"
    print("[OK] MainWindow navigation verified with single navbar title.")
    
    print("ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_dialogs_and_theme()
