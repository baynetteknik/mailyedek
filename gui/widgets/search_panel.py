"""
search_panel.py — Full-text search panel using FTS5.
"""

import logging
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QGroupBox, QTextEdit, QMessageBox,
)

from core.mail_engine import MailEngine

logger = logging.getLogger(__name__)


class SearchPanel(QWidget):
    """Full-text search panel."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        header = QLabel("Full-Text Search")
        header.setProperty("heading", True)
        layout.addWidget(header)

        sub = QLabel("Search across all archived emails by subject, sender, "
                     "recipients, and content using SQLite FTS5.")
        sub.setProperty("subheading", True)
        layout.addWidget(sub)

        # Search bar
        search_box = QGroupBox()
        search_layout = QHBoxLayout(search_box)
        search_layout.setContentsMargins(12, 8, 12, 8)

        self.input_query = QLineEdit()
        self.input_query.setPlaceholderText("Search emails... (e.g. invoice, report@company.com, 'project alpha')")
        self.input_query.setMinimumHeight(36)
        self.input_query.setStyleSheet("font-size: 14px;")
        search_layout.addWidget(self.input_query, stretch=1)

        self.btn_search = QPushButton("🔍 Search")
        self.btn_search.setProperty("success", True)
        self.btn_search.setMinimumHeight(36)
        search_layout.addWidget(self.btn_search)

        self.btn_rebuild = QPushButton("Rebuild Index")
        self.btn_rebuild.setProperty("outline", True)
        self.btn_rebuild.setProperty("small", True)
        search_layout.addWidget(self.btn_rebuild)

        layout.addWidget(search_box)

        # Results
        result_box = QGroupBox("Search Results")
        result_layout = QVBoxLayout(result_box)

        self.label_count = QLabel("0 results")
        self.label_count.setProperty("status", True)
        result_layout.addWidget(self.label_count)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "ID", "Date", "From", "To", "Subject", "Folder", "Flags"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        result_layout.addWidget(self.table)

        # Preview area
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(180)
        self.preview.setPlaceholderText("Click a row to preview the email...")
        result_layout.addWidget(self.preview)

        layout.addWidget(result_box, stretch=1)

        # Connections
        self.btn_search.clicked.connect(self._search)
        self.btn_rebuild.clicked.connect(self._rebuild_index)
        self.input_query.returnPressed.connect(self._search)
        self.table.itemSelectionChanged.connect(self._show_preview)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @Slot()
    def _search(self):
        query = self.input_query.text().strip()
        if not query:
            return

        try:
            results = self.engine.search(query, limit=200)
            self.label_count.setText(f"{len(results)} results")
            self._results = results
            self.table.setRowCount(len(results))

            for i, r in enumerate(results):
                self.table.setItem(i, 0, QTableWidgetItem(str(r.get("id", ""))))
                date_val = (r.get("date") or "")[:19]
                self.table.setItem(i, 1, QTableWidgetItem(date_val))
                self.table.setItem(i, 2, QTableWidgetItem((r.get("sender") or "")[:40]))
                self.table.setItem(i, 3, QTableWidgetItem((r.get("recipients") or "")[:40]))
                self.table.setItem(i, 4, QTableWidgetItem((r.get("subject") or "")[:60]))
                self.table.setItem(i, 5, QTableWidgetItem(r.get("folder", "")))
                self.table.setItem(i, 6, QTableWidgetItem((r.get("flags") or "")[:20]))

            self.table.resizeColumnsToContents()
            if results:
                self.table.selectRow(0)

        except Exception as exc:
            QMessageBox.critical(self, "Search Error", str(exc))

    @Slot()
    def _rebuild_index(self):
        try:
            self.engine.db.rebuild_fts_index()
            QMessageBox.information(self, "Success", "FTS index rebuilt.")
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    @Slot()
    def _show_preview(self):
        row = self.table.currentRow()
        if row < 0 or not hasattr(self, "_results") or row >= len(self._results):
            self.preview.clear()
            return

        r = self._results[row]
        preview = (
            f"From:    {r.get('sender', '')}\n"
            f"To:      {r.get('recipients', '')}\n"
            f"CC:      {r.get('cc', '')}\n"
            f"Date:    {r.get('date', '')}\n"
            f"Subject: {r.get('subject', '')}\n"
            f"Folder:  {r.get('folder', '')}\n"
            f"Size:    {r.get('size_bytes', 0)} bytes\n"
            f"Flags:   {r.get('flags', '')}\n"
            f"Hash:    {(r.get('sha256_hash') or '')[:16]}...\n"
        )
        self.preview.setPlainText(preview)

    def refresh(self):
        pass
