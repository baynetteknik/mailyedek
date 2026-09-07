"""
test_workers_live_execution.py
Verify ServerProfileTestWorker and AccountConnectionTestWorker execute asynchronously and emit finished signal.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop
from core.settings import AppSettings
from core.mail_engine import MailEngine
from gui.dialogs.account_dialog import ServerProfileTestWorker, AccountConnectionTestWorker

def main():
    app = QApplication.instance() or QApplication(sys.argv)
    settings = AppSettings()
    engine = MailEngine(settings=settings)

    print("--- 1. Testing ServerProfileTestWorker (Cenuta Profile ID 49) ---")
    worker = ServerProfileTestWorker(engine, 35, 49, "Cenuta Mail")
    loop = QEventLoop()
    res = {}

    def on_finished(prof_id, prof_name, ok, msg):
        res["prof_id"] = prof_id
        res["prof_name"] = prof_name
        res["ok"] = ok
        res["msg"] = msg
        loop.quit()

    worker.finished.connect(on_finished)
    worker.start()
    loop.exec()

    print(f"Worker Finished Signal Received: ok={res.get('ok')}, msg={res.get('msg')}")
    assert res.get("ok") is True

    print("\n--- 2. Testing AccountConnectionTestWorker (Invalid credentials) ---")
    worker2 = AccountConnectionTestWorker("srv10.cenuta.email", 993, True, "muhasebe@ozmedmedikal.com.tr", "YanlisSifre123")
    loop2 = QEventLoop()
    res2 = {}

    def on_finished2(ok, msg):
        res2["ok"] = ok
        res2["msg"] = msg
        loop2.quit()

    worker2.finished.connect(on_finished2)
    worker2.start()
    loop2.exec()

    print(f"Worker2 Finished Signal Received: ok={res2.get('ok')}, msg={res2.get('msg')}")
    assert res2.get("ok") is False
    assert "Kimlik Doğrulama Hatası" in res2.get("msg") or "Authentication" in res2.get("msg") or "geçersiz" in res2.get("msg")

    print("\nAll live worker signal and error diagnostic tests passed with 100% success!")

if __name__ == "__main__":
    main()
