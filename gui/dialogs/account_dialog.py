"""
account_dialog.py — Add/Edit email account dialog with connection test.
"""

import logging
import threading
from typing import Any, Dict, Optional

from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QSpinBox, QCheckBox, QPushButton, QLabel,
    QMessageBox, QProgressBar, QDialogButtonBox, QFrame,
    QComboBox, QFileDialog, QInputDialog,
)

from core.mail_engine import MailEngine
from core.settings import AppSettings

logger = logging.getLogger(__name__)


class AccountDialog(QDialog):
    """Modal dialog for adding or editing an email account."""

    def __init__(self, engine: MailEngine, parent=None,
                 account: Optional[Dict[str, Any]] = None,
                 settings: AppSettings = None):
        super().__init__(parent)
        self.engine = engine
        self.account = account  # None = add mode, dict = edit mode
        self.settings = settings or AppSettings()
        self._is_edit = account is not None
        self._is_loading = True
        self._setup_ui()
        self._load_data()
        self._is_loading = False

    def _setup_ui(self):
        title = "Edit Account" if self._is_edit else "Add New Account"
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog {
                background: #f8f9fa;
            }
            QLabel[heading="true"] {
                font-size: 18px;
                font-weight: 700;
                color: #1a1a2e;
                padding: 4px 0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Header
        header = QLabel("📧  " + title)
        header.setProperty("heading", True)
        layout.addWidget(header)

        sub = QLabel("IMAP email account configuration. "
                     "Credentials are encrypted with AES-256 before storage.")
        sub.setStyleSheet("color: #666; font-size: 12px; margin-bottom: 8px;")
        layout.addWidget(sub)

        # Form
        form_frame = QFrame()
        form_frame.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #e0e3e8;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        form = QFormLayout(form_frame)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self.input_label = QLineEdit()
        self.input_label.setPlaceholderText("e.g. Work Gmail, Personal Outlook")
        form.addRow("Label:", self.input_label)

        self.input_email = QLineEdit()
        self.input_email.setPlaceholderText("user@example.com")
        form.addRow("Email:", self.input_email)

        self.input_host = QLineEdit()
        self.input_host.setPlaceholderText("imap.gmail.com")
        form.addRow("IMAP Host:", self.input_host)

        port_row = QHBoxLayout()
        self.input_port = QSpinBox()
        self.input_port.setRange(1, 65535)
        self.input_port.setValue(993)
        self.input_port.setFixedWidth(100)
        port_row.addWidget(self.input_port)
        self.input_ssl = QCheckBox("Use SSL/TLS")
        self.input_ssl.setChecked(True)
        port_row.addWidget(self.input_ssl)
        port_row.addStretch()
        form.addRow("Port:", port_row)

        self.input_username = QLineEdit()
        self.input_username.setPlaceholderText("Same as email, or app-specific password")
        form.addRow("Username:", self.input_username)

        self.input_password = QLineEdit()
        self.input_password.setPlaceholderText("App password or mailbox password")
        self.input_password.setEchoMode(QLineEdit.Password)
        form.addRow("Password:", self.input_password)

        self.combo_storage = QComboBox()
        self.combo_storage.addItem("Default (data/ directory)", None)
        for loc in self.settings.storage_locations():
            self.combo_storage.addItem(loc.name, loc.name)
        self.combo_storage.addItem("📂  Browse for folder...", "__BROWSE__")
        self.combo_storage.currentIndexChanged.connect(self._on_storage_changed)
        form.addRow("Storage:", self.combo_storage)

        layout.addWidget(form_frame)

        # Connection test button + progress
        test_row = QHBoxLayout()
        self.btn_test = QPushButton("🔌  Test Connection")
        self.btn_test.setProperty("outline", True)
        self.btn_test.setCursor(Qt.PointingHandCursor)
        self.btn_test.setMinimumHeight(36)
        test_row.addWidget(self.btn_test)

        self.test_status = QLabel("")
        self.test_status.setStyleSheet("font-size: 12px; padding-left: 8px;")
        test_row.addWidget(self.test_status)
        test_row.addStretch()
        layout.addLayout(test_row)

        self.test_progress = QProgressBar()
        self.test_progress.setVisible(False)
        self.test_progress.setMaximumHeight(4)
        self.test_progress.setTextVisible(False)
        layout.addWidget(self.test_progress)

        # Buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setProperty("outline", True)
        self.btn_cancel.setMinimumWidth(100)
        btn_box.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("💾  Save Account" if not self._is_edit
                                     else "💾  Update Account")
        self.btn_save.setProperty("success", True)
        self.btn_save.setMinimumWidth(140)
        self.btn_save.setMinimumHeight(36)
        btn_box.addWidget(self.btn_save)

        layout.addLayout(btn_box)

        # Connections
        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_test.clicked.connect(self._test_connection)

    def _is_path_outside_default(self, folder_path: str) -> bool:
        try:
            data_path = self.settings.data_path().resolve()
            target_path = Path(folder_path).resolve()
            return not str(target_path).startswith(str(data_path))
        except Exception:
            return False

    def _on_storage_changed(self, idx: int):
        if hasattr(self, '_is_loading') and self._is_loading:
            return

        selected_loc_name = self.combo_storage.itemData(idx)

        if selected_loc_name == "__BROWSE__":
            folder = QFileDialog.getExistingDirectory(
                self, "Select Storage Folder", str(Path.cwd()),
                QFileDialog.ShowDirsOnly
            )
            if folder:
                if self._is_path_outside_default(folder):
                    QMessageBox.warning(
                        self, "Uyarı: Harici Dizin",
                        f"Uyarı: Seçilen yedekleme/depolama klasörü varsayılan veri dizininin dışındadır.\n\n"
                        f"Senkronizasyon (aktif veritabanı ve önbellek) yalnızca varsayılan veri dizini ({self.settings.data_path()}) içinde çalışacaktır. "
                        f"Bu konum sadece harici yedeklemeler/aktarımlar için kullanılacaktır."
                    )
                name, ok = QInputDialog.getText(
                    self, "Storage Name",
                    "Give this storage location a name:"
                )
                if ok and name.strip():
                    name = name.strip()
                    self.settings.add_storage_location(name, folder)
                    self.combo_storage.insertItem(
                        self.combo_storage.count() - 1, name, name
                    )
                    self.combo_storage.setCurrentIndex(
                        self.combo_storage.findText(name)
                    )
                    return
            # User cancelled → revert to Default
            self.combo_storage.setCurrentIndex(0)
        elif selected_loc_name:
            path_found = None
            for loc in self.settings.storage_locations():
                if loc.name == selected_loc_name:
                    path_found = loc.path
                    break
            if path_found and self._is_path_outside_default(path_found):
                QMessageBox.warning(
                    self, "Uyarı: Harici Dizin",
                    f"Uyarı: Seçilen yedekleme/depolama klasörü varsayılan veri dizininin dışındadır.\n\n"
                    f"Senkronizasyon (aktif veritabanı ve önbellek) yalnızca varsayılan veri dizini ({self.settings.data_path()}) içinde çalışacaktır. "
                    f"Bu konum sadece harici yedeklemeler/aktarımlar için kullanılacaktır."
                )

    def _load_data(self):
        if self.account:
            self.input_label.setText(self.account.get("label", ""))
            self.input_email.setText(self.account.get("email", ""))
            self.input_host.setText(self.account.get("imap_host", ""))
            self.input_port.setValue(self.account.get("imap_port", 993))
            self.input_ssl.setChecked(bool(self.account.get("use_ssl", True)))
            # Username needs decryption
            try:
                username_enc = self.account.get("username_enc", "")
                if username_enc:
                    username = self.engine.crypto.decrypt(username_enc)
                    self.input_username.setText(username)
                else:
                    self.input_username.setText(self.account.get("email", ""))
            except Exception:
                self.input_username.setText(self.account.get("email", ""))
            self.input_password.setPlaceholderText("(unchanged — leave blank to keep)")

            # Restore storage location
            stor_name = self.settings.account_storage(self.account["id"])
            if stor_name:
                idx = self.combo_storage.findText(stor_name)
                if idx >= 0:
                    self.combo_storage.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save(self):
        label = self.input_label.text().strip()
        email_addr = self.input_email.text().strip()
        host = self.input_host.text().strip()
        port = self.input_port.value()
        use_ssl = self.input_ssl.isChecked()
        username = self.input_username.text().strip() or email_addr
        password = self.input_password.text()

        # Validation
        errors = []
        if not label:
            errors.append("Label is required")
        if not email_addr or "@" not in email_addr:
            errors.append("Valid email address is required")
        if not host:
            errors.append("IMAP host is required")
        if not self._is_edit and not password:
            errors.append("Password is required")

        if errors:
            QMessageBox.warning(self, "Validation Error",
                                "Please fix the following:\n• " + "\n• ".join(errors))
            return

        # Check if we should auto-suggest domain/user folder
        if "@" in email_addr:
            parts = email_addr.split("@", 1)
            username_part = parts[0].strip()
            domain_part = parts[1].strip()
        else:
            username_part = ""
            domain_part = ""

        current_assigned = self.settings.account_storage(self.account["id"]) if self._is_edit else None
        if not current_assigned and domain_part and username_part:
            data_dir = self.settings.data_path()
            constructed_path = data_dir / domain_part / username_part
            suggested_name = f"{domain_part}_{username_part}"
            
            reply = QMessageBox.question(
                self, "Yedekleme Klasörü Oluşturma",
                f"Bu hesap için otomatik yedekleme/depolama klasörü oluşturulsun mu?\n\nYol: {constructed_path}",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                try:
                    constructed_path.mkdir(parents=True, exist_ok=True)
                    self.settings.add_storage_location(suggested_name, str(constructed_path))
                    self.combo_storage.insertItem(self.combo_storage.count() - 1, suggested_name, suggested_name)
                    self.combo_storage.setCurrentIndex(self.combo_storage.findText(suggested_name))
                except Exception as exc:
                    QMessageBox.warning(self, "Klasör Oluşturma Hatası", f"Klasör oluşturulamadı:\n{exc}")

        try:
            if self._is_edit:
                # Update existing
                acc_id = self.account["id"]
                update_data = {
                    "label": label,
                    "email": email_addr,
                    "imap_host": host,
                    "imap_port": port,
                    "use_ssl": int(use_ssl),
                }
                if username:
                    update_data["username_enc"] = self.engine.crypto.encrypt(username)
                if password:
                    update_data["password_enc"] = self.engine.crypto.encrypt(password)

                self.engine.accounts.update(acc_id, **update_data)
                self.engine.audit.append("account.updated", account_id=acc_id)
                QMessageBox.information(self, "Success", "Account updated.")
            else:
                # Add new
                acc_id = self.engine.add_account(
                    label=label, email=email_addr,
                    imap_host=host, imap_port=port,
                    use_ssl=use_ssl, username=username, password=password,
                )
                QMessageBox.information(self, "Success",
                                        f"Account added with ID: {acc_id}")

            # Save storage location assignment
            stor_name = self.combo_storage.currentData()
            if stor_name:
                self.settings.set_account_storage(acc_id, stor_name)
            else:
                self.settings.set_account_storage(acc_id, None)

            self.accept()

        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save account:\n{exc}")

    # ------------------------------------------------------------------
    # Connection Test
    # ------------------------------------------------------------------

    @Slot()
    def _test_connection(self):
        host = self.input_host.text().strip()
        port = self.input_port.value()
        use_ssl = self.input_ssl.isChecked()
        username = self.input_username.text().strip() or self.input_email.text().strip()
        password = self.input_password.text()

        if not host:
            self.test_status.setText("⚠️ Enter host first")
            self.test_status.setStyleSheet("color: #e67e22; font-size: 12px;")
            return
        if not password and not self._is_edit:
            self.test_status.setText("⚠️ Enter password first")
            self.test_status.setStyleSheet("color: #e67e22; font-size: 12px;")
            return

        # For edit mode with no password change, decrypt existing
        if not password and self._is_edit:
            try:
                password = self.engine.crypto.decrypt(self.account.get("password_enc", ""))
            except Exception:
                self.test_status.setText("⚠️ Enter password to test")
                self.test_status.setStyleSheet("color: #e67e22; font-size: 12px;")
                return

        self.btn_test.setEnabled(False)
        self.test_progress.setVisible(True)
        self.test_progress.setRange(0, 0)
        self.test_status.setText("⏳ Testing connection...")
        self.test_status.setStyleSheet("color: #4361ee; font-size: 12px;")

        def test():
            from infrastructure.imap_client import ImapClient
            client = ImapClient()
            ok = client.connect(host, port, use_ssl, username, password)
            if ok:
                client.disconnect()
            self.btn_test.setEnabled(True)
            self.test_progress.setVisible(False)
            if ok:
                self.test_status.setText("✅ Connection successful")
                self.test_status.setStyleSheet("color: #2d6a4f; font-size: 12px; font-weight: 600;")
            else:
                self.test_status.setText("❌ Connection failed — check settings")
                self.test_status.setStyleSheet("color: #e63946; font-size: 12px; font-weight: 600;")

        threading.Thread(target=test, daemon=True).start()
