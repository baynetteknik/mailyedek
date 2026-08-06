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
    
    # Check if data path fell back because it was not accessible (e.g., missing or renamed folder)
    raw_path = settings._data.get("data_path")
    if raw_path:
        raw_path_obj = Path(raw_path)
        path_missing = False
        try:
            path_missing = not raw_path_obj.exists()
        except OSError:
            path_missing = True

        if path_missing:
            from PySide6.QtWidgets import QFileDialog
            reply = QMessageBox.warning(
                None,
                "Veri Dizini Bulunamadı",
                f"Yapılandırılmış veri dizini ({raw_path}) bulunamadı veya taşındı/yeniden adlandırıldı.\n\n"
                "Lütfen bu veri dizininin yeni yerini seçin.",
                QMessageBox.Ok | QMessageBox.Cancel
            )
            if reply == QMessageBox.Ok:
                parent_dir = ""
                try:
                    if raw_path_obj.parent.exists():
                        parent_dir = str(raw_path_obj.parent)
                except OSError:
                    pass
                if not parent_dir:
                    parent_dir = str(Path.cwd())

                folder = QFileDialog.getExistingDirectory(
                    None, "Yeni Veri Dizinini (Ana Depolama Alanı) Seçin", parent_dir
                )
                if folder:
                    new_path = Path(folder).resolve()
                    settings.set_data_path(new_path)

                    # Update storage locations paths if they point to or are inside the old path
                    locs = settings.get("storage_locations", [])
                    updated_locs = []
                    for loc in locs:
                        loc_path = loc.get("path", "")
                        if loc_path:
                            try:
                                if Path(loc_path).resolve() == raw_path_obj.resolve():
                                    loc["path"] = str(new_path)
                                elif str(Path(loc_path).resolve()).startswith(str(raw_path_obj.resolve())):
                                    rel = Path(loc_path).resolve().relative_to(raw_path_obj.resolve())
                                    loc["path"] = str(new_path / rel)
                            except Exception:
                                pass
                        updated_locs.append(loc)
                    settings.set("storage_locations", updated_locs)
                    settings.save()

                    QMessageBox.information(
                        None,
                        "Veri Dizini Güncellendi",
                        f"Veri dizini '{new_path}' olarak güncellendi.\nUygulama şimdi yeniden başlatılacaktır.",
                        QMessageBox.Ok
                    )
                    # Restart app
                    import subprocess
                    subprocess.Popen([sys.executable] + sys.argv)
                    sys.exit(0)
                else:
                    sys.exit(0)
            else:
                sys.exit(0)

    actual_path = settings.data_path()

    db_path = settings.db_path()
    key_file = settings.key_file_path()
    logger.info("Data path: %s", actual_path)

    # Create and show main window
    window = MainWindow(db_path=db_path, key_file=key_file, settings=settings)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
