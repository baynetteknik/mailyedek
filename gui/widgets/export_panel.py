"""
export_panel.py — Full-page email export & server migration panel with 3-panel layout.

Features:
- ThreePanelWorkspaceTemplate architecture (Sol: Domain/Grup filtresi, Orta: ProGrid, Sağ: İşlem paneli).
- ProGridWidget with customizable, filterable, persistent columns and crisp Account Details readability.
- Multi-column separation (Check, Label, Email, Domain/Group, Host, Stats, Profile, Progress, Actions).
- Comprehensive migration options, inode checking, profile configuration dialog, and real-time reports.
"""

import os
import re
import imaplib
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional, List
from datetime import datetime

from PySide6.QtCore import Qt, Slot, Signal, QDate
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame, QScrollArea,
    QComboBox, QListWidget, QListWidgetItem, QCheckBox, QDateEdit,
    QLineEdit, QPushButton, QFileDialog, QProgressBar, QTextEdit,
    QMessageBox, QLabel, QAbstractItemView, QGroupBox, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QDialogButtonBox,
    QSizePolicy
)

from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.templates.three_panel_workspace import ThreePanelWorkspaceTemplate
from gui.widgets.pro_grid_widget import ProGridWidget

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Clickable Stat Card Widget
# ---------------------------------------------------------------------------

class StatCard(QFrame):
    def __init__(self, title: str, value: str = "0000", bg_color: str = "#3b82f6", callback=None, tooltip_text="", parent=None):
        super().__init__(parent)
        self.callback = callback
        if tooltip_text:
            self.setToolTip(tooltip_text)
            
        self.setStyleSheet(f"""
            StatCard {{
                background-color: {bg_color};
                border: 2px solid #cbd5e1;
                border-radius: 8px;
                padding: 6px;
            }}
            StatCard:hover {{
                border-color: #3b82f6;
            }}
        """)
        self.setMinimumHeight(65)
        self.setCursor(Qt.PointingHandCursor if callback else Qt.ArrowCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        
        self.title_label = QLabel(title.upper())
        self.title_label.setStyleSheet("font-size:10px; color:#ffffff; font-weight:bold; border:none; background:transparent;")
        self.title_label.setAlignment(Qt.AlignCenter)
        
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet("font-size:18px; font-weight:900; color:#ffffff; border:none; background:transparent;")
        self.value_label.setAlignment(Qt.AlignCenter)
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, val: str):
        if val.isdigit():
            val = f"{int(val):04d}"
        self.value_label.setText(val)

    def mousePressEvent(self, event):
        if self.callback:
            self.callback()
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Dynamic Config Dialog
# ---------------------------------------------------------------------------

class ExportConfigDialog(QDialog):
    """Popup configuration dialog to handle profiles, target formats, filters, and target IMAP credentials."""
    
    match_completed = Signal(list)
    match_failed = Signal(str)

    def __init__(self, engine: MailEngine, settings: AppSettings, account_id: Optional[int] = None, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings
        self.account_id = account_id
        self._is_loading = True
        
        self.setWindowTitle("Dışa Aktarım ve Sunucu Eşleştirme Ayarları")
        self.resize(1000, 650)
        
        self.match_completed.connect(self._on_match_completed)
        self.match_failed.connect(self._on_match_failed)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
            }
            QGroupBox {
                color: #1e293b;
                font-weight: bold;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 18px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
                color: #4361ee;
            }
            QLabel {
                color: #475569;
                font-weight: bold;
                font-size: 11px;
                background: transparent;
            }
            QLineEdit, QComboBox, QDateEdit {
                background-color: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 5px;
                font-size: 11px;
            }
            QLineEdit:focus, QComboBox:focus, QDateEdit:focus {
                border: 1px solid #4361ee;
            }
            QPushButton {
                background-color: #f1f5f9;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e2e8f0;
                border-color: #94a3b8;
            }
        """)
        
        self._setup_ui()
        self._load_profiles()
        self._load_folders_from_db()
        self._is_loading = False
        self._on_format_changed()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        
        main_columns_layout = QHBoxLayout(scroll_content)
        main_columns_layout.setSpacing(16)
        main_columns_layout.setContentsMargins(0, 0, 0, 0)

        # Left Column: Profile & Target/Server settings
        left_col = QVBoxLayout()
        left_col.setSpacing(10)

        prof_group = QGroupBox("Kayıtlı Profiller / Şablonlar")
        prof_form = QFormLayout(prof_group)
        prof_form.setSpacing(6)
        
        self.combo_profile = QComboBox()
        self.combo_profile.currentIndexChanged.connect(self._on_profile_selection_changed)
        prof_form.addRow("Profil:", self.combo_profile)

        self.input_profile_name = QLineEdit()
        self.input_profile_name.setPlaceholderText("Yeni Profil Adı...")
        prof_form.addRow("Profil Adı:", self.input_profile_name)

        prof_btns = QHBoxLayout()
        self.btn_save_profile = QPushButton("💾 Kaydet")
        self.btn_save_profile.setStyleSheet("background:#10b981; color:white; font-weight:bold; padding:6px;")
        self.btn_save_profile.clicked.connect(self._save_current_profile)

        self.btn_copy_profile = QPushButton("📋 Kopyala")
        self.btn_copy_profile.setStyleSheet("background:#3b82f6; color:white; font-weight:bold; padding:6px;")
        self.btn_copy_profile.clicked.connect(self._copy_current_profile)

        self.btn_delete_profile = QPushButton("🗑 Sil")
        self.btn_delete_profile.setStyleSheet("background:#ef4444; color:white; font-weight:bold; padding:6px;")
        self.btn_delete_profile.clicked.connect(self._delete_selected_profile)

        prof_btns.addWidget(self.btn_save_profile)
        prof_btns.addWidget(self.btn_copy_profile)
        prof_btns.addWidget(self.btn_delete_profile)
        prof_form.addRow("", prof_btns)
        
        left_col.addWidget(prof_group)

        config_group = QGroupBox("Hedef Biçim ve Sunucu Ayarları")
        opts_form = QFormLayout(config_group)
        opts_form.setSpacing(8)

        self.combo_format = QComboBox()
        self.combo_format.addItem("ZIP Arşivi (.zip)", "ZIP")
        self.combo_format.addItem("EML Dizin Yapısı (Thunderbird / Opera)", "DIRECTORY")
        self.combo_format.addItem("JSON Meta Veri Dosyası (.json)", "JSON")
        self.combo_format.addItem("MBOX Dosya Paketi (.mbox)", "MBOX")
        self.combo_format.addItem("IMAP Mail Sunucusu (Server Migration)", "IMAP_SERVER")
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)
        opts_form.addRow("Hedef Format:", self.combo_format)

        self.path_label = QLabel("Hedef Dizin:")
        self.path_layout = QHBoxLayout()
        self.input_path = QLineEdit()
        self.input_path.setReadOnly(True)
        self.input_path.setPlaceholderText("Hedef dizin seçin...")
        self.btn_browse = QPushButton("Gözat...")
        self.btn_browse.setStyleSheet("background:#cbd5e1; padding:4px 8px; font-weight:bold;")
        self.btn_browse.clicked.connect(self._on_browse)
        self.path_layout.addWidget(self.input_path)
        self.path_layout.addWidget(self.btn_browse)
        opts_form.addRow(self.path_label, self.path_layout)

        self.server_group = QWidget()
        server_form = QFormLayout(self.server_group)
        server_form.setContentsMargins(0, 0, 0, 0)
        server_form.setSpacing(6)

        # Dynamic Load Account Combo
        self.combo_load_account = QComboBox()
        self.combo_load_account.addItem("— Kayıtlı Hesaplardan Doldur... —", None)
        try:
            if self.engine and hasattr(self.engine, "accounts"):
                for acc in self.engine.accounts.list_all():
                    lbl = f"👤 {acc.get('label') or 'Hesap'} ({acc.get('email')})"
                    self.combo_load_account.addItem(lbl, acc)
        except Exception:
            pass
        self.combo_load_account.currentIndexChanged.connect(self._on_load_account_changed)
        server_form.addRow("Dinamik Hesap:", self.combo_load_account)

        # Saved Target Server Combo & Actions
        self.combo_saved_servers = QComboBox()
        self.combo_saved_servers.currentIndexChanged.connect(self._on_saved_server_changed)
        server_form.addRow("Kayıtlı Sunucu:", self.combo_saved_servers)

        srv_btns = QHBoxLayout()
        self.btn_save_server = QPushButton("💾 Sunucuyu Kaydet")
        self.btn_save_server.setStyleSheet("background:#10b981; color:white; font-weight:bold; padding:4px 8px; font-size:11px;")
        self.btn_save_server.clicked.connect(self._save_target_server)

        self.btn_delete_server = QPushButton("🗑️ Sunucuyu Sil")
        self.btn_delete_server.setStyleSheet("background:#ef4444; color:white; font-weight:bold; padding:4px 8px; font-size:11px;")
        self.btn_delete_server.clicked.connect(self._delete_target_server)

        srv_btns.addWidget(self.btn_save_server)
        srv_btns.addWidget(self.btn_delete_server)
        server_form.addRow("", srv_btns)
        
        self.input_host = QLineEdit()
        self.input_host.setPlaceholderText("Örn: imap.mail.com")
        server_form.addRow("Sunucu Adresi:", self.input_host)
        
        port_layout = QHBoxLayout()
        self.input_port = QLineEdit("993")
        self.input_port.setFixedWidth(60)
        self.chk_ssl = QCheckBox("SSL/TLS")
        self.chk_ssl.setChecked(True)
        self.chk_ssl.setStyleSheet("color:#1e293b; font-weight:bold;")
        port_layout.addWidget(self.input_port)
        port_layout.addWidget(self.chk_ssl)
        port_layout.addStretch()
        server_form.addRow("Port Yapılandırması:", port_layout)
        
        self.input_username = QLineEdit()
        self.input_username.setPlaceholderText("Kullanıcı adı veya E-posta")
        server_form.addRow("Kullanıcı Adı:", self.input_username)
        
        self.input_password = QLineEdit()
        self.input_password.setPlaceholderText("Posta kutusu şifresi")
        self.input_password.setEchoMode(QLineEdit.Password)
        server_form.addRow("Şifre:", self.input_password)

        self.btn_test_target = QPushButton("🔌 Sunucu Bağlantısını Test Et")
        self.btn_test_target.setStyleSheet("background:#4361ee; color:white; font-weight:bold; padding:6px;")
        self.btn_test_target.clicked.connect(self._test_target_connection)
        server_form.addRow("", self.btn_test_target)

        self.lbl_target_test_status = QLabel("")
        self.lbl_target_test_status.setStyleSheet("font-size:11px; font-weight:bold;")
        server_form.addRow("", self.lbl_target_test_status)
        opts_form.addRow("", self.server_group)
        
        left_col.addWidget(config_group)
        left_col.addStretch()

        # Right Column: Date Filters and Folders Selection
        right_col = QVBoxLayout()
        right_col.setSpacing(10)

        filters_group = QGroupBox("Tarih Filtresi ve Klasör Seçimi")
        filters_layout = QVBoxLayout(filters_group)
        filters_layout.setSpacing(10)
        filters_layout.setContentsMargins(12, 18, 12, 12)

        dates_form = QFormLayout()
        dates_form.setSpacing(6)

        dates_layout = QHBoxLayout()
        self.chk_since = QCheckBox("Başlangıç:")
        self.chk_since.setStyleSheet("color:#1e293b; font-weight:bold;")
        self.date_since = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_since.setCalendarPopup(True)
        self.date_since.setEnabled(False)
        self.chk_since.toggled.connect(self.date_since.setEnabled)

        self.chk_before = QCheckBox("Bitiş:")
        self.chk_before.setStyleSheet("color:#1e293b; font-weight:bold;")
        self.date_before = QDateEdit(QDate.currentDate())
        self.date_before.setCalendarPopup(True)
        self.date_before.setEnabled(False)
        self.chk_before.toggled.connect(self.date_before.setEnabled)

        dates_layout.addWidget(self.chk_since)
        dates_layout.addWidget(self.date_since)
        dates_layout.addWidget(self.chk_before)
        dates_layout.addWidget(self.date_before)
        dates_form.addRow("Tarih Aralığı:", dates_layout)

        filters_layout.addLayout(dates_form)

        self.folder_list = QListWidget()
        self.folder_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.folder_list.setMinimumHeight(320)
        self.folder_list.setStyleSheet("""
            QListWidget {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
            }
            QListWidget::item {
                background-color: #ffffff;
                padding: 6px 8px;
                border-bottom: 1px solid #f1f5f9;
            }
            QListWidget::item:hover {
                background-color: #f8fafc;
            }
            QListWidget::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #4361ee;
                border-radius: 3px;
                background-color: #ffffff;
            }
            QListWidget::indicator:checked {
                background-color: #10b981;
                border-color: #10b981;
                image: url("data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20stroke%3D%22white%22%20stroke-width%3D%224%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%3E%3Cpolyline%20points%3D%2220%206%209%2017%204%2012%22%3E%3C%2Fpolyline%3E%3C%2Fsvg%3E");
            }
            QListWidget::indicator:unchecked {
                background-color: #ffffff;
            }
        """)
        self.folder_list.itemChanged.connect(self._on_folder_item_changed)
        
        folder_ctrls = QHBoxLayout()
        btn_all = QPushButton("Tümü")
        btn_all.setStyleSheet("background-color: #2563eb !important; color: #ffffff !important; font-weight: bold; padding: 4px 12px; font-size: 11px; border-radius: 4px;")
        btn_all.clicked.connect(self._select_all_folders)

        btn_none = QPushButton("Temizle")
        btn_none.setStyleSheet("background-color: #2563eb !important; color: #ffffff !important; font-weight: bold; padding: 4px 12px; font-size: 11px; border-radius: 4px;")
        btn_none.clicked.connect(self._select_none_folders)

        self.btn_fetch_server_folders = QPushButton("🔍 Sunucudan Oku ve Eşleştir")
        self.btn_fetch_server_folders.setToolTip(
            "Hedef IMAP sunucusuna bağlanarak sunucudaki klasör listesini okur ve "
            "yerel klasörlerinizle eşleşen standart klasörleri (Gelen, Gönderilen, "
            "Taslaklar, Çöp, Arşiv, Spam) otomatik olarak seçer."
        )
        self.btn_fetch_server_folders.setStyleSheet("background-color: #2563eb !important; color: #ffffff !important; font-weight: bold; padding: 4px 12px; font-size: 11px; border-radius: 4px;")
        self.btn_fetch_server_folders.clicked.connect(self._fetch_server_folders_and_recommend)

        folder_ctrls.addWidget(btn_all)
        folder_ctrls.addWidget(btn_none)
        folder_ctrls.addWidget(self.btn_fetch_server_folders)
        folder_ctrls.addStretch()

        self.lbl_folder_summary = QLabel("Seçilen Klasörler: 0 / 0")
        self.lbl_folder_summary.setStyleSheet("color:#10b981; font-weight:bold; font-size:11px;")
        folder_ctrls.addWidget(self.lbl_folder_summary)

        warning_label = QLabel("⚠️ Hedef sunucuda eşleşen klasörlerin gönderilmesi önerilir.")
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet("background-color:#fffbeb; color:#b45309; border:1px solid #fef3c7; border-radius:6px; padding:6px; font-size:11px; font-weight:bold;")
        filters_layout.addWidget(warning_label)
        filters_layout.addWidget(QLabel("Klasör Listesi:"))
        filters_layout.addWidget(self.folder_list)
        filters_layout.addLayout(folder_ctrls)

        right_col.addWidget(filters_group)

        main_columns_layout.addLayout(left_col, 1)
        main_columns_layout.addLayout(right_col, 1)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b_ok = buttons.button(QDialogButtonBox.Ok)
        if b_ok:
            b_ok.setText("Uygula")
            b_ok.setStyleSheet("background-color: #2563eb !important; color: #ffffff !important; font-weight: bold; padding: 8px 20px; border-radius: 6px; min-width: 90px;")
        b_cancel = buttons.button(QDialogButtonBox.Cancel)
        if b_cancel:
            b_cancel.setText("İptal")
            b_cancel.setStyleSheet("background-color: #2563eb !important; color: #ffffff !important; font-weight: bold; padding: 8px 20px; border-radius: 6px; min-width: 90px;")

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_profiles(self):
        self.combo_profile.blockSignals(True)
        self.combo_profile.clear()
        self.combo_profile.addItem("— Yeni Profil / Yapılandırma —", None)
        profiles = self.settings.get("export_profiles", [])
        for p in profiles:
            if isinstance(p, dict) and p.get("name"):
                self.combo_profile.addItem(p["name"], p)
        self.combo_profile.blockSignals(False)
        self._load_saved_servers()

    def _load_saved_servers(self):
        if not hasattr(self, "combo_saved_servers"):
            return
        self.combo_saved_servers.blockSignals(True)
        self.combo_saved_servers.clear()
        self.combo_saved_servers.addItem("— Kayıtlı Sunucu Seçin —", None)
        servers = self.settings.get("saved_target_servers", [])
        for s in servers:
            if isinstance(s, dict) and s.get("name"):
                self.combo_saved_servers.addItem(s["name"], s)
        self.combo_saved_servers.blockSignals(False)

    @Slot(int)
    def _on_load_account_changed(self, idx: int):
        if getattr(self, '_is_loading', False) or idx <= 0:
            return
        acc = self.combo_load_account.itemData(idx)
        if not acc or not isinstance(acc, dict):
            return
            
        self.input_host.setText(acc.get("imap_host", ""))
        self.input_port.setText(str(acc.get("imap_port", 993)))
        self.chk_ssl.setChecked(bool(acc.get("use_ssl", True)))
        self.input_username.setText(acc.get("username") or acc.get("email") or "")
        
        pwd_enc = acc.get("password_encrypted", "")
        if pwd_enc:
            try:
                dec_pwd = self.engine.crypto.decrypt(pwd_enc)
                self.input_password.setText(dec_pwd)
            except Exception:
                self.input_password.clear()
        else:
            self.input_password.clear()

    @Slot(int)
    def _on_saved_server_changed(self, idx: int):
        if getattr(self, '_is_loading', False) or idx <= 0:
            return
        srv = self.combo_saved_servers.itemData(idx)
        if not srv or not isinstance(srv, dict):
            return
            
        self.input_host.setText(srv.get("imap_host", ""))
        self.input_port.setText(str(srv.get("imap_port", 993)))
        self.chk_ssl.setChecked(bool(srv.get("imap_ssl", True)))
        self.input_username.setText(srv.get("imap_username", ""))
        
        pwd_enc = srv.get("imap_password_enc", "")
        if pwd_enc:
            try:
                self.input_password.setText(self.engine.crypto.decrypt(pwd_enc))
            except Exception:
                self.input_password.clear()
        else:
            self.input_password.clear()

    @Slot()
    def _save_target_server(self):
        host = self.input_host.text().strip()
        if not host:
            QMessageBox.warning(self, "Eksik Bilgi", "Lütfen en azından sunucu adresini girin.")
            return

        user = self.input_username.text().strip()
        srv_name = f"{host} ({user})" if user else host

        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Sunucu Kaydet", "Sunucu Şablon Adı:", text=srv_name)
        if not ok or not name.strip():
            return
            
        name = name.strip()
        pwd = self.input_password.text()
        pwd_enc = ""
        if pwd:
            try:
                pwd_enc = self.engine.crypto.encrypt(pwd)
            except Exception:
                pass

        srv_obj = {
            "name": name,
            "imap_host": host,
            "imap_port": self.input_port.text().strip(),
            "imap_ssl": self.chk_ssl.isChecked(),
            "imap_username": user,
            "imap_password_enc": pwd_enc
        }

        servers = self.settings.get("saved_target_servers", [])
        servers = [s for s in servers if isinstance(s, dict) and s.get("name") != name]
        servers.append(srv_obj)
        self.settings.set("saved_target_servers", servers)
        self.settings.save()

        QMessageBox.information(self, "Kaydedildi", f"'{name}' sunucu ayarları kaydedildi.")
        self._load_saved_servers()

    @Slot()
    def _delete_target_server(self):
        idx = self.combo_saved_servers.currentIndex()
        srv = self.combo_saved_servers.itemData(idx)
        if not srv or not isinstance(srv, dict):
            return

        name = srv.get("name")
        if QMessageBox.question(self, "Silmeyi Onayla", f"'{name}' sunucu şablonunu silmek istiyor musunuz?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            servers = self.settings.get("saved_target_servers", [])
            servers = [s for s in servers if isinstance(s, dict) and s.get("name") != name]
            self.settings.set("saved_target_servers", servers)
            self.settings.save()
            
            QMessageBox.information(self, "Silindi", "Sunucu şablonu silindi.")
            self._load_saved_servers()

    @Slot()
    def _copy_current_profile(self):
        curr_name = self.input_profile_name.text().strip() or "Yeni_Profil"
        from PySide6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(self, "Profili Çoğalt / Kopyala", "Yeni Profil Adını Giriniz:", text=f"{curr_name}_Kopya")
        if not ok or not new_name.strip():
            return
            
        new_name = new_name.strip()
        fmt = self.combo_format.currentData()
        pwd = self.input_password.text()
        pwd_enc = ""
        if pwd:
            try:
                pwd_enc = self.engine.crypto.encrypt(pwd)
            except Exception:
                pass

        profile = {
            "name": new_name,
            "format": fmt,
            "target_path": self.input_path.text().strip(),
            "imap_host": self.input_host.text().strip(),
            "imap_port": self.input_port.text().strip(),
            "imap_ssl": self.chk_ssl.isChecked(),
            "imap_username": self.input_username.text().strip(),
            "imap_password_enc": pwd_enc,
            "folders": self._get_selected_folders(),
            "since_date": f"{self.date_since.date().year()}-{self.date_since.date().month():02d}-{self.date_since.date().day():02d} 00:00:00" if self.chk_since.isChecked() else None,
            "before_date": f"{self.date_before.date().year()}-{self.date_before.date().month():02d}-{self.date_before.date().day():02d} 23:59:59" if self.chk_before.isChecked() else None,
        }

        profiles = self.settings.get("export_profiles", [])
        profiles = [p for p in profiles if isinstance(p, dict) and p.get("name") != new_name]
        profiles.append(profile)
        self.settings.set("export_profiles", profiles)
        self.settings.save()

        QMessageBox.information(self, "Profil Kopyalandı", f"'{new_name}' profili başarıyla oluşturuldu.")
        self._load_profiles()
        f_idx = self.combo_profile.findText(new_name)
        if f_idx >= 0:
            self.combo_profile.setCurrentIndex(f_idx)

    @Slot()
    def _delete_selected_profile(self):
        idx = self.combo_profile.currentIndex()
        prof = self.combo_profile.itemData(idx)
        if not prof or not isinstance(prof, dict):
            return

        reply = QMessageBox.question(self, "Sil", f"'{prof.get('name')}' profilini silmek istediğinizden emin misiniz?")
        if reply == QMessageBox.Yes:
            profiles = self.settings.get("export_profiles", [])
            profiles = [p for p in profiles if p.get("name") != prof.get("name")]
            self.settings.set("export_profiles", profiles)
            self.settings.save()
            
            QMessageBox.information(self, "Silindi", "Profil silindi.")
            self._load_profiles()

    def _load_folders_from_db(self):
        self.folder_list.blockSignals(True)
        self.folder_list.clear()
        
        try:
            with self.engine.db.get_conn() as conn:
                if self.account_id:
                    rows = conn.execute(
                        "SELECT DISTINCT folder FROM mail_metadata WHERE account_id=? AND is_deleted=0 ORDER BY folder ASC",
                        (self.account_id,)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT DISTINCT folder FROM mail_metadata WHERE is_deleted=0 ORDER BY folder ASC"
                    ).fetchall()

            from infrastructure.imap_client import format_folder_display_name
            
            for r in rows:
                orig_folder = r["folder"]
                display_name = format_folder_display_name(orig_folder)
                
                item = QListWidgetItem(display_name)
                item.setData(Qt.UserRole, orig_folder)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                
                standard_keywords = ["inbox", "sent", "draft", "spam", "junk", "trash", "archive", 
                                   "gelen", "giden", "gönderilen", "taslak", "çöp", "arşiv", "istenmeyen"]
                is_rec = any(w in display_name.lower() for w in standard_keywords)
                
                if is_rec:
                    item.setCheckState(Qt.Checked)
                    item.setForeground(QColor("#2d6a4f"))
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                else:
                    item.setCheckState(Qt.Unchecked)
                    item.setForeground(QColor("#64748b"))
                
                self.folder_list.addItem(item)
        except Exception as exc:
            logger.error("Failed to load folder list: %s", exc)
        finally:
            self.folder_list.blockSignals(False)

    def _select_all_folders(self):
        self.folder_list.blockSignals(True)
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            item.setCheckState(Qt.Checked)
            item.setForeground(QColor("#10b981"))
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        self.folder_list.blockSignals(False)
        total = self.folder_list.count()
        self.lbl_folder_summary.setText(f"Seçilen Klasörler: {total} / {total}")

    def _select_none_folders(self):
        self.folder_list.blockSignals(True)
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            item.setCheckState(Qt.Unchecked)
            item.setForeground(QColor("#64748b"))
            f = item.font()
            f.setBold(False)
            item.setFont(f)
        self.folder_list.blockSignals(False)
        self.lbl_folder_summary.setText(f"Seçilen Klasörler: 0 / {self.folder_list.count()}")

    def _get_selected_folders(self) -> Optional[List[str]]:
        folders = []
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            if item.checkState() == Qt.Checked:
                orig = item.data(Qt.UserRole)
                folders.append(orig if orig is not None else item.text())
        return folders if len(folders) < self.folder_list.count() else None

    @Slot(QListWidgetItem)
    def _on_folder_item_changed(self, item: QListWidgetItem):
        if item.checkState() == Qt.Checked:
            item.setForeground(QColor("#10b981"))
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        else:
            item.setForeground(QColor("#64748b"))
            f = item.font()
            f.setBold(False)
            item.setFont(f)

        total = self.folder_list.count()
        checked = sum(1 for i in range(total) if self.folder_list.item(i).checkState() == Qt.Checked)
        self.lbl_folder_summary.setText(f"Seçilen Klasörler: {checked} / {total}")

    @Slot()
    def _on_format_changed(self):
        fmt = self.combo_format.currentData()
        is_server = (fmt == "IMAP_SERVER")
        self.server_group.setVisible(is_server)
        self.input_path.setVisible(not is_server)
        self.btn_browse.setVisible(not is_server)
        self.path_label.setVisible(not is_server)

    @Slot()
    def _on_browse(self):
        fmt = self.combo_format.currentData()
        if fmt == "ZIP":
            path, _ = QFileDialog.getSaveFileName(self, "Hedef Zip Dosyasını Seçin", "", "Zip Archives (*.zip)")
        elif fmt == "JSON":
            path, _ = QFileDialog.getSaveFileName(self, "Hedef JSON Dosyasını Seçin", "", "JSON Files (*.json)")
        elif fmt == "MBOX":
            path, _ = QFileDialog.getSaveFileName(self, "Hedef MBOX Dosyasını Seçin", "", "MBOX Files (*.mbox)")
        else:
            path = QFileDialog.getExistingDirectory(self, "Hedef Dizin Seçin")
        if path:
            self.input_path.setText(path)

    @Slot(int)
    def _on_profile_selection_changed(self, idx: int):
        if self._is_loading:
            return
        prof = self.combo_profile.itemData(idx)
        if prof is None:
            self.input_profile_name.clear()
            self.input_profile_name.setEnabled(True)
            self.combo_format.setCurrentIndex(0)
            self.input_path.clear()
            self.chk_since.setChecked(False)
            self.chk_before.setChecked(False)
            self.input_host.clear()
            self.input_port.setText("993")
            self.chk_ssl.setChecked(True)
            self.input_username.clear()
            self.input_password.clear()
            self._select_all_folders()
            return
            
        self.input_profile_name.setText(prof.get("name", ""))
        self.input_profile_name.setEnabled(False)
        
        fmt = prof.get("format", "ZIP")
        f_idx = self.combo_format.findData(fmt)
        if f_idx >= 0:
            self.combo_format.setCurrentIndex(f_idx)
            
        self.input_path.setText(prof.get("target_path", ""))
        self.input_host.setText(prof.get("imap_host", ""))
        self.input_port.setText(str(prof.get("imap_port", 993)))
        self.chk_ssl.setChecked(prof.get("imap_ssl", True))
        self.input_username.setText(prof.get("imap_username", ""))
        
        pwd_enc = prof.get("imap_password_enc", "")
        if pwd_enc:
            try:
                self.input_password.setText(self.engine.crypto.decrypt(pwd_enc))
            except Exception:
                self.input_password.clear()
        else:
            self.input_password.clear()

    @Slot()
    def _save_current_profile(self):
        name = self.input_profile_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Eksik Bilgi", "Lütfen bir profil adı girin.")
            return

        fmt = self.combo_format.currentData()
        pwd = self.input_password.text()
        pwd_enc = ""
        if pwd:
            try:
                pwd_enc = self.engine.crypto.encrypt(pwd)
            except Exception:
                pass

        profile = {
            "name": name,
            "format": fmt,
            "target_path": self.input_path.text().strip(),
            "imap_host": self.input_host.text().strip(),
            "imap_port": self.input_port.text().strip(),
            "imap_ssl": self.chk_ssl.isChecked(),
            "imap_username": self.input_username.text().strip(),
            "imap_password_enc": pwd_enc,
            "folders": self._get_selected_folders(),
            "since_date": f"{self.date_since.date().year()}-{self.date_since.date().month():02d}-{self.date_since.date().day():02d} 00:00:00" if self.chk_since.isChecked() else None,
            "before_date": f"{self.date_before.date().year()}-{self.date_before.date().month():02d}-{self.date_before.date().day():02d} 23:59:59" if self.chk_before.isChecked() else None,
        }

        profiles = self.settings.get("export_profiles", [])
        profiles = [p for p in profiles if isinstance(p, dict) and p.get("name") != name]
        profiles.append(profile)
        self.settings.set("export_profiles", profiles)
        self.settings.save()

        QMessageBox.information(self, "Kaydedildi", f"'{name}' profili başarıyla kaydedildi.")
        self._load_profiles()

    @Slot()
    def _delete_selected_profile(self):
        idx = self.combo_profile.currentIndex()
        prof = self.combo_profile.itemData(idx)
        if not prof or not isinstance(prof, dict):
            return

        reply = QMessageBox.question(self, "Sil", f"'{prof.get('name')}' profilini silmek istediğinizden emin misiniz?")
        if reply == QMessageBox.Yes:
            profiles = self.settings.get("export_profiles", [])
            profiles = [p for p in profiles if p.get("name") != prof.get("name")]
            self.settings.set("export_profiles", profiles)
            self.settings.save()
            
            QMessageBox.information(self, "Silindi", "Profil silindi.")
            self._load_profiles()

    @Slot()
    def _test_target_connection(self):
        import time
        import socket
        import ssl as ssl_lib

        host = self.input_host.text().strip()
        port_str = self.input_port.text().strip()
        use_ssl = self.chk_ssl.isChecked()
        user = self.input_username.text().strip()
        pwd = self.input_password.text()

        if not host or not user or not pwd:
            self.lbl_target_test_status.setText("⚠️ Lütfen Sunucu Adresi, Kullanıcı Adı ve Şifre girin")
            self.lbl_target_test_status.setStyleSheet("color: #e67e22;")
            return

        self.btn_test_target.setEnabled(False)
        self.lbl_target_test_status.setText("⏳ Sunucu yanıt süresi ve yetenekleri test ediliyor...")
        self.lbl_target_test_status.setStyleSheet("color: #4361ee;")

        def test():
            start_time = time.time()
            try:
                port = int(port_str) if port_str else (993 if use_ssl else 143)
                if use_ssl:
                    client = imaplib.IMAP4_SSL(host, port, timeout=15)
                else:
                    client = imaplib.IMAP4(host, port, timeout=15)
                
                caps = getattr(client, 'capabilities', None)
                if not caps and hasattr(client, 'welcome'):
                    caps = client.welcome
                caps_str = ", ".join(caps) if isinstance(caps, (list, tuple)) else str(caps or "Standard IMAP4")

                client.login(user, pwd)
                duration_ms = int((time.time() - start_time) * 1000)
                client.logout()

                success_msg = f"✅ Bağlantı Başarılı ({duration_ms} ms) | Port: {port} (SSL: {'Aktif' if use_ssl else 'Pasif'})\nYetki/Modül: {str(caps_str)[:70]}..."
                self.lbl_target_test_status.setText(success_msg)
                self.lbl_target_test_status.setStyleSheet("color: #2d6a4f;")

                detailed_log = (
                    f"🔌 [IMAP Bağlantı Testi Başarılı] Host: {host}:{port} | SSL: {use_ssl} | "
                    f"Kullanıcı: {user} | Yanıt Süresi: {duration_ms} ms | Yetenekler: {caps_str}"
                )
                logger.info(detailed_log)
                if self.parent() and hasattr(self.parent(), '_log_signal'):
                    self.parent()._log_signal.emit(detailed_log)

            except socket.gaierror as e:
                err_text = f"❌ DNS / Sunucu Adresi Bulunamadı ({host})"
                self.lbl_target_test_status.setText(err_text)
                self.lbl_target_test_status.setStyleSheet("color: #e63946;")
                logger.error("IMAP Test Error: DNS resolution failed for %s: %s", host, e)
                if self.parent() and hasattr(self.parent(), '_log_signal'):
                    self.parent()._log_signal.emit(f"❌ [IMAP Test Hatası] Sunucu adresi çözülemedi ({host}): {e}")

            except (TimeoutError, socket.timeout) as e:
                err_text = f"❌ Zaman Aşımı! ({host}:{port_str} yanıt vermiyor)"
                self.lbl_target_test_status.setText(err_text)
                self.lbl_target_test_status.setStyleSheet("color: #e63946;")
                logger.error("IMAP Test Error: Connection timeout for %s:%s: %s", host, port_str, e)
                if self.parent() and hasattr(self.parent(), '_log_signal'):
                    self.parent()._log_signal.emit(f"❌ [IMAP Test Hatası] Sunucu bağlantı zaman aşımı ({host}:{port_str}): {e}")

            except ssl_lib.SSLError as e:
                err_text = f"❌ SSL/TLS Sertifika veya Port Hatası"
                self.lbl_target_test_status.setText(err_text)
                self.lbl_target_test_status.setStyleSheet("color: #e63946;")
                logger.error("IMAP Test Error: SSL failure for %s:%s: %s", host, port_str, e)
                if self.parent() and hasattr(self.parent(), '_log_signal'):
                    self.parent()._log_signal.emit(f"❌ [IMAP Test Hatası] SSL/TLS El sıkışma hatası ({host}:{port_str}): {e}")

            except Exception as e:
                err_msg = str(e)
                if "AUTHENTICATIONFAILED" in err_msg.upper() or "LOGIN" in err_msg.upper() or "AUTHENTICATE" in err_msg.upper():
                    err_text = f"❌ Kimlik Doğrulama Başarısız (Kullanıcı adı veya şifre hatalı)"
                else:
                    err_text = f"❌ Bağlantı Hatası: {err_msg[:60]}"
                self.lbl_target_test_status.setText(err_text)
                self.lbl_target_test_status.setStyleSheet("color: #e63946;")
                logger.error("IMAP Test Error: %s", e)
                if self.parent() and hasattr(self.parent(), '_log_signal'):
                    self.parent()._log_signal.emit(f"❌ [IMAP Test Hatası] {e}")

            finally:
                self.btn_test_target.setEnabled(True)

        threading.Thread(target=test, daemon=True).start()

    def _fetch_server_folders_and_recommend(self):
        host = self.input_host.text().strip()
        port_str = self.input_port.text().strip()
        ssl = self.chk_ssl.isChecked()
        user = self.input_username.text().strip()
        pwd = self.input_password.text()

        if not host or not user or not pwd:
            QMessageBox.warning(self, "Bilgi Eksik", "Lütfen önce sunucu adresi, kullanıcı adı ve şifre bilgilerini doldurun.")
            return

        self.btn_fetch_server_folders.setEnabled(False)
        self.btn_fetch_server_folders.setText("⏳ Sunucudan Okunuyor...")
        
        def task():
            try:
                port = int(port_str) if port_str else (993 if ssl else 143)
                if ssl:
                    client = imaplib.IMAP4_SSL(host, port, timeout=15)
                else:
                    client = imaplib.IMAP4(host, port, timeout=15)
                
                client.login(user, pwd)
                from infrastructure.imap_client import decode_imap_utf7

                list_re = re.compile(
                    r'\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+(?:"(?P<name_quoted>[^"]*)"|(?P<name_unquoted>[^\s]+))'
                )
                
                server_folders = []
                status, list_data = client.list()
                if status == "OK" and list_data:
                    for item in list_data:
                        if not item:
                            continue
                        decoded = item.decode('utf-8', errors='replace')
                        m = list_re.search(decoded)
                        if m:
                            flags = m.group("flags") or ""
                            raw_name = m.group("name_quoted") if m.group("name_quoted") is not None else m.group("name_unquoted")
                            if raw_name:
                                try:
                                    folder_decoded = decode_imap_utf7(raw_name)
                                except Exception:
                                    folder_decoded = raw_name
                                server_folders.append({
                                    "name": folder_decoded.lower(),
                                    "flags": flags.lower()
                                })
                client.logout()

                target_types = set()
                for sf in server_folders:
                    name_lower = sf["name"]
                    flags_lower = sf["flags"]
                    
                    if '\\inbox' in flags_lower or 'inbox' in name_lower or 'gelen' in name_lower:
                        target_types.add('inbox')
                    elif '\\sent' in flags_lower or any(p in name_lower for p in ('sent', 'gönderilen', 'gönderilmiş', 'giden')):
                        target_types.add('sent')
                    elif '\\drafts' in flags_lower or any(p in name_lower for p in ('draft', 'taslak')):
                        target_types.add('drafts')
                    elif '\\junk' in flags_lower or '\\spam' in flags_lower or any(p in name_lower for p in ('spam', 'junk', 'istenmeyen')):
                        target_types.add('spam')
                    elif '\\trash' in flags_lower or any(p in name_lower for p in ('trash', 'çöp', 'silinmiş')):
                        target_types.add('trash')
                    elif '\\archive' in flags_lower or any(p in name_lower for p in ('archive', 'arşiv')):
                        target_types.add('archive')

                self.match_completed.emit(list(target_types))
            except Exception as e:
                self.match_failed.emit(str(e))

        threading.Thread(target=task, daemon=True).start()

    @Slot(list)
    def _on_match_completed(self, target_types):
        from infrastructure.imap_client import decode_imap_utf7
        self.folder_list.blockSignals(True)
        
        matched_count = 0
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            orig_folder = item.data(Qt.UserRole)
            
            decoded = orig_folder
            try:
                if orig_folder.startswith("_") and orig_folder.endswith("-"):
                    temp = "&" + orig_folder[1:].replace("_", "/")
                    decoded = decode_imap_utf7(temp)
                elif orig_folder.startswith("&"):
                    decoded = decode_imap_utf7(orig_folder)
            except Exception:
                pass
            
            decoded_lower = decoded.lower()
            
            folder_type = decoded_lower
            if 'sent' in decoded_lower or 'giden' in decoded_lower:
                folder_type = 'sent'
            elif 'draft' in decoded_lower or 'taslak' in decoded_lower:
                folder_type = 'drafts'
            elif 'spam' in decoded_lower or 'junk' in decoded_lower or 'istenmeyen' in decoded_lower:
                folder_type = 'spam'
            elif 'trash' in decoded_lower or 'çöp' in decoded_lower:
                folder_type = 'trash'
            elif 'archive' in decoded_lower or 'arşiv' in decoded_lower:
                folder_type = 'archive'
            elif 'inbox' in decoded_lower or 'gelen' in decoded_lower:
                folder_type = 'inbox'

            if folder_type in target_types:
                item.setCheckState(Qt.Checked)
                item.setForeground(QColor("#2d6a4f"))
                f = item.font()
                f.setBold(True)
                item.setFont(f)
                matched_count += 1
            else:
                item.setCheckState(Qt.Unchecked)
                item.setForeground(QColor("#64748b"))
                f = item.font()
                f.setBold(False)
                item.setFont(f)

        self.folder_list.blockSignals(False)
        total = self.folder_list.count()
        self.lbl_folder_summary.setText(f"Seçilen Klasörler: {matched_count} / {total}")
        
        self.btn_fetch_server_folders.setEnabled(True)
        self.btn_fetch_server_folders.setText("🔍 Sunucudan Oku ve Eşleştir")
        
        QMessageBox.information(
            self, 
            "Eşleştirme Tamamlandı", 
            f"Hedef sunucu ile eşleşen {matched_count} adet klasör otomatik seçildi."
        )

    @Slot(str)
    def _on_match_failed(self, err_msg):
        self.btn_fetch_server_folders.setEnabled(True)
        self.btn_fetch_server_folders.setText("🔍 Sunucudan Oku ve Eşleştir")
        QMessageBox.critical(self, "Bağlantı Hatası", f"Sunucu klasörleri okunurken hata oluştu:\n{err_msg}")


class ExportConfirmDialog(QDialog):
    def __init__(self, account_previews: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dışa Aktarım Planını Onayla")
        self.resize(950, 500)
        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
            }
            QPushButton, QDialogButtonBox QPushButton {
                background-color: #2563eb !important;
                color: #ffffff !important;
                font-weight: bold;
                font-size: 13px;
                padding: 10px 24px;
                border-radius: 6px;
                border: none;
                min-width: 110px;
                min-height: 28px;
            }
            QPushButton:hover, QDialogButtonBox QPushButton:hover {
                background-color: #1d4ed8 !important;
                color: #ffffff !important;
            }
            QPushButton:pressed, QDialogButtonBox QPushButton:pressed {
                background-color: #1e40af !important;
                color: #ffffff !important;
            }
            QPushButton:disabled, QDialogButtonBox QPushButton:disabled {
                background-color: #94a3b8 !important;
                color: #f8fafc !important;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header_layout = QHBoxLayout()
        header_icon = QLabel("📊")
        header_icon.setStyleSheet("font-size: 24px;")
        header_layout.addWidget(header_icon)
        
        header_title = QLabel(f"<b>Dışa Aktarım Planı Detayları</b><br/>{len(account_previews)} adet hesabın verileri aktarılacaktır:")
        header_title.setStyleSheet("font-size: 13px; color: #1e293b;")
        header_layout.addWidget(header_title, 1)
        layout.addLayout(header_layout)

        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels([
            "Hesap Adı / E-Posta", "Format", "Hedef Dosya / Dizin", "Klasör Sayısı", "Aktarılacak Mail Sayısı"
        ])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                color: #1e293b;
                font-size: 11px;
            }
        """)

        total_mails = 0
        table.setRowCount(len(account_previews))
        for i, prev in enumerate(account_previews):
            table.setItem(i, 0, QTableWidgetItem(prev["label"]))
            table.setItem(i, 1, QTableWidgetItem(prev["format"]))
            table.setItem(i, 2, QTableWidgetItem(prev["resolved_target"]))
            table.setItem(i, 3, QTableWidgetItem(str(prev["folders"])))
            table.setItem(i, 4, QTableWidgetItem(str(prev["mails"])))
            total_mails += prev["mails"]

        layout.addWidget(table)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_ok = btns.button(QDialogButtonBox.Ok)
        if btn_ok:
            btn_ok.setText("Evet, Başlat")
            btn_ok.setStyleSheet("background-color: #2563eb !important; color: #ffffff !important; font-weight: bold; padding: 10px 24px; border-radius: 6px; font-size: 13px; min-width: 110px;")

        btn_cancel = btns.button(QDialogButtonBox.Cancel)
        if btn_cancel:
            btn_cancel.setText("İptal")
            btn_cancel.setStyleSheet("background-color: #2563eb !important; color: #ffffff !important; font-weight: bold; padding: 10px 24px; border-radius: 6px; font-size: 13px; min-width: 110px;")

        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)


# ---------------------------------------------------------------------------
# Main ExportPanel (ThreePanel Workspace Layout)
# ---------------------------------------------------------------------------

class ExportPanel(QWidget):
    """Full-page panel for configuring export definitions & running server migrations with 3 panels."""

    _log_signal = Signal(str)
    _progress_signal = Signal(int, str, int, int, object)
    _export_done_signal = Signal(int, object)
    _export_error_signal = Signal(int, str)
    _overall_progress_signal = Signal(int)
    _export_all_finished_signal = Signal()

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.settings = AppSettings()
        
        self._active_exports = {}
        self._accounts_ui = {}
        self._all_selected_flag = False
        self._current_config = {
            "format": "ZIP",
            "target_path": str(Path("data/exports")),
            "imap_host": "",
            "imap_port": "993",
            "imap_ssl": True,
            "imap_username": "",
            "imap_password": "",
            "folders": None,
            "since_date": None,
            "before_date": None,
        }

        self._setup_ui()
        self.refresh()

        self._log_signal.connect(self._on_log_message)
        self._progress_signal.connect(self._on_export_progress)
        self._export_done_signal.connect(self._on_export_done)
        self._export_error_signal.connect(self._on_export_error)
        self._overall_progress_signal.connect(self._on_overall_progress)
        self._export_all_finished_signal.connect(self._on_export_all_finished)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # -------------------------------------------------------------------
        # ThreePanel Workspace Container
        # -------------------------------------------------------------------
        self.workspace = ThreePanelWorkspaceTemplate(title="Export & Server Migration Workspace", parent=self)
        main_layout.addWidget(self.workspace)

        # Build Left Panel (Sol Panel: Domain & Group Filters)
        self._setup_left_panel()

        # Build Center Panel (Orta Panel: Pro Grid Table)
        self._setup_center_panel()

        # Build Right Panel (Sağ Panel: Operations & Live Logs)
        self._setup_right_panel()

        # Load persisted layout states
        self.workspace.load_splitter_state(self.settings, "export_workspace")
        self.grid.load_grid_state()

    # -----------------------------------------------------------------------
    # Sol Panel Setup
    # -----------------------------------------------------------------------
    def _setup_left_panel(self):
        left_layout = self.workspace.left_inner_layout

        # Domain Filter Combo
        left_layout.addWidget(QLabel("🌐 Domain Filtresi:"))
        self.combo_domain = QComboBox()
        self.combo_domain.setStyleSheet("""
            QComboBox {
                background-color: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 5px;
                font-size: 11px;
            }
        """)
        self.combo_domain.currentIndexChanged.connect(self._apply_filters)
        left_layout.addWidget(self.combo_domain)

        # Group Filter Combo
        left_layout.addWidget(QLabel("👥 Grup Filtresi:"))
        self.combo_group = QComboBox()
        self.combo_group.setStyleSheet(self.combo_domain.styleSheet())
        self.combo_group.currentIndexChanged.connect(self._apply_filters)
        left_layout.addWidget(self.combo_group)

        left_layout.addSpacing(10)

        # Quick Select Action Buttons
        self.btn_select_all = QPushButton("✔️ Tümünü Seç")
        self.btn_select_all.setStyleSheet("""
            QPushButton {
                background-color: #e0e7ff;
                color: #3730a3;
                font-weight: bold;
                border: 1px solid #c7d2fe;
                border-radius: 5px;
                padding: 6px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #c7d2fe; }
        """)
        self.btn_select_all.clicked.connect(lambda: self._set_all_checkboxes(True))
        left_layout.addWidget(self.btn_select_all)

        self.btn_deselect_all = QPushButton("❌ Seçimleri Temizle")
        self.btn_deselect_all.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #475569;
                font-weight: bold;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 6px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #e2e8f0; }
        """)
        self.btn_deselect_all.clicked.connect(lambda: self._set_all_checkboxes(False))
        left_layout.addWidget(self.btn_deselect_all)

        self.btn_reset_filters = QPushButton("🔄 Filtreleri Sıfırla")
        self.btn_reset_filters.setStyleSheet(self.btn_deselect_all.styleSheet())
        self.btn_reset_filters.clicked.connect(self._reset_filters)
        left_layout.addWidget(self.btn_reset_filters)

        left_layout.addStretch()

        # Status Summary Badge in Left Sidebar
        self.lbl_left_summary = QLabel("Hesaplar yükleniyor...")
        self.lbl_left_summary.setWordWrap(True)
        self.lbl_left_summary.setStyleSheet("""
            QLabel {
                background-color: #f8fafc;
                color: #334155;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                padding: 8px;
                font-size: 11px;
                font-weight: 600;
            }
        """)
        left_layout.addWidget(self.lbl_left_summary)

    # -----------------------------------------------------------------------
    # Orta Panel Setup (ProGrid)
    # -----------------------------------------------------------------------
    def _setup_center_panel(self):
        center_layout = self.workspace.center_layout

        self.grid = ProGridWidget(settings=self.settings, grid_id="export_workspace", parent=self)
        self.account_table = self.grid.table

        # Configure columns for maximum legibility and readability
        self.account_table.setColumnCount(9)
        self.account_table.setHorizontalHeaderLabels([
            "Seç", "Hesap Etiketi", "E-Posta Adresi", "Domain / Grup", 
            "Sunucu", "Yerel İstatistik", "Hedef Profil", "Durum & İlerleme", "Aksiyonlar"
        ])
        
        header = self.account_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)

        self.account_table.setColumnWidth(1, 160)
        self.account_table.setColumnWidth(2, 220)
        self.account_table.setColumnWidth(3, 140)
        self.account_table.setColumnWidth(4, 150)

        self.grid.filter_changed.connect(self._apply_filters)
        center_layout.addWidget(self.grid)

    # -----------------------------------------------------------------------
    # Sağ Panel Setup (İşlem & Live Logs)
    # -----------------------------------------------------------------------
    def _setup_right_panel(self):
        right_layout = self.workspace.right_inner_layout

        # Top Section: Metric Stat Cards
        stats_layout = QVBoxLayout()
        stats_layout.setSpacing(6)

        row1 = QHBoxLayout()
        self.card_total_mails = StatCard("Arşivdeki Mailler", "0000", bg_color="#3b82f6", callback=self._show_archived_emails_info)
        self.card_exported_count = StatCard("Aktarılanlar", "0000", bg_color="#10b981", callback=self._show_exported_count_info)
        row1.addWidget(self.card_total_mails)
        row1.addWidget(self.card_exported_count)

        row2 = QHBoxLayout()
        self.card_error_count = StatCard("Hatalar", "0000", bg_color="#ef4444", callback=self._show_errors_info)
        self.card_status = StatCard("Durum", "Idle", bg_color="#6366f1", callback=self._show_migration_status_info)
        row2.addWidget(self.card_error_count)
        row2.addWidget(self.card_status)

        self.card_total_selected = StatCard("Seçilen Hesaplar", "0000", bg_color="#475569", callback=self._show_selected_accounts_info)

        stats_layout.addLayout(row1)
        stats_layout.addLayout(row2)
        stats_layout.addWidget(self.card_total_selected)
        right_layout.addLayout(stats_layout)

        right_layout.addSpacing(6)

        # Primary Action Buttons
        self.btn_export_selected = QPushButton("🚀 SEÇİLİ HESAPLARDA DIŞA AKTAR")
        self.btn_export_selected.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                font-weight: 900;
                border: 1.5px solid #059669;
                border-radius: 6px;
                padding: 10px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #059669; }
        """)
        self.btn_export_selected.clicked.connect(self._run_export_on_checked)
        right_layout.addWidget(self.btn_export_selected)

        self.btn_check_inodes = QPushButton("🔍 INODE / MESAJ SAYILARINI KONTROL ET")
        self.btn_check_inodes.setStyleSheet("""
            QPushButton {
                background-color: #4361ee;
                color: white;
                font-weight: 900;
                border: 1.5px solid #3a56d4;
                border-radius: 6px;
                padding: 8px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #3a56d4; }
        """)
        self.btn_check_inodes.clicked.connect(self._check_inodes_and_report)
        right_layout.addWidget(self.btn_check_inodes)

        self.btn_configure = QPushButton("⚙️ HEDEF VE FİLTRE YAPILANDIRMASI")
        self.btn_configure.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #0f172a;
                font-weight: 800;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #e2e8f0; }
        """)
        self.btn_configure.clicked.connect(self._open_config_dialog)
        right_layout.addWidget(self.btn_configure)

        right_layout.addSpacing(6)

        # Bottom Section: Splitter for Live Mail Report & Console Log
        right_splitter = QSplitter(Qt.Vertical)

        # Inode / Mail Report Table
        self.report_table = QTableWidget()
        self.report_table.setColumnCount(4)
        self.report_table.setHorizontalHeaderLabels(["Klasör / Mail", "Gönderen", "Tarih", "Durum"])
        self.report_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.report_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.report_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.report_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.report_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.report_table.verticalHeader().setVisible(False)
        self.report_table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                color: #0f172a;
                gridline-color: #f1f5f9;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-size: 10px;
            }
        """)
        right_splitter.addWidget(self.report_table)

        # Log Output Console
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("""
            QTextEdit {
                background: #1e293b;
                color: #a8d8ea;
                font-family: 'Consolas', monospace;
                font-size: 10px;
                border-radius: 6px;
            }
        """)
        right_splitter.addWidget(self.log_output)

        right_splitter.setSizes([140, 100])
        right_layout.addWidget(right_splitter, stretch=1)

        # Progress bar
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        self.overall_progress.setVisible(False)
        self.overall_progress.setMaximumHeight(8)
        self.overall_progress.setTextVisible(False)
        right_layout.addWidget(self.overall_progress)

    # -----------------------------------------------------------------------
    # Filters & Filtering Logic
    # -----------------------------------------------------------------------

    @Slot()
    def _apply_filters(self):
        sel_domain = self.combo_domain.currentText()
        sel_group = self.combo_group.currentText()
        search_text = self.grid.input_search.text().strip().lower()

        total_rows = self.account_table.rowCount()
        visible_rows = 0

        for row in range(total_rows):
            domain_item = self.account_table.item(row, 3)
            domain_group_str = domain_item.text() if domain_item else ""

            match_domain = (sel_domain == "Tüm Domainler" or sel_domain.lower() in domain_group_str.lower())
            match_group = (sel_group == "Tüm Gruplar" or sel_group.lower() in domain_group_str.lower())

            # Text search matching label (col 1), email (col 2), host (col 4)
            match_text = True
            if search_text:
                lbl_text = self.account_table.item(row, 1).text().lower() if self.account_table.item(row, 1) else ""
                email_text = self.account_table.item(row, 2).text().lower() if self.account_table.item(row, 2) else ""
                host_text = self.account_table.item(row, 4).text().lower() if self.account_table.item(row, 4) else ""
                match_text = (search_text in lbl_text or search_text in email_text or search_text in host_text)

            is_visible = match_domain and match_group and match_text
            self.account_table.setRowHidden(row, not is_visible)
            if is_visible:
                visible_rows += 1

        self.grid.lbl_counter.setText(f"{visible_rows} / {total_rows} Kayıt")
        self.lbl_left_summary.setText(f"Görüntülenen: {visible_rows} / {total_rows} hesap\nDomain: {sel_domain}\nGrup: {sel_group}")

    @Slot()
    def _reset_filters(self):
        self.combo_domain.setCurrentIndex(0)
        self.combo_group.setCurrentIndex(0)
        self.grid.input_search.clear()
        self._apply_filters()

    def _set_all_checkboxes(self, state: bool):
        for row in range(self.account_table.rowCount()):
            if not self.account_table.isRowHidden(row):
                widget = self.account_table.cellWidget(row, 0)
                if widget:
                    chk = widget.findChild(QCheckBox)
                    if chk:
                        chk.setChecked(state)
        self._update_stats_on_selection()

    # -----------------------------------------------------------------------
    # Helper & Slot implementations
    # -----------------------------------------------------------------------

    @Slot()
    def _open_config_dialog(self, account_id: Optional[int] = None):
        if account_id is None:
            checked = self._get_checked_account_ids()
            if checked:
                account_id = checked[0]

        dialog = ExportConfigDialog(self.engine, self.settings, account_id=account_id, parent=self)
        
        c = self._current_config
        f_idx = dialog.combo_format.findData(c["format"])
        if f_idx >= 0:
            dialog.combo_format.setCurrentIndex(f_idx)
        dialog.input_path.setText(c["target_path"])
        dialog.input_host.setText(c["imap_host"])
        dialog.input_port.setText(c["imap_port"])
        dialog.chk_ssl.setChecked(c["imap_ssl"])
        dialog.input_username.setText(c["imap_username"])
        dialog.input_password.setText(c["imap_password"])
        
        if dialog.exec() == QDialog.Accepted:
            fmt = dialog.combo_format.currentData()
            self._current_config = {
                "format": fmt,
                "target_path": dialog.input_path.text().strip(),
                "imap_host": dialog.input_host.text().strip(),
                "imap_port": dialog.input_port.text().strip(),
                "imap_ssl": dialog.chk_ssl.isChecked(),
                "imap_username": dialog.input_username.text().strip(),
                "imap_password": dialog.input_password.text(),
                "folders": dialog._get_selected_folders(),
                "since_date": f"{dialog.date_since.date().year()}-{dialog.date_since.date().month():02d}-{dialog.date_since.date().day():02d} 00:00:00" if dialog.chk_since.isChecked() else None,
                "before_date": f"{dialog.date_before.date().year()}-{dialog.date_before.date().month():02d}-{dialog.date_before.date().day():02d} 23:59:59" if dialog.chk_before.isChecked() else None,
            }
            self.refresh()
            self.log_output.append("Export ayarları başarıyla güncellendi.")

    @Slot(QComboBox)
    def _open_config_dialog_for_combo(self, combo: QComboBox, account_id: Optional[int] = None):
        selected_name = combo.currentText()
        dialog = ExportConfigDialog(self.engine, self.settings, account_id=account_id, parent=self)
        
        if selected_name != "Default (ZIP)":
            profiles = self.settings.get("export_profiles", [])
            prof = next((p for p in profiles if isinstance(p, dict) and p.get("name") == selected_name), None)
            if prof:
                f_idx = dialog.combo_profile.findText(selected_name)
                if f_idx >= 0:
                    dialog.combo_profile.setCurrentIndex(f_idx)
                    
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    def _show_info_dialog(self, title: str, text: str):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(550, 320)
        dialog.setStyleSheet("QDialog { background-color: #f8fafc; } QLabel { color: #1e293b; font-weight: bold; }")
        layout = QVBoxLayout(dialog)
        
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(text)
        txt.setStyleSheet("QTextEdit { background-color: #ffffff; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 12px; padding: 10px; }")
        layout.addWidget(txt)
        
        btn = QPushButton("Kapat")
        btn.setStyleSheet("QPushButton { background-color: #4361ee; color: white; font-weight: bold; padding: 6px 18px; border-radius: 4px; } QPushButton:hover { background-color: #3a56d4; }")
        btn.clicked.connect(dialog.accept)
        layout.addWidget(btn, 0, Qt.AlignCenter)
        dialog.exec()

    def _show_selected_accounts_info(self):
        checked_ids = self._get_checked_account_ids()
        if not checked_ids:
            msg = "Şu anda tabloda hiçbir hesap seçili değil.\nLütfen en az bir hesabın onay kutusunu işaretleyin."
        else:
            msg = f"Seçilen hesap sayısı: {len(checked_ids)}\n\nHesap Listesi:\n"
            try:
                with self.engine.db.get_conn() as conn:
                    placeholders = ",".join("?" for _ in checked_ids)
                    rows = conn.execute(f"SELECT id, label, email FROM accounts WHERE id IN ({placeholders})").fetchall()
                    for idx, r in enumerate(rows):
                        msg += f"  {idx+1}. Etiket: {r['label']} | E-Posta: {r['email']} (ID: {r['id']})\n"
            except Exception as e:
                msg += f"Hesaplar yüklenirken hata oluştu: {e}"
        self._show_info_dialog("Seçilen Hesap Detayları", msg)

    def _show_archived_emails_info(self):
        checked_ids = self._get_checked_account_ids()
        if not checked_ids:
            msg = "Toplam arşivlenen posta sayısını görmek için en az bir hesap seçin."
        else:
            msg = "Seçilen hesaplar için veritabanı istatistikleri:\n\n"
            try:
                with self.engine.db.get_conn() as conn:
                    for aid in checked_ids:
                        acc_row = conn.execute("SELECT label, email FROM accounts WHERE id=?", (aid,)).fetchone()
                        cnt_row = conn.execute("SELECT COUNT(*) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (aid,)).fetchone()
                        fld_row = conn.execute("SELECT COUNT(DISTINCT folder) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (aid,)).fetchone()
                        
                        label = acc_row["label"] if acc_row else f"ID: {aid}"
                        email = acc_row["email"] if acc_row else "?"
                        msg += f"• Hesap: {label} ({email})\n"
                        msg += f"  - Arşivlenen Mailler: {cnt_row['cnt'] if cnt_row else 0}\n"
                        msg += f"  - Klasörler: {fld_row['cnt'] if fld_row else 0}\n\n"
            except Exception as e:
                msg += f"İstatistikler sorgulanırken hata oluştu: {e}"
        self._show_info_dialog("Arşiv Veritabanı Detayları", msg)

    def _show_exported_count_info(self):
        msg = f"Dışa Aktarım Raporu\n\nBu çalıştırmada başarıyla aktarılan toplam e-posta sayısı: {self.card_exported_count.value_label.text()}"
        self._show_info_dialog("Aktarım İstatistikleri", msg)

    def _show_errors_info(self):
        msg = f"Hata Takip Özeti\n\nHata durumu: {self.card_error_count.value_label.text()}\nDetaylar için log konsolunu inceleyebilirsiniz."
        self._show_info_dialog("Hata Özeti", msg)

    def _show_migration_status_info(self):
        msg = f"Mevcut Aktarım Durumu: {self.card_status.value_label.text()}\n\n- Idle: Komut bekleniyor.\n- Running: E-postalar aktarılıyor.\n- Complete: Tamamlandı."
        self._show_info_dialog("Aktarım Durumu", msg)

    @Slot()
    def _check_inodes_and_report(self):
        checked_ids = self._get_checked_account_ids()
        if not checked_ids:
            QMessageBox.warning(self, "Hesap Seçilmedi", "Lütfen sayım kontrolü için en az bir hesap seçin.")
            return

        first_checked_id = checked_ids[0]
        row_idx = -1
        for i in range(self.account_table.rowCount()):
            widget = self.account_table.cellWidget(i, 0)
            if widget:
                chk = widget.findChild(QCheckBox)
                if chk and chk.property("account_id") == first_checked_id:
                    row_idx = i
                    break

        if row_idx == -1:
            return

        c = self._get_profile_for_row(row_idx)
        fmt = c.get("format", "ZIP")
        if fmt != "IMAP_SERVER":
            QMessageBox.warning(self, "Desteklenmeyen Hedef", "Inode kontrolleri yalnızca hedef IMAP sunucuları için desteklenir.")
            return

        host = c.get("imap_host", "")
        port_str = str(c.get("imap_port", "993"))
        ssl = c.get("imap_ssl", True)
        user = c.get("imap_username", "")
        pwd_enc = c.get("imap_password_enc", "")
        pwd = ""
        if pwd_enc:
            try:
                pwd = self.engine.crypto.decrypt(pwd_enc)
            except Exception:
                pass

        if not host or not user or not pwd:
            QMessageBox.warning(self, "Eksik Kimlik Bilgileri", "Hedef IMAP sunucusu kimlik bilgileri eksik.")
            return

        self.btn_check_inodes.setEnabled(False)
        self.btn_check_inodes.setText("⏳ Inode'lar Hesaplanıyor...")

        def fetch_task():
            try:
                port = int(port_str) if port_str else (993 if ssl else 143)
                if ssl:
                    client = imaplib.IMAP4_SSL(host, port, timeout=15)
                else:
                    client = imaplib.IMAP4(host, port, timeout=15)
                client.login(user, pwd)

                status, data = client.list()
                target_counts = {}
                if status == "OK" and data:
                    for line in data:
                        if not line:
                            continue
                        line_str = line.decode('utf-8', errors='replace')
                        m = re.search(r'"([^"]+)"$', line_str)
                        fname = m.group(1) if m else line_str.split()[-1]
                        st, cnt_data = client.select(f'"{fname}"', readonly=True)
                        if st == "OK" and cnt_data:
                            try:
                                target_counts[fname] = int(cnt_data[0])
                            except Exception:
                                pass
                client.logout()

                # Populate report table
                self.report_table.setRowCount(0)
                with self.engine.db.get_conn() as conn:
                    rows = conn.execute("SELECT folder, COUNT(*) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0 GROUP BY folder", (first_checked_id,)).fetchall()
                    for r in rows:
                        f_name = r["folder"]
                        loc_cnt = r["cnt"]
                        tgt_cnt = target_counts.get(f_name, "N/A")
                        
                        r_idx = self.report_table.rowCount()
                        self.report_table.insertRow(r_idx)
                        self.report_table.setItem(r_idx, 0, QTableWidgetItem(f_name))
                        self.report_table.setItem(r_idx, 1, QTableWidgetItem(f"Yerel: {loc_cnt}"))
                        self.report_table.setItem(r_idx, 2, QTableWidgetItem(f"Sunucu: {tgt_cnt}"))
                        
                        st_item = QTableWidgetItem("Eşleşti" if str(loc_cnt) == str(tgt_cnt) else "Farklı")
                        st_item.setForeground(QColor("#10b981") if str(loc_cnt) == str(tgt_cnt) else QColor("#ef4444"))
                        self.report_table.setItem(r_idx, 3, st_item)

            except Exception as e:
                self._log_signal.emit(f"❌ Inode kontolü başarısız: {e}")
            finally:
                self.btn_check_inodes.setEnabled(True)
                self.btn_check_inodes.setText("🔍 INODE / MESAJ SAYILARINI KONTROL ET")

        threading.Thread(target=fetch_task, daemon=True).start()

    def _get_checked_account_ids(self) -> List[int]:
        ids = []
        for i in range(self.account_table.rowCount()):
            widget = self.account_table.cellWidget(i, 0)
            if widget:
                chk = widget.findChild(QCheckBox)
                if chk and chk.isChecked():
                    ids.append(chk.property("account_id"))
        return ids

    def _get_profile_for_row(self, row_idx: int) -> dict:
        prof_widget = self.account_table.cellWidget(row_idx, 6)
        profile_name = "Default (ZIP)"
        if prof_widget:
            combo = prof_widget.findChild(QComboBox)
            if combo:
                profile_name = combo.currentText()
        if profile_name == "Default (ZIP)":
            return self._current_config
        profiles = self.settings.get("export_profiles", [])
        prof = next((p for p in profiles if isinstance(p, dict) and p.get("name") == profile_name), None)
        return prof or {"format": "ZIP", "target_path": str(Path("data/exports"))}

    def _get_export_stats_for_checked(self) -> list:
        checked_ids = self._get_checked_account_ids()
        stats = []
        for idx, acc_id in enumerate(checked_ids):
            row_idx = -1
            for r_i in range(self.account_table.rowCount()):
                widget = self.account_table.cellWidget(r_i, 0)
                if widget:
                    chk = widget.findChild(QCheckBox)
                    if chk and chk.property("account_id") == acc_id:
                        row_idx = r_i
                        break
            if row_idx == -1:
                continue

            c = self._get_profile_for_row(row_idx)
            folders = c.get("folders")
            since_date = c.get("since_date")
            before_date = c.get("before_date")

            conditions = ["account_id = ?", "is_deleted = 0"]
            params = [acc_id]
            
            if folders:
                placeholders = ", ".join("?" for _ in folders)
                conditions.append(f"folder IN ({placeholders})")
                params.extend(folders)
                
            if since_date:
                conditions.append("date >= ?")
                params.append(since_date)
                
            if before_date:
                conditions.append("date <= ?")
                params.append(before_date)

            where_clause = " AND ".join(conditions)
            
            try:
                with self.engine.db.get_conn() as conn:
                    row_cnt = conn.execute(f"SELECT COUNT(*) as cnt FROM mail_metadata WHERE {where_clause}", params).fetchone()
                    total_mails = row_cnt["cnt"] if row_cnt else 0
                    
                    row_fold = conn.execute(f"SELECT COUNT(DISTINCT folder) as cnt FROM mail_metadata WHERE {where_clause}", params).fetchone()
                    total_folders = row_fold["cnt"] if row_fold else 0
            except Exception:
                total_mails = 0
                total_folders = 0

            account_label = ""
            lbl_item = self.account_table.item(row_idx, 1)
            if lbl_item:
                account_label = lbl_item.text()

            fmt = c.get("format") or "ZIP"
            raw_path = c.get("target_path") or "data/exports"
            
            acc = self.engine.accounts.get(acc_id)
            raw_sub = acc.get("export_subfolder") or "" if acc else ""
            subfolder = re.sub(r'[\/:*?"<>|]', '_', raw_sub).strip()
            
            if fmt == "IMAP_SERVER":
                target_host = c.get("imap_host") or "Target IMAP"
                resolved_target = f"IMAP Server: {target_host} (Alt klasör: {subfolder})" if subfolder else f"IMAP Server: {target_host}"
            else:
                path = Path(raw_path)
                if fmt == "DIRECTORY":
                    resolved_target = str(path / subfolder) if subfolder else str(path)
                else:
                    if path.suffix == "":
                        ext_map = {"ZIP": ".zip", "JSON": ".json", "MBOX": ".mbox"}
                        filename = f"mails_{acc_id}{ext_map.get(fmt, '.zip')}"
                        path = path / filename
                    resolved_target = str(path.parent / subfolder / path.name) if subfolder else str(path)

            stats.append({
                "account_id": acc_id,
                "label": account_label or f"Hesap #{acc_id}",
                "folders": total_folders,
                "folders_list": folders,
                "mails": total_mails,
                "format": fmt,
                "resolved_target": resolved_target,
                "config": c
            })
        return stats

    @Slot()
    def _run_export_on_checked(self):
        checked_ids = self._get_checked_account_ids()
        if not checked_ids:
            QMessageBox.warning(self, "Hesap Seçilmedi", "Lütfen tablodan en az bir hesap işaretleyin.")
            return

        stats = self._get_export_stats_for_checked()
        
        dialog = ExportConfirmDialog(stats, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # Prepare export tasks on the main GUI thread
        tasks = []
        for st in stats:
            acc_id = st["account_id"]
            c = st.get("config") or {}
            fmt = c.get("format", "ZIP")
            resolved_target = st.get("resolved_target") or c.get("target_path") or "data/exports"
            target_path = Path(resolved_target)

            imap_host = None
            imap_port = None
            imap_ssl = c.get("imap_ssl", True)
            imap_username = None
            imap_password = None

            if fmt == "IMAP_SERVER":
                imap_host = c.get("imap_host", "")
                port_str = str(c.get("imap_port", "993"))
                imap_username = c.get("imap_username", "")
                pwd_enc = c.get("imap_password_enc", "")
                if pwd_enc:
                    try:
                        imap_password = self.engine.crypto.decrypt(pwd_enc)
                    except Exception:
                        pass

                if not imap_host or not imap_username or not imap_password:
                    self.log_output.append(f"⚠️ Hesap ID {acc_id} atlanıyor: IMAP kimlik bilgileri eksik.")
                    continue
                try:
                    imap_port = int(port_str) if port_str else 993
                except ValueError:
                    self.log_output.append(f"⚠️ Hesap ID {acc_id} atlanıyor: Port biçim hatası.")
                    continue

            folders = c.get("folders")
            since_date = c.get("since_date")
            before_date = c.get("before_date")

            tasks.append({
                "acc_id": acc_id,
                "fmt": fmt,
                "target_path": target_path,
                "folders": folders,
                "since_date": since_date,
                "before_date": before_date,
                "imap_host": imap_host,
                "imap_port": imap_port,
                "imap_ssl": imap_ssl,
                "imap_username": imap_username,
                "imap_password": imap_password,
            })

        if not tasks:
            QMessageBox.warning(self, "Geçersiz Konfigürasyon", "Seçili hesaplar için geçerli bir dışa aktarım konfigürasyonu bulunamadı.")
            return

        self.btn_export_selected.setEnabled(False)
        self.btn_configure.setEnabled(False)
        self.card_status.set_value("Running")
        self.overall_progress.setVisible(True)
        self.overall_progress.setValue(0)

        self.log_output.append(f"=== {len(tasks)} adet hesap için dışa aktarım başlatılıyor ===")

        self.report_table.setColumnCount(4)
        self.report_table.setHorizontalHeaderLabels(["Klasör / Mail", "Gönderen", "Tarih", "Durum"])
        self.report_table.setRowCount(0)

        def run_all():
            try:
                total_tasks = len(tasks)
                for idx, task in enumerate(tasks):
                    acc_id = task["acc_id"]
                    cancel_event = threading.Event()
                    self._active_exports[acc_id] = {
                        "cancel_event": cancel_event,
                        "status": "Starting",
                    }

                    def make_cb(aid):
                        def cb(current, total, email_meta=None):
                            self._progress_signal.emit(aid, "Dışa Aktarılıyor", current, total, email_meta)
                        return cb

                    try:
                        report = self.engine.export_mails(
                            account_id=acc_id,
                            format_type=task["fmt"],
                            output_path=task["target_path"],
                            folders=task["folders"],
                            since_date=task["since_date"],
                            before_date=task["before_date"],
                            progress_callback=make_cb(acc_id),
                            imap_host=task["imap_host"],
                            imap_port=task["imap_port"],
                            imap_ssl=task["imap_ssl"],
                            imap_username=task["imap_username"],
                            imap_password=task["imap_password"],
                        )
                        self._export_done_signal.emit(acc_id, report)
                    except Exception as exc:
                        logger.exception("Export failed for account %d: %s", acc_id, exc)
                        self._export_error_signal.emit(acc_id, str(exc))

                    pct = int((idx + 1) * 100 / total_tasks)
                    self._overall_progress_signal.emit(pct)
            finally:
                self._export_all_finished_signal.emit()

        threading.Thread(target=run_all, daemon=True).start()

    @Slot(int, str, int, int, object)
    def _on_export_progress(self, account_id: int, status_text: str, current: int, total: int, email_meta: object):
        ui = self._accounts_ui.get(account_id)
        if ui:
            ui["lbl_status"].setText(f"{status_text} ({current}/{total})")
            ui["progress_bar"].setRange(0, total if total > 0 else 100)
            ui["progress_bar"].setValue(current)
            left = max(0, total - current)
            ui["progress_bar"].setFormat(f"{current} / {left}")
        self.card_exported_count.set_value(str(current))

        if email_meta and isinstance(email_meta, dict):
            row = self.report_table.rowCount()
            self.report_table.insertRow(row)
            subj = str(email_meta.get('subject', '') or '')[:20]
            fld = str(email_meta.get('folder', '') or '')
            sender = str(email_meta.get('sender', '') or '')[:20]
            dt = str(email_meta.get('date', '') or '')[:10]
            self.report_table.setItem(row, 0, QTableWidgetItem(f"{fld} / {subj}"))
            self.report_table.setItem(row, 1, QTableWidgetItem(sender))
            self.report_table.setItem(row, 2, QTableWidgetItem(dt))
            
            st = str(email_meta.get("status", "Dışa Aktarıldı"))
            st_item = QTableWidgetItem(st)
            if "Mevcut" in st or "Duplicate" in st:
                st_item.setForeground(QColor("#f59e0b"))
            elif "Gönderildi" in st or "Exported" in st or "Aktarıldı" in st:
                st_item.setForeground(QColor("#10b981"))
            elif "Hata" in st or "Error" in st:
                st_item.setForeground(QColor("#ef4444"))
            self.report_table.setItem(row, 3, st_item)
            self.report_table.scrollToBottom()

    @Slot(int)
    def _on_overall_progress(self, pct: int):
        self.overall_progress.setValue(pct)

    @Slot()
    def _on_export_all_finished(self):
        self.card_status.set_value("Idle")
        self.btn_export_selected.setEnabled(True)
        self.btn_configure.setEnabled(True)
        self.overall_progress.setVisible(False)

    @Slot(int, object)
    def _on_export_done(self, account_id: int, report: dict):
        ui = self._accounts_ui.get(account_id)
        if ui:
            ui["btn_start"].setEnabled(True)
            ui["lbl_status"].setText("Done")
            ui["progress_bar"].setRange(0, 100)
            ui["progress_bar"].setValue(100)
            ui["progress_bar"].setFormat("Done")
        self._active_exports.pop(account_id, None)
        self.log_output.append(f"✅ Hesap ID {account_id} dışa aktarımı tamamlandı: {report.get('exported', 0)} aktarıldı, {report.get('errors', 0)} hata.")
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    @Slot(int, str)
    def _on_export_error(self, account_id: int, err_msg: str):
        ui = self._accounts_ui.get(account_id)
        if ui:
            ui["btn_start"].setEnabled(True)
            ui["lbl_status"].setText("Error")
            ui["progress_bar"].setRange(0, 100)
            ui["progress_bar"].setValue(0)
        self._active_exports.pop(account_id, None)
        self.log_output.append(f"❌ Hesap ID {account_id} aktarımı başarısız: {err_msg}")
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())
        self.card_error_count.set_value("Error")

    @Slot(str)
    def _on_log_message(self, msg: str):
        self.log_output.append(msg)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def _update_stats_on_selection(self):
        checked = self._get_checked_account_ids()
        self.card_total_selected.set_value(str(len(checked)))
        total_mails = 0
        if checked:
            try:
                with self.engine.db.get_conn() as conn:
                    placeholders = ",".join("?" for _ in checked)
                    row = conn.execute(f"SELECT COUNT(*) as cnt FROM mail_metadata WHERE account_id IN ({placeholders}) AND is_deleted=0", checked).fetchone()
                    total_mails = row["cnt"] if row else 0
            except Exception:
                pass
        self.card_total_mails.set_value(str(total_mails))

    # -----------------------------------------------------------------------
    # Data Refresh & Grid Rendering
    # -----------------------------------------------------------------------

    def refresh(self):
        self.account_table.blockSignals(True)
        self.account_table.setRowCount(0)
        self._accounts_ui.clear()
        
        try:
            accounts = self.engine.list_accounts()
            self.account_table.setRowCount(len(accounts))
            
            profiles = self.settings.get("export_profiles", [])
            profile_names = [p.get("name") for p in profiles if isinstance(p, dict) and p.get("name")]
            
            domains = set()
            groups = set()

            for i, acc in enumerate(accounts):
                acc_id = acc["id"]
                label = acc.get("label", "")
                email = acc.get("email", "")
                host = acc.get("imap_host", "")
                group_val = acc.get("account_group", "").strip()
                
                domain_val = email.split("@")[-1] if "@" in email else "Diğer"
                domains.add(domain_val)
                if group_val:
                    groups.add(group_val)

                # Query counts
                local_mails_cnt = 0
                folders_cnt = 0
                try:
                    with self.engine.db.get_conn() as conn:
                        row_mails = conn.execute("SELECT COUNT(*) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (acc_id,)).fetchone()
                        local_mails_cnt = row_mails["cnt"] if row_mails else 0
                        row_folders = conn.execute("SELECT COUNT(DISTINCT folder) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (acc_id,)).fetchone()
                        folders_cnt = row_folders["cnt"] if row_folders else 0
                except Exception:
                    pass

                # Col 0: Checkbox
                chk_widget = QWidget()
                chk_widget.setStyleSheet("background: transparent;")
                chk_layout = QHBoxLayout(chk_widget)
                chk_layout.setContentsMargins(0, 0, 0, 0)
                
                chk = QCheckBox()
                chk.setStyleSheet("""
                    QCheckBox::indicator {
                        width: 18px;
                        height: 18px;
                        border: 2px solid #4361ee;
                        border-radius: 4px;
                        background-color: #ffffff;
                    }
                    QCheckBox::indicator:checked {
                        background-color: #10b981;
                        border-color: #10b981;
                        image: url("data:image/svg+xml;utf8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20stroke%3D%22white%22%20stroke-width%3D%224%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%3E%3Cpolyline%20points%3D%2220%206%209%2017%204%2012%22%3E%3C%2Fpolyline%3E%3C%2Fsvg%3E");
                    }
                """)
                chk.setProperty("account_id", acc_id)
                chk.setChecked(False)
                chk.toggled.connect(lambda checked: self._update_stats_on_selection())
                chk_layout.addWidget(chk, 0, Qt.AlignCenter)
                self.account_table.setCellWidget(i, 0, chk_widget)

                # Col 1: Account Label (Crisp & Bold)
                item_label = QTableWidgetItem(label)
                item_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
                item_label.setForeground(QColor("#1e293b"))
                self.account_table.setItem(i, 1, item_label)

                # Col 2: Email Address (High Contrast, Readable)
                item_email = QTableWidgetItem(email)
                item_email.setFont(QFont("Segoe UI", 10))
                item_email.setForeground(QColor("#0369a1"))
                self.account_table.setItem(i, 2, item_email)

                # Col 3: Domain / Group
                dom_grp_str = f"{domain_val} | {group_val}" if group_val else domain_val
                item_dom = QTableWidgetItem(dom_grp_str)
                item_dom.setFont(QFont("Segoe UI", 9))
                item_dom.setForeground(QColor("#475569"))
                self.account_table.setItem(i, 3, item_dom)

                # Col 4: Host
                item_host = QTableWidgetItem(host)
                item_host.setFont(QFont("Segoe UI", 9))
                item_host.setForeground(QColor("#64748b"))
                self.account_table.setItem(i, 4, item_host)

                # Col 5: Stats
                stats_str = f"📁 {folders_cnt} klasör  |  📧 {local_mails_cnt} mail"
                item_stats = QTableWidgetItem(stats_str)
                item_stats.setFont(QFont("Segoe UI", 9, QFont.Bold))
                item_stats.setForeground(QColor("#047857"))
                self.account_table.setItem(i, 5, item_stats)

                # Col 6: Export Profile Dropdown + ⚙️ Button
                prof_widget = QWidget()
                prof_widget.setStyleSheet("background: transparent;")
                prof_layout = QHBoxLayout(prof_widget)
                prof_layout.setContentsMargins(2, 2, 2, 2)
                prof_layout.setSpacing(4)
                
                combo = QComboBox()
                combo.setStyleSheet("""
                    QComboBox {
                        background-color: #ffffff;
                        color: #0f172a;
                        border: 1px solid #cbd5e1;
                        border-radius: 4px;
                        padding: 3px;
                        font-size: 11px;
                        min-width: 110px;
                    }
                """)
                combo.addItem("Default (ZIP)")
                for name in profile_names:
                    combo.addItem(name)
                
                btn_edit_prof = QPushButton("⚙")
                btn_edit_prof.setToolTip("Profili Düzenle")
                btn_edit_prof.setCursor(Qt.PointingHandCursor)
                btn_edit_prof.setStyleSheet("QPushButton { background-color: #f1f5f9; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 4px; font-weight: bold; font-size: 11px; padding: 3px; min-width: 22px; max-width: 22px; } QPushButton:hover { background-color: #cbd5e1; }")
                btn_edit_prof.clicked.connect(lambda checked, c=combo, aid=acc_id: self._open_config_dialog_for_combo(c, aid))
                
                prof_layout.addWidget(combo, stretch=1)
                prof_layout.addWidget(btn_edit_prof)
                self.account_table.setCellWidget(i, 6, prof_widget)

                # Col 7: Progress & Status
                prog_widget = QWidget()
                prog_widget.setStyleSheet("background: transparent;")
                prog_layout = QVBoxLayout(prog_widget)
                prog_layout.setContentsMargins(4, 2, 4, 2)
                prog_layout.setSpacing(2)
                
                lbl_status = QLabel("Bekliyor")
                lbl_status.setStyleSheet("color: #475569; font-size: 10px; background: transparent;")
                progress_bar = QProgressBar()
                progress_bar.setRange(0, 100)
                progress_bar.setValue(0)
                progress_bar.setTextVisible(True)
                progress_bar.setFormat("0 / 0")
                progress_bar.setStyleSheet("""
                    QProgressBar {
                        background: #e2e8f0;
                        border: none;
                        border-radius: 3px;
                        height: 10px;
                        font-size: 8px;
                        text-align: center;
                        color: #1e293b;
                    }
                    QProgressBar::chunk {
                        background: #4361ee;
                        border-radius: 3px;
                    }
                """)
                prog_layout.addWidget(lbl_status)
                prog_layout.addWidget(progress_bar)
                self.account_table.setCellWidget(i, 7, prog_widget)

                # Col 8: Actions
                actions_widget = QWidget()
                actions_widget.setStyleSheet("background: transparent;")
                actions_layout = QHBoxLayout(actions_widget)
                actions_layout.setContentsMargins(2, 2, 2, 2)
                actions_layout.setSpacing(4)
                
                btn_start = QPushButton("▶")
                btn_start.setToolTip("Bu Hesap İçin Aktarımı Başlat")
                btn_start.setStyleSheet("background:#10b981; color:white; font-size:10px; font-weight:bold; padding:3px 6px; border-radius:3px;")
                btn_start.clicked.connect(lambda checked, aid=acc_id: self._run_individual_export(aid))
                
                actions_layout.addWidget(btn_start)
                self.account_table.setCellWidget(i, 8, actions_widget)

                self._accounts_ui[acc_id] = {
                    "chk": chk,
                    "lbl_status": lbl_status,
                    "progress_bar": progress_bar,
                    "btn_start": btn_start,
                }

            # Update Domain & Group Combo boxes
            self.combo_domain.blockSignals(True)
            self.combo_domain.clear()
            self.combo_domain.addItem("Tüm Domainler")
            for d in sorted(domains):
                self.combo_domain.addItem(d)
            self.combo_domain.blockSignals(False)

            self.combo_group.blockSignals(True)
            self.combo_group.clear()
            self.combo_group.addItem("Tüm Gruplar")
            for g in sorted(groups):
                self.combo_group.addItem(g)
            self.combo_group.blockSignals(False)

            self.grid.update_counter()
            self._apply_filters()

        except Exception as e:
            logger.error("Hesap listesi yenilenirken hata oluştu: %s", e)
        finally:
            self.account_table.blockSignals(False)

    def _run_individual_export(self, account_id: int):
        for i in range(self.account_table.rowCount()):
            widget = self.account_table.cellWidget(i, 0)
            if widget:
                chk = widget.findChild(QCheckBox)
                if chk:
                    chk.setChecked(chk.property("account_id") == account_id)
        self._update_stats_on_selection()
        self._run_export_on_checked()
