"""
account_panel.py — Account management panel with dialog-based add/edit.
"""

import logging
import threading
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QMessageBox, QGroupBox,
    QFrame, QProgressBar, QDialog,
)

from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.dialogs.account_dialog import AccountDialog

logger = logging.getLogger(__name__)


class AccountPanel(QWidget):
    """Account management with add/edit/deactivate/delete and connection test."""

    def __init__(self, engine: MailEngine, parent=None, settings: AppSettings = None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings or AppSettings()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        # Header
        header = QLabel("Account Management")
        header.setProperty("heading", True)
        layout.addWidget(header)

        sub = QLabel("Manage your IMAP email accounts. "
                     "Passwords are encrypted with AES-256 before storage.")
        sub.setProperty("subheading", True)
        layout.addWidget(sub)

        # Toolbar
        toolbar = QFrame()
        toolbar.setStyleSheet("""
            QFrame { background: #ffffff; border-radius: 8px; padding: 8px; }
        """)
        tool_layout = QHBoxLayout(toolbar)
        tool_layout.setContentsMargins(12, 8, 12, 8)

        self.btn_add = QPushButton("➕  Add Account")
        self.btn_add.setProperty("success", True)
        tool_layout.addWidget(self.btn_add)

        self.btn_edit = QPushButton("✏️  Edit")
        self.btn_edit.setEnabled(False)
        tool_layout.addWidget(self.btn_edit)

        self.btn_toggle_active = QPushButton("⏸  Deactivate")
        self.btn_toggle_active.setEnabled(False)
        self.btn_toggle_active.setProperty("outline", True)
        tool_layout.addWidget(self.btn_toggle_active)

        self.btn_test = QPushButton("🔌  Test Connection")
        self.btn_test.setEnabled(False)
        self.btn_test.setProperty("outline", True)
        tool_layout.addWidget(self.btn_test)

        self.btn_delete = QPushButton("🗑  Delete")
        self.btn_delete.setEnabled(False)
        self.btn_delete.setProperty("danger", True)
        tool_layout.addWidget(self.btn_delete)

        self.btn_clean_start = QPushButton("🗑  Clean Start")
        self.btn_clean_start.setToolTip("Clear all archived emails and attachments but keep configurations")
        self.btn_clean_start.setProperty("danger", True)
        tool_layout.addWidget(self.btn_clean_start)

        tool_layout.addStretch()

        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setProperty("outline", True)
        tool_layout.addWidget(self.btn_refresh)

        layout.addWidget(toolbar)

        # Test progress
        self.test_progress = QProgressBar()
        self.test_progress.setVisible(False)
        self.test_progress.setMaximumHeight(4)
        self.test_progress.setTextVisible(False)
        layout.addWidget(self.test_progress)

        self.test_status = QLabel("")
        self.test_status.setProperty("status", True)
        layout.addWidget(self.test_status)

        # Account table
        table_box = QGroupBox("Configured Accounts")
        table_layout = QVBoxLayout(table_box)

        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "ID", "Label", "Email", "IMAP Host", "Port", "SSL", "Status", "Storage", "Last Updated"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        table_layout.addWidget(self.table)

        layout.addWidget(table_box, stretch=1)

        # Connections
        self.btn_add.clicked.connect(self._add_account)
        self.btn_edit.clicked.connect(self._edit_account)
        self.btn_toggle_active.clicked.connect(self._toggle_active)
        self.btn_test.clicked.connect(self._test_selected)
        self.btn_delete.clicked.connect(self._delete_account)
        self.btn_clean_start.clicked.connect(self._clean_start)
        self.btn_refresh.clicked.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(self._edit_account)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @Slot()
    def _add_account(self):
        dialog = AccountDialog(self.engine, self, settings=self.settings)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    @Slot()
    def _edit_account(self):
        row = self.table.currentRow()
        if row < 0:
            return
        acc_id = int(self.table.item(row, 0).text())
        acc = self.engine.accounts.get(acc_id)
        if not acc:
            QMessageBox.warning(self, "Error", "Account not found.")
            return

        dialog = AccountDialog(self.engine, self, account=acc, settings=self.settings)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    @Slot()
    def _toggle_active(self):
        row = self.table.currentRow()
        if row < 0:
            return
        acc_id = int(self.table.item(row, 0).text())
        acc = self.engine.accounts.get(acc_id)
        if not acc:
            return

        is_active = bool(acc.get("is_active", True))
        new_status = 0 if is_active else 1
        label = acc.get("label", "")

        action = "deactivate" if is_active else "activate"
        reply = QMessageBox.question(
            self, f"{action.title()} Account",
            f"Are you sure you want to {action} '{label}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.engine.accounts.update(acc_id, is_active=new_status)
                self.engine.audit.append(
                    f"account.{'deactivated' if is_active else 'activated'}",
                    account_id=acc_id
                )
                self.refresh()
            except Exception as exc:
                QMessageBox.critical(self, "Error", str(exc))

    @Slot()
    def _test_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        acc_id = int(self.table.item(row, 0).text())
        acc = self.engine.accounts.get(acc_id)
        if not acc:
            return

        self.test_progress.setVisible(True)
        self.test_progress.setRange(0, 0)
        self.test_status.setText(f"⏳ Testing {acc.get('label', '')}...")
        self.test_status.setStyleSheet("color: #4361ee; font-size: 12px;")
        self.btn_test.setEnabled(False)

        def test():
            from infrastructure.imap_client import ImapClient
            try:
                username = self.engine.crypto.decrypt(acc.get("username_enc", ""))
                password = self.engine.crypto.decrypt(acc.get("password_enc", ""))
                client = ImapClient()
                ok = client.connect(
                    acc["imap_host"], acc["imap_port"],
                    bool(acc["use_ssl"]), username, password
                )
                if ok:
                    client.disconnect()
                self.btn_test.setEnabled(True)
                self.test_progress.setVisible(False)
                if ok:
                    self.test_status.setText(f"✅ {acc.get('label', '')}: Connection OK")
                    self.test_status.setStyleSheet("color: #2d6a4f; font-size: 12px; font-weight: 600;")
                else:
                    self.test_status.setText(f"❌ {acc.get('label', '')}: Connection failed")
                    self.test_status.setStyleSheet("color: #e63946; font-size: 12px; font-weight: 600;")
            except Exception as exc:
                self.btn_test.setEnabled(True)
                self.test_progress.setVisible(False)
                self.test_status.setText(f"❌ Error: {exc}")
                self.test_status.setStyleSheet("color: #e63946; font-size: 12px;")

        threading.Thread(target=test, daemon=True).start()

    @Slot()
    def _delete_account(self):
        row = self.table.currentRow()
        if row < 0:
            return
        acc_id = int(self.table.item(row, 0).text())
        acc = self.engine.accounts.get(acc_id)
        if not acc:
            return

        if bool(acc.get("is_active", True)):
            QMessageBox.warning(
                self, "Cannot Delete",
                f"Account '{acc.get('label', '')}' is active.\n"
                "Deactivate it first, then delete."
            )
            return

        label = acc.get("label", "")
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Permanently delete '{label}' (ID: {acc_id})?\n\n"
            "All associated emails, attachments, and sync state will be removed.\n"
            "This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.engine.remove_account(acc_id)
                self.refresh()
            except Exception as exc:
                QMessageBox.critical(self, "Error", f"Failed to delete:\n{exc}")

    @Slot()
    def _clean_start(self):
        reply = QMessageBox.question(
            self, "Temiz Başlangıç (Clean Start)",
            "Tüm arşivlenmiş e-postalar, ek dosyalar ve senkronizasyon geçmişi kalıcı olarak silinecektir.\n"
            "Yapılandırılmış e-posta hesapları korunacaktır.\n"
            "Bu işlem geri alınamaz. Devam etmek istiyor musunuz?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.engine.clear_archive_data()
                QMessageBox.information(
                    self, "Success",
                    "Canlı eşitleme arşivi başarıyla sıfırlandı. Temiz başlangıç hazır."
                )
                self.refresh()
            except Exception as exc:
                QMessageBox.critical(self, "Error", f"Sıfırlama başarısız oldu:\n{exc}")

    @Slot()
    def _on_selection_changed(self):
        has_selection = self.table.currentRow() >= 0
        self.btn_edit.setEnabled(has_selection)
        self.btn_toggle_active.setEnabled(has_selection)
        self.btn_test.setEnabled(has_selection)
        self.btn_delete.setEnabled(has_selection)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self):
        try:
            accounts = self.engine.list_accounts()
            self.table.setRowCount(len(accounts))
            for i, acc in enumerate(accounts):
                self.table.setItem(i, 0, QTableWidgetItem(str(acc["id"])))
                self.table.setItem(i, 1, QTableWidgetItem(acc.get("label", "")))
                self.table.setItem(i, 2, QTableWidgetItem(acc.get("email", "")))
                self.table.setItem(i, 3, QTableWidgetItem(acc.get("imap_host", "")))
                self.table.setItem(i, 4, QTableWidgetItem(str(acc.get("imap_port", ""))))
                self.table.setItem(i, 5, QTableWidgetItem("Yes" if acc.get("use_ssl") else "No"))

                is_active = bool(acc.get("is_active", True))
                status_text = "✅ Active" if is_active else "⏸ Inactive"
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(Qt.darkGreen if is_active else Qt.darkGray)
                self.table.setItem(i, 6, status_item)

                # Storage location
                stor_name = self.settings.account_storage(acc["id"]) or "Default"
                self.table.setItem(i, 7, QTableWidgetItem(stor_name))

                updated = (acc.get("updated_at") or "")[:19]
                self.table.setItem(i, 8, QTableWidgetItem(updated))

            self.table.resizeColumnsToContents()
            # Ensure status and storage columns are visible
            self.table.setColumnWidth(6, 110)
            self.table.setColumnWidth(7, 100)

        except Exception as exc:
            logger.error("Refresh error: %s", exc)
