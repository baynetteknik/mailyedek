"""
test_thread_lifecycle_backup_restore.py — Verify that rapid navigation and repeated refresh
of BackupPanel and RestorePanel never crash with 'QThread: Destroyed while thread is still running'.
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
from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.main_window import MainWindow


def test_rapid_backup_restore_navigation():
    print("Testing rapid navigation between Backup and Restore panels...")
    app = QApplication.instance() or QApplication(sys.argv)
    test_db = Path("scratch/test_data/mail_archive.db")
    test_db.parent.mkdir(parents=True, exist_ok=True)
    engine = MailEngine(db_path=test_db)
    settings = AppSettings(settings_dir=Path("scratch/test_data"))

    window = MainWindow(engine=engine, settings=settings)

    # Rapidly toggle between backup and restore 10 times in a row
    for i in range(10):
        window._navigate("backup")
        app.processEvents()
        window._navigate("restore")
        app.processEvents()
        window._navigate("backup")
        app.processEvents()

    # Call refresh explicitly multiple times while threads are running
    backup_panel = window._get_or_create_panel("backup")
    restore_panel = window._get_or_create_panel("restore")

    for _ in range(5):
        backup_panel.refresh()
        restore_panel.refresh()
        app.processEvents()

    # Let threads finish
    time.sleep(0.5)
    app.processEvents()

    print("✅ Rapid navigation and concurrent refresh completed with NO thread crashes!")


if __name__ == "__main__":
    test_rapid_backup_restore_navigation()
