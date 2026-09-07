"""
schedule_panel.py — Task scheduler panel.
"""

import logging
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt, Slot, Signal, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QTextEdit, QMessageBox, QFormLayout, QLineEdit, QSpinBox,
    QComboBox,
)

from core.mail_engine import MailEngine
from core.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class ScheduleDataLoaderWorker(QThread):
    """Background worker to query scheduled tasks asynchronously."""
    tasks_loaded_signal = Signal(list)
    error_signal = Signal(str)

    def __init__(self, scheduler: TaskScheduler, parent=None):
        super().__init__(parent)
        self.scheduler = scheduler

    def run(self):
        try:
            tasks = self.scheduler.list_tasks()
            self.tasks_loaded_signal.emit(tasks)
        except Exception as e:
            logger.exception("ScheduleDataLoaderWorker error: %s", e)
            self.error_signal.emit(str(e))


class SchedulePanel(QWidget):
    """Task scheduler management panel."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._scheduler = TaskScheduler()
        self._worker: Optional[ScheduleDataLoaderWorker] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        header = QLabel("Zamanlanmış Görevler (Scheduler)")
        header.setProperty("heading", True)
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #1e3a8a;")
        layout.addWidget(header)

        sub = QLabel("APScheduler tabanlı periyodik senkronizasyon ve yedekleme görev yöneticisi.")
        sub.setProperty("subheading", True)
        sub.setStyleSheet("font-size: 12px; color: #64748b;")
        layout.addWidget(sub)

        # Controls
        ctrl_box = QGroupBox("Zamanlayıcı Kontrolleri")
        ctrl_layout = QHBoxLayout(ctrl_box)

        self.btn_start = QPushButton("▶ Zamanlayıcıyı Başlat")
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #16a34a;
                color: #ffffff;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #15803d; }
        """)
        ctrl_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹ Durdur")
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background-color: #ef4444;
                color: #ffffff;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #dc2626; }
        """)
        ctrl_layout.addWidget(self.btn_stop)

        self.btn_refresh = QPushButton("🔄 Görevleri Yenile")
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #e2e8f0; }
        """)
        ctrl_layout.addWidget(self.btn_refresh)

        ctrl_layout.addStretch()
        self.label_status = QLabel("Durum: Durduruldu")
        self.label_status.setStyleSheet("font-weight: 600; color: #64748b;")
        ctrl_layout.addWidget(self.label_status)

        layout.addWidget(ctrl_box)

        # Tasks table
        table_box = QGroupBox("Zamanlanmış Görev Listesi")
        table_layout = QVBoxLayout(table_box)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Görev ID", "Tür", "Zamanlama", "Hedef Fonksiyon"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        table_layout.addWidget(self.table)

        layout.addWidget(table_box, stretch=1)

        # Log
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(150)
        self.log_output.setPlaceholderText("Zamanlayıcı işlem günlüğü...")
        layout.addWidget(self.log_output)

        # Connections
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_refresh.clicked.connect(self.refresh)

    @Slot()
    def _start(self):
        try:
            self._scheduler.start()
            self.label_status.setText("Durum: ✅ Çalışıyor")
            self.label_status.setStyleSheet("font-weight: 700; color: #16a34a;")
            self.log_output.append("Zamanlayıcı arka planda başlatıldı.")
        except Exception as exc:
            QMessageBox.critical(self, "Hata", str(exc))

    @Slot()
    def _stop(self):
        try:
            self._scheduler.stop()
            self.label_status.setText("Durum: ⏹ Durduruldu")
            self.label_status.setStyleSheet("font-weight: 700; color: #dc2626;")
            self.log_output.append("Zamanlayıcı durduruldu.")
        except Exception as exc:
            QMessageBox.critical(self, "Hata", str(exc))

    def refresh(self):
        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_reading"):
            parent_mw.notify_disk_reading("💾 Disk Okunuyor", "Zamanlanmış görevler ve kuyruk taranıyor...")

        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait()

        self._worker = ScheduleDataLoaderWorker(self._scheduler, parent=self)
        self._worker.tasks_loaded_signal.connect(self._on_tasks_loaded)
        self._worker.error_signal.connect(self._on_tasks_error)
        self._worker.start()

    @Slot(list)
    def _on_tasks_loaded(self, tasks: list):
        self.table.setRowCount(len(tasks))
        for i, t in enumerate(tasks):
            self.table.setItem(i, 0, QTableWidgetItem(t.get("id", "")))
            self.table.setItem(i, 1, QTableWidgetItem(t.get("type", "")))
            sched = t.get("cron") or f"Her {t.get('hours', 0)} saat {t.get('minutes', 0)} dk"
            self.table.setItem(i, 2, QTableWidgetItem(sched))
            self.table.setItem(i, 3, QTableWidgetItem(t.get("func_name", "")))
        self.table.resizeColumnsToContents()

        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_ready"):
            parent_mw.notify_disk_ready(f"{len(tasks)} görev listelendi.")

    @Slot(str)
    def _on_tasks_error(self, err_msg: str):
        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_ready"):
            parent_mw.notify_disk_ready("Görevler yüklenemedi.")
        logger.error("SchedulePanel refresh error: %s", err_msg)

