"""
health_panel.py — System health check panel.
"""

import logging
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt, Slot, Signal, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QGroupBox, QTextEdit, QMessageBox,
)

from core.mail_engine import MailEngine
from core.health_check import HealthChecker

logger = logging.getLogger(__name__)


class HealthCheckWorker(QThread):
    """Background worker to run comprehensive system diagnostics without UI freeze."""
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, checker: HealthChecker, parent=None):
        super().__init__(parent)
        self.checker = checker

    def run(self):
        try:
            res = self.checker.check_all()
            self.finished_signal.emit(res)
        except Exception as e:
            logger.exception("HealthCheckWorker error: %s", e)
            self.error_signal.emit(str(e))


class HealthPanel(QWidget):
    """System health monitoring panel."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._checker = HealthChecker(
            engine.db, engine.crypto,
            engine.accounts, engine.audit,
        )
        self._worker: Optional[HealthCheckWorker] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        header = QLabel("Sistem Sağlığı & Tanılama (Health Check)")
        header.setProperty("heading", True)
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #1e3a8a;")
        layout.addWidget(header)

        sub = QLabel("Kapsamlı sistem kontrolleri: disk alanı, veritabanı erişimi, "
                     "şifreleme anahtarı, denetim zinciri ve hesap durumları.")
        sub.setProperty("subheading", True)
        sub.setStyleSheet("font-size: 12px; color: #64748b;")
        layout.addWidget(sub)

        # Controls
        ctrl_box = QGroupBox()
        ctrl_layout = QHBoxLayout(ctrl_box)
        ctrl_layout.setContentsMargins(12, 8, 12, 8)

        self.label_overall = QLabel("Genel Durum: Bilinmiyor")
        self.label_overall.setStyleSheet("font-size: 15px; font-weight: 700; color: #334155;")
        ctrl_layout.addWidget(self.label_overall)
        ctrl_layout.addStretch()

        self.btn_run = QPushButton("🔄 Sağlık Taramasını Başlat")
        self.btn_run.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-weight: bold;
                padding: 6px 16px;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        ctrl_layout.addWidget(self.btn_run)

        layout.addWidget(ctrl_box)

        # Results table
        table_box = QGroupBox("Tanılama Sonuçları")
        table_layout = QVBoxLayout(table_box)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Kontrol", "Durum", "Süre", "Mesaj"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        table_layout.addWidget(self.table)

        layout.addWidget(table_box, stretch=1)

        # Details
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(180)
        self.details.setPlaceholderText("Tam tanılama ayrıntıları burada listelenir...")
        layout.addWidget(self.details)

        self.btn_run.clicked.connect(self._run_checks)

    @Slot()
    def _run_checks(self):
        self.btn_run.setEnabled(False)
        self.btn_run.setText("⏳ Taranıyor...")

        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_reading"):
            parent_mw.notify_disk_reading("💾 Disk Okunuyor", "Sistem sağlığı, disk alanı ve veritabanı taranıyor...")

        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait()

        self._worker = HealthCheckWorker(self._checker, parent=self)
        self._worker.finished_signal.connect(self._on_checks_finished)
        self._worker.error_signal.connect(self._on_checks_error)
        self._worker.start()

    @Slot(dict)
    def _on_checks_finished(self, result: dict):
        self.btn_run.setEnabled(True)
        self.btn_run.setText("🔄 Sağlık Taramasını Başlat")

        checks = result.get("checks", [])
        overall = result.get("status", "unknown")

        status_map = {"ok": "✅ Sağlıklı", "warning": "⚠️ Uyarı Var", "error": "❌ Kritik Hata"}
        color_map = {"ok": "#16a34a", "warning": "#d97706", "error": "#dc2626"}
        self.label_overall.setText(f"Genel Durum: {status_map.get(overall, overall)}")
        self.label_overall.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {color_map.get(overall, '#333')}")

        self.table.setRowCount(len(checks))
        status_icons = {"ok": "✅", "warning": "⚠️", "error": "❌"}
        for i, c in enumerate(checks):
            self.table.setItem(i, 0, QTableWidgetItem(c.get("name", "")))
            icon = status_icons.get(c.get("status", ""), "?")
            self.table.setItem(i, 1, QTableWidgetItem(f"{icon} {c.get('status', '')}"))
            self.table.setItem(i, 2, QTableWidgetItem(f"{c.get('duration_ms', 0):.1f}ms"))
            self.table.setItem(i, 3, QTableWidgetItem(c.get("message", "")[:80]))
        self.table.resizeColumnsToContents()

        details_text = f"Sistem Tanılaması — {result.get('timestamp', '')}\n{'='*50}\n\n"
        for c in checks:
            details_text += f"--- {c['name']} ---\n"
            details_text += f"Durum: {c['status']}\n"
            details_text += f"Süre:  {c['duration_ms']:.1f}ms\n"
            details_text += f"Mesaj: {c['message']}\n"
            if c.get("details"):
                for k, v in c["details"].items():
                    details_text += f"  {k}: {v}\n"
            details_text += "\n"
        self.details.setPlainText(details_text)

        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_ready"):
            parent_mw.notify_disk_ready("Sistem sağlık taraması tamamlandı.")

    @Slot(str)
    def _on_checks_error(self, err_msg: str):
        self.btn_run.setEnabled(True)
        self.btn_run.setText("🔄 Sağlık Taramasını Başlat")
        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_ready"):
            parent_mw.notify_disk_ready("Sağlık taraması başarısız oldu.")
        QMessageBox.critical(self, "Sağlık Taraması Hatası", err_msg)

    def refresh(self):
        self._run_checks()

