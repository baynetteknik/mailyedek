"""
restore_panel.py — Restore from cloud backup panel.
"""

import logging
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QTextEdit, QMessageBox, QComboBox, QLineEdit,
    QFormLayout, QCheckBox, QTabWidget,
)

from core.mail_engine import MailEngine

logger = logging.getLogger(__name__)


class RestorePanel(QWidget):
    """Restore panel with S3 and Google Drive tabs."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        header = QLabel("Restore from Backup")
        header.setProperty("heading", True)
        layout.addWidget(header)

        sub = QLabel("Restore archived emails from cloud backups back to your "
                     "local database or directly to an IMAP server.")
        sub.setProperty("subheading", True)
        layout.addWidget(sub)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, stretch=1)

        self._setup_s3_tab()
        self._setup_gdrive_tab()

        # Log
        log_box = QGroupBox("Restore Log")
        log_layout = QVBoxLayout(log_box)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(150)
        log_layout.addWidget(self.log_output)
        layout.addWidget(log_box)

    def _setup_s3_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        form_box = QGroupBox("S3 Restore")
        form = QFormLayout(form_box)

        self.s3_bucket = QLineEdit()
        self.s3_bucket.setPlaceholderText("my-mail-archive-bucket")
        form.addRow("Bucket:", self.s3_bucket)

        self.s3_key = QLineEdit()
        self.s3_key.setPlaceholderText("backups/mail_backup_1_20250101.tar.gz")
        form.addRow("Remote Key:", self.s3_key)

        self.s3_region = QLineEdit("us-east-1")
        form.addRow("Region:", self.s3_region)

        self.s3_access_key = QLineEdit()
        self.s3_access_key.setPlaceholderText("Leave blank for IAM role")
        form.addRow("Access Key:", self.s3_access_key)

        self.s3_secret_key = QLineEdit()
        self.s3_secret_key.setEchoMode(QLineEdit.Password)
        form.addRow("Secret Key:", self.s3_secret_key)

        self.s3_target_imap = QCheckBox("Push restored mails directly to IMAP server")
        form.addRow("", self.s3_target_imap)

        self.s3_folder_lang = QComboBox()
        self.s3_folder_lang.addItem("Orijinal Dilinde Bırak", "original")
        self.s3_folder_lang.addItem("Türkçeleştir (TR)", "tr")
        self.s3_folder_lang.addItem("İngilizceye Çevir (EN)", "en")
        initial_restore_lang = self.engine.settings.folder_translation_restore() if hasattr(self.engine, "settings") else "original"
        idx = self.s3_folder_lang.findData(initial_restore_lang)
        if idx >= 0:
            self.s3_folder_lang.setCurrentIndex(idx)
        form.addRow("Sunucuya Gönderirken Klasör İsimleri:", self.s3_folder_lang)

        self.s3_dry_run = QCheckBox("Dry Run (preview only)")
        form.addRow("", self.s3_dry_run)

        btn_row = QHBoxLayout()
        self.btn_s3_restore = QPushButton("📥 Restore from S3")
        self.btn_s3_restore.setProperty("success", True)
        btn_row.addWidget(self.btn_s3_restore)
        btn_row.addStretch()
        form.addRow("", btn_row)

        tab_layout.addWidget(form_box)
        tab_layout.addStretch()
        self.tabs.addTab(tab, "Amazon S3")

        self.btn_s3_restore.clicked.connect(self._restore_s3)

    def _setup_gdrive_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        form_box = QGroupBox("Google Drive Restore")
        form = QFormLayout(form_box)

        self.gdrive_name = QLineEdit()
        self.gdrive_name.setPlaceholderText("mail_backup_1_20250101.tar.gz")
        form.addRow("Remote Filename:", self.gdrive_name)

        self.gdrive_credentials = QLineEdit()
        self.gdrive_credentials.setPlaceholderText("Path to credentials.json")
        form.addRow("Credentials:", self.gdrive_credentials)

        self.gdrive_target_imap = QCheckBox("Push restored mails directly to IMAP server")
        form.addRow("", self.gdrive_target_imap)

        self.gdrive_folder_lang = QComboBox()
        self.gdrive_folder_lang.addItem("Orijinal Dilinde Bırak", "original")
        self.gdrive_folder_lang.addItem("Türkçeleştir (TR)", "tr")
        self.gdrive_folder_lang.addItem("İngilizceye Çevir (EN)", "en")
        initial_restore_lang = self.engine.settings.folder_translation_restore() if hasattr(self.engine, "settings") else "original"
        idx = self.gdrive_folder_lang.findData(initial_restore_lang)
        if idx >= 0:
            self.gdrive_folder_lang.setCurrentIndex(idx)
        form.addRow("Sunucuya Gönderirken Klasör İsimleri:", self.gdrive_folder_lang)

        self.gdrive_dry_run = QCheckBox("Dry Run (preview only)")
        form.addRow("", self.gdrive_dry_run)

        btn_row = QHBoxLayout()
        self.btn_gdrive_restore = QPushButton("📥 Restore from Google Drive")
        self.btn_gdrive_restore.setProperty("success", True)
        btn_row.addWidget(self.btn_gdrive_restore)
        btn_row.addStretch()
        form.addRow("", btn_row)

        tab_layout.addWidget(form_box)
        tab_layout.addStretch()
        self.tabs.addTab(tab, "Google Drive")

        self.btn_gdrive_restore.clicked.connect(self._restore_gdrive)

    # ------------------------------------------------------------------
    # Restore operations
    # ------------------------------------------------------------------

    @Slot()
    def _restore_s3(self):
        bucket = self.s3_bucket.text().strip()
        key = self.s3_key.text().strip()
        if not bucket or not key:
            QMessageBox.warning(self, "Validation", "Bucket and Key are required.")
            return

        self.btn_s3_restore.setEnabled(False)
        dry = self.s3_dry_run.isChecked()
        self.log_output.append("Starting S3 restore...")

        folder_lang = self.s3_folder_lang.currentData() or "original"
        if hasattr(self.engine, "settings"):
            self.engine.settings.set_folder_translation_restore(folder_lang)

        from datetime import datetime
        start_time_str = datetime.utcnow().isoformat()
        
        def task():
            try:
                result = self.engine.restore_from_s3(
                    remote_key=key,
                    bucket_name=bucket,
                    region=self.s3_region.text().strip() or "us-east-1",
                    target_imap=self.s3_target_imap.isChecked(),
                    dry_run=dry,
                    access_key_id=self.s3_access_key.text().strip() or None,
                    secret_access_key=self.s3_secret_key.text().strip() or None,
                    folder_lang=folder_lang,
                )
                result["started_at"] = start_time_str
                result["finished_at"] = datetime.utcnow().isoformat()
                self.btn_s3_restore.setEnabled(True)
                self.log_output.append(
                    f"Restore: {result.get('mails_restored', 0)} mails, "
                    f"{result.get('hash_verified', 0)} hashes verified, "
                    f"{result.get('errors', 0)} errors"
                )
                if not dry:
                    try:
                        self.engine.reporter.generate_restore_report(result, "both")
                    except Exception as e:
                        logger.error("Failed to generate restore report: %s", e)
            except Exception as exc:
                self.btn_s3_restore.setEnabled(True)
                self.log_output.append(f"ERROR: {exc}")

        threading.Thread(target=task, daemon=True).start()

    @Slot()
    def _restore_gdrive(self):
        name = self.gdrive_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Remote filename is required.")
            return

        self.btn_gdrive_restore.setEnabled(False)
        dry = self.gdrive_dry_run.isChecked()
        self.log_output.append("Starting Google Drive restore...")

        folder_lang = self.gdrive_folder_lang.currentData() or "original"
        if hasattr(self.engine, "settings"):
            self.engine.settings.set_folder_translation_restore(folder_lang)

        from datetime import datetime
        start_time_str = datetime.utcnow().isoformat()

        def task():
            try:
                result = self.engine.restore_from_gdrive(
                    remote_name=name,
                    target_imap=self.gdrive_target_imap.isChecked(),
                    dry_run=dry,
                    folder_lang=folder_lang,
                )
                result["started_at"] = start_time_str
                result["finished_at"] = datetime.utcnow().isoformat()
                self.btn_gdrive_restore.setEnabled(True)
                self.log_output.append(
                    f"Restore: {result.get('mails_restored', 0)} mails, "
                    f"{result.get('errors', 0)} errors"
                )
                if not dry:
                    try:
                        self.engine.reporter.generate_restore_report(result, "both")
                    except Exception as e:
                        logger.error("Failed to generate restore report: %s", e)
            except Exception as exc:
                self.btn_gdrive_restore.setEnabled(True)
                self.log_output.append(f"ERROR: {exc}")

        threading.Thread(target=task, daemon=True).start()

    def refresh(self):
        pass
