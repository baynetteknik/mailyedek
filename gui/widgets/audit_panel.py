"""
audit_panel.py — Audit trail viewer with hash chain verification.
"""

import logging
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QTextEdit, QMessageBox,
)

from core.mail_engine import MailEngine

logger = logging.getLogger(__name__)


class AuditPanel(QWidget):
    """Audit trail viewer panel."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        header = QLabel("Audit Trail")
        header.setProperty("heading", True)
        layout.addWidget(header)

        sub = QLabel("Immutable, append-only audit log with SHA-256 hash chaining. "
                     "Every operation is permanently recorded.")
        sub.setProperty("subheading", True)
        layout.addWidget(sub)

        # Controls
        ctrl_box = QGroupBox()
        ctrl_layout = QHBoxLayout(ctrl_box)
        ctrl_layout.setContentsMargins(12, 8, 12, 8)

        self.label_chain = QLabel("Chain Status: Unknown")
        self.label_chain.setStyleSheet("font-weight: 600; font-size: 13px;")
        ctrl_layout.addWidget(self.label_chain)

        ctrl_layout.addStretch()

        self.btn_verify = QPushButton("🔗 Verify Chain")
        self.btn_verify.setProperty("outline", True)
        ctrl_layout.addWidget(self.btn_verify)

        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setProperty("outline", True)
        ctrl_layout.addWidget(self.btn_refresh)

        layout.addWidget(ctrl_box)

        # Table
        table_box = QGroupBox("Audit Entries")
        table_layout = QVBoxLayout(table_box)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "ID", "Timestamp", "Action", "Account", "Mail", "Details"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        table_layout.addWidget(self.table)

        layout.addWidget(table_box, stretch=1)

        # Preview
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(120)
        self.preview.setPlaceholderText("Select an entry to see full details...")
        layout.addWidget(self.preview)

        # Connections
        self.btn_verify.clicked.connect(self._verify_chain)
        self.btn_refresh.clicked.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._show_details)

    @Slot()
    def _verify_chain(self):
        try:
            valid = self.engine.verify_audit_chain()
            if valid:
                self.label_chain.setText("Chain Status: ✅ INTEGRITY VERIFIED")
                self.label_chain.setStyleSheet("font-weight: 600; color: #2d6a4f;")
            else:
                self.label_chain.setText("Chain Status: ❌ BROKEN — Tampering detected!")
                self.label_chain.setStyleSheet("font-weight: 600; color: #e63946;")
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    @Slot()
    def _show_details(self):
        row = self.table.currentRow()
        if row < 0 or not hasattr(self, "_entries") or row >= len(self._entries):
            self.preview.clear()
            return
        e = self._entries[row]
        self.preview.setPlainText(
            f"Action:       {e.get('action', '')}\n"
            f"Timestamp:    {e.get('timestamp', '')}\n"
            f"Account ID:   {e.get('account_id', '')}\n"
            f"Mail ID:      {e.get('mail_id', '')}\n"
            f"Details:      {e.get('details', '')}\n"
            f"Prev Hash:    {(e.get('previous_hash') or '')[:20]}...\n"
            f"Current Hash: {(e.get('current_hash') or '')[:20]}..."
        )

    def refresh(self):
        try:
            entries = self.engine.get_audit_log(limit=200)
            self._entries = entries
            self.table.setRowCount(len(entries))
            for i, e in enumerate(entries):
                self.table.setItem(i, 0, QTableWidgetItem(str(e.get("id", ""))))
                ts = (e.get("timestamp") or "")[:19]
                self.table.setItem(i, 1, QTableWidgetItem(ts))
                self.table.setItem(i, 2, QTableWidgetItem(e.get("action", "")))
                self.table.setItem(i, 3, QTableWidgetItem(str(e.get("account_id", ""))))
                self.table.setItem(i, 4, QTableWidgetItem(str(e.get("mail_id", ""))))
                details = (e.get("details") or "")[:60]
                self.table.setItem(i, 5, QTableWidgetItem(details))
            self.table.resizeColumnsToContents()

            # Auto-verify on refresh
            if entries:
                valid = self.engine.verify_audit_chain()
                if valid:
                    self.label_chain.setText("Chain Status: ✅ INTEGRITY VERIFIED")
                    self.label_chain.setStyleSheet("font-weight: 600; color: #2d6a4f;")
                else:
                    self.label_chain.setText("Chain Status: ❌ BROKEN")
                    self.label_chain.setStyleSheet("font-weight: 600; color: #e63946;")
        except Exception as exc:
            logger.error("Refresh error: %s", exc)
