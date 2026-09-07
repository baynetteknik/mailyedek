"""
audit_panel.py — Audit trail viewer with hash chain verification.
"""

import logging
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt, Slot, Signal, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QTextEdit, QMessageBox,
)

from core.mail_engine import MailEngine

logger = logging.getLogger(__name__)


class AuditDataLoaderWorker(QThread):
    """Background worker to query audit log entries and verify SHA-256 chain."""
    data_loaded_signal = Signal(list, bool)  # entries, is_chain_valid
    error_signal = Signal(str)

    def __init__(self, engine: MailEngine, limit: int = 200, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.limit = limit

    def run(self):
        try:
            entries = self.engine.get_audit_log(limit=self.limit)
            is_valid = False
            if entries:
                is_valid = self.engine.verify_audit_chain()
            self.data_loaded_signal.emit(entries, is_valid)
        except Exception as e:
            logger.exception("AuditDataLoaderWorker error: %s", e)
            self.error_signal.emit(str(e))


class AuditPanel(QWidget):
    """Audit trail viewer panel."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._entries: List[Dict[str, Any]] = []
        self._worker: Optional[AuditDataLoaderWorker] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        header = QLabel("Denetim Günlüğü (Audit Trail)")
        header.setProperty("heading", True)
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #1e3a8a;")
        layout.addWidget(header)

        sub = QLabel("Değiştirilemez, ekleme-tabanlı denetim günlüğü ve SHA-256 kriptografik doğrulama zinciri.")
        sub.setProperty("subheading", True)
        sub.setStyleSheet("font-size: 12px; color: #64748b;")
        layout.addWidget(sub)

        # Controls
        ctrl_box = QGroupBox()
        ctrl_layout = QHBoxLayout(ctrl_box)
        ctrl_layout.setContentsMargins(12, 8, 12, 8)

        self.label_chain = QLabel("Zincir Durumu: Bilinmiyor")
        self.label_chain.setStyleSheet("font-weight: 600; font-size: 13px; color: #334155;")
        ctrl_layout.addWidget(self.label_chain)

        ctrl_layout.addStretch()

        self.btn_verify = QPushButton("🔗 Zinciri Doğrula")
        self.btn_verify.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        ctrl_layout.addWidget(self.btn_verify)

        self.btn_refresh = QPushButton("🔄 Yenile")
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

        layout.addWidget(ctrl_box)

        # Table
        table_box = QGroupBox("Denetim Kayıtları")
        table_layout = QVBoxLayout(table_box)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "ID", "Zaman", "İşlem", "Hesap ID", "Mail ID", "Detaylar"
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
        self.preview.setPlaceholderText("Ayrıntıları görmek için bir satır seçin...")
        layout.addWidget(self.preview)

        # Connections
        self.btn_verify.clicked.connect(self.refresh)
        self.btn_refresh.clicked.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._show_details)

    @Slot()
    def _show_details(self):
        row = self.table.currentRow()
        if row < 0 or not self._entries or row >= len(self._entries):
            self.preview.clear()
            return
        e = self._entries[row]
        self.preview.setPlainText(
            f"İşlem:         {e.get('action', '')}\n"
            f"Zaman:         {e.get('timestamp', '')}\n"
            f"Hesap ID:      {e.get('account_id', '')}\n"
            f"Mail ID:       {e.get('mail_id', '')}\n"
            f"Detay:         {e.get('details', '')}\n"
            f"Önceki Hash:   {(e.get('previous_hash') or '')[:20]}...\n"
            f"Mevcut Hash:   {(e.get('current_hash') or '')[:20]}..."
        )

    def refresh(self):
        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_reading"):
            parent_mw.notify_disk_reading("💾 Disk Okunuyor", "Denetim günlüğü (Audit Trail) ve SHA-256 zinciri taranıyor...")

        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait()

        self._worker = AuditDataLoaderWorker(self.engine, limit=200, parent=self)
        self._worker.data_loaded_signal.connect(self._on_audit_loaded)
        self._worker.error_signal.connect(self._on_audit_error)
        self._worker.start()

    @Slot(list, bool)
    def _on_audit_loaded(self, entries: list, is_valid: bool):
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

        if entries:
            if is_valid:
                self.label_chain.setText("Zincir Durumu: ✅ BÜTÜNLÜK DOĞRULANDI (SHA-256)")
                self.label_chain.setStyleSheet("font-weight: 700; color: #16a34a;")
            else:
                self.label_chain.setText("Zincir Durumu: ❌ BOZUK — Bütünlük ihlali tespit edildi!")
                self.label_chain.setStyleSheet("font-weight: 700; color: #dc2626;")
        else:
            self.label_chain.setText("Zincir Durumu: Kayıt yok")
            self.label_chain.setStyleSheet("font-weight: 600; color: #64748b;")

        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_ready"):
            parent_mw.notify_disk_ready(f"{len(entries)} denetim kaydı yüklendi.")

    @Slot(str)
    def _on_audit_error(self, err_msg: str):
        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_ready"):
            parent_mw.notify_disk_ready("Denetim günlüğü okunamadı.")
        QMessageBox.critical(self, "Hata", f"Denetim günlüğü yüklenirken hata oluştu:\n{err_msg}")

