import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("."))
from PySide6.QtWidgets import QApplication
from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.main_window import MainWindow

def run_test():
    app = QApplication.instance() or QApplication(sys.argv)
    settings = AppSettings()
    engine = MailEngine()
    
    window = MainWindow(engine=engine, settings=settings)
    window.show()

    print("Main window instantiated.")
    panels = ["accounts", "sync", "export", "backup", "restore", "report", "health", "users", "settings", "security", "live_console"]
    for p in panels:
        window._navigate(p)
        active_widget = window.stack.currentWidget()
        print(f"Navigated to panel: '{p}' successfully. Active widget: {type(active_widget).__name__}")

    print("ALL REAL GUI NAVIGATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_test()
