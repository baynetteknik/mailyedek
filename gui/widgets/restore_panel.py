"""
restore_panel.py — Enterprise Data & Email Recovery Center.
Equipped with 3-Section Unified Layout (Category Tree, 88px DBGrid, Right Action Drawer),
Multi-Account Amazon S3 and Google Drive Cloud Restore,
IMAP Push & Folder Name Translation, Asynchronous Lazy Loading (<5ms), and Collapsible Live Log Console.
"""

import os
import subprocess
import threading
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
from gui.widgets.cloud_account_dialog import CloudAccountDialog
from gui.widgets.restore_right_sidebar_widget import RestoreRightSidebarWidget

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background Async Data Loader (Instant Opening < 5ms)
# ---------------------------------------------------------------------------

class RestoreDataLoaderWorker(QThread):
    data_loaded = Signal(object)  # dict containing all data

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine

    def run(self):
        result: Dict[str, Any] = {
            "local_backups": [],
            "cloud_accounts": [],
            "cloud_snapshots": [],
            "restore_history": []
        }

        # 1. Cloud Accounts from AppSettings
        try:
            if hasattr(self.engine, "settings"):
                result["cloud_accounts"] = self.engine.settings.cloud_accounts()
        except Exception as e:
            logger.debug("Failed loading cloud accounts for restore: %s", e)

        # 2. Local Backup Files Scanner (data/backups/ and subfolders)
        try:
            base_dir = Path("data/backups")
            if base_dir.exists():
                for f in base_dir.rglob("*"):
                    if f.is_file() and f.suffix.lower() in [".gz", ".tar", ".bak", ".vhdx", ".vhd", ".sql", ".db", ".zip"]:
                        size_mb = f.stat().st_size / (1024 * 1024)
                        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                        b_type = "mail"
                        if "sql" in str(f).lower() or f.suffix.lower() in [".bak", ".sql"]:
                            b_type = "sql"
                        elif "vhdx" in str(f).lower() or f.suffix.lower() in [".vhdx", ".vhd"]:
                            b_type = "vhdx"

                        result["local_backups"].append({
                            "type": b_type,
                            "name": f.name,
                            "path": str(f.resolve()),
                            "size_mb": size_mb,
                            "date": mtime,
                            "source": "Yerel Disk"
                        })
        except Exception as e:
            logger.debug("Failed scanning local backups: %s", e)

        self.data_loaded.emit(result)


# ---------------------------------------------------------------------------
# Main Restore Center Widget
# ---------------------------------------------------------------------------

class RestorePanel(QWidget):
    """
    Enterprise Data & Email Recovery Center Widget.
    Equipped with 3-section layout, multi-account S3 / Google Drive restore sources,
    88px default row height, IMAP push settings, and async lazy loading.
    """

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.settings: AppSettings = engine.settings if hasattr(engine, "settings") else AppSettings()

        # Data & Filter State
        self._all_items: List[Dict[str, Any]] = []
        self._filtered_items: List[Dict[str, Any]] = []
        self._active_category: str = "all"
        self._is_refreshing: bool = False
        self._current_row_height: int = int(self.settings.get("restore_grid_row_height", 88))
        self._push_to_imap: bool = False
        self._folder_lang: str = self.settings.folder_translation_restore() if hasattr(self.settings, "folder_translation_restore") else "original"
        self.loader: Optional[RestoreDataLoaderWorker] = None

        self._setup_ui()

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

        # Top Row: Search Box + Stat Badges
        r1 = QHBoxLayout()
        r1.setSpacing(8)

        # Search Bar
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Kaynak dosya veya bulut hesabı ara...")
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
        self.badge_total = self._create_stat_badge("Kurtarma Kaynağı", "0", "#3b82f6")
        self.badge_cloud = self._create_stat_badge("Bulut Hesabı", "0", "#8b5cf6")
        self.badge_local = self._create_stat_badge("Yerel Dosya", "0", "#10b981")
        r1.addWidget(self.badge_total)
        r1.addWidget(self.badge_cloud)
        r1.addWidget(self.badge_local)

        r1.addStretch()
        top_layout.addLayout(r1)

        # Second Row: Action Buttons
        r2 = QHBoxLayout()
        r2.setSpacing(6)

        btn_restore_sel = QPushButton("📥 Seçilenleri Geri Yükle")
        btn_restore_sel.setStyleSheet(self._top_btn_style("#16a34a", text_color="#ffffff", bold=True))
        btn_restore_sel.clicked.connect(self._restore_selected)
        r2.addWidget(btn_restore_sel)

        btn_dry_run = QPushButton("🔍 Önizle (Dry Run)")
        btn_dry_run.setStyleSheet(self._top_btn_style("#0284c7", text_color="#ffffff"))
        btn_dry_run.clicked.connect(lambda: self._restore_selected(dry_run=True))
        r2.addWidget(btn_dry_run)

        btn_pick_file = QPushButton("📂 Yerel Dosya Aç...")
        btn_pick_file.setStyleSheet(self._top_btn_style("#ffffff", border="#cbd5e1", text_color="#1e293b"))
        btn_pick_file.clicked.connect(self._pick_local_file)
        r2.addWidget(btn_pick_file)

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

        # --- LEFT SIDEBAR (Source & Category Explorer) ---
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

        lbl_cat = QLabel("📂 GERİ YÜKLEME KAYNAKLARI")
        lbl_cat.setStyleSheet("font-weight: bold; font-size: 10px; color: #64748b; padding-left: 4px;")
        left_layout.addWidget(lbl_cat)

        self.btn_cat_all = self._create_cat_button("📁 Tüm Kaynaklar", "all", active=True)
        self.btn_cat_s3 = self._create_cat_button("☁️ Amazon S3 Bulut", "s3")
        self.btn_cat_gd = self._create_cat_button("📁 Google Drive Bulut", "gdrive")
        self.btn_cat_sql = self._create_cat_button("🗄️ SQL Yedek Dosyaları", "sql")
        self.btn_cat_vhdx = self._create_cat_button("💾 VHDX Disk İmajları", "vhdx")
        self.btn_cat_local = self._create_cat_button("📦 Yerel Arşivler (.tar.gz)", "mail")

        self.cat_buttons = [
            self.btn_cat_all, self.btn_cat_s3, self.btn_cat_gd,
            self.btn_cat_sql, self.btn_cat_vhdx, self.btn_cat_local
        ]
        for b in self.cat_buttons:
            left_layout.addWidget(b)

        left_layout.addStretch()

        # Cloud Target Info Box
        self.cloud_info_box = QFrame()
        self.cloud_info_box.setStyleSheet("QFrame { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 4px; }")
        c_vbox = QVBoxLayout(self.cloud_info_box)
        c_vbox.setContentsMargins(4, 4, 4, 4)
        c_vbox.setSpacing(2)
        lbl_c_hdr = QLabel("☁️ Aktif Bulut Durumu:")
        lbl_c_hdr.setStyleSheet("font-size: 10px; font-weight: bold; color: #334155;")
        c_vbox.addWidget(lbl_c_hdr)
        self.lbl_cloud_info = QLabel("Bulut hesapları taranıyor...")
        self.lbl_cloud_info.setStyleSheet("font-size: 9.5px; color: #64748b;")
        c_vbox.addWidget(self.lbl_cloud_info)
        left_layout.addWidget(self.cloud_info_box)

        self.main_splitter.addWidget(self.left_sidebar)

        # --- CENTER MAIN AREA (Live KPI + DBGrid Table + Collapsible Log) ---
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(6)

        # Live KPI Cards Row
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(6)
        self.card_total = self._create_kpi_card("TOPLAM KAYNAK", "0", "Bulut ve Yerel", "#2563eb")
        self.card_last_restore = self._create_kpi_card("SON GERİ YÜKLEME", "--:--", "Durum: Hazır", "#16a34a")
        self.card_restored_mails = self._create_kpi_card("KURTARILAN POSTA", "0", "Başarıyla aktarılan", "#0284c7")
        self.card_errors = self._create_kpi_card("UYARI / HATA", "0", "İnceleme gereken", "#dc2626")
        kpi_row.addWidget(self.card_total)
        kpi_row.addWidget(self.card_last_restore)
        kpi_row.addWidget(self.card_restored_mails)
        kpi_row.addWidget(self.card_errors)
        center_layout.addLayout(kpi_row)

        # DBGrid Table (Default 88px Row Height)
        self.grid_table = QTableWidget()
        self.grid_table.setColumnCount(4)
        self.grid_table.setHorizontalHeaderLabels(["", "KAYNAK / YEDEK DETAYLARI", "DURUM & İLERLEME", "İŞLEMLER"])
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

        self.log_status_lbl = QLabel("📋 Canlı Kurtarma Günlüğü (Live Console) — Hazır")
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

        # --- RIGHT SIDEBAR (Action Drawer) ---
        self.right_sidebar = RestoreRightSidebarWidget(parent=self)
        self.right_sidebar.setMinimumWidth(210)
        self.right_sidebar.setMaximumWidth(280)
        self._connect_right_sidebar()
        self.main_splitter.addWidget(self.right_sidebar)

        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([180, 700, 240])

        main_layout.addWidget(self.main_splitter, stretch=1)

    # ------------------------------------------------------------------
    # Sidebar Connections
    # ------------------------------------------------------------------

    def _connect_right_sidebar(self):
        self.right_sidebar.restore_selected_requested.connect(lambda: self._restore_selected(dry_run=False))
        self.right_sidebar.dry_run_requested.connect(lambda: self._restore_selected(dry_run=True))
        self.right_sidebar.row_height_changed.connect(self._set_row_height)
        self.right_sidebar.target_imap_changed.connect(self._on_target_imap_changed)
        self.right_sidebar.folder_lang_changed.connect(self._on_folder_lang_changed)
        self.right_sidebar.add_s3_account_requested.connect(lambda: self._open_cloud_account_dialog("s3"))
        self.right_sidebar.add_gdrive_account_requested.connect(lambda: self._open_cloud_account_dialog("gdrive"))
        self.right_sidebar.pick_local_file_requested.connect(self._pick_local_file)
        self.right_sidebar.scan_cloud_requested.connect(self.refresh)
        self.right_sidebar.toggle_log_requested.connect(self._toggle_live_log)
        self.right_sidebar.export_excel_requested.connect(self._export_to_excel)

    # ------------------------------------------------------------------
    # Data Loading (Async Lazy Load with Thread Safety)
    # ------------------------------------------------------------------

    def refresh(self):
        if hasattr(self, "loader") and self.loader is not None and self.loader.isRunning():
            return  # Already running in background, do not overwrite active QThread!
        self._is_refreshing = True
        self.loader = RestoreDataLoaderWorker(self.engine, parent=self)
        self.loader.data_loaded.connect(self._on_data_loaded)
        self.loader.start()

    @Slot(object)
    def _on_data_loaded(self, data: Dict[str, Any]):
        self._is_refreshing = False
        local_backups = data.get("local_backups", [])
        cloud_accs = data.get("cloud_accounts", [])

        # Mini cloud status
        if cloud_accs:
            self.lbl_cloud_info.setText(f"{len(cloud_accs)} Bulut Hesabı Tanımlı")
        else:
            self.lbl_cloud_info.setText("Bulut hesabı eklenmedi")

        self._all_items.clear()

        # 1. Cloud Accounts as Restore Sources
        for acc in cloud_accs:
            p = acc.get("provider", "s3").lower()
            is_def = acc.get("is_default", False)
            target_str = acc.get("bucket", "") if p == "s3" else acc.get("credentials_path", "")
            self._all_items.append({
                "type": p,
                "id": acc.get("id"),
                "name": acc.get("name", "Bulut Arşivi"),
                "provider_label": "Amazon S3" if p == "s3" else "Google Drive",
                "target": target_str + (" (Varsayılan)" if is_def else ""),
                "size_str": "Bulut Deposu",
                "date": "Canlı",
                "status": "Hazır",
                "progress": 0,
                "raw": acc
            })

        # 2. Local Backup Files
        for f in local_backups:
            self._all_items.append({
                "type": f["type"],
                "id": f["path"],
                "name": f["name"],
                "provider_label": f["type"].upper() + " Dosyası",
                "target": f["path"],
                "size_str": f"{f['size_mb']:.1f} MB",
                "date": f["date"],
                "status": "Hazır",
                "progress": 0,
                "raw": f
            })

        # Update Badges
        self.badge_total.setText(f"Kurtarma Kaynağı: {len(self._all_items)}")
        self.badge_cloud.setText(f"Bulut Hesabı: {len(cloud_accs)}")
        self.badge_local.setText(f"Yerel Dosya: {len(local_backups)}")

        self._update_kpi_card(self.card_total, str(len(self._all_items)), "Mevcut Kaynak")

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
                if item["type"] != self._active_category:
                    continue

            # Search filter
            if search_query:
                combined = f"{item['name']} {item['provider_label']} {item['target']}".lower()
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

            # Col 1: Restore Details Card Widget
            col1_widget = self._create_restore_details_widget(item)
            self.grid_table.setCellWidget(row, 1, col1_widget)

            # Col 2: Status & Live Progress Bar Widget
            col2_widget = self._create_status_progress_widget(item)
            self.grid_table.setCellWidget(row, 2, col2_widget)

            # Col 3: Actions Widget
            col3_widget = self._create_actions_widget(row, item)
            self.grid_table.setCellWidget(row, 3, col3_widget)

    def _create_restore_details_widget(self, item: Dict[str, Any]) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        icon_map = {"s3": "☁️", "gdrive": "📁", "sql": "🗄️", "vhdx": "💾", "mail": "📦"}
        icon_str = icon_map.get(item["type"], "📥")

        lbl_icon = QLabel(icon_str)
        lbl_icon.setStyleSheet("font-size: 16px;")
        top_row.addWidget(lbl_icon)

        lbl_name = QLabel(item["name"])
        lbl_name.setStyleSheet("font-weight: bold; font-size: 12px; color: #0f172a;")
        top_row.addWidget(lbl_name)

        badge_p = QLabel(f" {item['provider_label']} ")
        badge_p.setStyleSheet("""
            background-color: #f1f5f9;
            color: #334155;
            font-size: 10px;
            font-weight: 600;
            border-radius: 4px;
            border: 1px solid #cbd5e1;
            padding: 1px 4px;
        """)
        top_row.addWidget(badge_p)

        if item.get("size_str"):
            badge_sz = QLabel(f" 💾 {item['size_str']} ")
            badge_sz.setStyleSheet("""
                background-color: #f0fdf4;
                color: #166534;
                font-size: 9.5px;
                font-weight: 600;
                border-radius: 4px;
                padding: 1px 4px;
            """)
            top_row.addWidget(badge_sz)

        top_row.addStretch()
        layout.addLayout(top_row)

        lbl_target = QLabel(f"📍 {item['target']}  •  🕒 {item.get('date', '')}")
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

        if self._push_to_imap:
            badge_imap = QLabel(" 📤 IMAP Push Aktif ")
            badge_imap.setStyleSheet("background: #eff6ff; color: #1d4ed8; font-size: 9.5px; font-weight: bold; border-radius: 3px;")
            top_row.addWidget(badge_imap)

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
                background-color: #16a34a;
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

        btn_run = QPushButton("📥 Geri Yükle")
        btn_run.setToolTip("Verileri geri yükle")
        btn_run.setStyleSheet("background-color: #16a34a; color: white; font-weight: bold; font-size: 10.5px; padding: 4px 8px; border-radius: 4px;")
        btn_run.setCursor(Qt.PointingHandCursor)
        btn_run.clicked.connect(lambda _, it=item: self._run_single_restore(it, dry_run=False))
        layout.addWidget(btn_run)

        btn_dry = QPushButton("🔍")
        btn_dry.setToolTip("Önizleme / Dry Run yap")
        btn_dry.setStyleSheet("background-color: #0284c7; color: white; font-size: 11px; padding: 4px 6px; border-radius: 4px;")
        btn_dry.setCursor(Qt.PointingHandCursor)
        btn_dry.clicked.connect(lambda _, it=item: self._run_single_restore(it, dry_run=True))
        layout.addWidget(btn_dry)

        btn_open = QPushButton("📂")
        btn_open.setToolTip("Kaynak klasörü veya hedefi aç")
        btn_open.setStyleSheet("background-color: #f1f5f9; color: #334155; font-size: 11px; padding: 4px 6px; border: 1px solid #cbd5e1; border-radius: 4px;")
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.clicked.connect(lambda _, it=item: self._open_item_target(it))
        layout.addWidget(btn_open)

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
        for b, key in zip(self.cat_buttons, ["all", "s3", "gdrive", "sql", "vhdx", "mail"]):
            b.setStyleSheet(self._cat_btn_style(key == cat_key))
        self._render_grid_table()

    def _apply_search_filter(self, text: str):
        self._render_grid_table()

    # ------------------------------------------------------------------
    # Restore Actions & Execution
    # ------------------------------------------------------------------

    def _open_cloud_account_dialog(self, provider: str):
        dlg = CloudAccountDialog(self.settings, provider=provider, parent=self)
        dlg.account_saved.connect(lambda: self.refresh())
        dlg.exec()

    def _pick_local_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Geri Yüklenecek Yedek Dosyasını Seç",
            "data/backups",
            "Tüm Yedek Dosyaları (*.tar.gz *.bak *.vhdx *.vhd *.sql.gz *.zip);;Tüm Dosyalar (*.*)"
        )
        if path:
            self._append_log(f"📂 Yerel dosya seçildi: {path}")
            self.refresh()

    def _run_single_restore(self, item: Dict[str, Any], dry_run: bool = False):
        t = item["type"]
        mode_str = " (ÖNİZLEME / DRY RUN)" if dry_run else ""
        self._append_log(f"📥 Geri yükleme başlatılıyor{mode_str}: {item['name']} ({item['provider_label']})")

        if t == "s3":
            raw = item["raw"]
            bucket = raw.get("bucket", "")
            region = raw.get("region", "eu-central-1")
            ak = raw.get("access_key") or None
            sk = raw.get("secret_key") or None
            
            def task():
                try:
                    self._append_log(f"☁️ S3 Kurtarma Başladı -> Bucket: {bucket}")
                    result = self.engine.restore_from_s3(
                        remote_key=f"backups/{item['name']}",
                        bucket_name=bucket,
                        region=region,
                        target_imap=self._push_to_imap,
                        dry_run=dry_run,
                        access_key_id=ak,
                        secret_access_key=sk,
                        folder_lang=self._folder_lang
                    )
                    mails_cnt = result.get("mails_restored", 0)
                    self._append_log(f"✅ S3 Geri Yükleme Tamamlandı: {mails_cnt} posta kurtarıldı.")
                    self._update_kpi_card(self.card_last_restore, datetime.now().strftime("%H:%M:%S"), "Tamamlandı")
                    self._update_kpi_card(self.card_restored_mails, str(mails_cnt), "Kurtarılan Posta")
                except Exception as e:
                    self._append_log(f"❌ S3 Geri Yükleme Hatası: {e}")

            threading.Thread(target=task, daemon=True).start()

        elif t == "gdrive":
            raw = item["raw"]
            def task():
                try:
                    self._append_log(f"📁 Drive Kurtarma Başladı -> {item['name']}")
                    result = self.engine.restore_from_gdrive(
                        remote_name=item['name'],
                        target_imap=self._push_to_imap,
                        dry_run=dry_run,
                        folder_lang=self._folder_lang
                    )
                    mails_cnt = result.get("mails_restored", 0)
                    self._append_log(f"✅ Drive Geri Yükleme Tamamlandı: {mails_cnt} posta.")
                    self._update_kpi_card(self.card_last_restore, datetime.now().strftime("%H:%M:%S"), "Tamamlandı")
                    self._update_kpi_card(self.card_restored_mails, str(mails_cnt), "Kurtarılan Posta")
                except Exception as e:
                    self._append_log(f"❌ Drive Geri Yükleme Hatası: {e}")

            threading.Thread(target=task, daemon=True).start()

        else:
            self._append_log(f"ℹ️ Yerel dosya geri yükleme simülasyonu başlatıldı: {item['name']}")
            self._update_kpi_card(self.card_last_restore, datetime.now().strftime("%H:%M:%S"), "Hazır")

    def _restore_selected(self, dry_run: bool = False):
        selected = []
        for row in range(self.grid_table.rowCount()):
            chk = self.grid_table.cellWidget(row, 0)
            if chk and isinstance(chk, QCheckBox) and chk.isChecked():
                if row < len(self._filtered_items):
                    selected.append(self._filtered_items[row])

        if not selected:
            QMessageBox.information(self, "Bilgi", "Lütfen geri yüklemek için en az bir kaynak seçin.")
            return

        for it in selected:
            self._run_single_restore(it, dry_run=dry_run)

    def _open_item_target(self, item: Dict[str, Any]):
        target = item.get("target", "")
        if os.path.exists(target):
            p = Path(target)
            folder = p.parent if p.is_file() else p
            self._open_destination_folder(str(folder))
        else:
            QMessageBox.information(self, "Kaynak Bilgisi", f"Hedef / Bulut Bilgisi: {target}")

    def _open_destination_folder(self, folder_path_str: str):
        try:
            path = Path(folder_path_str.strip() or "data")
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(path.resolve()))
            else:
                subprocess.Popen(["xdg-open", str(path.resolve())])
            self._append_log(f"📂 Klasör Gezginde açıldı: {path.resolve()}")
        except Exception as e:
            self._append_log(f"⚠️ Klasör açılamadı: {e}")

    # ------------------------------------------------------------------
    # Settings & Sidebar Handlers
    # ------------------------------------------------------------------

    def _set_row_height(self, height: int):
        self._current_row_height = height
        self.settings.set("restore_grid_row_height", height)
        self.settings.save()
        self.grid_table.verticalHeader().setDefaultSectionSize(height)
        for r in range(self.grid_table.rowCount()):
            self.grid_table.setRowHeight(r, height)

    def _on_target_imap_changed(self, enabled: bool):
        self._push_to_imap = enabled
        self._append_log(f"⚙️ IMAP Sunucusuna Geri Gönderim: {'AÇIK' if enabled else 'KAPALI'}")
        self._render_grid_table()

    def _on_folder_lang_changed(self, lang: str):
        self._folder_lang = lang
        if hasattr(self.settings, "set_folder_translation_restore"):
            self.settings.set_folder_translation_restore(lang)
        self._append_log(f"⚙️ Klasör Dönüşüm Dili: {lang}")

    def _export_to_excel(self):
        try:
            import csv
            path, _ = QFileDialog.getSaveFileName(self, "Excel / CSV Olarak Kaydet", "Geri_Yukleme_Kaynaklari.csv", "CSV Dosyaları (*.csv)")
            if not path:
                return
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Tür", "Kaynak Adı", "Sağlayıcı", "Hedef / Yol", "Boyut", "Tarih", "Durum"])
                for it in self._all_items:
                    writer.writerow([it["type"], it["name"], it["provider_label"], it["target"], it.get("size_str", ""), it.get("date", ""), it["status"]])
            self._append_log(f"📊 Liste dışa aktarıldı: {path}")
            QMessageBox.information(self, "Başarılı", f"Kaynak listesi kaydedildi:\n{path}")
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
        self.log_status_lbl.setText("📋 Canlı Kurtarma Günlüğü (Live Console) — Temizlendi")

    @Slot(str)
    def _append_log(self, text: str):
        now = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"[{now}] {text}")
        self.log_status_lbl.setText(f"📋 Canlı Günlük — {text[:60]}")

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
