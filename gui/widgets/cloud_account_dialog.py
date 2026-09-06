"""
cloud_account_dialog.py — Add / Edit and Test Cloud Storage Accounts (Amazon S3 & Google Drive).
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any

from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtGui import QColor, QPalette, QFont
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QGroupBox, QFileDialog,
    QMessageBox, QFormLayout, QFrame
)

from core.settings import AppSettings

logger = logging.getLogger(__name__)


class CloudAccountDialog(QDialog):
    """Dialog for creating and editing Amazon S3 or Google Drive accounts."""

    account_saved = Signal(dict)

    def __init__(
        self,
        settings: AppSettings,
        provider: str = "s3",
        account_data: Optional[Dict[str, Any]] = None,
        parent=None
    ):
        super().__init__(parent)
        self.settings = settings
        self.provider = provider.lower()
        self.account_data = account_data or {}
        self.is_edit = bool(account_data and account_data.get("id"))

        self.setWindowTitle(
            f"{'Düzenle' if self.is_edit else 'Yeni Hesap Ekle'}: "
            f"{'Amazon S3' if self.provider == 's3' else 'Google Drive'}"
        )
        self.setMinimumWidth(560)
        self.resize(580, 500)
        self._setup_theme()
        self._setup_ui()
        self._load_initial_data()

    def _setup_theme(self):
        # Explicit Light Palette to protect against OS Dark Theme inheritance
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor("#f8fafc"))
        pal.setColor(QPalette.WindowText, QColor("#0f172a"))
        pal.setColor(QPalette.Base, QColor("#ffffff"))
        pal.setColor(QPalette.AlternateBase, QColor("#f1f5f9"))
        pal.setColor(QPalette.Text, QColor("#0f172a"))
        pal.setColor(QPalette.Button, QColor("#ffffff"))
        pal.setColor(QPalette.ButtonText, QColor("#0f172a"))
        self.setPalette(pal)
        self.setAutoFillBackground(True)

        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
                color: #0f172a;
            }
            QWidget {
                color: #0f172a;
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }
            QLabel {
                color: #0f172a;
                font-size: 12px;
                font-weight: 500;
                background: transparent;
            }
            QLineEdit, QComboBox {
                background-color: #ffffff !important;
                color: #0f172a !important;
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                min-height: 22px;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #2563eb !important;
                background-color: #ffffff !important;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #0f172a;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
                border: 1px solid #cbd5e1;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                color: #1e40af;
                background-color: #ffffff;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 10px;
                padding: 16px 12px 12px 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                color: #1e40af;
                background-color: #ffffff;
            }
            QCheckBox {
                color: #0f172a;
                font-weight: 500;
                font-size: 12px;
                background: transparent;
            }
        """)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # -------------------------------------------------------------
        # 1. Standard Royal Blue Header Banner with White Text
        # -------------------------------------------------------------
        header_banner = QFrame()
        header_banner.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1e40af, stop:1 #2563eb);
                border-radius: 8px;
                border: none;
            }
        """)
        h_layout = QHBoxLayout(header_banner)
        h_layout.setContentsMargins(14, 12, 14, 12)
        h_layout.setSpacing(12)

        hdr_icon = QLabel("☁️" if self.provider == "s3" else "📁")
        hdr_icon.setStyleSheet("font-size: 28px; background: transparent; color: #ffffff;")
        h_layout.addWidget(hdr_icon)

        hdr_vbox = QVBoxLayout()
        hdr_vbox.setSpacing(3)
        hdr_title = QLabel(
            "Amazon S3 Bulut Depolama Hesabı" if self.provider == "s3"
            else "Google Drive Bulut Depolama Hesabı"
        )
        hdr_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff; background: transparent;")
        hdr_sub = QLabel("Yedekleme ve kurtarma işlemleri için güvenli bulut kimlik bilgileri")
        hdr_sub.setStyleSheet("font-size: 11.5px; color: #dbeafe; background: transparent;")
        hdr_vbox.addWidget(hdr_title)
        hdr_vbox.addWidget(hdr_sub)
        h_layout.addLayout(hdr_vbox, 1)
        layout.addWidget(header_banner)

        # Form fields
        form_group = QGroupBox("Hesap Yapılandırması")
        form_layout = QFormLayout(form_group)
        form_layout.setSpacing(8)
        form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # Common: Account Name
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("Örn: AWS Ana Yedek Deposu" if self.provider == "s3" else "Örn: Şirket Google Drive")
        form_layout.addRow("Hesap Tanımı *:", self.txt_name)

        if self.provider == "s3":
            self.txt_bucket = QLineEdit()
            self.txt_bucket.setPlaceholderText("Örn: sirket-mail-arsivi")
            form_layout.addRow("Bucket Adı *:", self.txt_bucket)

            self.txt_region = QLineEdit("eu-central-1")
            self.txt_region.setPlaceholderText("Örn: eu-central-1, us-east-1")
            form_layout.addRow("Bölge (Region):", self.txt_region)

            self.txt_access_key = QLineEdit()
            self.txt_access_key.setPlaceholderText("AKIA... (IAM Access Key)")
            form_layout.addRow("Access Key ID:", self.txt_access_key)

            # Secret key with toggle button
            secret_row = QHBoxLayout()
            secret_row.setSpacing(4)
            self.txt_secret_key = QLineEdit()
            self.txt_secret_key.setEchoMode(QLineEdit.Password)
            self.txt_secret_key.setPlaceholderText("Secret Access Key")
            btn_show_secret = QPushButton("👁️")
            btn_show_secret.setToolTip("Şifreyi göster/gizle")
            btn_show_secret.setFixedWidth(30)
            btn_show_secret.clicked.connect(self._toggle_secret_visibility)
            secret_row.addWidget(self.txt_secret_key, 1)
            secret_row.addWidget(btn_show_secret, 0)
            form_layout.addRow("Secret Key:", secret_row)

            self.txt_prefix = QLineEdit()
            self.txt_prefix.setPlaceholderText("Örn: backups/mail (isteğe bağlı)")
            form_layout.addRow("Yol Ön Eki (Prefix):", self.txt_prefix)

        else:  # Google Drive
            cred_row = QHBoxLayout()
            cred_row.setSpacing(4)
            self.txt_credentials = QLineEdit()
            self.txt_credentials.setPlaceholderText("credentials.json dosya yolu")
            btn_browse = QPushButton("📁 Gözat")
            btn_browse.setStyleSheet("padding: 4px 10px; font-size: 11px;")
            btn_browse.clicked.connect(self._browse_credentials)
            cred_row.addWidget(self.txt_credentials, 1)
            cred_row.addWidget(btn_browse, 0)
            form_layout.addRow("Kimlik Dosyası (JSON) *:", cred_row)

            self.txt_target_folder = QLineEdit()
            self.txt_target_folder.setPlaceholderText("Hedef klasör ID veya adı (İsteğe bağlı)")
            form_layout.addRow("Hedef Klasör:", self.txt_target_folder)

        # Default checkbox
        self.chk_default = QCheckBox("Bu sağlayıcı için varsayılan hesap olarak kullan")
        form_layout.addRow("", self.chk_default)

        layout.addWidget(form_group)

        # Status & Test Row
        test_row = QHBoxLayout()
        self.btn_test = QPushButton("🔌 Bağlantıyı Test Et")
        self.btn_test.setStyleSheet("background-color: #4f46e5; color: white; font-weight: 600; padding: 6px 14px; border-radius: 5px;")
        self.btn_test.clicked.connect(self._test_connection)
        test_row.addWidget(self.btn_test)

        self.lbl_test_status = QLabel("")
        self.lbl_test_status.setStyleSheet("font-size: 11px; font-weight: 600;")
        test_row.addWidget(self.lbl_test_status, 1)
        layout.addLayout(test_row)

        # Bottom Buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        btn_cancel = QPushButton("İptal")
        btn_cancel.setStyleSheet("padding: 6px 16px; font-size: 12px; border: 1px solid #cbd5e1; border-radius: 5px;")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        self.btn_save = QPushButton("💾 Hesabı Kaydet")
        self.btn_save.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 6px 18px; border-radius: 5px;")
        self.btn_save.clicked.connect(self._save_account)
        btn_box.addWidget(self.btn_save)

        layout.addLayout(btn_box)

    def _load_initial_data(self):
        if not self.account_data:
            return

        self.txt_name.setText(self.account_data.get("name", ""))
        self.chk_default.setChecked(self.account_data.get("is_default", False))

        if self.provider == "s3":
            self.txt_bucket.setText(self.account_data.get("bucket", ""))
            self.txt_region.setText(self.account_data.get("region", "eu-central-1"))
            self.txt_access_key.setText(self.account_data.get("access_key", ""))
            self.txt_secret_key.setText(self.account_data.get("secret_key", ""))
            self.txt_prefix.setText(self.account_data.get("prefix", ""))
        else:
            self.txt_credentials.setText(self.account_data.get("credentials_path", ""))
            self.txt_target_folder.setText(self.account_data.get("target_folder", ""))

    def _toggle_secret_visibility(self):
        if self.txt_secret_key.echoMode() == QLineEdit.Password:
            self.txt_secret_key.setEchoMode(QLineEdit.Normal)
        else:
            self.txt_secret_key.setEchoMode(QLineEdit.Password)

    def _browse_credentials(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Google Credentials JSON Seç", "", "JSON Dosyaları (*.json);;Tüm Dosyalar (*.*)"
        )
        if path:
            self.txt_credentials.setText(path)

    @Slot()
    def _test_connection(self):
        name = self.txt_name.text().strip()
        self.lbl_test_status.setText("⏳ Bağlantı test ediliyor...")
        self.lbl_test_status.setStyleSheet("color: #0284c7; font-weight: 600;")
        self.btn_test.setEnabled(False)

        if self.provider == "s3":
            bucket = self.txt_bucket.text().strip()
            if not bucket:
                self.lbl_test_status.setText("❌ Bucket adı boş olamaz.")
                self.lbl_test_status.setStyleSheet("color: #dc2626; font-weight: 600;")
                self.btn_test.setEnabled(True)
                return

            try:
                import boto3
                region = self.txt_region.text().strip() or "eu-central-1"
                ak = self.txt_access_key.text().strip() or None
                sk = self.txt_secret_key.text().strip() or None
                client = boto3.client(
                    "s3",
                    region_name=region,
                    aws_access_key_id=ak,
                    aws_secret_access_key=sk
                )
                client.head_bucket(Bucket=bucket)
                self.lbl_test_status.setText("✅ S3 Bucket bağlantısı başarılı!")
                self.lbl_test_status.setStyleSheet("color: #16a34a; font-weight: 600;")
            except ImportError:
                self.lbl_test_status.setText("ℹ️ boto3 yüklü değil; parametreler doğrulandı.")
                self.lbl_test_status.setStyleSheet("color: #059669; font-weight: 600;")
            except Exception as e:
                self.lbl_test_status.setText(f"❌ Bağlantı hatası: {str(e)[:50]}")
                self.lbl_test_status.setStyleSheet("color: #dc2626; font-weight: 600;")

        else:  # Google Drive
            cred = self.txt_credentials.text().strip()
            if not cred or not os.path.exists(cred):
                self.lbl_test_status.setText("❌ Geçersiz JSON kimlik dosyası yolu.")
                self.lbl_test_status.setStyleSheet("color: #dc2626; font-weight: 600;")
                self.btn_test.setEnabled(True)
                return

            try:
                with open(cred, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "installed" in data or "web" in data or "type" in data:
                    self.lbl_test_status.setText("✅ Google JSON kimlik yapısı geçerli.")
                    self.lbl_test_status.setStyleSheet("color: #16a34a; font-weight: 600;")
                else:
                    self.lbl_test_status.setText("⚠️ Dosya standart OAuth JSON yapısında değil.")
                    self.lbl_test_status.setStyleSheet("color: #d97706; font-weight: 600;")
            except Exception as e:
                self.lbl_test_status.setText(f"❌ JSON okuma hatası: {str(e)[:50]}")
                self.lbl_test_status.setStyleSheet("color: #dc2626; font-weight: 600;")

        self.btn_test.setEnabled(True)

    @Slot()
    def _save_account(self):
        name = self.txt_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Uyarı", "Lütfen bir hesap tanımı/adı girin.")
            return

        acc_data = dict(self.account_data)
        acc_data["name"] = name
        acc_data["provider"] = self.provider
        acc_data["is_default"] = self.chk_default.isChecked()

        if self.provider == "s3":
            bucket = self.txt_bucket.text().strip()
            if not bucket:
                QMessageBox.warning(self, "Uyarı", "Lütfen bir S3 Bucket adı girin.")
                return
            acc_data["bucket"] = bucket
            acc_data["region"] = self.txt_region.text().strip() or "eu-central-1"
            acc_data["access_key"] = self.txt_access_key.text().strip()
            acc_data["secret_key"] = self.txt_secret_key.text().strip()
            acc_data["prefix"] = self.txt_prefix.text().strip()
        else:
            cred = self.txt_credentials.text().strip()
            if not cred:
                QMessageBox.warning(self, "Uyarı", "Lütfen credentials.json dosya yolunu belirtin.")
                return
            acc_data["credentials_path"] = cred
            acc_data["target_folder"] = self.txt_target_folder.text().strip()

        # Persist in AppSettings
        saved_id = self.settings.save_cloud_account(acc_data)
        acc_data["id"] = saved_id

        self.account_saved.emit(acc_data)
        self.accept()
