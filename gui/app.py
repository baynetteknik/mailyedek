#!/usr/bin/env python3
"""
app.py — GUI entry point for the Mail Archive System.

Usage:
    python -m gui.app
    python gui/app.py

Uses PySide6 (Qt6) for a professional desktop interface.
LGPL licensed — free for commercial and personal use.
"""

import sys
import logging
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFont

from gui.main_window import MainWindow
from core.settings import AppSettings

PROJECT_ROOT = Path(__file__).parent.parent
LOG_DIR = PROJECT_ROOT / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(str(LOG_DIR / "gui_app.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("gui")


def main():
    """Launch the GUI application."""
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "mailarchive.system.1.0"
        )
    except Exception:
        pass

    app = QApplication(sys.argv)

    # Global font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # High-DPI support
    app.setStyle("Fusion")

    # Global stylesheet
    style_path = PROJECT_ROOT / "gui" / "resources" / "style.qss"
    if style_path.exists():
        try:
            with open(style_path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
        except Exception as exc:
            logger.warning("Could not load style.qss: %s", exc)

    # Load settings for custom data path
    settings = AppSettings()
    actual_path = settings.data_path()
    db_path = settings.db_path()
    key_file = settings.key_file_path()
    logger.info("Starting Mail Archive system with data path: %s", actual_path)

    # Create main window
    window = MainWindow(db_path=db_path, key_file=key_file, settings=settings)

    # Prompt user authentication at startup
    if not window.prompt_login():
        logger.info("Login cancelled by user, closing application.")
        sys.exit(0)

    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
