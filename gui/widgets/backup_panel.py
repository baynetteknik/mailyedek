"""
backup_panel.py — Enterprise Backup & Recovery Center (Email Cloud, SQL Server, and VHDX/Hyper-V).
Equipped with 3-Section Unified Layout (Category Tree, 88px DBGrid, Right Action Drawer),
Multi-Account Amazon S3 and Google Drive DBGrid Management,
Numeric Retention Stepper, Asynchronous Lazy Loading (<5ms), and Collapsible Live Log Console.
"""

import os
import subprocess
import threading
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    Qt, Signal, Slot, QObject, QThread, QPoint, QSize,
    QAbstractTableModel, QModelIndex, QSortFilterProxyModel
)
from PySide6.QtGui import QColor, QFont, QCursor, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QGroupBox, QTextEdit, QMessageBox, QComboBox, QLineEdit,
    QFormLayout, QCheckBox, QFileDialog, QTabWidget, QSpinBox,
    QSplitter, QFrame, QRadioButton, QButtonGroup, QScrollArea,
    QDialog, QDialogButtonBox, QApplication, QMenu
)

from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.widgets.numeric_stepper import NumericStepperWidget
from gui.widgets.cloud_account_dialog import CloudAccountDialog
from gui.dialogs.sql_job_dialog import SqlJobDialog
from gui.dialogs.vhdx_job_dialog import VhdxJobDialog
from gui.dialogs.delete_confirm_dialog import DeleteConfirmDialog
from gui.widgets.backup_right_sidebar_widget import BackupRightSidebarWidget

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured Log Entry & Model
# ---------------------------------------------------------------------------

class BackupLogEntry:
    __slots__ = ('time', 'level', 'source', 'message')

    def __init__(self, time_str: str, level: str, source: str, message: str):
        self.time = time_str
        self.level = level
        self.source = source
        self.message = message


class BackupLogTableModel(QAbstractTableModel):
    COLUMNS = ["Saat", "Seviye", "Kaynak", "Mesaj"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[BackupLogEntry] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLUMNS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        entry = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            return [entry.time, entry.level, entry.source, entry.message][col]
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def append_entry(self, entry: BackupLogEntry):
        row = len(self._rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append(entry)
        self.endInsertRows()

    def clear_entries(self):
        c = len(self._rows)
        if c == 0:
            return
        self.beginRemoveRows(QModelIndex(), 0, c - 1)
        self._rows.clear()
        self.endRemoveRows()


# ---------------------------------------------------------------------------
# Background Async Data Loader (Instant Opening < 5ms)
# ---------------------------------------------------------------------------

class BackupDataLoaderWorker(QThread):
    data_loaded = Signal(object)  # dict containing all data

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine

    def run(self):
        result: Dict[str, Any] = {
            "sql_jobs": [],
            "vhdx_jobs": [],
            "cloud_accounts": [],
            "drives": [],
            "history": []
        }

        # 1. Cloud Accounts from AppSettings
        try:
            if hasattr(self.engine, "settings"):
                result["cloud_accounts"] = self.engine.settings.cloud_accounts()
        except Exception as e:
            logger.debug("Failed loading cloud accounts: %s", e)

        # 2. Available Drives
        try:
            result["drives"] = self.engine.list_available_drives()
        except Exception as e:
            logger.debug("Failed loading drives: %s", e)

        # 3. Saved SQL Jobs
        try:
            if hasattr(self.engine, "get_sql_backup_jobs"):
                result["sql_jobs"] = self.engine.get_sql_backup_jobs()
            elif hasattr(self.engine, "sql_backup_usecase"):
                result["sql_jobs"] = self.engine.sql_backup_usecase.list_jobs()
        except Exception as e:
            logger.debug("Failed loading SQL jobs: %s", e)

        # 4. Saved VHDX Jobs
        try:
            if hasattr(self.engine, "get_vhdx_backup_jobs"):
                result["vhdx_jobs"] = self.engine.get_vhdx_backup_jobs()
            elif hasattr(self.engine, "vhdx_backup_usecase"):
                result["vhdx_jobs"] = self.engine.vhdx_backup_usecase.list_jobs()
        except Exception as e:
            logger.debug("Failed loading VHDX jobs: %s", e)

        # 5. History
        try:
            if hasattr(self.engine, "get_backup_history"):
                result["history"] = self.engine.get_backup_history(limit=50)
        except Exception as e:
            logger.debug("Failed loading backup history: %s", e)

        self.data_loaded.emit(result)


# ---------------------------------------------------------------------------
# Backup Worker Signals
# ---------------------------------------------------------------------------

class BackupWorkerSignals(QObject):
    log_message = Signal(str)
    sql_progress = Signal(str)
    vhdx_progress = Signal(str, float, float)
    finished = Signal(str, object)
    error = Signal(str, str)


# ---------------------------------------------------------------------------
# Main Backup & Recovery Center Widget
# ---------------------------------------------------------------------------

class BackupPanel(QWidget):
    """
    Enterprise Backup & Recovery Center Widget.
    Equipped with 3-section layout, multi-account S3 / Google Drive DBGrid,
    88px row height, numeric retention stepper, and async lazy loading.
    """

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.settings: AppSettings = engine.settings if hasattr(engine, "settings") else AppSettings()
        self.signals = BackupWorkerSignals()

        # Internal Data Cache
        self._all_items: List[Dict[str, Any]] = []
        self._filtered_items: List[Dict[str, Any]] = []
        self._active_category: str = "all"
        self._is_refreshing: bool = False
        self._current_row_height: int = int(self.settings.get("backup_grid_row_height", 88))
        self._retention_mode: str = "count"
        self._retention_val: int = 10
        self.loader: Optional[BackupDataLoaderWorker] = None

        self._setup_signals()
        self._setup_ui()
        self._init_compat_combos()

    def _setup_signals(self):
        self.signals.log_message.connect(self._append_log)
        self.signals.sql_progress.connect(self._on_sql_progress)
        self.signals.vhdx_progress.connect(self._on_vhdx_progress)
        self.signals.finished.connect(self._on_backup_finished)
        self.signals.error.connect(self._on_backup_error)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(6)

        # -------------------------------------------------------------
        # 1. TOP HEADER & SEARCH & QUICK ACTION BAR (Compact & Clean)
        # -------------------------------------------------------------
        top_bar = QFrame()
        top_bar.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 4px;
            }
        """)
        top_layout = QVBoxLayout(top_bar)
        top_layout.setContentsMargins(8, 6, 8, 6)
        top_layout.setSpacing(6)

        # Top Row: Search Box + Quick Stat Badges
        r1 = QHBoxLayout()
        r1.setSpacing(8)

        # Search Bar
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Görev, veritabanı veya bulut hesabı ara...")
        self.txt_search.setFixedWidth(280)
        self.txt_search.setFixedHeight(28)
        self.txt_search.setStyleSheet("""
            QLineEdit {
                background: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 2px 8px;
                font-size: 11px;
                color: #0f172a;
            }
            QLineEdit:focus {
                background: #ffffff;
                border-color: #2563eb;
            }
        """)
        self.txt_search.textChanged.connect(self._apply_search_filter)
        r1.addWidget(self.txt_search)

        # Quick Stat Badges
        self.badge_total = self._create_stat_badge("Toplam Görev", "0", "#3b82f6")
        self.badge_ready = self._create_stat_badge("Hazır", "0", "#10b981")
        self.badge_cloud = self._create_stat_badge("Bulut Hesabı", "0", "#8b5cf6")
        r1.addWidget(self.badge_total)
        r1.addWidget(self.badge_ready)
        r1.addWidget(self.badge_cloud)

        r1.addStretch()
        top_layout.addLayout(r1)

        # Second Row: Action Buttons
        r2 = QHBoxLayout()
        r2.setSpacing(6)

        btn_run_sel = QPushButton("⚡ Seçilenleri Yedekle")
        btn_run_sel.setStyleSheet(self._top_btn_style("#2563eb", text_color="#ffffff", bold=True))
        btn_run_sel.clicked.connect(self._backup_selected)
        r2.addWidget(btn_run_sel)

        btn_add_sql = QPushButton("➕ Yeni SQL Görevi")
        btn_add_sql.setStyleSheet(self._top_btn_style("#ffffff", border="#cbd5e1", text_color="#1e293b"))
        btn_add_sql.clicked.connect(self._open_new_sql_job_dialog)
        r2.addWidget(btn_add_sql)

        btn_add_vhdx = QPushButton("➕ Yeni VHDX Görevi")
        btn_add_vhdx.setStyleSheet(self._top_btn_style("#ffffff", border="#cbd5e1", text_color="#1e293b"))
        btn_add_vhdx.clicked.connect(self._open_new_vhdx_job_dialog)
        r2.addWidget(btn_add_vhdx)

        btn_add_s3 = QPushButton("☁️ Amazon S3 Ekle")
        btn_add_s3.setStyleSheet(self._top_btn_style("#ffffff", border="#0284c7", text_color="#0284c7"))
        btn_add_s3.clicked.connect(lambda: self._open_cloud_account_dialog("s3"))
        r2.addWidget(btn_add_s3)

        btn_add_gd = QPushButton("📁 Google Drive Ekle")
        btn_add_gd.setStyleSheet(self._top_btn_style("#ffffff", border="#059669", text_color="#059669"))
        btn_add_gd.clicked.connect(lambda: self._open_cloud_account_dialog("gdrive"))
        r2.addWidget(btn_add_gd)

        btn_refresh = QPushButton("🔄 Yenile")
        btn_refresh.setStyleSheet(self._top_btn_style("#f1f5f9", border="#cbd5e1", text_color="#475569"))
        btn_refresh.clicked.connect(self.refresh)
        r2.addWidget(btn_refresh)

        r2.addStretch()
        top_layout.addLayout(r2)
        main_layout.addWidget(top_bar)

        # -------------------------------------------------------------
        # 2. MAIN 3-SECTION SPLITTER (Left Tree, Center Grid+Log, Right Sidebar)
        # -------------------------------------------------------------
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(4)

        # --- LEFT SIDEBAR (Category / Target Explorer) ---
        self.left_sidebar = QFrame()
        self.left_sidebar.setMinimumWidth(160)
        self.left_sidebar.setMaximumWidth(280)
        self.left_sidebar.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
            }
        """)
        left_layout = QVBoxLayout(self.left_sidebar)
        left_layout.setContentsMargins(6, 8, 6, 8)
        left_layout.setSpacing(4)

        lbl_cat = QLabel("📂 KATEGORİLER & HEDEFLER")
        lbl_cat.setStyleSheet("font-weight: bold; font-size: 10px; color: #64748b; padding-left: 4px;")
        left_layout.addWidget(lbl_cat)

        self.btn_cat_all = self._create_cat_button("📁 Tüm Yedekler", "all", active=True)
        self.btn_cat_sql = self._create_cat_button("🗄️ SQL Veritabanları", "sql")
        self.btn_cat_vhdx = self._create_cat_button("💾 Hyper-V & VHDX", "vhdx")
        self.btn_cat_s3 = self._create_cat_button("☁️ Amazon S3 Hesapları", "s3")
        self.btn_cat_gd = self._create_cat_button("📁 Google Drive Hesapları", "gdrive")
        self.btn_cat_history = self._create_cat_button("📜 Yedekleme Geçmişi", "history")

        self.cat_buttons = [
            self.btn_cat_all, self.btn_cat_sql, self.btn_cat_vhdx,
            self.btn_cat_s3, self.btn_cat_gd, self.btn_cat_history
        ]
        for b in self.cat_buttons:
            left_layout.addWidget(b)

        left_layout.addStretch()

        # Drive Status Mini Box
        self.drive_status_box = QFrame()
        self.drive_status_box.setStyleSheet("QFrame { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 4px; }")
        drive_vbox = QVBoxLayout(self.drive_status_box)
        drive_vbox.setContentsMargins(4, 4, 4, 4)
        drive_vbox.setSpacing(2)
        lbl_drv_hdr = QLabel("💾 Depolama Durumu:")
        lbl_drv_hdr.setStyleSheet("font-size: 10px; font-weight: bold; color: #334155;")
        drive_vbox.addWidget(lbl_drv_hdr)
        self.lbl_drive_info = QLabel("Diskler taranıyor...")
        self.lbl_drive_info.setStyleSheet("font-size: 9.5px; color: #64748b;")
        drive_vbox.addWidget(self.lbl_drive_info)
        left_layout.addWidget(self.drive_status_box)

        self.main_splitter.addWidget(self.left_sidebar)

        # --- CENTER MAIN AREA (Live KPI + DBGrid Table + Collapsible Log) ---
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(6)

        # Live KPI Cards Row
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(6)
        self.card_total = self._create_kpi_card("TOPLAM YEDEKLEME", "0", "Tamamlanan işlem", "#2563eb")
        self.card_last_succ = self._create_kpi_card("SON BAŞARILI", "--:--", "Otomatik/Manuel", "#16a34a")
        self.card_storage = self._create_kpi_card("DEPOLAMA ALANI", "-- GB", "Kullanılabilir", "#0284c7")
        self.card_errors = self._create_kpi_card("UYARI / HATA", "0", "İnceleme gereken", "#dc2626")
        kpi_row.addWidget(self.card_total)
        kpi_row.addWidget(self.card_last_succ)
        kpi_row.addWidget(self.card_storage)
        kpi_row.addWidget(self.card_errors)
        center_layout.addLayout(kpi_row)

        # DBGrid Table (Default 88px Row Height)
        self.grid_table = QTableWidget()
        self.grid_table.setColumnCount(4)
        self.grid_table.setHorizontalHeaderLabels(["", "GÖREV & HEDEF DETAYLARI", "DURUM & İLERLEME", "İŞLEMLER"])
        self.grid_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.grid_table.setColumnWidth(0, 36)
        self.grid_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.grid_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.grid_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.grid_table.setColumnWidth(3, 210)
        self.grid_table.verticalHeader().setDefaultSectionSize(self._current_row_height)
        self.grid_table.verticalHeader().setVisible(False)
        self.grid_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.grid_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.grid_table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                gridline-color: #f1f5f9;
            }
            QHeaderView::section {
                background-color: #f8fafc;
                color: #475569;
                font-weight: bold;
                font-size: 11px;
                border: none;
                border-bottom: 2px solid #e2e8f0;
                padding: 6px;
            }
            QTableWidget::item:selected {
                background-color: #eff6ff;
            }
        """)
        center_layout.addWidget(self.grid_table, stretch=1)

        # Collapsible Live Console (Bottom)
        self.log_container = QFrame()
        self.log_container.setObjectName("log_container")
        self.log_container.setStyleSheet("""
            QFrame#log_container {
                background-color: #0f172a;
                border-radius: 6px;
                border: 1px solid #1e293b;
            }
        """)
        log_layout = QVBoxLayout(self.log_container)
        log_layout.setContentsMargins(8, 4, 8, 4)
        log_layout.setSpacing(4)

        log_hdr_row = QHBoxLayout()
        log_hdr_row.setSpacing(8)

        self.log_status_lbl = QLabel("📋 Canlı İşlem Günlüğü (Live Console) — Hazır")
        self.log_status_lbl.setStyleSheet("color: #94a3b8; font-weight: 600; font-size: 10.5px;")
        log_hdr_row.addWidget(self.log_status_lbl, stretch=1)

        self.btn_toggle_log = QPushButton("👁️ Günlüğü Göster")
        self.btn_toggle_log.setStyleSheet("background-color: #334155; color: #f1f5f9; font-size: 10.5px; font-weight: 600; padding: 2px 8px; border-radius: 4px; border: 1px solid #475569;")
        self.btn_toggle_log.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_log.clicked.connect(self._toggle_live_log)
        log_hdr_row.addWidget(self.btn_toggle_log)

        btn_clear_log = QPushButton("🧹 Temizle")
        btn_clear_log.setStyleSheet("background-color: #1e293b; color: #94a3b8; font-size: 10.5px; padding: 2px 8px; border-radius: 4px; border: 1px solid #334155;")
        btn_clear_log.setCursor(Qt.PointingHandCursor)
        btn_clear_log.clicked.connect(self._clear_log)
        log_hdr_row.addWidget(btn_clear_log)

        log_layout.addLayout(log_hdr_row)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(110)
        self.log_output.setStyleSheet("""
            QTextEdit {
                background-color: #020617;
                color: #38bdf8;
                font-family: 'Consolas', monospace;
                font-size: 10.5px;
                border-radius: 4px;
                padding: 4px;
                border: 1px solid #1e293b;
            }
        """)
        self.log_output.setVisible(False)
        log_layout.addWidget(self.log_output)

        center_layout.addWidget(self.log_container)
        self.main_splitter.addWidget(center_widget)

        # --- RIGHT SIDEBAR (Action Drawer & Retention Stepper) ---
        self.right_sidebar = BackupRightSidebarWidget(parent=self)
        self.right_sidebar.setMinimumWidth(210)
        self.right_sidebar.setMaximumWidth(280)
        self._connect_right_sidebar()
        self.main_splitter.addWidget(self.right_sidebar)

        # Set initial splitter proportions: 180px : 1fr : 240px
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([180, 700, 240])

        main_layout.addWidget(self.main_splitter, stretch=1)

    # ------------------------------------------------------------------
    # Sidebar Connections
    # ------------------------------------------------------------------

    def _connect_right_sidebar(self):
        self.right_sidebar.backup_selected_requested.connect(self._backup_selected)
        self.right_sidebar.backup_all_requested.connect(self._backup_all)
        self.right_sidebar.row_height_changed.connect(self._set_row_height)
        self.right_sidebar.retention_changed.connect(self._on_retention_changed)
        self.right_sidebar.add_s3_account_requested.connect(lambda: self._open_cloud_account_dialog("s3"))
        self.right_sidebar.add_gdrive_account_requested.connect(lambda: self._open_cloud_account_dialog("gdrive"))
        self.right_sidebar.new_sql_job_requested.connect(self._open_new_sql_job_dialog)
        self.right_sidebar.new_vhdx_job_requested.connect(self._open_new_vhdx_job_dialog)
        self.right_sidebar.toggle_log_requested.connect(self._toggle_live_log)
        self.right_sidebar.export_excel_requested.connect(self._export_to_excel)

    # ------------------------------------------------------------------
    # Data Loading (Async Lazy Load with Thread Safety)
    # ------------------------------------------------------------------

    def refresh(self):
        """Asynchronously load data to ensure instant UI rendering < 5ms."""
        if hasattr(self, "loader") and self.loader is not None and self.loader.isRunning():
            return  # Already running in background, do not overwrite active QThread!
        self._is_refreshing = True
        parent_mw = self.parent() if hasattr(self, "parent") else None
        if parent_mw and hasattr(parent_mw, "notify_disk_reading"):
            parent_mw.notify_disk_reading("💾 Disk Okunuyor", "Yedekleme görevleri ve depolama alanları diskten taranıyor...")
        self.loader = BackupDataLoaderWorker(self.engine, parent=self)
        self.loader.data_loaded.connect(self._on_data_loaded)
        self.loader.start()

    @Slot(object)
    def _on_data_loaded(self, data: Dict[str, Any]):
        self._is_refreshing = False
        parent_mw = self.parent() if hasattr(self, "parent") else None
        if parent_mw and hasattr(parent_mw, "notify_disk_ready"):
            parent_mw.notify_disk_ready("✅ Yedekleme Görevleri Hazır", "Görev ve bulut hesapları güncellendi.", auto_dismiss_seconds=3)
        sql_jobs = data.get("sql_jobs", [])
        vhdx_jobs = data.get("vhdx_jobs", [])
        cloud_accs = data.get("cloud_accounts", [])
        drives = data.get("drives", [])
        history = data.get("history", [])

        # Update mini drive status box
        if drives:
            lines = []
            for d in drives[:3]:
                lines.append(f"{d.get('path', '')} ({d.get('free_gb', 0):.1f} GB Boş)")
            self.lbl_drive_info.setText("\n".join(lines))
            total_free = sum(d.get("free_gb", 0) for d in drives)
            self._update_kpi_card(self.card_storage, f"{total_free:.0f} GB", "Kullanılabilir Alan")
        else:
            self.lbl_drive_info.setText("Sabit disk: Hazır")

        # Rebuild _all_items list
        self._all_items.clear()

        # 1. SQL Jobs
        for job in sql_jobs:
            self._all_items.append({
                "type": "sql",
                "id": job.get("id", job.get("name")),
                "name": job.get("name", "SQL Yedek"),
                "engine": job.get("engine_type", "mssql").upper(),
                "target": job.get("dest_dir", "data/backups/sql"),
                "retention": f"{job.get('retention_value', 10)} adet",
                "status": "Hazır",
                "progress": 0,
                "raw": job
            })

        # 2. VHDX Jobs
        for job in vhdx_jobs:
            self._all_items.append({
                "type": "vhdx",
                "id": job.get("id", job.get("name")),
                "name": job.get("name", "VHDX Yedek"),
                "engine": "VHDX / Hyper-V",
                "target": job.get("dest_dir", "data/backups/vhdx"),
                "retention": f"{job.get('retention_value', 10)} adet",
                "status": "Hazır",
                "progress": 0,
                "raw": job
            })

        # 3. Cloud Accounts (S3 & Google Drive)
        for acc in cloud_accs:
            p = acc.get("provider", "s3").lower()
            is_def = acc.get("is_default", False)
            target_str = acc.get("bucket", "") if p == "s3" else acc.get("credentials_path", "")
            self._all_items.append({
                "type": p,
                "id": acc.get("id"),
                "name": acc.get("name", "Bulut Deposu"),
                "engine": "Amazon S3" if p == "s3" else "Google Drive",
                "target": f"Hedef: {target_str}" + (" (Varsayılan)" if is_def else ""),
                "retention": "Bulut Deposu",
                "status": "Hazır",
                "progress": 0,
                "raw": acc
            })

        # Update Badge counts
        self.badge_total.setText(f"Toplam Görev: {len(self._all_items)}")
        self.badge_ready.setText(f"Hazır: {len(self._all_items)}")
        self.badge_cloud.setText(f"Bulut Hesabı: {len(cloud_accs)}")

        self._update_kpi_card(self.card_total, str(len(history) or len(self._all_items)), "Aktif/Geçmiş")

        self._render_grid_table()

    # ------------------------------------------------------------------
    # Rendering & DBGrid Population (88px Row Height)
    # ------------------------------------------------------------------

    def _render_grid_table(self):
        search_query = self.txt_search.text().strip().lower()

        filtered = []
        for item in self._all_items:
            # Category filter
            if self._active_category != "all":
                if self._active_category == "history":
                    pass  # history handled separately
                elif item["type"] != self._active_category:
                    continue

            # Search text filter
            if search_query:
                combined = f"{item['name']} {item['engine']} {item['target']}".lower()
                if search_query not in combined:
                    continue

            filtered.append(item)

        self._filtered_items = filtered
        self.grid_table.setRowCount(len(filtered))

        for row, item in enumerate(filtered):
            self.grid_table.setRowHeight(row, self._current_row_height)

            # Col 0: Checkbox
            chk = QCheckBox()
            chk.setStyleSheet("QCheckBox { margin-left: 10px; }")
            chk.setChecked(True)
            self.grid_table.setCellWidget(row, 0, chk)

            # Col 1: Job & Target Details Card Widget
            col1_widget = self._create_job_details_widget(item)
            self.grid_table.setCellWidget(row, 1, col1_widget)

            # Col 2: Status & Live Progress Bar Widget
            col2_widget = self._create_status_progress_widget(item)
            self.grid_table.setCellWidget(row, 2, col2_widget)

            # Col 3: Actions Widget
            col3_widget = self._create_actions_widget(row, item)
            self.grid_table.setCellWidget(row, 3, col3_widget)

    def _create_job_details_widget(self, item: Dict[str, Any]) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        # Type Icon & Engine Badge
        icon_map = {"sql": "🗄️", "vhdx": "💾", "s3": "☁️", "gdrive": "📁"}
        icon_str = icon_map.get(item["type"], "📦")

        lbl_icon = QLabel(icon_str)
        lbl_icon.setStyleSheet("font-size: 16px;")
        top_row.addWidget(lbl_icon)

        lbl_name = QLabel(item["name"])
        lbl_name.setStyleSheet("font-weight: bold; font-size: 12px; color: #0f172a;")
        top_row.addWidget(lbl_name)

        badge_engine = QLabel(f" {item['engine']} ")
        badge_engine.setStyleSheet("""
            background-color: #f1f5f9;
            color: #334155;
            font-size: 10px;
            font-weight: 600;
            border-radius: 4px;
            border: 1px solid #cbd5e1;
            padding: 1px 4px;
        """)
        top_row.addWidget(badge_engine)

        if item.get("retention"):
            badge_ret = QLabel(f" 🛡️ {item['retention']} ")
            badge_ret.setStyleSheet("""
                background-color: #eff6ff;
                color: #1d4ed8;
                font-size: 9.5px;
                font-weight: 600;
                border-radius: 4px;
                padding: 1px 4px;
            """)
            top_row.addWidget(badge_ret)

        top_row.addStretch()
        layout.addLayout(top_row)

        lbl_target = QLabel(f"📍 {item['target']}")
        lbl_target.setStyleSheet("font-size: 10.5px; color: #64748b;")
        layout.addWidget(lbl_target)

        return w

    def _create_status_progress_widget(self, item: Dict[str, Any]) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        lbl_status = QLabel(f"● {item['status']}")
        lbl_status.setStyleSheet("color: #16a34a; font-weight: bold; font-size: 11px;")
        top_row.addWidget(lbl_status)
        top_row.addStretch()

        lbl_pct = QLabel(f"{item.get('progress', 0)}%")
        lbl_pct.setStyleSheet("font-size: 10.5px; font-weight: bold; color: #475569;")
        top_row.addWidget(lbl_pct)
        layout.addLayout(top_row)

        pbar = QProgressBar()
        pbar.setFixedHeight(12)
        pbar.setValue(item.get("progress", 0))
        pbar.setTextVisible(False)
        pbar.setStyleSheet("""
            QProgressBar {
                background-color: #f1f5f9;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background-color: #2563eb;
                border-radius: 4px;
            }
        """)
        layout.addWidget(pbar)

        return w

    def _create_actions_widget(self, row: int, item: Dict[str, Any]) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        btn_run = QPushButton("⚡ Yedekle")
        btn_run.setToolTip("Görevi şimdi çalıştır")
        btn_run.setStyleSheet("background-color: #16a34a; color: white; font-weight: bold; font-size: 10.5px; padding: 4px 8px; border-radius: 4px;")
        btn_run.setCursor(Qt.PointingHandCursor)
        btn_run.clicked.connect(lambda _, it=item: self._run_single_backup(it))
        layout.addWidget(btn_run)

        btn_edit = QPushButton("✏️")
        btn_edit.setToolTip("Yapılandırmayı düzenle")
        btn_edit.setStyleSheet("background-color: #f1f5f9; color: #334155; font-size: 11px; padding: 4px 6px; border: 1px solid #cbd5e1; border-radius: 4px;")
        btn_edit.setCursor(Qt.PointingHandCursor)
        btn_edit.clicked.connect(lambda _, it=item: self._edit_item(it))
        layout.addWidget(btn_edit)

        btn_open = QPushButton("📂")
        btn_open.setToolTip("Hedef klasörü Windows Gezgininde aç")
        btn_open.setStyleSheet("background-color: #f1f5f9; color: #334155; font-size: 11px; padding: 4px 6px; border: 1px solid #cbd5e1; border-radius: 4px;")
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.clicked.connect(lambda _, it=item: self._open_item_target(it))
        layout.addWidget(btn_open)

        btn_del = QPushButton("🗑️")
        btn_del.setToolTip("Görevi / Hesabı sil")
        btn_del.setStyleSheet("background-color: #fee2e2; color: #dc2626; font-size: 11px; padding: 4px 6px; border: 1px solid #fca5a5; border-radius: 4px;")
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.clicked.connect(lambda _, it=item: self._delete_item(it))
        layout.addWidget(btn_del)

        return w

    # ------------------------------------------------------------------
    # Category & Filter Handlers
    # ------------------------------------------------------------------

    def _create_cat_button(self, text: str, cat_key: str, active: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(self._cat_btn_style(active))
        btn.clicked.connect(lambda: self._on_category_selected(cat_key))
        return btn

    def _cat_btn_style(self, active: bool = False) -> str:
        bg = "#eff6ff" if active else "transparent"
        color = "#2563eb" if active else "#334155"
        border = "1px solid #bfdbfe" if active else "1px solid transparent"
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {color};
                font-weight: {'bold' if active else '600'};
                font-size: 11px;
                text-align: left;
                padding: 6px 10px;
                border: {border};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: #f1f5f9;
                color: #0f172a;
            }}
        """

    def _on_category_selected(self, cat_key: str):
        self._active_category = cat_key
        for b, key in zip(self.cat_buttons, ["all", "sql", "vhdx", "s3", "gdrive", "history"]):
            b.setStyleSheet(self._cat_btn_style(key == cat_key))
        self._render_grid_table()

    def _apply_search_filter(self, text: str):
        self._render_grid_table()

    # ------------------------------------------------------------------
    # Backward-Compatible Drive & Form Extraction Helpers
    # ------------------------------------------------------------------

    def _init_compat_combos(self):
        self.sql_drive_combo = QComboBox()
        self.vhdx_drive_combo = QComboBox()
        self._refresh_all_drive_combos()

    def _refresh_all_drive_combos(self):
        """Populate / refresh logical drives in drive comboboxes."""
        drives = []
        try:
            drives = self.engine.list_available_drives()
        except Exception:
            pass

        for combo in [self.sql_drive_combo, self.vhdx_drive_combo]:
            combo.clear()
            combo.addItem("Sabit Klasör (Varsayılan)", "")
            for d in drives:
                p = d.get("path", "")
                lbl = d.get("label", "Sürücü")
                free = d.get("free_gb", 0)
                combo.addItem(f"{p} [{lbl}] - {free:.1f} GB Boş", d)

    def _get_sql_form_data(self) -> Dict[str, Any]:
        """Return standardized SQL backup configuration data."""
        return {
            "name": "SQL_Backup",
            "engine_type": "mssql",
            "host": "localhost",
            "port": 1433,
            "auth_type": "windows",
            "username": "",
            "password": "",
            "database_name": "master",
            "backup_type": "FULL",
            "dest_dir": "data/backups/sql",
            "compress": True,
            "verify": True,
            "retention_mode": self._retention_mode,
            "retention_value": self._retention_val,
            "retention_days": self._retention_val if self._retention_mode == "days" else 30,
            "auto_on_usb_connect": False,
            "target_drive_label": ""
        }

    def _get_vhdx_form_data(self) -> Dict[str, Any]:
        """Return standardized VHDX backup configuration data."""
        return {
            "name": "VHDX_Backup",
            "mode": "file",
            "source_path": "",
            "compress_mode": "raw",
            "dest_dir": "data/backups/vhdx",
            "use_vss": True,
            "verify_hash": True,
            "retention_mode": self._retention_mode,
            "retention_value": self._retention_val,
            "retention_days": self._retention_val if self._retention_mode == "days" else 30,
            "auto_on_usb_connect": False,
            "target_drive_label": ""
        }

    # ------------------------------------------------------------------
    # Actions & Dialogs
    # ------------------------------------------------------------------

    def _open_cloud_account_dialog(self, provider: str, account_data: Optional[dict] = None):
        dlg = CloudAccountDialog(self.settings, provider=provider, account_data=account_data, parent=self)
        dlg.account_saved.connect(lambda: self.refresh())
        dlg.exec()

    def _open_new_sql_job_dialog(self, job_data: Optional[dict] = None):
        """Open modern modal dialog for creating or editing an SQL backup job."""
        dlg = SqlJobDialog(self.engine, job_data=job_data, parent=self)
        dlg.job_saved.connect(lambda data: (self._append_log(f"✅ SQL Görevi Kaydedildi: {data.get('name')}"), self.refresh()))
        dlg.exec()

    def _open_new_vhdx_job_dialog(self, job_data: Optional[dict] = None):
        """Open modern modal dialog for creating or editing a Hyper-V / VHDX backup job."""
        dlg = VhdxJobDialog(self.engine, job_data=job_data, parent=self)
        dlg.job_saved.connect(lambda data: (self._append_log(f"✅ VHDX Görevi Kaydedildi: {data.get('name')}"), self.refresh()))
        dlg.exec()

    def _run_single_backup(self, item: Dict[str, Any]):
        t = item["type"]
        self._append_log(f"🚀 Yedekleme başlatılıyor: {item['name']} ({item['engine']})")
        if t == "s3":
            raw = item["raw"]
            self._backup_to_s3_account(raw)
        elif t == "gdrive":
            raw = item["raw"]
            self._backup_to_gdrive_account(raw)
        elif t == "sql":
            self._run_sql_job(item["raw"])
        elif t == "vhdx":
            self._run_vhdx_job(item["raw"])

    def _backup_to_s3_account(self, acc: dict):
        bucket = acc.get("bucket", "")
        region = acc.get("region", "eu-central-1")
        ak = acc.get("access_key") or None
        sk = acc.get("secret_key") or None
        
        def task():
            try:
                self.signals.log_message.emit(f"☁️ S3 Yedekleme Başladı -> Bucket: {bucket}, Bölge: {region}")
                accounts = self.engine.list_accounts()
                if not accounts:
                    self.signals.log_message.emit("⚠️ Yedeklenecek e-posta hesabı bulunamadı.")
                    return
                for a in accounts:
                    acc_id = a.get("id")
                    self.signals.log_message.emit(f"⏳ Hesaba ait postalar S3'e yükleniyor: {a.get('email')}...")
                    report = self.engine.backup_to_s3(
                        account_id=acc_id,
                        bucket_name=bucket,
                        region=region,
                        access_key_id=ak,
                        secret_access_key=sk
                    )
                    self.signals.log_message.emit(f"✅ S3 Yedek Tamamlandı: {a.get('email')} -> {report.get('uploaded_files', 0)} dosya")
                self.signals.finished.emit("s3", {"status": "success"})
            except Exception as e:
                self.signals.error.emit("S3 Hatası", str(e))

        threading.Thread(target=task, daemon=True).start()

    def _backup_to_gdrive_account(self, acc: dict):
        cred = acc.get("credentials_path", "")
        def task():
            try:
                self.signals.log_message.emit(f"📁 Google Drive Yedekleme Başladı -> Kimlik: {cred}")
                accounts = self.engine.list_accounts()
                if not accounts:
                    self.signals.log_message.emit("⚠️ Yedeklenecek e-posta hesabı bulunamadı.")
                    return
                for a in accounts:
                    acc_id = a.get("id")
                    self.signals.log_message.emit(f"⏳ Drive'a yükleniyor: {a.get('email')}...")
                    report = self.engine.backup_to_gdrive(account_id=acc_id)
                    self.signals.log_message.emit(f"✅ Drive Yedek Tamamlandı: {a.get('email')}")
                self.signals.finished.emit("gdrive", {"status": "success"})
            except Exception as e:
                self.signals.error.emit("Google Drive Hatası", str(e))

        threading.Thread(target=task, daemon=True).start()

    def _run_sql_job(self, job_data: dict):
        def task():
            try:
                self.signals.log_message.emit(f"🗄️ SQL Yedek Başlatıldı: {job_data.get('name')}")
                if hasattr(self.engine, "sql_backup_usecase"):
                    rep = self.engine.sql_backup_usecase.run_job(job_data)
                    self.signals.log_message.emit(f"✅ SQL Yedek Tamamlandı: {rep.get('dest_file')}")
                self.signals.finished.emit("sql", {"status": "success"})
            except Exception as e:
                self.signals.error.emit("SQL Yedek Hatası", str(e))

        threading.Thread(target=task, daemon=True).start()

    def _run_vhdx_job(self, job_data: dict):
        def task():
            try:
                self.signals.log_message.emit(f"💾 VHDX Yedek Başlatıldı: {job_data.get('name')}")
                if hasattr(self.engine, "vhdx_backup_usecase"):
                    rep = self.engine.vhdx_backup_usecase.run_job(job_data)
                    self.signals.log_message.emit(f"✅ VHDX Yedek Tamamlandı: {rep.get('dest_file')}")
                self.signals.finished.emit("vhdx", {"status": "success"})
            except Exception as e:
                self.signals.error.emit("VHDX Yedek Hatası", str(e))

        threading.Thread(target=task, daemon=True).start()

    def _backup_selected(self):
        selected = []
        for row in range(self.grid_table.rowCount()):
            chk = self.grid_table.cellWidget(row, 0)
            if chk and isinstance(chk, QCheckBox) and chk.isChecked():
                if row < len(self._filtered_items):
                    selected.append(self._filtered_items[row])

        if not selected:
            QMessageBox.information(self, "Bilgi", "Lütfen yedeklemek için en az bir görev veya bulut hesabı seçin.")
            return

        self._append_log(f"⚡ {len(selected)} adet seçili görev sırayla çalıştırılıyor...")
        for it in selected:
            self._run_single_backup(it)

    def _backup_all(self):
        self._append_log("🚀 Tüm görevler sırayla çalıştırılıyor...")
        for it in self._all_items:
            self._run_single_backup(it)

    def _edit_item(self, item: Dict[str, Any]):
        t = item["type"]
        if t in ("s3", "gdrive"):
            self._open_cloud_account_dialog(t, account_data=item.get("raw"))
        elif t == "sql":
            self._open_new_sql_job_dialog(job_data=item.get("raw"))
        elif t == "vhdx":
            self._open_new_vhdx_job_dialog(job_data=item.get("raw"))
        else:
            QMessageBox.information(self, "Düzenle", f"{item['name']} görevi düzenleme penceresi.")

    def _delete_item(self, item: Dict[str, Any]):
        t = item["type"]
        ans = DeleteConfirmDialog.confirm_deletion(
            parent=self,
            title="Yedekleme Görevini Sil",
            item_name=item["name"],
            item_type=item.get("engine", item["type"]),
            target_info=item.get("target", ""),
            warning_message="Bu işlem seçili yedekleme görevini veya bulut hesabı bağlantısını sistemden kaldıracaktır. Bu işlem geri alınamaz.",
            banner_title="Yedekleme Görevini Sil",
            banner_subtitle="Lütfen silmek istediğiniz yedekleme yapılandırmasını onaylayın"
        )
        if not ans:
            return

        if t in ("s3", "gdrive"):
            self.settings.remove_cloud_account(item["id"])
            self._append_log(f"🗑️ Bulut Hesabı Silindi: {item['name']}")
        elif t == "sql" and hasattr(self.engine, "sql_backup_usecase"):
            self.engine.sql_backup_usecase.delete_job(item["id"])
            self._append_log(f"🗑️ SQL Görevi Silindi: {item['name']}")
        elif t == "vhdx" and hasattr(self.engine, "vhdx_backup_usecase"):
            self.engine.vhdx_backup_usecase.delete_job(item["id"])
            self._append_log(f"🗑️ VHDX Görevi Silindi: {item['name']}")

        self.refresh()

    def _open_item_target(self, item: Dict[str, Any]):
        target = item.get("target", "")
        if "data" in target or os.path.exists(target):
            path_str = target.replace("Hedef: ", "").split(" (")[0].strip()
            self._open_destination_folder(path_str)
        else:
            QMessageBox.information(self, "Hedef", f"Hedef Detayı: {target}")

    def _open_destination_folder(self, folder_path_str: str):
        try:
            path = Path(folder_path_str.strip() or "data")
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(path.resolve()))
            else:
                subprocess.Popen(["xdg-open", str(path.resolve())])
            self._append_log(f"📂 Hedef klasör Gezginde açıldı: {path.resolve()}")
        except Exception as e:
            self._append_log(f"⚠️ Klasör açılamadı ({folder_path_str}): {e}")

    # ------------------------------------------------------------------
    # Stepper & Row Height Adjustments
    # ------------------------------------------------------------------

    def _set_row_height(self, height: int):
        self._current_row_height = height
        self.settings.set("backup_grid_row_height", height)
        self.settings.save()
        self.grid_table.verticalHeader().setDefaultSectionSize(height)
        for r in range(self.grid_table.rowCount()):
            self.grid_table.setRowHeight(r, height)

    def _on_retention_changed(self, mode: str, val: int):
        self._retention_mode = mode
        self._retention_val = val
        self._append_log(f"🛡️ Saklama Politikası güncellendi: {val} {mode}")

    def _export_to_excel(self):
        try:
            import csv
            path, _ = QFileDialog.getSaveFileName(self, "Excel / CSV Olarak Kaydet", "Yedekleme_Gorevleri.csv", "CSV Dosyaları (*.csv)")
            if not path:
                return
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Tür", "Görev / Hesap Adı", "Motor / Sağlayıcı", "Hedef", "Saklama", "Durum"])
                for it in self._all_items:
                    writer.writerow([it["type"], it["name"], it["engine"], it["target"], it["retention"], it["status"]])
            self._append_log(f"📊 Liste dışa aktarıldı: {path}")
            QMessageBox.information(self, "Başarılı", f"Yedekleme listesi başarıyla kaydedildi:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Dışa aktarma başarısız: {e}")

    # ------------------------------------------------------------------
    # Live Console & Helpers
    # ------------------------------------------------------------------

    def _toggle_live_log(self):
        is_expanded = not self.log_output.isHidden()
        self.log_output.setVisible(not is_expanded)
        if not is_expanded:
            self.btn_toggle_log.setText("🙈 Günlüğü Gizle")
        else:
            self.btn_toggle_log.setText("👁️ Günlüğü Göster")

    def _clear_log(self):
        self.log_output.clear()
        self.log_status_lbl.setText("📋 Canlı İşlem Günlüğü (Live Console) — Temizlendi")

    @Slot(str)
    def _append_log(self, text: str):
        now = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"[{now}] {text}")
        self.log_status_lbl.setText(f"📋 Canlı Günlük — {text[:60]}")

    @Slot(str)
    def _on_sql_progress(self, msg: str):
        self._append_log(f"SQL: {msg}")

    @Slot(str, float, float)
    def _on_vhdx_progress(self, msg: str, pct: float, speed: float):
        self._append_log(f"VHDX: {msg} ({pct:.1f}% - {speed:.1f} MB/s)")

    @Slot(str, object)
    def _on_backup_finished(self, b_type: str, rep: dict):
        self._append_log(f"🎉 {b_type.upper()} Yedekleme başarıyla tamamlandı!")
        self._update_kpi_card(self.card_last_succ, datetime.now().strftime("%H:%M:%S"), "Son Başarılı")
        self.refresh()

    @Slot(str, str)
    def _on_backup_error(self, title: str, err: str):
        self._append_log(f"❌ HATA ({title}): {err}")
        QMessageBox.critical(self, title, err)

    # ------------------------------------------------------------------
    # UI Styling & Component Helpers
    # ------------------------------------------------------------------

    def _create_stat_badge(self, label: str, val: str, color: str) -> QLabel:
        lbl = QLabel(f"{label}: {val}")
        lbl.setStyleSheet(f"""
            background-color: #ffffff;
            color: {color};
            font-weight: bold;
            font-size: 11px;
            border: 1px solid #cbd5e1;
            border-radius: 5px;
            padding: 3px 8px;
        """)
        return lbl

    def _create_kpi_card(self, title: str, val: str, sub: str, color: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-top: 3px solid {color};
                border-radius: 6px;
                padding: 4px;
            }}
        """)
        lyt = QVBoxLayout(card)
        lyt.setContentsMargins(6, 4, 6, 4)
        lyt.setSpacing(2)

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet("font-size: 9.5px; font-weight: bold; color: #64748b;")
        lyt.addWidget(lbl_t)

        lbl_v = QLabel(val)
        lbl_v.setObjectName("kpi_val")
        lbl_v.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color};")
        lyt.addWidget(lbl_v)

        lbl_s = QLabel(sub)
        lbl_s.setObjectName("kpi_sub")
        lbl_s.setStyleSheet("font-size: 9.5px; color: #94a3b8;")
        lyt.addWidget(lbl_s)

        return card

    def _update_kpi_card(self, card: QFrame, val: str, sub: Optional[str] = None):
        v = card.findChild(QLabel, "kpi_val")
        if v:
            v.setText(val)
        if sub:
            s = card.findChild(QLabel, "kpi_sub")
            if s:
                s.setText(sub)

    def _top_btn_style(self, bg_color: str, border: Optional[str] = None, text_color: str = "#ffffff", bold: bool = False) -> str:
        b_str = f"border: 1px solid {border};" if border else "border: none;"
        return f"""
            QPushButton {{
                background-color: {bg_color};
                color: {text_color};
                font-weight: {'bold' if bold else '600'};
                font-size: 11px;
                {b_str}
                border-radius: 5px;
                padding: 4px 10px;
                min-height: 24px;
            }}
            QPushButton:hover {{
                opacity: 0.9;
                background-color: {bg_color};
            }}
        """
