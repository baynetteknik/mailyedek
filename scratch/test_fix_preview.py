import sys
import os
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.widgets.search_panel import SearchPanel

app = QApplication.instance() or QApplication(sys.argv)
s = AppSettings()
e = MailEngine(s.data_path() / "metadata.db", settings=s)
sp = SearchPanel(e)
sp.resize(1600, 900)
sp.show()

# If we call adjust_positions:
sp.db_grid.filter_bar.adjust_positions()
app.processEvents()

fb = sp.db_grid.filter_bar
print("Filter edits count:", len(fb.line_edits))
for i, ed in fb.line_edits.items():
    print(f"Col {i}: visible={ed.isVisible()}, isHidden={ed.isHidden()}, geom=({ed.x()}, {ed.y()}, {ed.width()}, {ed.height()}), placeholder='{ed.placeholderText()}'")
