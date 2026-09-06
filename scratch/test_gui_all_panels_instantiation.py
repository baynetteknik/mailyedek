"""
test_gui_all_panels_instantiation.py — Verify all panels in MainWindow can be instantiated and navigated to without blocking.
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


def test_main_window_all_panels():
    import traceback
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        test_db = Path("scratch/test_data/mail_archive.db")
        test_db.parent.mkdir(parents=True, exist_ok=True)
        engine = MailEngine(db_path=test_db)
        settings = AppSettings(settings_dir=Path("scratch/test_data"))

        window = MainWindow(engine=engine, settings=settings)
        print("MainWindow initialized.")

        panels_to_test = [
            "mail", "accounts", "sync", "export", "backup", "restore",
            "search", "audit", "schedule", "report", "health", "settings"
        ]

        for p in panels_to_test:
            t0 = time.time()
            window._navigate(p)
            app.processEvents()
            elapsed_ms = (time.time() - t0) * 1000
            active_widget = window.stack.currentWidget()
            print(f"Panel '{p}' loaded in {elapsed_ms:.1f} ms. Active widget: {type(active_widget).__name__}")
            assert active_widget is not None, f"Panel {p} returned None widget"

        print("\n🎉 ALL PANELS INSTANTIATED AND NAVIGATED TO SUCCESSFULLY! 🎉")
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    test_main_window_all_panels()
