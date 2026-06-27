"""
health_panel.py — System health check panel.
"""

import logging
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QGroupBox, QTextEdit, QMessageBox,
)

from core.mail_engine import MailEngine
from core.health_check import HealthChecker

logger = logging.getLogger(__name__)


class HealthPanel(QWidget):
    """System health monitoring panel."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._checker = HealthChecker(
            engine.db, engine.crypto,
            engine.accounts, engine.audit,
        )
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        header = QLabel("System Health")
        header.setProperty("heading", True)
        layout.addWidget(header)

        sub = QLabel("Comprehensive system diagnostics: disk space, database, "
                     "encryption key, audit chain, and account status.")
        sub.setProperty("subheading", True)
        layout.addWidget(sub)

        # Controls
        ctrl_box = QGroupBox()
        ctrl_layout = QHBoxLayout(ctrl_box)
        ctrl_layout.setContentsMargins(12, 8, 12, 8)

        self.label_overall = QLabel("Overall Status: Unknown")
        self.label_overall.setStyleSheet("font-size: 16px; font-weight: 700;")
        ctrl_layout.addWidget(self.label_overall)
        ctrl_layout.addStretch()

        self.btn_run = QPushButton("🔄 Run Health Check")
        self.btn_run.setProperty("success", True)
        ctrl_layout.addWidget(self.btn_run)

        layout.addWidget(ctrl_box)

        # Results table
        table_box = QGroupBox("Health Check Results")
        table_layout = QVBoxLayout(table_box)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Check", "Status", "Duration", "Message"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        table_layout.addWidget(self.table)

        layout.addWidget(table_box, stretch=1)

        # Details
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(180)
        self.details.setPlaceholderText("Full diagnostic details appear here...")
        layout.addWidget(self.details)

        self.btn_run.clicked.connect(self._run_checks)

    @Slot()
    def _run_checks(self):
        self.btn_run.setEnabled(False)
        self.btn_run.setText("Running...")

        try:
            result = self._checker.check_all()
            checks = result.get("checks", [])
            overall = result.get("status", "unknown")

            # Overall status
            status_map = {"ok": "✅ Healthy", "warning": "⚠️ Warning", "error": "❌ Critical"}
            color_map = {"ok": "#2d6a4f", "warning": "#e67e22", "error": "#e63946"}
            self.label_overall.setText(f"Overall Status: {status_map.get(overall, overall)}")
            self.label_overall.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {color_map.get(overall, '#333')}")

            # Table
            self.table.setRowCount(len(checks))
            status_icons = {"ok": "✅", "warning": "⚠️", "error": "❌"}
            for i, c in enumerate(checks):
                self.table.setItem(i, 0, QTableWidgetItem(c.get("name", "")))
                icon = status_icons.get(c.get("status", ""), "?")
                self.table.setItem(i, 1, QTableWidgetItem(f"{icon} {c.get('status', '')}"))
                self.table.setItem(i, 2, QTableWidgetItem(f"{c.get('duration_ms', 0):.1f}ms"))
                self.table.setItem(i, 3, QTableWidgetItem(c.get("message", "")[:80]))
            self.table.resizeColumnsToContents()

            # Details
            details_text = f"Health Check — {result.get('timestamp', '')}\n{'='*50}\n\n"
            for c in checks:
                details_text += f"--- {c['name']} ---\n"
                details_text += f"Status: {c['status']}\n"
                details_text += f"Time:   {c['duration_ms']:.1f}ms\n"
                details_text += f"Msg:    {c['message']}\n"
                if c.get("details"):
                    for k, v in c["details"].items():
                        details_text += f"  {k}: {v}\n"
                details_text += "\n"
            self.details.setPlainText(details_text)

        except Exception as exc:
            QMessageBox.critical(self, "Health Check Error", str(exc))
        finally:
            self.btn_run.setEnabled(True)
            self.btn_run.setText("🔄 Run Health Check")

    def refresh(self):
        pass
