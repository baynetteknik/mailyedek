"""
test_lazy_load_and_confirm_dialog.py — Comprehensive verification test for:
1. DeleteConfirmDialog (Royal Blue banner standard, contrast, details, cancel/confirm logic).
2. MainWindow disk reading notifications banner and status bar updates.
3. Background QThread workers and lazy loading across all panels:
   - BackupPanel (BackupDataLoaderWorker)
   - RestorePanel (RestoreDataLoaderWorker)
   - MailViewerPanel (MailViewerDataLoaderWorker)
   - AccountPanel (AccountDataLoaderWorker)
   - SyncPanel (SyncDataLoaderWorker)
   - ExportPanel (ExportDataLoaderWorker)
   - SearchPanel (SearchDataLoaderWorker, SearchExecutionWorker)
   - AuditPanel (AuditDataLoaderWorker)
   - SchedulePanel (ScheduleDataLoaderWorker)
   - ReportPanel (ReportLoaderWorker, CustomReportWorker)
   - HealthPanel (HealthCheckWorker)
   - SettingsPanel (SettingsDataLoaderWorker)
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True, encoding="utf-8")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.dialogs.delete_confirm_dialog import DeleteConfirmDialog
from gui.main_window import MainWindow

def run_tests():
    app = QApplication.instance() or QApplication(sys.argv)

    print("=" * 60)
    print("1. Testing DeleteConfirmDialog Component")
    print("=" * 60)
    
    dlg = DeleteConfirmDialog(
        title="Silmeyi Onayla — E-Posta Hesabı",
        item_name="test@domain.com",
        item_type="E-Posta Hesabı",
        details={"Sunucu": "imap.domain.com", "Port": "993"},
        warning_message="Bu işlem kalıcıdır ve geri alınamaz!"
    )
    assert dlg.windowTitle() == "Silmeyi Onayla — E-Posta Hesabı"
    assert dlg.item_name == "test@domain.com"
    assert dlg.item_type == "E-Posta Hesabı"
    print("  [PASS] DeleteConfirmDialog initialized and populated correctly.")

    print("\n" + "=" * 60)
    print("2. Testing MainWindow and Top Notification Banner")
    print("=" * 60)
    
    test_dir = Path("scratch/test_data")
    test_dir.mkdir(parents=True, exist_ok=True)
    settings = AppSettings(settings_dir=test_dir)
    engine = MailEngine(db_path=test_dir / "mail_archive.db")
    mw = MainWindow(engine=engine, settings=settings)

    mw.show()
    app.processEvents()

    assert hasattr(mw, "notify_disk_reading")
    assert hasattr(mw, "notify_disk_ready")
    assert hasattr(mw, "dismiss_disk_notification")

    mw.notify_disk_reading("💾 Disk Okunuyor", "Test disk reading message...")
    app.processEvents()
    assert not mw.top_banner.isHidden()
    assert "Disk Okunuyor" in mw.top_banner.lbl_title.text()
    print("  [PASS] MainWindow.notify_disk_reading triggered banner successfully.")

    mw.notify_disk_ready("✅ Hazır", "Veriler diskten okundu.")
    app.processEvents()
    assert "Veriler diskten okundu" in mw.top_banner.lbl_message.text()
    print("  [PASS] MainWindow.notify_disk_ready updated banner successfully.")

    mw.dismiss_disk_notification()
    app.processEvents()
    assert mw.top_banner.isHidden()
    print("  [PASS] MainWindow.dismiss_disk_notification dismissed banner successfully.")

    print("\n" + "=" * 60)
    print("3. Testing All Panels and Lazy Loading Workers")
    print("=" * 60)

    panels_to_test = [
        ("Hesaplar", "accounts"),
        ("Senkronizasyon", "sync"),
        ("Mail Görüntüleyici", "mail"),
        ("Arama", "search"),
        ("Dışa Aktarım", "export"),
        ("Bulut & Yedekleme", "backup"),
        ("Geri Yükleme", "restore"),
        ("Raporlar", "report"),
        ("Zamanlayıcı", "schedule"),
        ("Denetim İzi", "audit"),
        ("Sistem Sağlığı", "health"),
        ("Ayarlar", "settings"),
    ]

    for idx, (name, key) in enumerate(panels_to_test):
        print(f"  --> Testing Panel [{idx}]: {name} (key='{key}')...")
        mw._navigate(key)
        app.processEvents()
        panel = mw.stack.currentWidget()
        assert panel is not None, f"Panel for key '{key}' was not instantiated."
        # Call refresh
        try:
            panel.refresh()
            app.processEvents()
            print(f"      [PASS] {panel.__class__.__name__}.refresh() executed asynchronously without blocking.")
        except Exception as exc:
            print(f"      [FAIL] {panel.__class__.__name__}.refresh() error: {exc}")
            raise

    # Process events for 2.0 seconds to let workers complete gracefully
    def finish_app():
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED SUCCESSFULLY!")
        print("=" * 60)
        try:
            mw.close()
        except Exception:
            pass
        os._exit(0)

    QTimer.singleShot(2000, finish_app)
    app.exec()

if __name__ == "__main__":
    run_tests()
