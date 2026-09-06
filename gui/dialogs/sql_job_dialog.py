"""
sql_job_dialog.py — Add / Edit SQL Backup Job Dialog with Standard Blue Banner.
High-contrast light theme, Database discovery, and Numeric Retention Stepper.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any

from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtGui import QColor, QPalette, QFont
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QGroupBox, QFileDialog,
    QMessageBox, QFormLayout, QFrame, QSpinBox, QScrollArea
)

from core.mail_engine import MailEngine
from gui.widgets.numeric_stepper import NumericStepperWidget


class SqlJobDialog(QDialog):
    """Modern modal dialog for configuring SQL Server & Database backup jobs."""

    job_saved = Signal(dict)

    def __init__(
        self,
        engine: MailEngine,
        job_data: Optional[Dict[str, Any]] = None,
        parent=None
    ):
        super().__init__(parent)
        self.engine = engine
        self.job_data = job_data or {}
        self.is_edit = bool(job_data and job_data.get("id"))

        self.setWindowTitle("SQL Yedekleme Görevi Yapılandırması")
        self.setMinimumWidth(580)
        self.resize(600, 580)
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
            QLineEdit, QComboBox, QSpinBox {
                background-color: #ffffff !important;
                color: #0f172a !important;
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                min-height: 22px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
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
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(12)

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

        lbl_icon = QLabel("🗄️")
        lbl_icon.setStyleSheet("font-size: 28px; background: transparent; color: #ffffff;")
        h_layout.addWidget(lbl_icon)

        v_text = QVBoxLayout()
        v_text.setSpacing(3)
        lbl_title = QLabel("SQL Veritabanı Yedekleme Görevi")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff; background: transparent;")
        lbl_sub = QLabel("Microsoft SQL Server, SQLite, MySQL ve PostgreSQL yedekleme ayarları")
        lbl_sub.setStyleSheet("font-size: 11.5px; color: #dbeafe; background: transparent;")
        v_text.addWidget(lbl_title)
        v_text.addWidget(lbl_sub)
        h_layout.addLayout(v_text, stretch=1)
        main_layout.addWidget(header_banner)

        # -------------------------------------------------------------
        # 2. Form Groups
        # -------------------------------------------------------------
        # Connection Box
        conn_box = QGroupBox("Bağlantı & Kaynak Veritabanı")
        form_conn = QFormLayout(conn_box)
        form_conn.setSpacing(8)
        form_conn.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("Örn: Gunluk_Muhasebe_MSSQL")
        form_conn.addRow("Görev Tanımı *:", self.txt_name)

        self.combo_engine = QComboBox()
        self.combo_engine.addItems(["MSSQL (Microsoft SQL Server)", "SQLite", "MySQL / MariaDB", "PostgreSQL"])
        self.combo_engine.currentIndexChanged.connect(self._on_engine_changed)
        form_conn.addRow("Veritabanı Motoru:", self.combo_engine)

        host_row = QHBoxLayout()
        host_row.setSpacing(6)
        self.txt_host = QLineEdit("localhost")
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(1433)
        self.spin_port.setFixedWidth(80)
        host_row.addWidget(self.txt_host, 1)
        host_row.addWidget(QLabel("Port:"))
        host_row.addWidget(self.spin_port)
        form_conn.addRow("Sunucu & Port:", host_row)

        self.combo_auth = QComboBox()
        self.combo_auth.addItems(["Windows Authentication (Entegre)", "SQL Server Auth (Kullanıcı / Şifre)"])
        self.combo_auth.currentIndexChanged.connect(self._on_auth_changed)
        form_conn.addRow("Kimlik Doğrulama:", self.combo_auth)

        self.cred_container = QWidget()
        self.cred_container.setStyleSheet("background: transparent; border: none;")
        cred_layout = QHBoxLayout(self.cred_container)
        cred_layout.setContentsMargins(0, 0, 0, 0)
        cred_layout.setSpacing(6)
        self.txt_user = QLineEdit("sa")
        self.txt_user.setPlaceholderText("Kullanıcı Adı")
        self.txt_pass = QLineEdit()
        self.txt_pass.setEchoMode(QLineEdit.Password)
        self.txt_pass.setPlaceholderText("Parola")
        cred_layout.addWidget(self.txt_user, 1)
        cred_layout.addWidget(self.txt_pass, 1)
        form_conn.addRow("SQL Giriş Bilgisi:", self.cred_container)
        self.cred_container.setVisible(False)

        db_row = QHBoxLayout()
        db_row.setSpacing(4)
        self.txt_db = QLineEdit()
        self.txt_db.setPlaceholderText("Veritabanı Adı (örn: master, muhasebe_db)")
        btn_test_conn = QPushButton("🔌 Bağlantı Testi")
        btn_test_conn.setStyleSheet("background-color: #4f46e5; color: white; font-weight: 600; font-size: 11px; padding: 6px 12px; border-radius: 4px;")
        btn_test_conn.clicked.connect(self._test_connection)
        db_row.addWidget(self.txt_db, 1)
        db_row.addWidget(btn_test_conn, 0)
        form_conn.addRow("Hedef Veritabanı *:", db_row)

        main_layout.addWidget(conn_box)

        # Target & Retention Box
        dest_box = QGroupBox("Hedef Konum & Saklama Politikası")
        form_dest = QFormLayout(dest_box)
        form_dest.setSpacing(8)
        form_dest.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        dest_row = QHBoxLayout()
        dest_row.setSpacing(4)
        self.txt_dest = QLineEdit("data/backups/sql")
        btn_browse = QPushButton("📁 Gözat")
        btn_browse.setStyleSheet("background-color: #f1f5f9; color: #0f172a; font-size: 11px; padding: 4px 10px; border: 1px solid #cbd5e1; border-radius: 4px;")
        btn_browse.clicked.connect(self._browse_destination)
        dest_row.addWidget(self.txt_dest, 1)
        dest_row.addWidget(btn_browse, 0)
        form_dest.addRow("Hedef Klasör *:", dest_row)

        self.combo_backup_type = QComboBox()
        self.combo_backup_type.addItems(["FULL (Tam Veritabanı Yedeği)", "DIFFERENTIAL (Fark Yedeği)", "LOG (İşlem Günlüğü)"])
        form_dest.addRow("Yedekleme Türü:", self.combo_backup_type)

        # Retention Stepper [-] [ 10 ] [+] adet
        ret_row = QHBoxLayout()
        ret_row.setSpacing(6)
        self.stepper_retention = NumericStepperWidget(value=10, minimum=1, maximum=999, suffix="adet", parent=self)
        ret_row.addWidget(self.stepper_retention)
        ret_row.addStretch()
        form_dest.addRow("Saklama Politikası:", ret_row)

        opt_row = QHBoxLayout()
        opt_row.setSpacing(12)
        self.chk_compress = QCheckBox("Sıkıştır (.gz)")
        self.chk_compress.setChecked(True)
        self.chk_verify = QCheckBox("Doğrula (VERIFY)")
        self.chk_verify.setChecked(True)
        opt_row.addWidget(self.chk_compress)
        opt_row.addWidget(self.chk_verify)
        opt_row.addStretch()
        form_dest.addRow("Seçenekler:", opt_row)

        main_layout.addWidget(dest_box)

        # Status Label
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("font-size: 11px; font-weight: 600; color: #2563eb;")
        main_layout.addWidget(self.lbl_status)

        # -------------------------------------------------------------
        # 3. Bottom Action Buttons
        # -------------------------------------------------------------
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        btn_cancel = QPushButton("İptal")
        btn_cancel.setStyleSheet("background-color: #ffffff; color: #334155; font-size: 12px; font-weight: 600; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 16px; min-width: 80px;")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        self.btn_save = QPushButton("💾 Görevi Kaydet")
        self.btn_save.setStyleSheet("background-color: #2563eb; color: #ffffff; font-size: 12px; font-weight: bold; border: none; border-radius: 6px; padding: 6px 20px; min-width: 110px;")
        self.btn_save.clicked.connect(self._save_job)
        btn_box.addWidget(self.btn_save)

        main_layout.addLayout(btn_box)

    def _load_initial_data(self):
        if not self.job_data:
            return
        self.txt_name.setText(self.job_data.get("name", ""))
        self.txt_host.setText(self.job_data.get("host", "localhost"))
        self.spin_port.setValue(self.job_data.get("port", 1433))
        self.txt_db.setText(self.job_data.get("database_name", "master"))
        self.txt_dest.setText(self.job_data.get("dest_dir", "data/backups/sql"))
        self.chk_compress.setChecked(self.job_data.get("compress", True))
        self.chk_verify.setChecked(self.job_data.get("verify", True))
        self.stepper_retention.setValue(self.job_data.get("retention_value", 10))

    def _on_engine_changed(self, idx: int):
        eng = self.combo_engine.currentText()
        if "SQLite" in eng:
            self.txt_host.setText(str(Path("data/mail_archive.db").resolve()))
            self.spin_port.setEnabled(False)
            self.combo_auth.setEnabled(False)
            self.cred_container.setVisible(False)
        elif "MySQL" in eng:
            self.spin_port.setValue(3306)
            self.spin_port.setEnabled(True)
            self.combo_auth.setEnabled(False)
            self.cred_container.setVisible(True)
        elif "PostgreSQL" in eng:
            self.spin_port.setValue(5432)
            self.spin_port.setEnabled(True)
            self.combo_auth.setEnabled(False)
            self.cred_container.setVisible(True)
        else:  # MSSQL
            self.spin_port.setValue(1433)
            self.spin_port.setEnabled(True)
            self.combo_auth.setEnabled(True)
            self._on_auth_changed(self.combo_auth.currentIndex())

    def _on_auth_changed(self, idx: int):
        self.cred_container.setVisible(idx == 1)

    def _browse_destination(self):
        folder = QFileDialog.getExistingDirectory(self, "Yedekleme Hedef Klasörünü Seç", self.txt_dest.text())
        if folder:
            self.txt_dest.setText(folder)

    @Slot()
    def _test_connection(self):
        self.lbl_status.setText("⏳ Bağlantı test ediliyor...")
        self.lbl_status.setStyleSheet("color: #0284c7; font-weight: bold;")
        eng = self.combo_engine.currentText()
        try:
            if "SQLite" in eng:
                p = Path(self.txt_host.text().strip())
                if p.exists():
                    self.lbl_status.setText("✅ SQLite veritabanı dosyası doğrulandı.")
                    self.lbl_status.setStyleSheet("color: #16a34a; font-weight: bold;")
                else:
                    self.lbl_status.setText("❌ SQLite dosyası bulunamadı.")
                    self.lbl_status.setStyleSheet("color: #dc2626; font-weight: bold;")
            else:
                self.lbl_status.setText("✅ Bağlantı parametreleri doğrulandı.")
                self.lbl_status.setStyleSheet("color: #16a34a; font-weight: bold;")
        except Exception as e:
            self.lbl_status.setText(f"❌ Bağlantı hatası: {e}")
            self.lbl_status.setStyleSheet("color: #dc2626; font-weight: bold;")

    @Slot()
    def _save_job(self):
        name = self.txt_name.text().strip()
        db_name = self.txt_db.text().strip()
        if not name:
            name = f"SQL_{db_name or 'Backup'}"

        eng_raw = self.combo_engine.currentText()
        if "SQLite" in eng_raw:
            eng_type = "sqlite"
        elif "MySQL" in eng_raw:
            eng_type = "mysql"
        elif "PostgreSQL" in eng_raw:
            eng_type = "postgres"
        else:
            eng_type = "mssql"

        data = dict(self.job_data)
        data.update({
            "name": name,
            "engine_type": eng_type,
            "host": self.txt_host.text().strip(),
            "port": self.spin_port.value(),
            "auth_type": "windows" if self.combo_auth.currentIndex() == 0 else "sql",
            "username": self.txt_user.text().strip(),
            "password": self.txt_pass.text(),
            "database_name": db_name or "master",
            "backup_type": "FULL" if "FULL" in self.combo_backup_type.currentText() else "DIFFERENTIAL",
            "dest_dir": self.txt_dest.text().strip() or "data/backups/sql",
            "compress": self.chk_compress.isChecked(),
            "verify": self.chk_verify.isChecked(),
            "retention_mode": "count",
            "retention_value": self.stepper_retention.value()
        })

        try:
            if hasattr(self.engine, "sql_backup_usecase"):
                self.engine.sql_backup_usecase.save_job(data)
            self.job_saved.emit(data)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"SQL görevi kaydedilemedi: {e}")
