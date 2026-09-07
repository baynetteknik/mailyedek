"""
settings_panel.py — Application Settings & Diagnostic Workspace.

Includes Port Listener & Traffic Analyzer, Language settings, Storage management,
and Network & Performance configurations.
"""

import os
import json
import logging
import shutil
from pathlib import Path
from typing import Optional, List, Dict

from PySide6.QtCore import Qt, Slot, QSize, Signal, QThread
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel, QFrame,
    QPushButton, QCheckBox, QComboBox, QLineEdit, QSpinBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog,
    QGroupBox, QFormLayout, QSplitter, QStyle, QTextEdit, QInputDialog,
)

from core.settings import AppSettings, StorageLocation
from core.mail_engine import MailEngine
from infrastructure.network_analyzer import PortListenerThread
from gui.dialogs.delete_confirm_dialog import DeleteConfirmDialog

logger = logging.getLogger(__name__)


class SettingsDataLoaderWorker(QThread):
    """Background worker to query users, SMTP settings, storage stats and disk usage."""
    data_loaded_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, engine: Optional[MailEngine], settings: AppSettings, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings

    def run(self):
        try:
            users = []
            if self.engine:
                users = self.engine.list_users()

            smtp_cfg = {}
            if self.engine:
                smtp_cfg = self.engine.get_smtp_settings()

            locations = [StorageLocation("Default", str(self.settings.data_path()))]
            locations.extend(self.settings.storage_locations())

            loc_status = []
            for loc in locations:
                exists = Path(loc.path).exists()
                loc_status.append({"name": loc.name, "path": loc.path, "exists": exists})

            # Disk info
            disk_info = {}
            try:
                path = self.settings.data_path()
                total, used, free = shutil.disk_usage(path)
                disk_info = {
                    "drive": str(path.drive or path.anchor),
                    "total_gb": total / (1024 ** 3),
                    "used_gb": used / (1024 ** 3),
                    "free_gb": free / (1024 ** 3),
                    "used_pct": int((used / total) * 100) if total > 0 else 0
                }
            except Exception as e:
                disk_info = {"error": str(e)}

            self.data_loaded_signal.emit({
                "users": users,
                "smtp": smtp_cfg,
                "locations": loc_status,
                "disk_info": disk_info
            })
        except Exception as e:
            logger.exception("SettingsDataLoaderWorker error: %s", e)
            self.error_signal.emit(str(e))



class SettingsPanel(QWidget):
    """Main Settings and Diagnostic Workspace Panel."""

    _log_signal = Signal(str)
    _git_done_signal = Signal(bool, str)
    _setup_done_signal = Signal(bool, str)

    def __init__(self, settings: AppSettings, engine: Optional[MailEngine] = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.engine = engine
        self._listener_thread: Optional[PortListenerThread] = None
        self._loader_worker: Optional[SettingsDataLoaderWorker] = None
        self._git_done_signal.connect(self._on_git_done)
        self._setup_done_signal.connect(self._on_setup_done)
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Tab Container
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                background: #ffffff;
                top: -1px;
            }
            QTabBar::tab {
                background: #f1f5f9;
                color: #475569;
                padding: 9px 18px;
                font-weight: 600;
                font-size: 12px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #2563eb;
                font-weight: bold;
                border: 1px solid #cbd5e1;
                border-bottom: 2px solid #2563eb;
            }
        """)

        # Save All Settings Button placed on Tab Bar Corner
        self.btn_save_all = QPushButton("💾 Tüm Ayarları Kaydet")
        self.btn_save_all.setCursor(Qt.PointingHandCursor)
        self.btn_save_all.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-weight: bold;
                font-size: 12px;
                padding: 6px 16px;
                border-radius: 5px;
                border: 1px solid #1d4ed8;
                margin-bottom: 3px;
                margin-right: 4px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        self.btn_save_all.clicked.connect(self._save_all_settings)
        self.tabs.setCornerWidget(self.btn_save_all, Qt.TopRightCorner)

        # Add Sub-Tabs
        self.tabs.addTab(self._create_rbac_tab(), "👥 Kullanıcılar & Yetkiler (RBAC)")
        self.tabs.addTab(self._create_smtp_tab(), "📧 E-Posta Bildirimleri (SMTP)")
        self.tabs.addTab(self._create_port_listener_tab(), "🔌 Port Dinleme & Trafik Analizörü")
        self.tabs.addTab(self._create_language_tab(), "🌍 Dil & Arayüz Ayarları")
        self.tabs.addTab(self._create_storage_tab(), "💾 Depolama & Veritabanı")
        self.tabs.addTab(self._create_network_tab(), "⚡ Ağ & Performans")
        self.tabs.addTab(self._create_version_git_tab(), "🚀 Versiyon & Git Yönetimi")

        main_layout.addWidget(self.tabs, stretch=1)

    # -----------------------------------------------------------------------
    # TAB 1: Port Listener & Traffic Analyzer
    # -----------------------------------------------------------------------
    def _create_port_listener_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Controls row
        ctrl_card = QFrame()
        ctrl_card.setStyleSheet("background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px;")
        ctrl_layout = QHBoxLayout(ctrl_card)

        self.btn_toggle_listener = QPushButton("🔴 Port Dinleyici Kapalı (Başlat)")
        self.btn_toggle_listener.setCheckable(True)
        self.btn_toggle_listener.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_listener.setStyleSheet("""
            QPushButton {
                background-color: #ef4444; color: white; font-weight: bold;
                padding: 8px 16px; border-radius: 6px; font-size: 12px;
            }
            QPushButton:checked {
                background-color: #10b981; color: white;
            }
        """)
        self.btn_toggle_listener.clicked.connect(self._toggle_port_listener)
        ctrl_layout.addWidget(self.btn_toggle_listener)

        ctrl_layout.addWidget(QLabel("Hedef Sunucular:"))
        self.input_target_hosts = QLineEdit("srv10.cenuta.email, mail.ohmteknik.com")
        self.input_target_hosts.setPlaceholderText("Virgülle ayrılmış sunucu adresleri")
        self.input_target_hosts.setStyleSheet("padding: 5px; font-size: 12px;")
        ctrl_layout.addWidget(self.input_target_hosts, stretch=1)

        ctrl_layout.addStretch()

        btn_diag_net = QPushButton("🔍 Windows Ağ Teşhisi Yap")
        btn_diag_net.setCursor(Qt.PointingHandCursor)
        btn_diag_net.setStyleSheet("background-color: #4361ee; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px; font-size: 11px;")
        btn_diag_net.clicked.connect(self._run_windows_network_diag)
        ctrl_layout.addWidget(btn_diag_net)

        btn_clear_log = QPushButton("🧹 Logları Temizle")
        btn_clear_log.setStyleSheet("padding: 5px 10px; font-size: 11px;")
        btn_clear_log.clicked.connect(lambda: self.table_listener_logs.setRowCount(0))
        ctrl_layout.addWidget(btn_clear_log)

        btn_export_log = QPushButton("📥 Logları Kaydet")
        btn_export_log.setStyleSheet("padding: 5px 10px; font-size: 11px;")
        btn_export_log.clicked.connect(self._export_listener_logs)
        ctrl_layout.addWidget(btn_export_log)

        layout.addWidget(ctrl_card)

        # Port Checkboxes Group
        ports_group = QGroupBox("Dinlenecek Portlar & Protokoller")
        ports_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        ports_layout = QHBoxLayout(ports_group)
        
        self.chk_port_993 = QCheckBox("IMAP SSL (993)")
        self.chk_port_143 = QCheckBox("IMAP Plain (143)")
        self.chk_port_995 = QCheckBox("POP3 SSL (995)")
        self.chk_port_110 = QCheckBox("POP3 Plain (110)")
        self.chk_port_465 = QCheckBox("SMTP SSL (465)")
        self.chk_port_587 = QCheckBox("SMTP TLS (587)")
        self.chk_port_2096 = QCheckBox("cPanel SSL (2096)")

        for chk in [self.chk_port_993, self.chk_port_143, self.chk_port_995,
                    self.chk_port_110, self.chk_port_465, self.chk_port_587, self.chk_port_2096]:
            chk.setChecked(True)
            ports_layout.addWidget(chk)

        layout.addWidget(ports_group)

        # Table of live connection events
        self.table_listener_logs = QTableWidget()
        self.table_listener_logs.setColumnCount(7)
        self.table_listener_logs.setHorizontalHeaderLabels([
            "Zaman", "Hedef Sunucu", "IP Adresi", "Port / Protokol", "Durum", "Gecikme", "Detaylar & Teşhis"
        ])
        self.table_listener_logs.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table_listener_logs.setStyleSheet("""
            QTableWidget { background: #ffffff; gridline-color: #e2e8f0; font-size: 11px; }
            QHeaderView::section { background: #f1f5f9; font-weight: bold; color: #334155; padding: 5px; }
        """)
        layout.addWidget(self.table_listener_logs, stretch=1)

        return widget

    # -----------------------------------------------------------------------
    # TAB 2: Language & UI Settings
    # -----------------------------------------------------------------------
    def _create_language_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        group = QGroupBox("Arayüz & Dil Tercihleri")
        group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 14px; }")
        form = QFormLayout(group)
        form.setSpacing(14)

        self.combo_language = QComboBox()
        self.combo_language.addItem("Türkçe 🇹🇷", "tr")
        self.combo_language.addItem("English 🇬🇧", "en")
        self.combo_language.addItem("Русский 🇷🇺", "ru")
        self.combo_language.setStyleSheet("padding: 6px; font-size: 13px; min-width: 200px;")
        form.addRow("Uygulama Dili (Language):", self.combo_language)

        self.combo_theme = QComboBox()
        self.combo_theme.addItem("Modern Açık Tema (Light Theme)", "light")
        self.combo_theme.addItem("Modern Koyu Tema (Dark Theme)", "dark")
        self.combo_theme.setStyleSheet("padding: 6px; font-size: 13px; min-width: 200px;")
        form.addRow("Arayüz Teması:", self.combo_theme)

        self.chk_auto_refresh = QCheckBox("Sayfalar arası geçişte verileri otomatik yenile")
        self.chk_auto_refresh.setChecked(True)
        form.addRow("Otomatik Yenileme:", self.chk_auto_refresh)

        layout.addWidget(group)
        layout.addStretch()
        return widget
    # -----------------------------------------------------------------------
    # TAB 3: Storage & Database Settings
    # -----------------------------------------------------------------------
    def _create_storage_tab(self) -> QWidget:
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 0, 0)

        from gui.templates.three_panel_workspace import ThreePanelWorkspaceTemplate
        from gui.dialogs.portable_import_dialog import PortableImportDialog

        ws = ThreePanelWorkspaceTemplate(title="💽 Depolama ve Veritabanı Yönetimi", parent=container)
        c_layout.addWidget(ws)

        ws.btn_toggle_left.setText("💽 Sol Disk Paneli")
        ws.btn_toggle_right.setText("🛠️ Sağ Veritabanı Paneli")

        # Load saved splitter sizes and panel visibility states
        ws.load_splitter_state(self.settings, "storage_workspace")

        left_vis = self.settings.get("storage_left_visible", True)
        right_vis = self.settings.get("storage_right_visible", True)

        ws.btn_toggle_left.setChecked(left_vis)
        ws.left_widget.setVisible(left_vis)
        ws.btn_toggle_right.setChecked(right_vis)
        ws.right_widget.setVisible(right_vis)

        # Connect auto-save signals for persistent sizes and toggle states
        ws.splitter.splitterMoved.connect(lambda *args: ws.save_splitter_state(self.settings, "storage_workspace"))

        def _on_storage_panel_toggled(panel_name: str, visible: bool):
            self.settings.set(f"storage_{panel_name}_visible", visible)
            self.settings.save()
            ws.save_splitter_state(self.settings, "storage_workspace")

        ws.panel_toggled.connect(_on_storage_panel_toggled)

        # -------------------------------------------------------------------
        # 1. SOL PANEL: Disk & Konum Listesi
        # -------------------------------------------------------------------
        ws.left_group.setTitle("💽 Disk & Depolama Yönetimi")
        
        # PROMINENT DISK SELECTION BUTTON
        btn_prominent_disk = QPushButton("💽  DİSK SEÇ / DİZİNİ DEĞİŞTİR")
        btn_prominent_disk.setToolTip("Ana mail arşiv veritabanı ve dosya dizin yolunu seçin / değiştirin")
        btn_prominent_disk.setCursor(Qt.PointingHandCursor)
        btn_prominent_disk.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-size: 12px;
                font-weight: 800;
                padding: 10px 14px;
                border-radius: 6px;
                border: 1px solid #1d4ed8;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        btn_prominent_disk.clicked.connect(self._change_data_directory)
        ws.left_inner_layout.addWidget(btn_prominent_disk)

        # Active Data Path Info Box
        path_box = QGroupBox("Aktif Çalışma Dizini")
        path_box.setStyleSheet(ws._group_box_style())
        p_layout = QVBoxLayout(path_box)
        
        self.lbl_data_path_val = QLabel(str(self.settings.data_path()))
        self.lbl_data_path_val.setStyleSheet("font-weight: bold; color: #2563eb; font-size: 11px;")
        self.lbl_data_path_val.setWordWrap(True)
        p_layout.addWidget(self.lbl_data_path_val)

        ws.left_inner_layout.addWidget(path_box)

        # Add Custom Storage Location Button
        btn_add_loc = QPushButton("➕ Adlandırılmış Konum Ekle")
        btn_add_loc.setCursor(Qt.PointingHandCursor)
        btn_add_loc.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-weight: bold;
                font-size: 11px;
                padding: 7px 12px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        btn_add_loc.clicked.connect(self._add_storage_location_dialog)
        ws.left_inner_layout.addWidget(btn_add_loc)

        # Disk Usage Progress Bar
        disk_box = QGroupBox("Disk Doluluk Oranı")
        disk_box.setStyleSheet(ws._group_box_style())
        d_layout = QVBoxLayout(disk_box)
        self.lbl_disk_info = QLabel("Yükleniyor...")
        self.lbl_disk_info.setStyleSheet("font-size: 11px; font-weight: bold; color: #475569;")
        d_layout.addWidget(self.lbl_disk_info)

        self.progress_disk = QProgressBar()
        self.progress_disk.setRange(0, 100)
        self.progress_disk.setStyleSheet("""
            QProgressBar { height: 14px; border-radius: 4px; text-align: center; font-size: 10px; font-weight: bold; color: #ffffff; }
            QProgressBar::chunk { background-color: #2563eb; border-radius: 4px; }
        """)
        d_layout.addWidget(self.progress_disk)
        ws.left_inner_layout.addWidget(disk_box)

        ws.left_inner_layout.addStretch()

        # -------------------------------------------------------------------
        # 2. ORTA PANEL: Kayıtlı Depolama Konumları Tablosu
        # -------------------------------------------------------------------
        center_box = QGroupBox("📂 Kayıtlı Depolama Konumları ve Yolları")
        center_box.setStyleSheet(ws._group_box_style())
        center_layout = QVBoxLayout(center_box)

        self.tbl_locations = QTableWidget()
        self.tbl_locations.setColumnCount(4)
        self.tbl_locations.setHorizontalHeaderLabels(["Konum Adı", "Hedef Dizin Yolu", "Durum", "Eylemler"])
        self.tbl_locations.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tbl_locations.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_locations.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_locations.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tbl_locations.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                color: #0f172a;
                gridline-color: #cbd5e1;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 500;
            }
            QHeaderView::section {
                background-color: #f1f5f9;
                color: #1e293b;
                font-weight: bold;
                border: 1px solid #cbd5e1;
                padding: 4px;
            }
        """)
        center_layout.addWidget(self.tbl_locations)

        ws.center_layout.addWidget(center_box)
        self._refresh_locations_table()

        # -------------------------------------------------------------------
        # 3. SAĞ PANEL: Veritabanı Bakım & Taşınabilir Disk Aktarımı
        # -------------------------------------------------------------------
        ws.right_group.setTitle("🛠️ Bakım & Dış Aktarım")

        # Database File Details Box
        db_details_box = QGroupBox("Veritabanı ve Anahtar Yolları")
        db_details_box.setStyleSheet(ws._group_box_style())
        db_form = QFormLayout(db_details_box)
        db_form.setSpacing(6)
        
        lbl_db = QLabel(str(self.settings.db_path().name))
        lbl_db.setStyleSheet("font-weight: bold; color: #2563eb;")
        db_form.addRow("Veritabanı:", lbl_db)

        lbl_key = QLabel(str(self.settings.key_file_path().name))
        lbl_key.setStyleSheet("font-weight: bold; color: #2563eb;")
        db_form.addRow("Anahtar Dosyası:", lbl_key)

        ws.right_inner_layout.addWidget(db_details_box)

        # Maintenance Actions
        maint_box = QGroupBox("Veritabanı İşlemleri")
        maint_box.setStyleSheet(ws._group_box_style())
        m_layout = QVBoxLayout(maint_box)

        btn_vacuum = QPushButton("🧹 Veritabanını Sıkıştır (VACUUM)")
        btn_vacuum.setCursor(Qt.PointingHandCursor)
        btn_vacuum.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                padding: 8px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        btn_vacuum.clicked.connect(self._vacuum_database)
        m_layout.addWidget(btn_vacuum)

        btn_backup_db = QPushButton("💾 Veritabanı Yedeği Al")
        btn_backup_db.setCursor(Qt.PointingHandCursor)
        btn_backup_db.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                padding: 8px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        btn_backup_db.clicked.connect(self._backup_database)
        m_layout.addWidget(btn_backup_db)

        # PORTABLE BACKUP IMPORT BUTTON
        btn_portable_import = QPushButton("📦 Taşınabilir Disk Yedeği İçe Aktar")
        btn_portable_import.setToolTip("Harici bir diskteki / klasördeki mail arşivini mevcut sisteme aktarır")
        btn_portable_import.setCursor(Qt.PointingHandCursor)
        btn_portable_import.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                padding: 9px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        btn_portable_import.clicked.connect(self._open_portable_import_dialog)
        m_layout.addWidget(btn_portable_import)

        ws.right_inner_layout.addWidget(maint_box)

        # Log Console
        log_box = QGroupBox("İşlem Logları")
        log_box.setStyleSheet(ws._group_box_style())
        l_layout = QVBoxLayout(log_box)
        
        self.txt_storage_log = QTextEdit()
        self.txt_storage_log.setReadOnly(True)
        self.txt_storage_log.setStyleSheet("background: #1e293b; color: #a8d8ea; font-family: monospace; font-size: 10px;")
        l_layout.addWidget(self.txt_storage_log)
        
        ws.right_inner_layout.addWidget(log_box, stretch=1)

        self._update_disk_space_info()
        return container

    def _open_portable_import_dialog(self):
        from gui.dialogs.portable_import_dialog import PortableImportDialog
        if not self.engine:
            QMessageBox.warning(self, "Hata", "MailEngine henüz başlatılmadı.")
            return
        dialog = PortableImportDialog(self.engine, self)
        if dialog.exec() == QDialog.Accepted:
            self._update_disk_space_info()
            self._refresh_locations_table()
            if hasattr(self, "txt_storage_log"):
                self.txt_storage_log.append("✅ Taşınabilir disk aktarımı tamamlandı ve görünüm güncellendi.")

    def _refresh_locations_table(self):
        if not hasattr(self, "tbl_locations"):
            return
        locations = [StorageLocation("Default", str(self.settings.data_path()))]
        locations.extend(self.settings.storage_locations())

        self.tbl_locations.setRowCount(0)
        for idx, loc in enumerate(locations):
            self.tbl_locations.insertRow(idx)
            self.tbl_locations.setItem(idx, 0, QTableWidgetItem(loc.name))
            self.tbl_locations.setItem(idx, 1, QTableWidgetItem(loc.path))

            exists = Path(loc.path).exists()
            st_item = QTableWidgetItem("🟢 Erişilebilir" if exists else "🔴 Bulunamadı")
            st_item.setForeground(QColor("#10b981") if exists else QColor("#ef4444"))
            st_item.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.tbl_locations.setItem(idx, 2, st_item)

            if loc.name == "Default":
                lbl_def = QLabel("— Varsayılan —")
                lbl_def.setAlignment(Qt.AlignCenter)
                lbl_def.setStyleSheet("color: #64748b; font-size: 10px;")
                self.tbl_locations.setCellWidget(idx, 3, lbl_def)
            else:
                btn_del = QPushButton("Sil")
                btn_del.setStyleSheet("background: #ef4444; color: white; font-weight: bold; padding: 2px 8px; font-size: 10px; border-radius: 3px;")
                btn_del.clicked.connect(lambda _, name=loc.name: self._remove_storage_location(name))
                self.tbl_locations.setCellWidget(idx, 3, btn_del)

    def _add_storage_location_dialog(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Depolama Konumu Ekle", "Konum Adı (ör. NAS_Archive, Disk_E):")
        if ok and name.strip():
            folder = QFileDialog.getExistingDirectory(self, "Depolama Klasörü Seçin")
            if folder:
                self.settings.add_storage_location(name.strip(), folder)
                self._refresh_locations_table()
                if hasattr(self, "txt_storage_log"):
                    self.txt_storage_log.append(f"Yeni depolama konumu eklendi: {name} -> {folder}")

    def _remove_storage_location(self, name: str):
        locs = self.settings.storage_locations()
        matched = [l for l in locs if l.name == name]
        path_info = matched[0].path if matched else name
        confirmed = DeleteConfirmDialog.confirm_deletion(
            parent=self,
            item_name=name,
            item_type="Depolama Konumu",
            details=f"Konum Adı: {name}\nKlasör Yolu: {path_info}\nBu konum depolama konumları listesinden kaldırılacaktır.",
            warning_text="Yalnızca liste kaydı silinir. Fiziksel diskteki arşiv verileri korunur."
        )
        if confirmed:
            self.settings.remove_storage_location(name)
            self._refresh_locations_table()
            if hasattr(self, "txt_storage_log"):
                self.txt_storage_log.append(f"Depolama konumu kaldırıldı: {name}")

    # -----------------------------------------------------------------------
    # TAB 4: Network & Performance
    # -----------------------------------------------------------------------
    def _create_network_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        group = QGroupBox("Ağ Bağlantısı & İletişim Tercihleri")
        group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 14px; }")
        form = QFormLayout(group)
        form.setSpacing(14)

        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(3, 120)
        self.spin_timeout.setValue(self.settings.network_timeout())
        self.spin_timeout.setSuffix(" saniye")
        self.spin_timeout.setStyleSheet("padding: 6px; font-size: 13px; max-width: 150px;")
        form.addRow("Bağlantı Zaman Aşımı (Timeout):", self.spin_timeout)

        self.chk_ssl_strict = QCheckBox("SSL / TLS Sertifika Doğrulamasını Sıkı Modda Çalıştır")
        self.chk_ssl_strict.setChecked(self.settings.ssl_strict_mode())
        form.addRow("SSL Sertifika Modu:", self.chk_ssl_strict)

        self.spin_max_threads = QSpinBox()
        self.spin_max_threads.setRange(1, 10)
        self.spin_max_threads.setValue(3)
        self.spin_max_threads.setStyleSheet("padding: 6px; font-size: 13px; max-width: 150px;")
        form.addRow("Eşzamanlı Senkronizasyon Sayısı:", self.spin_max_threads)

        layout.addWidget(group)
        layout.addStretch()
        return widget

    # -----------------------------------------------------------------------
    # TAB 5: Version & Git Management
    # -----------------------------------------------------------------------
    def _create_version_git_tab(self) -> QWidget:
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        from gui.templates.three_panel_workspace import ThreePanelWorkspaceTemplate
        from core.version import get_version, get_git_info

        ver = get_version()
        git_info = get_git_info()

        ws = ThreePanelWorkspaceTemplate(title="⚙️ Git & Versiyon Yönetimi Paneli", parent=widget)
        main_layout.addWidget(ws)

        ws.btn_toggle_left.setText("📊 Versiyon Paneli")
        ws.btn_toggle_right.setText("🖥️ İşlem Konsolu")

        # -------------------------------------------------------------------
        # 1. SOL PANEL: Versiyon Yükseltme & Git Commit Gönderme
        # -------------------------------------------------------------------
        ws.left_group.setTitle("📈 Versiyon & Sürüm Yayınlama")
        left_layout = ws.left_inner_layout

        self.lbl_ver_badge = QLabel(f"Sürüm: v{ver}")
        self.lbl_ver_badge.setStyleSheet("""
            background-color: #2563eb;
            color: #ffffff;
            font-size: 14px;
            font-weight: bold;
            padding: 8px 12px;
            border-radius: 6px;
        """)
        left_layout.addWidget(self.lbl_ver_badge)

        btn_bump_ver = QPushButton("📈 Versiyon Yükselt (+0.01)")
        btn_bump_ver.setCursor(Qt.PointingHandCursor)
        btn_bump_ver.setStyleSheet("padding: 8px 14px; font-weight: bold; background: #e2e8f0; border-radius: 4px; color: #0f172a;")
        btn_bump_ver.clicked.connect(self._bump_app_version)
        left_layout.addWidget(btn_bump_ver)

        left_layout.addSpacing(12)
        left_layout.addWidget(QLabel("Aktif Git Branch / Commit:"))
        self.lbl_git_branch = QLabel(f"{git_info['branch']}  ({git_info['commit']})")
        self.lbl_git_branch.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; font-weight: bold; color: #1e293b;")
        self.lbl_git_branch.setWordWrap(True)
        left_layout.addWidget(self.lbl_git_branch)

        left_layout.addSpacing(8)
        left_layout.addWidget(QLabel("Commit Mesajı:"))
        self.input_commit_msg = QLineEdit()
        self.input_commit_msg.setPlaceholderText(f"v{ver} için değişiklik açıklaması...")
        self.input_commit_msg.setStyleSheet("padding: 6px; font-size: 11px;")
        left_layout.addWidget(self.input_commit_msg)

        btn_git_push = QPushButton("🚀 Git Commit & Push Gönder")
        btn_git_push.setCursor(Qt.PointingHandCursor)
        btn_git_push.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 8px 14px; border-radius: 4px;")
        btn_git_push.clicked.connect(self._commit_and_push_git)
        left_layout.addWidget(btn_git_push)

        left_layout.addStretch()

        # -------------------------------------------------------------------
        # 2. ORTA PANEL: Remote Sunucu Ayarları & Setup Derleme
        # -------------------------------------------------------------------
        center_layout = ws.center_layout

        git_config_card = QGroupBox("Git Remote Sunucu & Repository Ayarları")
        git_config_card.setStyleSheet(ws._group_box_style())
        g_form = QFormLayout(git_config_card)
        g_form.setSpacing(10)

        self.input_git_remote = QLineEdit()
        self.input_git_remote.setText(self.settings.get("git_remote_url", "https://github.com/baynetteknik/mailyedek"))
        self.input_git_remote.setPlaceholderText("https://github.com/kullanici/repo.git")
        self.input_git_remote.setStyleSheet("padding: 6px; font-size: 12px;")
        g_form.addRow("Git Remote URL:", self.input_git_remote)

        self.input_git_branch_name = QLineEdit()
        self.input_git_branch_name.setText(git_info.get("branch", "main"))
        self.input_git_branch_name.setStyleSheet("padding: 6px; font-size: 12px;")
        g_form.addRow("Varsayılan Branch:", self.input_git_branch_name)

        g_btns = QHBoxLayout()
        btn_save_git_cfg = QPushButton("💾 Git Ayarlarını Kaydet")
        btn_save_git_cfg.setCursor(Qt.PointingHandCursor)
        btn_save_git_cfg.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px;")
        btn_save_git_cfg.clicked.connect(self._save_git_config)

        btn_del_git_remote = QPushButton("🗑️ Remote Bağlantıyı Sil")
        btn_del_git_remote.setCursor(Qt.PointingHandCursor)
        btn_del_git_remote.setStyleSheet("background-color: #ef4444; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px;")
        btn_del_git_remote.clicked.connect(self._delete_git_remote)

        g_btns.addWidget(btn_save_git_cfg)
        g_btns.addWidget(btn_del_git_remote)
        g_btns.addStretch()
        g_form.addRow("", g_btns)

        center_layout.addWidget(git_config_card)

        setup_card = QGroupBox("Kurulum Paketi & Kullanıcı Yardım Rehberi")
        setup_card.setStyleSheet(ws._group_box_style())
        setup_layout = QVBoxLayout(setup_card)
        setup_layout.setSpacing(10)

        btn_build_setup = QPushButton("📦 Dinamik Setup Paketini Oluştur (build_setup.py)")
        btn_build_setup.setCursor(Qt.PointingHandCursor)
        btn_build_setup.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 10px 16px; border-radius: 4px;")
        btn_build_setup.clicked.connect(self._build_setup_package)

        btn_open_guide = QPushButton("📖 Kurulum Yardım Rehberini Aç")
        btn_open_guide.setCursor(Qt.PointingHandCursor)
        btn_open_guide.setStyleSheet("background-color: #475569; color: white; font-weight: bold; padding: 10px 16px; border-radius: 4px;")
        btn_open_guide.clicked.connect(self._open_kurulum_rehberi)

        setup_layout.addWidget(btn_build_setup)
        setup_layout.addWidget(btn_open_guide)
        center_layout.addWidget(setup_card)

        # -------------------------------------------------------------------
        # 3. SAĞ PANEL: Git & Setup Konsol Çıktısı (Mavi Zemin Beyaz Yazı)
        # -------------------------------------------------------------------
        ws.right_group.setTitle("🖥️ Git & İşlem Konsolu")
        right_layout = ws.right_inner_layout

        self.text_ver_log = QTextEdit()
        self.text_ver_log.setReadOnly(True)
        self.text_ver_log.setStyleSheet("""
            QTextEdit {
                background-color: #2563eb;
                color: #ffffff;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                font-weight: bold;
                padding: 12px;
                border-radius: 6px;
                border: 1px solid #1d4ed8;
            }
        """)
        self.text_ver_log.setPlaceholderText("Git ve Setup işlem çıktıları burada görüntülenecektir...")
        right_layout.addWidget(self.text_ver_log, stretch=1)

        ws.load_splitter_state(self.settings, "git_workspace")
        ws.splitter.splitterMoved.connect(lambda *args: ws.save_splitter_state(self.settings, "git_workspace"))

        return widget

    @Slot()
    def _bump_app_version(self):
        from core.version import bump_version, get_version
        new_v = bump_version("patch")
        self.lbl_ver_badge.setText(f"Sürüm: v{new_v}")
        self.input_commit_msg.setPlaceholderText(f"v{new_v} için değişiklik açıklaması...")
        self.text_ver_log.append(f"📈 Uygulama versiyonu v{new_v} olarak güncellendi.")

    def _show_styled_info_dialog(self, title: str, text: str):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText(text)
        msg_box.setStandardButtons(QMessageBox.Ok)
        
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #ffffff;
            }
            QLabel {
                color: #0f172a !important;
                font-size: 13px !important;
                font-weight: 600 !important;
                background-color: transparent !important;
            }
            QPushButton {
                background-color: #2563eb !important;
                color: #ffffff !important;
                font-weight: bold !important;
                font-size: 13px !important;
                border: none !important;
                border-radius: 6px !important;
                padding: 8px 24px !important;
                min-width: 95px !important;
                min-height: 28px !important;
            }
            QPushButton:hover {
                background-color: #1d4ed8 !important;
                color: #ffffff !important;
            }
            QPushButton:pressed {
                background-color: #1e40af !important;
                color: #ffffff !important;
            }
        """)

        ok_btn = msg_box.button(QMessageBox.Ok)
        if ok_btn:
            ok_btn.setText("Tamam")
            ok_btn.setCursor(Qt.PointingHandCursor)

        msg_box.exec()

    @Slot(bool, str)
    def _on_git_done(self, ok: bool, res_msg: str):
        from core.version import get_git_info
        if ok:
            self.text_ver_log.append(res_msg)
            self._show_styled_info_dialog("Git İşlemi Başarılı", res_msg)
        else:
            self.text_ver_log.append(f"❌ {res_msg}")
            QMessageBox.warning(self, "Git İşlemi Uyarısı", res_msg)
        
        info = get_git_info()
        self.lbl_git_branch.setText(f"{info['branch']}  ({info['commit']})")

    @Slot(bool, str)
    def _on_setup_done(self, ok: bool, res_msg: str):
        if ok:
            self.text_ver_log.append(f"✅ Setup Paketi Derlendi: {res_msg}")
            self._show_styled_info_dialog("Setup Derleme Başarılı", f"Paket üretildi:\ninstaller/{res_msg}")
        else:
            self.text_ver_log.append(f"❌ Derleme Hatası:\n{res_msg[:300]}")
            QMessageBox.critical(self, "Derleme Hatası", res_msg[:500])

    @Slot()
    def _save_git_config(self):
        import subprocess
        from core.version import REPO_ROOT
        remote_url = self.input_git_remote.text().strip()
        branch = self.input_git_branch_name.text().strip() or "main"
        
        self.settings.set("git_remote_url", remote_url)
        self.settings.save()

        if remote_url:
            try:
                res = subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5)
                if res.returncode != 0:
                    subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5)
                self.text_ver_log.append(f"✅ Git remote URL güncellendi: {remote_url}")
            except Exception as e:
                self.text_ver_log.append(f"⚠️ Remote güncelleme uyarısı: {e}")

        self._show_styled_info_dialog("Kaydedildi", "Git remote ve branch ayarları başarıyla kaydedildi.")

    @Slot()
    def _delete_git_remote(self):
        import subprocess
        from core.version import REPO_ROOT
        remote_url = self.input_git_remote.text().strip()
        confirmed = DeleteConfirmDialog.confirm_deletion(
            parent=self,
            item_name="origin (Git Remote)",
            item_type="Git Remote Bağlantısı",
            details=f"Uzak Sunucu URL: {remote_url or 'Tanımlı değil'}\nGit 'origin' remote bağlantısı yerel depodan kaldırılacaktır.",
            warning_text="Bu işlem yalnızca uzak sunucu bağlantı adresini kaldırır, yerel commit geçmişini silmez."
        )
        if confirmed:
            try:
                subprocess.run(["git", "remote", "remove", "origin"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5)
                self.input_git_remote.clear()
                self.settings.set("git_remote_url", "")
                self.settings.save()
                self.text_ver_log.append("✅ Git remote 'origin' bağlantısı kaldırıldı.")
                self._show_styled_info_dialog("Silindi", "Git remote bağlantısı silindi.")
            except Exception as e:
                QMessageBox.critical(self, "Hata", f"Remote silinemedi: {e}")

    @Slot()
    def _commit_and_push_git(self):
        import threading
        from core.version import git_commit_and_push
        msg = self.input_commit_msg.text().strip()
        self.text_ver_log.append("⏳ Git commit & push başlatılıyor... Lütfen bekleyin...")

        def _worker():
            ok, res_msg = git_commit_and_push(msg)
            self._git_done_signal.emit(ok, res_msg)

        threading.Thread(target=_worker, daemon=True).start()

    @Slot()
    def _build_setup_package(self):
        import subprocess, sys
        from core.version import get_version
        v = get_version()
        self.text_ver_log.append(f"⏳ Setup paketi derleniyor (v{v})... Lütfen bekleyin...")
        
        def run_b():
            try:
                repo_root = Path(__file__).resolve().parent.parent.parent
                script_file = repo_root / "installer" / "build_setup.py"
                res = subprocess.run([sys.executable, str(script_file)], cwd=repo_root, capture_output=True, text=True, timeout=120)
                out = res.stdout + "\n" + res.stderr
                if res.returncode == 0:
                    pkg_name = f"MailArchiveSystem_v{v}_Kurulum_Paketi.zip"
                    self._setup_done_signal.emit(True, pkg_name)
                else:
                    self._setup_done_signal.emit(False, out)
            except Exception as exc:
                self._setup_done_signal.emit(False, str(exc))

        import threading
        threading.Thread(target=run_b, daemon=True).start()

    @Slot()
    def _open_kurulum_rehberi(self):
        repo_root = Path(__file__).resolve().parent.parent.parent
        rehber_file = repo_root / "installer" / "KURULUM_REHBERI.txt"
        if rehber_file.exists():
            os.startfile(str(rehber_file))
        else:
            QMessageBox.warning(self, "Dosya Bulunamadı", "KURULUM_REHBERI.txt dosyası bulunamadı.")

    # -----------------------------------------------------------------------
    # Logic & Slots
    # -----------------------------------------------------------------------
    def refresh(self):
        """Reload stored settings and update UI states."""
        # Language
        lang = self.settings.language()
        idx = self.combo_language.findData(lang)
        if idx >= 0:
            self.combo_language.setCurrentIndex(idx)

        # Port listener
        enabled = self.settings.port_listener_enabled()
        self.btn_toggle_listener.setChecked(enabled)
        self._update_listener_button_style(enabled)

        # Disk space
        self._update_disk_space_info()

    def _update_disk_space_info(self):
        try:
            path = self.settings.data_path()
            total, used, free = shutil.disk_usage(path)
            total_gb = total / (1024 ** 3)
            free_gb = free / (1024 ** 3)
            used_gb = used / (1024 ** 3)
            used_pct = int((used / total) * 100)

            self.lbl_disk_info.setText(
                f"Sürücü: {path.drive or path.anchor}  |  Toplam: {total_gb:.1f} GB  |  "
                f"Kullanılan: {used_gb:.1f} GB ({used_pct}%)  |  Boş Alan: {free_gb:.1f} GB"
            )
            self.progress_disk.setValue(used_pct)
        except Exception as exc:
            self.lbl_disk_info.setText(f"Disk bilgisi alınamadı: {exc}")

    @Slot()
    def _toggle_port_listener(self):
        enabled = self.btn_toggle_listener.isChecked()
        self.settings.set_port_listener_enabled(enabled)
        self._update_listener_button_style(enabled)

        if enabled:
            hosts = [h.strip() for h in self.input_target_hosts.text().split(",") if h.strip()]
            ports = []
            if self.chk_port_993.isChecked(): ports.append(993)
            if self.chk_port_143.isChecked(): ports.append(143)
            if self.chk_port_995.isChecked(): ports.append(995)
            if self.chk_port_110.isChecked(): ports.append(110)
            if self.chk_port_465.isChecked(): ports.append(465)
            if self.chk_port_587.isChecked(): ports.append(587)
            if self.chk_port_2096.isChecked(): ports.append(2096)

            self._start_port_listener(hosts, ports)
        else:
            self._stop_port_listener()

    def _update_listener_button_style(self, enabled: bool):
        if enabled:
            self.btn_toggle_listener.setText("🟢 Port Dinleyici Aktif (Durdur)")
        else:
            self.btn_toggle_listener.setText("🔴 Port Dinleyici Kapalı (Başlat)")

    def _start_port_listener(self, hosts: List[str], ports: List[int]):
        self._stop_port_listener()
        self._listener_thread = PortListenerThread(target_hosts=hosts, target_ports=ports, interval_sec=6, parent=self)
        self._listener_thread.log_signal.connect(self._add_listener_log_row)
        self._listener_thread.start()

    def _stop_port_listener(self):
        if self._listener_thread and self._listener_thread.isRunning():
            self._listener_thread.stop()
            self._listener_thread.wait(1500)
            self._listener_thread = None

    @Slot(dict)
    def _add_listener_log_row(self, data: dict):
        row = self.table_listener_logs.rowCount()
        self.table_listener_logs.insertRow(row)

        self.table_listener_logs.setItem(row, 0, QTableWidgetItem(data.get("timestamp", "")))
        self.table_listener_logs.setItem(row, 1, QTableWidgetItem(data.get("host", "")))
        self.table_listener_logs.setItem(row, 2, QTableWidgetItem(data.get("ip", "")))
        self.table_listener_logs.setItem(row, 3, QTableWidgetItem(f"{data.get('port')} ({data.get('protocol')})"))
        
        status_item = QTableWidgetItem(data.get("status", ""))
        if "🟢" in data.get("status", ""):
            status_item.setForeground(QColor("#10b981"))
            status_item.setFont(QFont("", -1, QFont.Bold))
        else:
            status_item.setForeground(QColor("#ef4444"))
        self.table_listener_logs.setItem(row, 4, status_item)

        lat = data.get("latency_ms", 0)
        self.table_listener_logs.setItem(row, 5, QTableWidgetItem(f"{lat} ms" if lat > 0 else "-"))
        self.table_listener_logs.setItem(row, 6, QTableWidgetItem(data.get("details", "")))

        # Keep max 200 rows
        if self.table_listener_logs.rowCount() > 200:
            self.table_listener_logs.removeRow(0)

        self.table_listener_logs.scrollToBottom()

    @Slot()
    def _export_listener_logs(self):
        path, _ = QFileDialog.getSaveFileName(self, "Logları Dışa Aktar", "port_listener_logs.txt", "Text Files (*.txt);;JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for r in range(self.table_listener_logs.rowCount()):
                    row_txt = " | ".join(self.table_listener_logs.item(r, c).text() for c in range(7) if self.table_listener_logs.item(r, c))
                    f.write(row_txt + "\n")
            QMessageBox.information(self, "Başarılı", f"Loglar dışa aktarıldı:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Hata", f"Loglar aktarılamadı: {exc}")

    @Slot()
    def _change_data_directory(self):
        new_dir = QFileDialog.getExistingDirectory(self, "Yeni Veri Dizini Seçin", str(self.settings.data_path()))
        if new_dir:
            p = Path(new_dir).resolve()
            self.settings.set_data_path(p)
            self.lbl_data_path_val.setText(str(p))

            from infrastructure.disk_identifier import (
                get_disk_signature,
                stamp_disk_signature,
            )

            existing_sig = get_disk_signature(p)
            if not existing_sig:
                stamp_reply = QMessageBox.question(
                    self,
                    "Diski Resmi Yedek Diski Olarak İmzala",
                    f"Seçtiğiniz bu yeni veri dizinini ({p}) sistemin her takıldığında otomatik tanıyacağı "
                    f"'Resmi Yedekleme Diski' olarak imzalamak ve sisteme tanıtmak ister misiniz?\n\n"
                    f"(Onaylarsanız diskin sürücü harfi değişse bile sistem diski tanıyacaktır).",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if stamp_reply == QMessageBox.Yes:
                    sig = stamp_disk_signature(p, label=f"Resmi Yedek Diski ({p.name})")
                    self.settings.set_data_disk_signature(sig)
            else:
                self.settings.set_data_disk_signature(existing_sig)

            self._update_disk_space_info()
            QMessageBox.information(self, "Dizin Güncellendi", f"Veri dizini başarıyla '{p}' olarak değiştirildi.")

    @Slot()
    def _vacuum_database(self):
        if not self.engine:
            return
        try:
            with self.engine.db.get_conn() as conn:
                conn.execute("VACUUM")
            QMessageBox.information(self, "Başarılı", "Veritabanı başarıyla sıkıştırıldı (VACUUM tamamlandı).")
        except Exception as exc:
            QMessageBox.critical(self, "Hata", f"VACUUM başarısız: {exc}")

    @Slot()
    def _backup_database(self):
        if not self.engine:
            return
        db_file = self.settings.db_path()
        if not db_file.exists():
            QMessageBox.warning(self, "Uyarı", "Veritabanı dosyası bulunamadı.")
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Veritabanı Yedeği Kaydet", f"mail_archive_backup_{int(time.time())}.db", "SQLite DB (*.db)")
        if dest:
            try:
                shutil.copy2(db_file, dest)
                QMessageBox.information(self, "Başarılı", f"Veritabanı yedeği alındı:\n{dest}")
            except Exception as exc:
                QMessageBox.critical(self, "Hata", f"Yedek alınamadı: {exc}")

    @Slot()
    def _save_all_settings(self):
        # Save Language
        lang = self.combo_language.currentData()
        self.settings.set_language(lang)

        # Save Network settings
        self.settings.set_network_timeout(self.spin_timeout.value())
        self.settings.set_ssl_strict_mode(self.chk_ssl_strict.isChecked())

        QMessageBox.information(self, "Ayarlar Kaydedildi", "Tüm uygulama ve ağ ayarları başarıyla kaydedildi.")

    @Slot()
    def _run_windows_network_diag(self):
        from infrastructure.network_analyzer import diagnose_windows_network
        
        target = self.input_target_hosts.text().split(",")[0].strip() or "srv10.cenuta.email"
        diag = diagnose_windows_network(target_host=target, target_port=993)

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Windows Ağ & Bağlantı Teşhis Raporu")

        status_icon = "🟢" if diag["tcp_ok"] else "🔴"
        details = [
            f"<b>Hedef Sunucu:</b> {diag['target_host']}:993",
            f"<b>DNS Çözümleme:</b> {'🟢 ' + str(diag['dns_ip']) if diag['dns_ok'] else '🔴 Başarısız'}",
            f"<b>TCP Bağlantısı:</b> {'🟢 Erişilebilir (' + str(diag['tcp_latency']) + ' ms)' if diag['tcp_ok'] else '🔴 ZAMAN AŞIMI / ENGELLEDİ'}",
            f"<b>Kaspersky Ağ Sürücüsü Algısı:</b> {'⚠️ AKTİF ALGISI' if diag['kaspersky_driver_found'] else '✅ Algılanmadı'}",
            "<br/><b>TEŞHİS VE ÖNERİLEN ÇÖZÜM ADIMLARI:</b>"
        ]

        for rec in diag["recommendations"]:
            details.append(f"• {rec}")

        msg_box.setText(f"<b>Ağ Durumu: {status_icon}</b><br/><br/>" + "<br/>".join(details))
        if diag["tcp_ok"]:
            msg_box.setIcon(QMessageBox.Information)
        else:
            msg_box.setIcon(QMessageBox.Warning)

        msg_box.setStyleSheet("QMessageBox { min-width: 550px; font-size: 12px; }")
        msg_box.exec()

    # -----------------------------------------------------------------------
    # TAB: RBAC & User Management
    # -----------------------------------------------------------------------
    def _create_rbac_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Users Table Group
        users_box = QGroupBox("👥 Kayıtlı Kullanıcılar ve Yetki Rolleri")
        users_box.setStyleSheet("font-weight: 600; font-size: 12px;")
        u_layout = QVBoxLayout(users_box)

        self.table_users = QTableWidget()
        self.table_users.setColumnCount(7)
        self.table_users.setHorizontalHeaderLabels(["ID", "Kullanıcı Adı", "Ad Soyad", "Yetki Rolü", "E-Posta", "Son Giriş", "İşlemler"])
        self.table_users.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table_users.horizontalHeader().setStretchLastSection(True)
        self.table_users.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_users.setEditTriggers(QTableWidget.NoEditTriggers)
        u_layout.addWidget(self.table_users)

        layout.addWidget(users_box, stretch=2)

        # Add New User Group
        add_box = QGroupBox("➕ Yeni Kullanıcı Ekle")
        add_box.setStyleSheet("font-weight: 600; font-size: 12px;")
        form = QFormLayout(add_box)
        form.setSpacing(8)

        row1 = QHBoxLayout()
        self.txt_new_user = QLineEdit()
        self.txt_new_user.setPlaceholderText("Örn: ahmet.yilmaz")
        self.txt_new_pass = QLineEdit()
        self.txt_new_pass.setEchoMode(QLineEdit.Password)
        self.txt_new_pass.setPlaceholderText("Güçlü şifre belirleyin")

        row1.addWidget(QLabel("Kullanıcı Adı:"), 0)
        row1.addWidget(self.txt_new_user, 2)
        row1.addWidget(QLabel("Şifre:"), 0)
        row1.addWidget(self.txt_new_pass, 2)
        form.addRow(row1)

        row2 = QHBoxLayout()
        self.txt_new_fullname = QLineEdit()
        self.txt_new_fullname.setPlaceholderText("Ad Soyad")
        self.txt_new_email = QLineEdit()
        self.txt_new_email.setPlaceholderText("kullanici@sirket.com")

        self.combo_new_role = QComboBox()
        self.combo_new_role.addItem("OPERATOR (Yedekleme & Geri Yükleme Yapabilir)", "OPERATOR")
        self.combo_new_role.addItem("ADMIN (Tam Yetkili Yönetici)", "ADMIN")
        self.combo_new_role.addItem("VIEWER (Sadece İzleme / Rapor)", "VIEWER")

        row2.addWidget(QLabel("Ad Soyad:"), 0)
        row2.addWidget(self.txt_new_fullname, 2)
        row2.addWidget(QLabel("E-Posta:"), 0)
        row2.addWidget(self.txt_new_email, 2)
        row2.addWidget(QLabel("Yetki:"), 0)
        row2.addWidget(self.combo_new_role, 2)
        form.addRow(row2)

        btn_row = QHBoxLayout()
        self.btn_create_user = QPushButton("👤 Kullanıcıyı Kaydet")
        self.btn_create_user.setStyleSheet("background-color: #2563eb; color: white; padding: 8px 20px; font-weight: bold;")
        self.btn_create_user.clicked.connect(self._create_user_clicked)
        btn_row.addWidget(self.btn_create_user)
        btn_row.addStretch()
        form.addRow("", btn_row)

        layout.addWidget(add_box, stretch=1)
        return widget

    def _refresh_users(self):
        if not self.engine:
            return
        users = self.engine.list_users()
        self.table_users.setRowCount(len(users))
        for i, u in enumerate(users):
            self.table_users.setItem(i, 0, QTableWidgetItem(str(u.get("id", ""))))
            self.table_users.setItem(i, 1, QTableWidgetItem(u.get("username", "")))
            self.table_users.setItem(i, 2, QTableWidgetItem(u.get("full_name", "") or "-"))

            role = u.get("role", "OPERATOR")
            role_item = QTableWidgetItem(role)
            if role == "ADMIN":
                role_item.setForeground(QColor("#7c3aed"))
                role_item.setFont(QFont("", -1, QFont.Bold))
            elif role == "OPERATOR":
                role_item.setForeground(QColor("#0284c7"))
            else:
                role_item.setForeground(QColor("#64748b"))
            self.table_users.setItem(i, 3, role_item)

            self.table_users.setItem(i, 4, QTableWidgetItem(u.get("email", "") or "-"))
            self.table_users.setItem(i, 5, QTableWidgetItem(u.get("last_login_at", "")[:19] or "Hiç giriş yapmadı"))

            # Actions
            act_w = QWidget()
            act_l = QHBoxLayout(act_w)
            act_l.setContentsMargins(2, 2, 2, 2)
            act_l.setSpacing(4)

            btn_pass = QPushButton("🔑 Şifre")
            btn_pass.setStyleSheet("background-color: #f59e0b; color: white; padding: 2px 6px; font-size: 11px;")
            uid = u.get("id")
            uname = u.get("username")
            btn_pass.clicked.connect(lambda _, uid=uid, uname=uname: self._change_user_password(uid, uname))
            act_l.addWidget(btn_pass)

            if uname != "admin":
                btn_del = QPushButton("🗑 Sil")
                btn_del.setStyleSheet("background-color: #ef4444; color: white; padding: 2px 6px; font-size: 11px;")
                btn_del.clicked.connect(lambda _, uid=uid, uname=uname: self._delete_user_clicked(uid, uname))
                act_l.addWidget(btn_del)

            self.table_users.setCellWidget(i, 6, act_w)

    def _create_user_clicked(self):
        username = self.txt_new_user.text().strip()
        password = self.txt_new_pass.text()
        full_name = self.txt_new_fullname.text().strip()
        email = self.txt_new_email.text().strip()
        role = self.combo_new_role.currentData()

        if not username or not password:
            QMessageBox.warning(self, "Eksik Bilgi", "Kullanıcı adı ve şifre zorunludur.")
            return

        ok, msg, uid = self.engine.create_user(username=username, password=password, role=role, full_name=full_name, email=email)
        if ok:
            QMessageBox.information(self, "Başarılı", f"Kullanıcı oluşturuldu (ID: {uid})")
            self.txt_new_user.clear()
            self.txt_new_pass.clear()
            self.txt_new_fullname.clear()
            self.txt_new_email.clear()
            self._refresh_users()
        else:
            QMessageBox.warning(self, "Hata", msg)

    def _change_user_password(self, user_id: int, username: str):
        new_pass, ok = QInputDialog.getText(self, "Şifre Değiştir", f"'{username}' için yeni şifre girin:", QLineEdit.Password)
        if ok and new_pass:
            success, msg = self.engine.update_user_password(user_id, new_pass)
            if success:
                QMessageBox.information(self, "Başarılı", f"'{username}' kullanıcısının şifresi güncellendi.")
            else:
                QMessageBox.warning(self, "Hata", msg)

    def _delete_user_clicked(self, user_id: int, username: str):
        confirmed = DeleteConfirmDialog.confirm_deletion(
            parent=self,
            item_name=username,
            item_type="Kullanıcı Hesabı",
            details=f"Kullanıcı ID: {user_id}\nKullanıcı Adı: {username}\nBu kullanıcı hesabı ve atanmış tüm yetkileri kalıcı olarak silinecektir.",
            warning_text="Bu işlem geri alınamaz! Kullanıcı sisteme tekrar giriş yapamayacaktır."
        )
        if confirmed:
            ok, msg = self.engine.delete_user(user_id)
            if ok:
                self._refresh_users()
            else:
                QMessageBox.warning(self, "Hata", msg)

    # -----------------------------------------------------------------------
    # TAB: SMTP Notifications
    # -----------------------------------------------------------------------
    def _create_smtp_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        box = QGroupBox("📧 SMTP E-Posta Bildirim Yapılandırması")
        box.setStyleSheet("font-weight: 600; font-size: 12px;")
        form = QFormLayout(box)
        form.setSpacing(10)

        self.chk_smtp_enabled = QCheckBox("E-Posta Bildirimlerini Etkinleştir (Yedekleme durum raporları gönderilsin)")
        form.addRow(self.chk_smtp_enabled)

        # Host, Port, TLS
        server_row = QHBoxLayout()
        self.txt_smtp_host = QLineEdit()
        self.txt_smtp_host.setPlaceholderText("smtp.gmail.com veya mail.sirketiniz.com")
        self.spin_smtp_port = QSpinBox()
        self.spin_smtp_port.setRange(1, 65535)
        self.spin_smtp_port.setValue(587)
        self.chk_smtp_tls = QCheckBox("STARTTLS / SSL Kullan")
        self.chk_smtp_tls.setChecked(True)

        server_row.addWidget(QLabel("SMTP Sunucu:"), 0)
        server_row.addWidget(self.txt_smtp_host, 3)
        server_row.addWidget(QLabel("Port:"), 0)
        server_row.addWidget(self.spin_smtp_port, 1)
        server_row.addWidget(self.chk_smtp_tls, 1)
        form.addRow(server_row)

        # Auth
        auth_row = QHBoxLayout()
        self.txt_smtp_user = QLineEdit()
        self.txt_smtp_user.setPlaceholderText("bildirim@sirketiniz.com")
        self.txt_smtp_pass = QLineEdit()
        self.txt_smtp_pass.setEchoMode(QLineEdit.Password)
        self.txt_smtp_pass.setPlaceholderText("SMTP Şifresi veya App Password")

        auth_row.addWidget(QLabel("Kullanıcı Adı:"), 0)
        auth_row.addWidget(self.txt_smtp_user, 2)
        auth_row.addWidget(QLabel("Şifre:"), 0)
        auth_row.addWidget(self.txt_smtp_pass, 2)
        form.addRow(auth_row)

        # From & To
        self.txt_smtp_from = QLineEdit()
        self.txt_smtp_from.setPlaceholderText("Yedekleme Sistemi <bildirim@sirketiniz.com>")
        form.addRow("Gönderen Adresi (From):", self.txt_smtp_from)

        self.txt_smtp_to = QLineEdit()
        self.txt_smtp_to.setPlaceholderText("admin@sirketiniz.com, bilgi-islem@sirketiniz.com (Virgülle ayırın)")
        form.addRow("Alıcı E-Postalar (To):", self.txt_smtp_to)

        # Triggers
        trig_row = QHBoxLayout()
        self.chk_notify_success = QCheckBox("Başarılı Yedeklemelerde Rapor Gönder")
        self.chk_notify_success.setChecked(True)
        self.chk_notify_failure = QCheckBox("Hata & Başarısız Yedeklemelerde Acil Uyarı Gönder")
        self.chk_notify_failure.setChecked(True)
        trig_row.addWidget(self.chk_notify_success)
        trig_row.addWidget(self.chk_notify_failure)
        trig_row.addStretch()
        form.addRow("Bildirim Koşulları:", trig_row)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_test_smtp = QPushButton("📨 Test E-Postası Gönder")
        self.btn_test_smtp.setStyleSheet("background-color: #0284c7; color: white; padding: 8px 18px; font-weight: bold;")
        self.btn_test_smtp.clicked.connect(self._test_smtp_clicked)

        self.btn_save_smtp = QPushButton("💾 SMTP Ayarlarını Kaydet")
        self.btn_save_smtp.setStyleSheet("background-color: #16a34a; color: white; padding: 8px 20px; font-weight: bold;")
        self.btn_save_smtp.clicked.connect(self._save_smtp_settings)

        btn_row.addWidget(self.btn_test_smtp)
        btn_row.addWidget(self.btn_save_smtp)
        btn_row.addStretch()
        form.addRow("", btn_row)

        layout.addWidget(box)
        layout.addStretch()
        return widget

    def _load_smtp_settings(self):
        if not self.engine:
            return
        cfg = self.engine.get_smtp_settings()
        self.chk_smtp_enabled.setChecked(cfg.get("enabled", False))
        self.txt_smtp_host.setText(cfg.get("host", ""))
        self.spin_smtp_port.setValue(cfg.get("port", 587))
        self.chk_smtp_tls.setChecked(cfg.get("use_tls", True))
        self.txt_smtp_user.setText(cfg.get("username", ""))
        self.txt_smtp_pass.setText(cfg.get("password", ""))
        self.txt_smtp_from.setText(cfg.get("from_address", ""))
        to_list = cfg.get("to_addresses", [])
        self.txt_smtp_to.setText(", ".join(to_list) if isinstance(to_list, list) else str(to_list))
        self.chk_notify_success.setChecked(cfg.get("notify_on_success", True))
        self.chk_notify_failure.setChecked(cfg.get("notify_on_failure", True))

    def _save_smtp_settings(self):
        if not self.engine:
            return
        to_raw = [x.strip() for x in self.txt_smtp_to.text().split(",") if x.strip()]
        cfg = {
            "enabled": self.chk_smtp_enabled.isChecked(),
            "host": self.txt_smtp_host.text().strip(),
            "port": self.spin_smtp_port.value(),
            "use_tls": self.chk_smtp_tls.isChecked(),
            "username": self.txt_smtp_user.text().strip(),
            "password": self.txt_smtp_pass.text(),
            "from_address": self.txt_smtp_from.text().strip() or self.txt_smtp_user.text().strip(),
            "to_addresses": to_raw,
            "notify_on_success": self.chk_notify_success.isChecked(),
            "notify_on_failure": self.chk_notify_failure.isChecked(),
        }
        self.engine.save_smtp_settings(cfg)
        QMessageBox.information(self, "Başarılı", "SMTP Bildirim Ayarları başarıyla kaydedildi.")

    def _test_smtp_clicked(self):
        if not self.engine:
            return
        to_raw = [x.strip() for x in self.txt_smtp_to.text().split(",") if x.strip()]
        recipient = to_raw[0] if to_raw else self.txt_smtp_user.text().strip()
        if not recipient:
            QMessageBox.warning(self, "Alıcı Gerekli", "Lütfen bir alıcı e-posta adresi belirtin.")
            return

        cfg = {
            "enabled": True,
            "host": self.txt_smtp_host.text().strip(),
            "port": self.spin_smtp_port.value(),
            "use_tls": self.chk_smtp_tls.isChecked(),
            "username": self.txt_smtp_user.text().strip(),
            "password": self.txt_smtp_pass.text(),
            "from_address": self.txt_smtp_from.text().strip() or self.txt_smtp_user.text().strip(),
            "to_addresses": [recipient],
        }

        self.btn_test_smtp.setEnabled(False)
        self.btn_test_smtp.setText("Gönderiliyor...")

        try:
            ok, msg = self.engine.test_smtp_connection(cfg, recipient=recipient)
            if ok:
                QMessageBox.information(self, "Test Başarılı", f"Test e-postası başarıyla '{recipient}' adresine gönderildi!")
            else:
                QMessageBox.warning(self, "Test Başarısız", f"E-posta gönderilemedi:\n{msg}")
        finally:
            self.btn_test_smtp.setEnabled(True)
            self.btn_test_smtp.setText("📨 Test E-Postası Gönder")

    def refresh(self):
        """Refresh users, SMTP config, and storage stats asynchronously."""
        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_reading"):
            parent_mw.notify_disk_reading("💾 Disk Okunuyor", "Kullanıcılar, SMTP ve disk durumu taranıyor...")

        if self._loader_worker and self._loader_worker.isRunning():
            self._loader_worker.quit()
            self._loader_worker.wait()

        self._loader_worker = SettingsDataLoaderWorker(self.engine, self.settings, parent=self)
        self._loader_worker.data_loaded_signal.connect(self._on_settings_data_loaded)
        self._loader_worker.error_signal.connect(self._on_settings_data_error)
        self._loader_worker.start()

    @Slot(dict)
    def _on_settings_data_loaded(self, data: dict):
        users = data.get("users", [])
        if hasattr(self, "table_users"):
            self.table_users.setRowCount(len(users))
            for i, u in enumerate(users):
                self.table_users.setItem(i, 0, QTableWidgetItem(str(u.get("id", ""))))
                self.table_users.setItem(i, 1, QTableWidgetItem(u.get("username", "")))
                self.table_users.setItem(i, 2, QTableWidgetItem(u.get("full_name", "") or "-"))

                role = u.get("role", "OPERATOR")
                role_item = QTableWidgetItem(role)
                if role == "ADMIN":
                    role_item.setForeground(QColor("#7c3aed"))
                    role_item.setFont(QFont("", -1, QFont.Bold))
                elif role == "OPERATOR":
                    role_item.setForeground(QColor("#0284c7"))
                else:
                    role_item.setForeground(QColor("#64748b"))
                self.table_users.setItem(i, 3, role_item)

                self.table_users.setItem(i, 4, QTableWidgetItem(u.get("email", "") or "-"))
                self.table_users.setItem(i, 5, QTableWidgetItem(u.get("last_login_at", "")[:19] or "Hiç giriş yapmadı"))

                act_w = QWidget()
                act_l = QHBoxLayout(act_w)
                act_l.setContentsMargins(2, 2, 2, 2)
                act_l.setSpacing(4)

                btn_pass = QPushButton("🔑 Şifre")
                btn_pass.setStyleSheet("background-color: #f59e0b; color: white; padding: 2px 6px; font-size: 11px;")
                uid = u.get("id")
                uname = u.get("username")
                btn_pass.clicked.connect(lambda _, uid=uid, uname=uname: self._change_user_password(uid, uname))
                act_l.addWidget(btn_pass)

                if uname != "admin":
                    btn_del = QPushButton("🗑 Sil")
                    btn_del.setStyleSheet("background-color: #ef4444; color: white; padding: 2px 6px; font-size: 11px;")
                    btn_del.clicked.connect(lambda _, uid=uid, uname=uname: self._delete_user_clicked(uid, uname))
                    act_l.addWidget(btn_del)

                self.table_users.setCellWidget(i, 6, act_w)

        # SMTP config
        cfg = data.get("smtp", {})
        if cfg and hasattr(self, "chk_smtp_enabled"):
            self.chk_smtp_enabled.setChecked(cfg.get("enabled", False))
            self.txt_smtp_host.setText(cfg.get("host", ""))
            self.spin_smtp_port.setValue(cfg.get("port", 587))
            self.chk_smtp_tls.setChecked(cfg.get("use_tls", True))
            self.txt_smtp_user.setText(cfg.get("username", ""))
            self.txt_smtp_pass.setText(cfg.get("password", ""))
            self.txt_smtp_from.setText(cfg.get("from_address", ""))
            to_list = cfg.get("to_addresses", [])
            self.txt_smtp_to.setText(", ".join(to_list) if isinstance(to_list, list) else str(to_list))
            self.chk_notify_success.setChecked(cfg.get("notify_on_success", True))
            self.chk_notify_failure.setChecked(cfg.get("notify_on_failure", True))

        # Locations
        loc_status = data.get("locations", [])
        if hasattr(self, "tbl_locations"):
            self.tbl_locations.setRowCount(0)
            for idx, loc in enumerate(loc_status):
                self.tbl_locations.insertRow(idx)
                self.tbl_locations.setItem(idx, 0, QTableWidgetItem(loc["name"]))
                self.tbl_locations.setItem(idx, 1, QTableWidgetItem(loc["path"]))

                exists = loc["exists"]
                st_item = QTableWidgetItem("🟢 Erişilebilir" if exists else "🔴 Bulunamadı")
                st_item.setForeground(QColor("#10b981") if exists else QColor("#ef4444"))
                st_item.setFont(QFont("Segoe UI", 9, QFont.Bold))
                self.tbl_locations.setItem(idx, 2, st_item)

                if loc["name"] == "Default":
                    lbl_def = QLabel("— Varsayılan —")
                    lbl_def.setAlignment(Qt.AlignCenter)
                    lbl_def.setStyleSheet("color: #64748b; font-size: 10px;")
                    self.tbl_locations.setCellWidget(idx, 3, lbl_def)
                else:
                    btn_del = QPushButton("Sil")
                    btn_del.setStyleSheet("background: #ef4444; color: white; font-weight: bold; padding: 2px 8px; font-size: 10px; border-radius: 3px;")
                    btn_del.clicked.connect(lambda _, name=loc["name"]: self._remove_storage_location(name))
                    self.tbl_locations.setCellWidget(idx, 3, btn_del)

        # Disk info
        disk_info = data.get("disk_info", {})
        if "error" not in disk_info and "total_gb" in disk_info:
            drive = disk_info.get("drive", "")
            total_gb = disk_info.get("total_gb", 0)
            used_gb = disk_info.get("used_gb", 0)
            free_gb = disk_info.get("free_gb", 0)
            used_pct = disk_info.get("used_pct", 0)

            if hasattr(self, "lbl_disk_info"):
                self.lbl_disk_info.setText(
                    f"Sürücü: {drive}  |  Toplam: {total_gb:.1f} GB  |  "
                    f"Kullanılan: {used_gb:.1f} GB ({used_pct}%)  |  Boş Alan: {free_gb:.1f} GB"
                )
            if hasattr(self, "progress_disk"):
                self.progress_disk.setValue(used_pct)

        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_ready"):
            parent_mw.notify_disk_ready("Sistem ayarları ve kullanıcılar yüklendi.")

    @Slot(str)
    def _on_settings_data_error(self, err_msg: str):
        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_ready"):
            parent_mw.notify_disk_ready("Ayarlar yüklenemedi.")
        logger.error("SettingsPanel data loading error: %s", err_msg)

    def apply_permissions(self, role: str):
        """Restrict RBAC tab and settings depending on role."""
        is_admin = (role.upper() == "ADMIN")
        self.btn_create_user.setEnabled(is_admin)
        self.btn_save_smtp.setEnabled(is_admin)
        self.btn_save_all.setEnabled(is_admin)

