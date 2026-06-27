"""
schedule_panel.py — Task scheduler panel.
"""

import logging
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QTextEdit, QMessageBox, QFormLayout, QLineEdit, QSpinBox,
    QComboBox,
)

from core.mail_engine import MailEngine
from core.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class SchedulePanel(QWidget):
    """Task scheduler management panel."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._scheduler = TaskScheduler()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        header = QLabel("Task Scheduler")
        header.setProperty("heading", True)
        layout.addWidget(header)

        sub = QLabel("Schedule periodic sync and backup tasks using APScheduler. "
                     "Configure cron expressions or interval-based triggers.")
        sub.setProperty("subheading", True)
        layout.addWidget(sub)

        # Controls
        ctrl_box = QGroupBox("Scheduler Controls")
        ctrl_layout = QHBoxLayout(ctrl_box)

        self.btn_start = QPushButton("▶ Start Scheduler")
        self.btn_start.setProperty("success", True)
        ctrl_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹ Stop Scheduler")
        self.btn_stop.setProperty("danger", True)
        ctrl_layout.addWidget(self.btn_stop)

        self.btn_refresh = QPushButton("🔄 Refresh Tasks")
        self.btn_refresh.setProperty("outline", True)
        ctrl_layout.addWidget(self.btn_refresh)

        ctrl_layout.addStretch()
        self.label_status = QLabel("Status: Stopped")
        self.label_status.setStyleSheet("font-weight: 600;")
        ctrl_layout.addWidget(self.label_status)

        layout.addWidget(ctrl_box)

        # Tasks table
        table_box = QGroupBox("Scheduled Tasks")
        table_layout = QVBoxLayout(table_box)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Task ID", "Type", "Schedule", "Function"])
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
        self.log_output.setPlaceholderText("Scheduler log...")
        layout.addWidget(self.log_output)

        # Connections
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_refresh.clicked.connect(self.refresh)

    @Slot()
    def _start(self):
        try:
            self._scheduler.start()
            self.label_status.setText("Status: ✅ Running")
            self.label_status.setStyleSheet("font-weight: 600; color: #2d6a4f;")
            self.log_output.append("Scheduler started in background.")
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    @Slot()
    def _stop(self):
        try:
            self._scheduler.stop()
            self.label_status.setText("Status: ⏹ Stopped")
            self.label_status.setStyleSheet("font-weight: 600; color: #e63946;")
            self.log_output.append("Scheduler stopped.")
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def refresh(self):
        try:
            tasks = self._scheduler.list_tasks()
            self.table.setRowCount(len(tasks))
            for i, t in enumerate(tasks):
                self.table.setItem(i, 0, QTableWidgetItem(t.get("id", "")))
                self.table.setItem(i, 1, QTableWidgetItem(t.get("type", "")))
                sched = t.get("cron") or f"Every {t.get('hours', 0)}h {t.get('minutes', 0)}m"
                self.table.setItem(i, 2, QTableWidgetItem(sched))
                self.table.setItem(i, 3, QTableWidgetItem(t.get("func_name", "")))
            self.table.resizeColumnsToContents()
        except Exception as exc:
            logger.error("Refresh error: %s", exc)
