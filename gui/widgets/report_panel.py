"""
report_panel.py — Reports panel (JSON & HTML generation).
"""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QTextEdit, QMessageBox, QComboBox, QFileDialog,
)

from core.mail_engine import MailEngine
from core.reporter import ReportGenerator

logger = logging.getLogger(__name__)


class ReportPanel(QWidget):
    """Report generation panel."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._reporter = ReportGenerator()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        header = QLabel("Reports")
        header.setProperty("heading", True)
        layout.addWidget(header)

        sub = QLabel("Generate structured reports in JSON and HTML format. "
                     "Reports are saved to data/reports/")
        sub.setProperty("subheading", True)
        layout.addWidget(sub)

        # Controls
        ctrl_box = QGroupBox("Generate Report")
        ctrl_layout = QHBoxLayout(ctrl_box)

        self.combo_account = QComboBox()
        self.combo_account.setMinimumWidth(250)
        ctrl_layout.addWidget(QLabel("Account:"))
        ctrl_layout.addWidget(self.combo_account)

        self.btn_sync_report = QPushButton("📊 Generate Sync Report")
        ctrl_layout.addWidget(self.btn_sync_report)

        self.btn_stats_report = QPushButton("📈 Database Statistics")
        self.btn_stats_report.setProperty("outline", True)
        ctrl_layout.addWidget(self.btn_stats_report)

        ctrl_layout.addStretch()
        layout.addWidget(ctrl_box)

        # Stats table
        stats_box = QGroupBox("Database Statistics")
        stats_layout = QVBoxLayout(stats_box)

        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(2)
        self.stats_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        self.stats_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.stats_table.verticalHeader().setVisible(False)
        stats_layout.addWidget(self.stats_table)

        layout.addWidget(stats_box, stretch=1)

        # Log
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(120)
        self.log_output.setPlaceholderText("Report generation log...")
        layout.addWidget(self.log_output)

        self.btn_sync_report.clicked.connect(self._gen_sync_report)
        self.btn_stats_report.clicked.connect(self._gen_stats_report)

    @Slot()
    def _gen_sync_report(self):
        acc_data = self.combo_account.currentData()
        if not acc_data:
            QMessageBox.warning(self, "No Account", "Select an account first.")
            return

        try:
            # Run sync first to get data
            report_dict = self.engine.sync_account(acc_data["id"])
            path = self._reporter.generate_sync_report(report_dict, output_format="both")
            self.log_output.append(f"Sync report generated: {path}")
            self.log_output.append(f"  Mails: {report_dict.get('mails_fetched', 0)}, "
                                   f"Errors: {report_dict.get('errors', 0)}")
        except Exception as exc:
            self.log_output.append(f"ERROR: {exc}")

    @Slot()
    def _gen_stats_report(self):
        try:
            stats = self.engine.get_stats()
            self.stats_table.setRowCount(len(stats))
            for i, (k, v) in enumerate(stats.items()):
                self.stats_table.setItem(i, 0, QTableWidgetItem(k.replace("_", " ").title()))
                self.stats_table.setItem(i, 1, QTableWidgetItem(str(v)))
            self.stats_table.resizeColumnsToContents()
            self.log_output.append("Database statistics updated.")
        except Exception as exc:
            self.log_output.append(f"ERROR: {exc}")

    def refresh(self):
        self.combo_account.clear()
        try:
            accounts = self.engine.list_accounts()
            for acc in accounts:
                self.combo_account.addItem(
                    f"{acc['label']} ({acc['email']})", acc
                )
        except Exception as exc:
            logger.error("Refresh error: %s", exc)
