"""
backup_panel.py — Cloud backup panel (S3 & Google Drive).
"""

import logging
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QGroupBox, QTextEdit, QMessageBox, QComboBox, QLineEdit,
    QFormLayout, QCheckBox, QFileDialog, QTabWidget,
)

from core.mail_engine import MailEngine

logger = logging.getLogger(__name__)


class BackupPanel(QWidget):
    """Cloud backup panel with S3 and Google Drive tabs."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        header = QLabel("Cloud Backup")
        header.setProperty("heading", True)
        layout.addWidget(header)

        sub = QLabel("Archive and upload your emails to Amazon S3 or Google Drive. "
                     "Supports filtered backups and dry-run mode.")
        sub.setProperty("subheading", True)
        layout.addWidget(sub)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, stretch=1)

        # S3 Tab
        self._setup_s3_tab()

        # Google Drive Tab
        self._setup_gdrive_tab()

        # Log output
        log_box = QGroupBox("Backup Log")
        log_layout = QVBoxLayout(log_box)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(150)
        log_layout.addWidget(self.log_output)
        layout.addWidget(log_box)

    def _setup_s3_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)

        form_box = QGroupBox("S3 Configuration")
        form = QFormLayout(form_box)

        self.s3_account = QComboBox()
        form.addRow("Account:", self.s3_account)

        self.s3_bucket = QLineEdit()
        self.s3_bucket.setPlaceholderText("my-mail-archive-bucket")
        form.addRow("Bucket:", self.s3_bucket)

        self.s3_region = QLineEdit("us-east-1")
        form.addRow("Region:", self.s3_region)

        self.s3_access_key = QLineEdit()
        self.s3_access_key.setPlaceholderText("Leave blank for IAM role / env vars")
        form.addRow("Access Key ID:", self.s3_access_key)

        self.s3_secret_key = QLineEdit()
        self.s3_secret_key.setEchoMode(QLineEdit.Password)
        form.addRow("Secret Key:", self.s3_secret_key)

        self.s3_filter_date = QLineEdit()
        self.s3_filter_date.setPlaceholderText("e.g. 2024-01-01 (optional)")
        form.addRow("Only before date:", self.s3_filter_date)

        self.s3_dry_run = QCheckBox("Dry Run (preview only)")
        form.addRow("", self.s3_dry_run)

        btn_row = QHBoxLayout()
        self.btn_s3_backup = QPushButton("☁️ Backup to S3")
        self.btn_s3_backup.setProperty("success", True)
        btn_row.addWidget(self.btn_s3_backup)
        btn_row.addStretch()
        form.addRow("", btn_row)

        tab_layout.addWidget(form_box)
        tab_layout.addStretch()
        self.tabs.addTab(tab, "Amazon S3")

        self.btn_s3_backup.clicked.connect(self._backup_s3)

    def _setup_gdrive_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)

        form_box = QGroupBox("Google Drive Configuration")
        form = QFormLayout(form_box)

        self.gdrive_account = QComboBox()
        form.addRow("Account:", self.gdrive_account)

        self.gdrive_credentials = QLineEdit()
        self.gdrive_credentials.setPlaceholderText("Path to credentials.json")
        form.addRow("Credentials File:", self.gdrive_credentials)

        btn_browse = QPushButton("Browse...")
        btn_browse.setProperty("outline", True)
        btn_browse.setProperty("small", True)
        cred_row = QHBoxLayout()
        cred_row.addWidget(self.gdrive_credentials)
        cred_row.addWidget(btn_browse)
        form.addRow("", cred_row)

        self.gdrive_filter_date = QLineEdit()
        self.gdrive_filter_date.setPlaceholderText("e.g. 2024-01-01 (optional)")
        form.addRow("Only before date:", self.gdrive_filter_date)

        self.gdrive_dry_run = QCheckBox("Dry Run (preview only)")
        form.addRow("", self.gdrive_dry_run)

        btn_row = QHBoxLayout()
        self.btn_gdrive_backup = QPushButton("☁️ Backup to Google Drive")
        self.btn_gdrive_backup.setProperty("success", True)
        btn_row.addWidget(self.btn_gdrive_backup)
        btn_row.addStretch()
        form.addRow("", btn_row)

        tab_layout.addWidget(form_box)
        tab_layout.addStretch()
        self.tabs.addTab(tab, "Google Drive")

        btn_browse.clicked.connect(lambda: self._browse_file(self.gdrive_credentials))
        self.btn_gdrive_backup.clicked.connect(self._backup_gdrive)

    # ------------------------------------------------------------------
    # Backup operations
    # ------------------------------------------------------------------

    @Slot()
    def _backup_s3(self):
        acc_data = self.s3_account.currentData()
        if not acc_data:
            QMessageBox.warning(self, "No Account", "Select an account first.")
            return

        bucket = self.s3_bucket.text().strip()
        if not bucket:
            QMessageBox.warning(self, "Validation", "Bucket name is required.")
            return

        self.btn_s3_backup.setEnabled(False)
        before = self.s3_filter_date.text().strip() or None
        dry = self.s3_dry_run.isChecked()
        self.log_output.append(f"Starting S3 backup for {acc_data['label']}...")

        def task():
            try:
                report = self.engine.backup_to_s3(
                    account_id=acc_data["id"],
                    bucket_name=bucket,
                    region=self.s3_region.text().strip() or "us-east-1",
                    access_key_id=self.s3_access_key.text().strip() or None,
                    secret_access_key=self.s3_secret_key.text().strip() or None,
                    before_date=before,
                    dry_run=dry,
                )
                self.btn_s3_backup.setEnabled(True)
                if dry:
                    self.log_output.append(
                        f"DRY RUN: Would backup {report.get('mails_backed_up', 0)} mails"
                    )
                else:
                    status = "OK" if report.get("errors", 0) == 0 else "ERROR"
                    self.log_output.append(
                        f"S3 backup {status}: {report.get('mails_backed_up', 0)} mails, "
                        f"{report.get('total_bytes', 0)} bytes"
                    )
            except Exception as exc:
                self.btn_s3_backup.setEnabled(True)
                self.log_output.append(f"S3 backup ERROR: {exc}")

        threading.Thread(target=task, daemon=True).start()

    @Slot()
    def _backup_gdrive(self):
        acc_data = self.gdrive_account.currentData()
        if not acc_data:
            QMessageBox.warning(self, "No Account", "Select an account first.")
            return

        creds_path = self.gdrive_credentials.text().strip()
        if creds_path and not Path(creds_path).exists():
            QMessageBox.warning(self, "Validation", "Credentials file not found.")
            return

        self.btn_gdrive_backup.setEnabled(False)
        before = self.gdrive_filter_date.text().strip() or None
        dry = self.gdrive_dry_run.isChecked()
        self.log_output.append(f"Starting Google Drive backup for {acc_data['label']}...")

        def task():
            try:
                report = self.engine.backup_to_gdrive(
                    account_id=acc_data["id"],
                    before_date=before,
                    dry_run=dry,
                    credentials_path=Path(creds_path) if creds_path else None,
                )
                self.btn_gdrive_backup.setEnabled(True)
                if dry:
                    self.log_output.append(
                        f"DRY RUN: Would backup {report.get('mails_backed_up', 0)} mails"
                    )
                else:
                    status = "OK" if report.get("errors", 0) == 0 else "ERROR"
                    self.log_output.append(
                        f"GDrive backup {status}: {report.get('mails_backed_up', 0)} mails"
                    )
            except Exception as exc:
                self.btn_gdrive_backup.setEnabled(True)
                self.log_output.append(f"GDrive backup ERROR: {exc}")

        threading.Thread(target=task, daemon=True).start()

    def _browse_file(self, line_edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path:
            line_edit.setText(path)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self):
        for combo in [self.s3_account, self.gdrive_account]:
            combo.clear()
            try:
                accounts = self.engine.list_accounts()
                for acc in accounts:
                    combo.addItem(f"{acc['label']} ({acc['email']})", acc)
            except Exception as exc:
                logger.error("Refresh error: %s", exc)
