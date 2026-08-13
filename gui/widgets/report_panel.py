"""
report_panel.py — Redesigned reports panel with Reports History, Custom Reports generator, and DB Stats.

Performance-optimized, standardized UI layout with left & right collapsible sidebars,
custom right-click context menus, interactive column sorting, and full-screen previews across all tabs.
"""

import json
import logging
import glob
import os
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Slot, QUrl, QDate, Signal, QThread
from PySide6.QtGui import QIcon, QFont, QColor, QDesktopServices, QAction, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QTextEdit, QMessageBox, QComboBox, QFileDialog, QTabWidget,
    QSplitter, QFrame, QLineEdit, QFormLayout, QCheckBox, QDateEdit,
    QListWidget, QListWidgetItem, QMenu, QTextBrowser,
)

from core.mail_engine import MailEngine
from core.reporter import ReportGenerator
from gui.dialogs.report_preview_dialog import ReportPreviewDialog

logger = logging.getLogger(__name__)


class CustomReportWorker(QThread):
    """Background worker for custom analytics report generation."""
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, engine: MailEngine, kwargs: dict, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.kwargs = kwargs

    def run(self):
        try:
            res = self.engine.generate_custom_report(**self.kwargs)
            self.finished.emit(res or {})
        except Exception as exc:
            logger.exception("Error generating custom report in worker: %s", exc)
            self.failed.emit(str(exc))


class ReportLoaderWorker(QThread):
    """Background worker for loading report JSON files and audit logs without UI freeze."""
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, engine: MailEngine, max_files: int = 300, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.max_files = max_files

    def run(self):
        try:
            reports_list = []
            accounts_map = {}
            try:
                accs = self.engine.accounts.get_all()
                accounts_map = {a["id"]: a for a in accs}
            except Exception:
                pass

            reports_dir = Path("data/reports")
            if reports_dir.exists():
                json_files = glob.glob(str(reports_dir / "*.json"))
                # Sort by file mtime descending so newest reports are loaded first
                json_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                json_files = json_files[:self.max_files]

                for path_str in json_files:
                    p = Path(path_str)
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            data = json.load(f)

                        data["file_path"] = str(p)
                        data["html_path"] = str(p.with_suffix(".html"))

                        if "timestamp" not in data:
                            data["timestamp"] = data.get("started_at", datetime.fromtimestamp(p.stat().st_mtime).isoformat())

                        reports_list.append(data)
                    except Exception as exc:
                        logger.warning("Failed to load report JSON %s: %s", path_str, exc)

            disk_ts_set = set(str(r.get("timestamp", ""))[:16] for r in reports_list)

            try:
                with self.engine.db.get_conn() as conn:
                    rows = conn.execute(
                        """SELECT * FROM audit_log 
                           WHERE action IN ('sync.completed', 'backup.s3', 'backup.gdrive', 'restore.s3', 'restore.gdrive') 
                           ORDER BY timestamp DESC LIMIT 500"""
                    ).fetchall()

                    for r in rows:
                        timestamp = str(r["timestamp"] or "")
                        if timestamp[:16] in disk_ts_set:
                            continue

                        action = r["action"]
                        details_str = r["details"] or "{}"
                        try:
                            details = json.loads(details_str)
                        except Exception:
                            details = {}

                        if action == "sync.completed":
                            r_type = "sync"
                        elif action in ("backup.s3", "backup.gdrive"):
                            r_type = "backup"
                        elif action in ("restore.s3", "restore.gdrive"):
                            r_type = "restore"
                        else:
                            r_type = "unknown"

                        a_info = accounts_map.get(r["account_id"], {}) if isinstance(accounts_map.get(r["account_id"]), dict) else {}
                        acc_label = a_info.get("label", f"Hesap #{r['account_id']}")
                        acc_email = a_info.get("email", "")
                        acc_grp = a_info.get("account_group", "")
                        display_label = f"{acc_label} ({acc_email})" if acc_email else acc_label

                        virtual_report = {
                            "type": r_type,
                            "timestamp": timestamp,
                            "account_label": display_label,
                            "account": display_label,
                            "account_id": r["account_id"],
                            "email": acc_email,
                            "account_group": acc_grp,
                            "is_virtual": True,
                            "raw_action": action,
                            "details": details,
                        }

                        if r_type == "sync":
                            virtual_report["mails_fetched"] = details.get("fetched", 0)
                            virtual_report["errors"] = details.get("errors", 0)
                            virtual_report["duplicates_found"] = details.get("duplicates", 0)
                            virtual_report["duration_seconds"] = details.get("duration", 0.0)
                        elif r_type == "backup":
                            virtual_report["target"] = details.get("bucket", "Cloud")
                            virtual_report["mails_backed_up"] = details.get("mails_backed_up", 0)
                            virtual_report["errors"] = 0 if details.get("success", True) else 1
                            virtual_report["total_bytes"] = details.get("size_bytes", 0)
                        elif r_type == "restore":
                            virtual_report["source"] = details.get("source", "Cloud Backup")
                            virtual_report["mails_restored"] = details.get("mails_restored", 0)
                            virtual_report["errors"] = details.get("errors", 0)

                        reports_list.append(virtual_report)
            except Exception as exc:
                logger.exception("Failed to query audit_log for report history: %s", exc)

            reports_list.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)
            self.finished.emit(reports_list)
        except Exception as exc:
            logger.exception("ReportLoaderWorker error: %s", exc)
            self.failed.emit(str(exc))


class StatsWorker(QThread):
    """Background worker for Database Statistics queries."""
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine

    def run(self):
        try:
            stats = self.engine.get_stats()
            self.finished.emit(stats or {})
        except Exception as exc:
            logger.exception("StatsWorker error: %s", exc)
            self.failed.emit(str(exc))


class DBSyncReportWorker(QThread):
    """Background worker for building DB archive sync reports without UI freeze."""
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, panel, scope_label: str, acc_list: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.panel = panel
        self.scope_label = scope_label
        self.acc_list = acc_list

    def run(self):
        try:
            reporter = self.panel.engine.reporter
            if len(self.acc_list) == 1:
                r_dict = self.panel._build_db_sync_report(self.acc_list[0]["id"])
                json_p = reporter.generate_sync_report(r_dict, output_format="both")
            else:
                reps = [self.panel._build_db_sync_report(a["id"]) for a in self.acc_list]
                json_p = reporter.generate_batch_sync_report(reps, group_name=self.scope_label, output_format="both")

            self.finished.emit(str(json_p))
        except Exception as exc:
            logger.exception("DBSyncReportWorker error: %s", exc)
            self.failed.emit(str(exc))


# Shared button style definitions
BTN_STYLE_BLUE = """
    QPushButton {
        background-color: #4361ee;
        color: white;
        font-weight: 600;
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 12px;
        border: none;
    }
    QPushButton:hover {
        background-color: #3a56d4;
    }
    QPushButton:disabled {
        background-color: #cbd5e1;
        color: #94a3b8;
    }
"""

BTN_STYLE_RED = """
    QPushButton {
        background-color: #ef4444;
        color: white;
        font-weight: 600;
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 12px;
        border: none;
    }
    QPushButton:hover {
        background-color: #dc2626;
    }
    QPushButton:disabled {
        background-color: #cbd5e1;
        color: #94a3b8;
    }
"""

BTN_STYLE_OUTLINE = """
    QPushButton {
        background-color: transparent;
        color: #4b5563;
        border: 1px solid #cbd5e1;
        font-weight: 600;
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: #f1f5f9;
        border-color: #94a3b8;
    }
"""

SIDEBAR_BTN_STYLE = """
    QPushButton {
        background-color: #f1f5f9;
        color: #475569;
        border: 1px solid #cbd5e1;
        border-radius: 4px;
        font-weight: bold;
        font-size: 10px;
        padding: 0px;
        min-height: 100px;
    }
    QPushButton:hover { background-color: #cbd5e1; }
"""


class ReportPanel(QWidget):
    """Reports panel listing history, custom reports generator, and database statistics."""
    _sync_done_signal = Signal(str)
    _sync_err_signal = Signal(str)

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._reporter = engine.reporter
        self._reports_list: List[Dict[str, Any]] = []
        self._filtered_reports: List[Dict[str, Any]] = []
        self._current_page: int = 1
        self._last_custom_report_res: Optional[dict] = None
        self._sync_done_signal.connect(self._on_sync_task_done_gui)
        self._sync_err_signal.connect(self._on_sync_task_err_gui)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Tabs (Standardized unified header style)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #cbd5e1;
                background: #ffffff;
                border-radius: 8px;
            }
            QTabBar::tab {
                background: #f1f5f9;
                border: 1px solid #cbd5e1;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 8px 18px;
                margin-right: 4px;
                font-weight: 600;
                color: #475569;
                font-size: 12px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                border-color: #cbd5e1;
                color: #4361ee;
                font-weight: bold;
            }
        """)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, stretch=1)

        # Tab 1: Reports History
        self.tab_history = QWidget()
        self._setup_history_tab()
        self.tabs.addTab(self.tab_history, "📊 İşlem Geçmişi & Raporlar")

        # Tab 2: Custom Analytics Generator
        self.tab_custom = QWidget()
        self._setup_custom_report_tab()
        self.tabs.addTab(self.tab_custom, "⚙️ Özel Rapor Oluştur")

        # Tab 3: Database Stats
        self.tab_stats = QWidget()
        self._setup_stats_tab()
        self.tabs.addTab(self.tab_stats, "📈 Veritabanı İstatistikleri")

        # Tab 4: Account Reports
        self.tab_account_reports = QWidget()
        self._setup_account_report_tab()
        self.tabs.addTab(self.tab_account_reports, "👤 Hesap Raporları")

    # ------------------------------------------------------------------
    # Tab 1: History & Main Reports View
    # ------------------------------------------------------------------

    def _setup_history_tab(self):
        main_layout = QHBoxLayout(self.tab_history)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Left Collapsible Sidebar
        self.sidebar_widget = QWidget()
        self.sidebar_widget.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(self.sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)

        lbl_groups = QLabel("🌐 GRUP / DOMAİN FİLTRESİ")
        lbl_groups.setStyleSheet("font-weight: bold; color: #4361ee; font-size: 11px;")
        sidebar_layout.addWidget(lbl_groups)

        self.group_filter_list = QListWidget()
        self.group_filter_list.setStyleSheet("""
            QListWidget {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-size: 11px;
                color: #1e293b;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #f1f5f9;
            }
            QListWidget::item:selected {
                background-color: #e0e7ff;
                color: #4361ee;
                font-weight: bold;
            }
        """)
        self.group_filter_list.itemSelectionChanged.connect(self._filter_reports)
        sidebar_layout.addWidget(self.group_filter_list)

        self.btn_gen_sidebar_sync = QPushButton("📊 Seçili Grup Sync Raporu")
        self.btn_gen_sidebar_sync.setStyleSheet(BTN_STYLE_BLUE)
        self.btn_gen_sidebar_sync.setToolTip("Sol listede seçilen grup veya domain için sync raporu üretir")
        self.btn_gen_sidebar_sync.clicked.connect(self._gen_sidebar_sync_report)
        sidebar_layout.addWidget(self.btn_gen_sidebar_sync)

        self.btn_toggle_sidebar = QPushButton("◀")
        self.btn_toggle_sidebar.setToolTip("Sol Menüyü Gizle/Göster")
        self.btn_toggle_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_sidebar.setFixedWidth(16)
        self.btn_toggle_sidebar.setStyleSheet(SIDEBAR_BTN_STYLE)
        self.btn_toggle_sidebar.clicked.connect(self._toggle_sidebar)

        main_layout.addWidget(self.sidebar_widget)
        main_layout.addWidget(self.btn_toggle_sidebar)

        # Center Content Area
        content_area = QWidget()
        layout = QVBoxLayout(content_area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        main_layout.addWidget(content_area, stretch=1)

        # Action Bar
        action_bar = QHBoxLayout()
        action_bar.setSpacing(8)

        self.btn_refresh_reports = QPushButton("🔄 Yenile")
        self.btn_refresh_reports.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_refresh_reports.clicked.connect(self._load_reports_history)
        action_bar.addWidget(self.btn_refresh_reports)

        self.top_input_search = QLineEdit()
        self.top_input_search.setPlaceholderText("🔍 Tüm alanlarda canlı ara (Hesap, Kaynak, İşlem Türü, Tarih vb.)...")
        self.top_input_search.setStyleSheet("""
            QLineEdit {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 12px;
                background-color: #ffffff;
                color: #0f172a;
                font-size: 12px;
                min-width: 250px;
            }
            QLineEdit:focus { border-color: #4361ee; }
        """)
        self.top_input_search.textChanged.connect(self._on_top_search_changed)
        action_bar.addWidget(self.top_input_search, stretch=1)

        self.btn_fullscreen_preview = QPushButton("🔍 Rapor Önizle (Tam Ekran)")
        self.btn_fullscreen_preview.setStyleSheet(BTN_STYLE_BLUE)
        self.btn_fullscreen_preview.setEnabled(False)
        self.btn_fullscreen_preview.clicked.connect(self._open_fullscreen_preview)
        action_bar.addWidget(self.btn_fullscreen_preview)

        self.btn_open_html = QPushButton("🌐 HTML Aç")
        self.btn_open_html.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_open_html.setEnabled(False)
        self.btn_open_html.clicked.connect(self._open_html_report)
        action_bar.addWidget(self.btn_open_html)

        self.btn_delete_report = QPushButton("🗑️ Sil")
        self.btn_delete_report.setStyleSheet(BTN_STYLE_RED)
        self.btn_delete_report.setEnabled(False)
        self.btn_delete_report.clicked.connect(self._delete_report)
        action_bar.addWidget(self.btn_delete_report)

        layout.addLayout(action_bar)

        # Table Grid
        self.table_reports = QTableWidget()
        self.table_reports.setColumnCount(6)
        self.table_reports.setHorizontalHeaderLabels([
            "Tarih & Saat", "İşlem Türü", "Hesap / Hedef", "Başarılı Mail", "Hatalar", "Durum"
        ])
        self.table_reports.setSortingEnabled(True)
        self.table_reports.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_reports.horizontalHeader().setStretchLastSection(True)
        self.table_reports.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_reports.setSelectionMode(QTableWidget.SingleSelection)
        self.table_reports.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_reports.setAlternatingRowColors(True)
        self.table_reports.verticalHeader().setVisible(False)
        self.table_reports.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_reports.customContextMenuRequested.connect(self._on_table_context_menu)
        self.table_reports.cellDoubleClicked.connect(lambda row, col: self._open_fullscreen_preview())
        self.table_reports.setStyleSheet("""
            QTableWidget {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background-color: #ffffff;
                color: #0f172a;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #f8fafc;
                color: #475569;
                font-weight: bold;
                padding: 8px;
                border: none;
                border-bottom: 2px solid #e2e8f0;
                font-size: 11px;
            }
            QTableWidget::item { padding: 8px 10px; }
            QTableWidget::item:selected { background-color: #e0e7ff; color: #4361ee; font-weight: bold; }
        """)
        self.table_reports.itemSelectionChanged.connect(self._on_report_selection_changed)
        layout.addWidget(self.table_reports, stretch=1)

        # Pagination Bar
        page_bar = QHBoxLayout()
        page_bar.setContentsMargins(0, 4, 0, 0)
        page_bar.setSpacing(8)

        self.btn_prev_page = QPushButton("◀ Önceki")
        self.btn_prev_page.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_prev_page.clicked.connect(self._on_prev_page)
        page_bar.addWidget(self.btn_prev_page)

        self.lbl_page_info = QLabel("Sayfa 1 / 1 (Toplam 0 Rapor)")
        self.lbl_page_info.setStyleSheet("font-weight: 600; color: #475569; font-size: 11px;")
        page_bar.addWidget(self.lbl_page_info)

        self.btn_next_page = QPushButton("Sonraki ▶")
        self.btn_next_page.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_next_page.clicked.connect(self._on_next_page)
        page_bar.addWidget(self.btn_next_page)

        page_bar.addStretch()

        lbl_psize = QLabel("Sayfa Başına:")
        lbl_psize.setStyleSheet("font-size: 11px; color: #64748b;")
        page_bar.addWidget(lbl_psize)

        self.combo_page_size = QComboBox()
        self.combo_page_size.addItems(["50 Rapor", "100 Rapor", "250 Rapor", "Tümü"])
        self.combo_page_size.currentIndexChanged.connect(self._on_page_size_changed)
        page_bar.addWidget(self.combo_page_size)

        layout.addLayout(page_bar)

        # Right Collapsible Sidebar (Filter Panel)
        self.btn_toggle_right_sidebar = QPushButton("▶")
        self.btn_toggle_right_sidebar.setToolTip("Sağ Filtre Panelini Gizle/Göster")
        self.btn_toggle_right_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_right_sidebar.setFixedWidth(16)
        self.btn_toggle_right_sidebar.setStyleSheet(SIDEBAR_BTN_STYLE)
        self.btn_toggle_right_sidebar.clicked.connect(self._toggle_right_sidebar)
        main_layout.addWidget(self.btn_toggle_right_sidebar)

        self.right_sidebar_widget = QWidget()
        self.right_sidebar_widget.setFixedWidth(220)
        right_layout = QVBoxLayout(self.right_sidebar_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        lbl_filters = QLabel("⚙️ RAPOR FİLTRELERİ")
        lbl_filters.setStyleSheet("font-weight: bold; color: #4361ee; font-size: 11px;")
        right_layout.addWidget(lbl_filters)

        filter_box = QGroupBox()
        filter_box.setStyleSheet("""
            QGroupBox {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        box_layout = QVBoxLayout(filter_box)
        box_layout.setSpacing(10)

        box_layout.addWidget(QLabel("Metin Ara:"))
        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("Hesap / Kaynak ara...")
        self.input_search.textChanged.connect(self._on_sidebar_search_changed)
        box_layout.addWidget(self.input_search)

        box_layout.addWidget(QLabel("İşlem Türü:"))
        self.combo_filter_type = QComboBox()
        self.combo_filter_type.addItems(["Tümü", "Sync", "Backup", "Restore", "Export", "Custom"])
        self.combo_filter_type.currentIndexChanged.connect(self._filter_reports)
        box_layout.addWidget(self.combo_filter_type)

        self.chk_errors_only = QCheckBox("⚠️ Sadece Hatalılar")
        self.chk_errors_only.toggled.connect(self._filter_reports)
        box_layout.addWidget(self.chk_errors_only)

        box_layout.addWidget(QLabel("Tarih Aralığı:"))
        self.chk_date_filter = QCheckBox("Tarih Filtresi Aktif")
        self.date_since = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_since.setCalendarPopup(True)
        self.date_since.setEnabled(False)
        self.date_before = QDateEdit(QDate.currentDate())
        self.date_before.setCalendarPopup(True)
        self.date_before.setEnabled(False)

        self.chk_date_filter.toggled.connect(self.date_since.setEnabled)
        self.chk_date_filter.toggled.connect(self.date_before.setEnabled)
        self.chk_date_filter.toggled.connect(self._filter_reports)
        self.date_since.dateChanged.connect(self._filter_reports)
        self.date_before.dateChanged.connect(self._filter_reports)

        box_layout.addWidget(self.chk_date_filter)
        box_layout.addWidget(QLabel("Başlangıç:"))
        box_layout.addWidget(self.date_since)
        box_layout.addWidget(QLabel("Bitiş:"))
        box_layout.addWidget(self.date_before)

        btn_clear_filters = QPushButton("🔄 Filtreleri Temizle")
        btn_clear_filters.setStyleSheet(BTN_STYLE_OUTLINE)
        btn_clear_filters.clicked.connect(self._clear_filters)
        box_layout.addWidget(btn_clear_filters)

        right_layout.addWidget(filter_box)
        right_layout.addStretch()

        main_layout.addWidget(self.right_sidebar_widget)

    # ------------------------------------------------------------------
    # Tab 2: Custom Analytics Report Generator (Standardized 3-Column Template)
    # ------------------------------------------------------------------

    def _setup_custom_report_tab(self):
        main_layout = QHBoxLayout(self.tab_custom)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # 1. Left Collapsible Sidebar
        self.custom_sidebar_widget = QWidget()
        self.custom_sidebar_widget.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(self.custom_sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)

        lbl_groups = QLabel("🌐 GRUP / DOMAİN FİLTRESİ")
        lbl_groups.setStyleSheet("font-weight: bold; color: #4361ee; font-size: 11px;")
        sidebar_layout.addWidget(lbl_groups)

        self.custom_group_filter_list = QListWidget()
        self.custom_group_filter_list.setStyleSheet(self.group_filter_list.styleSheet())
        self.custom_group_filter_list.itemSelectionChanged.connect(self._on_custom_sidebar_selection_changed)
        sidebar_layout.addWidget(self.custom_group_filter_list)

        self.btn_toggle_custom_sidebar = QPushButton("◀")
        self.btn_toggle_custom_sidebar.setToolTip("Sol Menüyü Gizle/Göster")
        self.btn_toggle_custom_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_custom_sidebar.setFixedWidth(16)
        self.btn_toggle_custom_custom_sidebar = self.btn_toggle_custom_sidebar
        self.btn_toggle_custom_sidebar.setStyleSheet(SIDEBAR_BTN_STYLE)
        self.btn_toggle_custom_sidebar.clicked.connect(self._toggle_custom_sidebar)

        main_layout.addWidget(self.custom_sidebar_widget)
        main_layout.addWidget(self.btn_toggle_custom_sidebar)

        # 2. Center Content Area (Full Height Body Report Preview)
        content_area = QWidget()
        layout = QVBoxLayout(content_area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        main_layout.addWidget(content_area, stretch=1)

        info_lbl = QLabel(
            "<b>📄 Özel Analiz Raporu Önizleme</b> — "
            "<span style='color:#64748b;'>Sağ menüdeki filtreleri seçip rapor oluşturabilirsiniz.</span>"
        )
        layout.addWidget(info_lbl)

        body_report_box = QGroupBox("Rapor Sonucu & Görsel Önizleme")
        body_report_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 4px;
                padding-top: 14px;
                background-color: #ffffff;
            }
        """)
        body_layout = QVBoxLayout(body_report_box)
        body_layout.setContentsMargins(8, 8, 8, 8)

        self.custom_browser_preview = QTextBrowser()
        self.custom_browser_preview.setStyleSheet("border: none; background-color: #ffffff;")
        self.custom_browser_preview.setPlaceholderText("Sağ taraftaki arama kriterlerini belirleyip 'Özel Analiz Raporu Oluştur' butonuna tıklayınız...")
        body_layout.addWidget(self.custom_browser_preview)

        layout.addWidget(body_report_box, stretch=1)

        # 3. Right Collapsible Sidebar (Filters & Actions Panel)
        self.btn_toggle_custom_right_sidebar = QPushButton("▶")
        self.btn_toggle_custom_right_sidebar.setToolTip("Sağ Filtre Panelini Gizle/Göster")
        self.btn_toggle_custom_right_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_custom_right_sidebar.setFixedWidth(16)
        self.btn_toggle_custom_right_sidebar.setStyleSheet(SIDEBAR_BTN_STYLE)
        self.btn_toggle_custom_right_sidebar.clicked.connect(self._toggle_custom_right_sidebar)
        main_layout.addWidget(self.btn_toggle_custom_right_sidebar)

        self.custom_right_sidebar_widget = QWidget()
        self.custom_right_sidebar_widget.setFixedWidth(240)
        right_layout = QVBoxLayout(self.custom_right_sidebar_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # Search Filters Form Box in Right Sidebar
        form_box = QGroupBox("⚙️ ARAMA KRİTERLERİ & FİLTRELER")
        form_box.setStyleSheet("""
            QGroupBox {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        form_layout = QFormLayout(form_box)
        form_layout.setSpacing(6)

        self.combo_custom_filter = QComboBox()
        self.combo_custom_filter.addItems([
            "Hesap Bazlı",
            "Domain Grubu Bazlı",
            "E-Posta Domaini Bazlı",
            "Tek E-Posta Adresi"
        ])
        self.combo_custom_filter.currentIndexChanged.connect(self._on_custom_filter_changed)
        form_layout.addRow("Kategori:", self.combo_custom_filter)

        self.combo_custom_account = QComboBox()
        form_layout.addRow("Hesap:", self.combo_custom_account)

        self.combo_custom_group = QComboBox()
        form_layout.addRow("Grup:", self.combo_custom_group)

        self.input_custom_domain = QLineEdit()
        self.input_custom_domain.setPlaceholderText("company.com")
        form_layout.addRow("Domain:", self.input_custom_domain)

        self.input_custom_email = QLineEdit()
        self.input_custom_email.setPlaceholderText("name@company.com")
        form_layout.addRow("E-Posta:", self.input_custom_email)

        self.chk_custom_since = QCheckBox("Şu tarihten yeni:")
        self.date_custom_since = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_custom_since.setCalendarPopup(True)
        self.date_custom_since.setEnabled(False)
        self.chk_custom_since.toggled.connect(self.date_custom_since.setEnabled)

        form_layout.addRow(self.chk_custom_since)
        form_layout.addRow(self.date_custom_since)

        self.chk_custom_before = QCheckBox("Şu tarihten eski:")
        self.date_custom_before = QDateEdit(QDate.currentDate())
        self.date_custom_before.setCalendarPopup(True)
        self.date_custom_before.setEnabled(False)
        self.chk_custom_before.toggled.connect(self.date_custom_before.setEnabled)

        form_layout.addRow(self.chk_custom_before)
        form_layout.addRow(self.date_custom_before)

        self.btn_generate_custom = QPushButton("📊 Özel Rapor Oluştur")
        self.btn_generate_custom.setStyleSheet(BTN_STYLE_BLUE)
        self.btn_generate_custom.setMinimumHeight(28)
        self.btn_generate_custom.clicked.connect(self._on_generate_custom)
        form_layout.addRow(self.btn_generate_custom)

        right_layout.addWidget(form_box)

        # Action Box in Right Sidebar
        action_box = QGroupBox("⚡ RAPOR İŞLEMLERİ & DIŞA AKTAR")
        action_box.setStyleSheet(form_box.styleSheet())
        ab_layout = QVBoxLayout(action_box)
        ab_layout.setSpacing(8)

        self.btn_custom_fullscreen = QPushButton("🔍 Tam Ekran Önizleme")
        self.btn_custom_fullscreen.setToolTip("PDF, Excel, Word, CSV, HTML kaydetme ve yazdırma ekranı açar")
        self.btn_custom_fullscreen.setStyleSheet(BTN_STYLE_BLUE)
        self.btn_custom_fullscreen.setEnabled(False)
        self.btn_custom_fullscreen.clicked.connect(self._open_custom_fullscreen_preview)
        ab_layout.addWidget(self.btn_custom_fullscreen)

        self.btn_custom_html = QPushButton("🌐 Tarayıcıda Aç (HTML)")
        self.btn_custom_html.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_custom_html.setEnabled(False)
        self.btn_custom_html.clicked.connect(self._open_custom_html_report)
        ab_layout.addWidget(self.btn_custom_html)

        right_layout.addWidget(action_box)
        right_layout.addStretch()

        main_layout.addWidget(self.custom_right_sidebar_widget)
        self._on_custom_filter_changed(0)

    # ------------------------------------------------------------------
    # Tab 3: Database Stats (Standardized 3-Column Template)
    # ------------------------------------------------------------------

    def _setup_stats_tab(self):
        main_layout = QHBoxLayout(self.tab_stats)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # 1. Left Collapsible Sidebar
        self.stats_sidebar_widget = QWidget()
        self.stats_sidebar_widget.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(self.stats_sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)

        lbl_groups = QLabel("🌐 GRUP / DOMAİN FİLTRESİ")
        lbl_groups.setStyleSheet("font-weight: bold; color: #4361ee; font-size: 11px;")
        sidebar_layout.addWidget(lbl_groups)

        self.stats_group_filter_list = QListWidget()
        self.stats_group_filter_list.setStyleSheet(self.group_filter_list.styleSheet())
        self.stats_group_filter_list.itemSelectionChanged.connect(self._on_stats_sidebar_selection_changed)
        sidebar_layout.addWidget(self.stats_group_filter_list)

        self.btn_toggle_stats_sidebar = QPushButton("◀")
        self.btn_toggle_stats_sidebar.setToolTip("Sol Menüyü Gizle/Göster")
        self.btn_toggle_stats_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_stats_sidebar.setFixedWidth(16)
        self.btn_toggle_stats_sidebar.setStyleSheet(SIDEBAR_BTN_STYLE)
        self.btn_toggle_stats_sidebar.clicked.connect(self._toggle_stats_sidebar)

        main_layout.addWidget(self.stats_sidebar_widget)
        main_layout.addWidget(self.btn_toggle_stats_sidebar)

        # 2. Center Content Area (Stats View stretch=1)
        content_area = QWidget()
        layout = QVBoxLayout(content_area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        main_layout.addWidget(content_area, stretch=1)

        stats_box = QGroupBox("📊 VERİTABANI İSTATİSTİKLERİ & ÖZET RAPOR")
        stats_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 4px;
                padding-top: 14px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                color: #4361ee;
            }
        """)
        stats_layout = QVBoxLayout(stats_box)
        stats_layout.setContentsMargins(10, 10, 10, 10)

        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(2)
        self.stats_table.setHorizontalHeaderLabels(["Sistem Metriği", "Değer"])
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.stats_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.stats_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background-color: #ffffff;
                color: #0f172a;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #f8fafc;
                color: #475569;
                font-weight: bold;
                padding: 8px;
                border: none;
                border-bottom: 2px solid #e2e8f0;
                font-size: 11px;
            }
            QTableWidget::item { padding: 8px 10px; }
        """)
        stats_layout.addWidget(self.stats_table)

        layout.addWidget(stats_box, stretch=1)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(80)
        self.log_output.setPlaceholderText("Rapor çıktısı...")
        self.log_output.setStyleSheet("""
            QTextEdit {
                background: #1a1a2e;
                color: #a8d8ea;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
        """)
        layout.addWidget(self.log_output)

        # 3. Right Collapsible Sidebar (Sync & Actions Panel)
        self.btn_toggle_stats_right_sidebar = QPushButton("▶")
        self.btn_toggle_stats_right_sidebar.setToolTip("Sağ Aksiyon Panelini Gizle/Göster")
        self.btn_toggle_stats_right_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_stats_right_sidebar.setFixedWidth(16)
        self.btn_toggle_stats_right_sidebar.setStyleSheet(SIDEBAR_BTN_STYLE)
        self.btn_toggle_stats_right_sidebar.clicked.connect(self._toggle_stats_right_sidebar)
        main_layout.addWidget(self.btn_toggle_stats_right_sidebar)

        self.stats_right_sidebar_widget = QWidget()
        self.stats_right_sidebar_widget.setFixedWidth(240)
        right_layout = QVBoxLayout(self.stats_right_sidebar_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        shortcut_box = QGroupBox("⚙️ SENKRONİZASYON & SYNC RAPORU")
        shortcut_box.setStyleSheet("""
            QGroupBox {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        shortcut_layout = QVBoxLayout(shortcut_box)
        shortcut_layout.setSpacing(8)

        shortcut_layout.addWidget(QLabel("Rapor Kapsamı:"))
        self.combo_sync_scope = QComboBox()
        self.combo_sync_scope.addItems([
            "👤 Tek Kullanıcı / Hesap",
            "📁 Domain / Hesap Grubu",
            "🌐 Tüm Hesaplar"
        ])
        self.combo_sync_scope.currentIndexChanged.connect(self._on_sync_scope_changed)
        shortcut_layout.addWidget(self.combo_sync_scope)

        self.lbl_sync_target = QLabel("Hesap Seçin:")
        shortcut_layout.addWidget(self.lbl_sync_target)

        self.combo_sync_account = QComboBox()
        shortcut_layout.addWidget(self.combo_sync_account)

        self.combo_sync_group = QComboBox()
        self.combo_sync_group.setVisible(False)
        shortcut_layout.addWidget(self.combo_sync_group)

        self.combo_account = self.combo_sync_account

        self.btn_sync_live = QPushButton("🔄 Canlı Senkronize Et")
        self.btn_sync_live.setStyleSheet(BTN_STYLE_BLUE)
        self.btn_sync_live.clicked.connect(lambda: self._gen_sync_report_action(live_sync=True))
        shortcut_layout.addWidget(self.btn_sync_live)

        self.btn_sync_db = QPushButton("📊 Arşivden Rapor Oluştur")
        self.btn_sync_db.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_sync_db.clicked.connect(lambda: self._gen_sync_report_action(live_sync=False))
        shortcut_layout.addWidget(self.btn_sync_db)

        self.btn_sync_report = self.btn_sync_live
        right_layout.addWidget(shortcut_box)

        action_box = QGroupBox("⚡ İSTATİSTİK İŞLEMLERİ & DIŞA AKTAR")
        action_box.setStyleSheet(shortcut_box.styleSheet())
        ab_layout = QVBoxLayout(action_box)
        ab_layout.setSpacing(8)

        self.btn_stats_report = QPushButton("📈 İstatistikleri Yenile")
        self.btn_stats_report.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_stats_report.clicked.connect(self._gen_stats_report)
        ab_layout.addWidget(self.btn_stats_report)

        self.btn_stats_fullscreen = QPushButton("🔍 Tam Ekran Önizleme")
        self.btn_stats_fullscreen.setToolTip("PDF, Excel, Word, CSV, HTML olarak kaydetme ve yazdırma ekranı açar")
        self.btn_stats_fullscreen.setStyleSheet(BTN_STYLE_BLUE)
        self.btn_stats_fullscreen.clicked.connect(self._open_stats_fullscreen_preview)
        ab_layout.addWidget(self.btn_stats_fullscreen)

        right_layout.addWidget(action_box)
        right_layout.addStretch()

        main_layout.addWidget(self.stats_right_sidebar_widget)

    # ------------------------------------------------------------------
    # Data Loading & Performance Optimization
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_tab_changed(self, index: int):
        if index == 2:
            self._gen_stats_report()
        elif index == 3:
            self._load_account_reports()

    def _load_reports_history(self):
        """Asynchronous history loading using ReportLoaderWorker without blocking the main UI thread."""
        self.btn_refresh_reports.setEnabled(False)
        self.log_output.append("Rapor geçmişi arka planda yükleniyor...")

        self._loader_worker = ReportLoaderWorker(self.engine, max_files=300, parent=self)
        self._loader_worker.finished.connect(self._on_reports_loaded_gui)
        self._loader_worker.failed.connect(self._on_reports_load_failed_gui)
        self._loader_worker.start()

    @Slot(list)
    def _on_reports_loaded_gui(self, reports: list):
        self.btn_refresh_reports.setEnabled(True)
        self._reports_list = reports
        self.log_output.append(f"Toplam {len(reports)} adet rapor geçmişi başarıyla yüklendi.")
        self._filter_reports()

    @Slot(str)
    def _on_reports_load_failed_gui(self, err_msg: str):
        self.btn_refresh_reports.setEnabled(True)
        self.log_output.append(f"HATA: Rapor geçmişi yüklenemedi: {err_msg}")
        QMessageBox.warning(self, "Hata", f"Rapor geçmişi yüklenirken hata oluştu:\n{err_msg}")

    @Slot(str)
    def _on_top_search_changed(self, text: str):
        if hasattr(self, "input_search") and self.input_search.text() != text:
            self.input_search.blockSignals(True)
            self.input_search.setText(text)
            self.input_search.blockSignals(False)
        self._filter_reports()

    @Slot(str)
    def _on_sidebar_search_changed(self, text: str):
        if hasattr(self, "top_input_search") and self.top_input_search.text() != text:
            self.top_input_search.blockSignals(True)
            self.top_input_search.setText(text)
            self.top_input_search.blockSignals(False)
        self._filter_reports()

    def _filter_reports(self):
        filter_type = self.combo_filter_type.currentText().lower()
        top_q = self.top_input_search.text().strip().lower() if hasattr(self, "top_input_search") else ""
        side_q = self.input_search.text().strip().lower() if hasattr(self, "input_search") else ""
        search_query = top_q or side_q

        errors_only = self.chk_errors_only.isChecked()
        date_filter_active = self.chk_date_filter.isChecked()

        since_str = self.date_since.date().toString("yyyy-MM-dd") if date_filter_active else ""
        before_str = self.date_before.date().toString("yyyy-MM-dd") if date_filter_active else ""

        selected_items = self.group_filter_list.selectedItems()
        group_filter_val = selected_items[0].data(Qt.UserRole) if selected_items else "ALL"

        accounts_map = {}
        try:
            accs = self.engine.accounts.get_all()
            accounts_map = {a["id"]: a for a in accs}
        except Exception:
            pass

        filtered: List[Dict[str, Any]] = []
        for r in self._reports_list:
            r_type = str(r.get("type", "")).lower()
            if filter_type != "tümü" and filter_type != r_type:
                continue

            if errors_only:
                err = r.get("errors", 0)
                if err <= 0:
                    continue

            if date_filter_active:
                ts = str(r.get("timestamp", ""))[:10]
                if ts:
                    if since_str and ts < since_str:
                        continue
                    if before_str and ts > before_str:
                        continue

            acc_id = r.get("account_id")
            a_info = accounts_map.get(acc_id, {}) if isinstance(accounts_map.get(acc_id), dict) else {}

            if search_query:
                searchable_text = " ".join([
                    str(r.get("account_label", "")),
                    str(r.get("account", "")),
                    str(r.get("email", "")),
                    str(r.get("account_group", "")),
                    str(r.get("target", "")),
                    str(r.get("source", "")),
                    str(r.get("type", "")),
                    str(r.get("timestamp", "")),
                    str(r.get("criteria", "")),
                    str(r.get("details", "")),
                    str(r.get("error_details", "")),
                    str(a_info.get("label", "")),
                    str(a_info.get("email", "")),
                    str(a_info.get("account_group", "")),
                ]).lower()

                if search_query not in searchable_text:
                    continue

            if group_filter_val and group_filter_val != "ALL":
                acc_email = (r.get("email") or a_info.get("email", "")).lower()
                acc_grp = (r.get("account_group") or a_info.get("account_group", "")).lower()
                acc_lbl = str(r.get("account_label") or r.get("account") or a_info.get("label", "")).lower()

                if group_filter_val.startswith("GROUP:"):
                    target_grp = group_filter_val.split("GROUP:")[1].lower()
                    grp_match = (acc_grp == target_grp) or (target_grp in acc_lbl) or (target_grp in acc_email)
                    if not grp_match:
                        continue
                elif group_filter_val.startswith("DOMAIN:"):
                    target_dom = group_filter_val.split("DOMAIN:")[1].lower()
                    dom_prefix = target_dom.split(".")[0]
                    dom_match = (target_dom in acc_lbl) or (target_dom in acc_email) or (acc_email.endswith(target_dom)) or (dom_prefix in acc_lbl) or (dom_prefix in acc_email) or (target_dom in acc_grp)
                    if not dom_match:
                        continue

            filtered.append(r)

        self._filtered_reports = filtered
        self._current_page = 1
        self._populate_table()

    def _populate_table(self):
        page_size_str = self.combo_page_size.currentText()
        if "50" in page_size_str:
            page_size = 50
        elif "100" in page_size_str:
            page_size = 100
        elif "250" in page_size_str:
            page_size = 250
        else:
            page_size = max(1, len(self._filtered_reports))

        total_items = len(self._filtered_reports)
        total_pages = max(1, (total_items + page_size - 1) // page_size)

        if self._current_page > total_pages:
            self._current_page = total_pages
        if self._current_page < 1:
            self._current_page = 1

        start_idx = (self._current_page - 1) * page_size
        end_idx = min(start_idx + page_size, total_items)
        page_items = self._filtered_reports[start_idx:end_idx]

        self.lbl_page_info.setText(f"Sayfa {self._current_page} / {total_pages} (Toplam {total_items} Rapor)")
        self.btn_prev_page.setEnabled(self._current_page > 1)
        self.btn_next_page.setEnabled(self._current_page < total_pages)

        self.table_reports.setUpdatesEnabled(False)
        self.table_reports.setSortingEnabled(False)
        self.table_reports.setRowCount(0)
        self.table_reports.setRowCount(len(page_items))

        for idx, r in enumerate(page_items):
            ts = str(r.get("timestamp", ""))
            formatted_date = ts[:16].replace("T", " ")
            item_date = QTableWidgetItem(formatted_date)
            item_date.setData(Qt.UserRole, r)
            self.table_reports.setItem(idx, 0, item_date)

            r_type = str(r.get("type", "")).upper()
            is_virtual = r.get("is_virtual", False)
            type_text = f"⚙️ {r_type}"
            if is_virtual:
                type_text += " (Geçmiş)"
            item_type = QTableWidgetItem(type_text)
            item_type.setData(Qt.UserRole, r)
            self.table_reports.setItem(idx, 1, item_type)

            label = r.get("account_label") or r.get("account") or r.get("target") or r.get("source") or "Unknown"
            item_label = QTableWidgetItem(str(label))
            item_label.setData(Qt.UserRole, r)
            self.table_reports.setItem(idx, 2, item_label)

            sc = 0
            if r_type == "SYNC":
                sc = r.get("mails_fetched", 0)
            elif r_type == "BACKUP":
                sc = r.get("mails_backed_up", 0)
            elif r_type == "RESTORE":
                sc = r.get("mails_restored", 0)
            elif r_type == "EXPORT":
                sc = r.get("exported_mails", r.get("exported", 0))
            elif r_type == "CUSTOM":
                sc = r.get("total_mails", 0)
            item_sc = QTableWidgetItem()
            item_sc.setData(Qt.DisplayRole, sc)
            item_sc.setData(Qt.UserRole, r)
            self.table_reports.setItem(idx, 3, item_sc)

            err = r.get("errors", 0)
            item_err = QTableWidgetItem()
            item_err.setData(Qt.DisplayRole, err)
            if err > 0:
                item_err.setForeground(QColor("#ef4444"))
                item_err.setFont(QFont("Segoe UI", 10, QFont.Bold))
            item_err.setData(Qt.UserRole, r)
            self.table_reports.setItem(idx, 4, item_err)

            status_item = QTableWidgetItem("Başarılı" if err == 0 else "Hatalı")
            status_item.setForeground(QColor("#10b981") if err == 0 else QColor("#ef4444"))
            status_item.setFont(QFont("Segoe UI", 10, QFont.Bold))
            status_item.setData(Qt.UserRole, r)
            self.table_reports.setItem(idx, 5, status_item)

        self.table_reports.setSortingEnabled(True)
        self.table_reports.setUpdatesEnabled(True)

        if total_items == 0:
            self.btn_open_html.setEnabled(False)
            self.btn_delete_report.setEnabled(False)
            self.btn_fullscreen_preview.setEnabled(False)

    @Slot()
    def _on_prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._populate_table()

    @Slot()
    def _on_next_page(self):
        self._current_page += 1
        self._populate_table()

    @Slot(int)
    def _on_page_size_changed(self, index: int):
        self._current_page = 1
        self._populate_table()

    # ------------------------------------------------------------------
    # Sidebar Selection Change Handlers
    # ------------------------------------------------------------------

    @Slot()
    def _on_custom_sidebar_selection_changed(self):
        items = self.custom_group_filter_list.selectedItems()
        if not items:
            return
        val = items[0].data(Qt.UserRole) or "ALL"
        if val.startswith("GROUP:"):
            grp = val.split("GROUP:")[1]
            self.combo_custom_filter.setCurrentIndex(1)
            idx = self.combo_custom_group.findText(grp)
            if idx >= 0:
                self.combo_custom_group.setCurrentIndex(idx)
        elif val.startswith("DOMAIN:"):
            dom = val.split("DOMAIN:")[1]
            self.combo_custom_filter.setCurrentIndex(2)
            self.input_custom_domain.setText(dom)

    @Slot()
    def _on_stats_sidebar_selection_changed(self):
        items = self.stats_group_filter_list.selectedItems()
        if not items:
            return
        val = items[0].data(Qt.UserRole) or "ALL"
        if val == "ALL":
            self.combo_sync_scope.setCurrentIndex(2)
        elif val.startswith("GROUP:"):
            grp = val.split("GROUP:")[1]
            self.combo_sync_scope.setCurrentIndex(1)
            idx = self.combo_sync_group.findText(grp)
            if idx >= 0:
                self.combo_sync_group.setCurrentIndex(idx)
        elif val.startswith("DOMAIN:"):
            dom = val.split("DOMAIN:")[1]
            self.combo_sync_scope.setCurrentIndex(1)
            idx = self.combo_sync_group.findText(f"@{dom}")
            if idx >= 0:
                self.combo_sync_group.setCurrentIndex(idx)
            else:
                self.combo_sync_group.addItem(f"@{dom}")
                self.combo_sync_group.setCurrentIndex(self.combo_sync_group.count() - 1)

    # ------------------------------------------------------------------
    # User Actions & Context Menu
    # ------------------------------------------------------------------

    def _on_table_context_menu(self, pos):
        item = self.table_reports.itemAt(pos)
        if not item:
            return
        row = item.row()
        r = self.table_reports.item(row, 0).data(Qt.UserRole)
        if not r:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 16px;
                border-radius: 4px;
                color: #1e293b;
                font-size: 12px;
            }
            QMenu::item:selected {
                background-color: #e0e7ff;
                color: #4361ee;
                font-weight: bold;
            }
        """)

        act_preview = QAction("🔍 Rapor Önizle (Tam Ekran)", self)
        act_preview.triggered.connect(self._open_fullscreen_preview)
        menu.addAction(act_preview)

        is_virtual = r.get("is_virtual", False)
        html_path = r.get("html_path", "")
        if not is_virtual and html_path and os.path.exists(html_path):
            act_open_html = QAction("🌐 Tarayıcıda Aç (HTML)", self)
            act_open_html.triggered.connect(self._open_html_report)
            menu.addAction(act_open_html)

        menu.addSeparator()

        act_sync_db = QAction("📊 Bu Hesap İçin Sync Raporu Oluştur (Arşiv)", self)
        act_sync_db.triggered.connect(self._gen_context_sync_report_db)
        menu.addAction(act_sync_db)

        act_sync_live = QAction("🔄 Canlı Senkronize Et & Rapor Oluştur", self)
        act_sync_live.triggered.connect(self._gen_context_sync_report_live)
        menu.addAction(act_sync_live)

        menu.addSeparator()

        act_copy = QAction("📋 Rapor Bilgilerini Kopyala", self)
        def copy_row():
            info_str = f"Tarih: {r.get('timestamp')}\nTür: {r.get('type')}\nHesap/Hedef: {r.get('account_label') or r.get('account')}\nDetay: {json.dumps(r, indent=2, ensure_ascii=False)}"
            QGuiApplication.clipboard().setText(info_str)
            self.log_output.append("Rapor bilgisi panoya kopyalandı.")
        act_copy.triggered.connect(copy_row)
        menu.addAction(act_copy)

        if not is_virtual:
            menu.addSeparator()
            act_delete = QAction("🗑️ Raporu Diskten Sil", self)
            act_delete.triggered.connect(self._delete_report)
            menu.addAction(act_delete)

        menu.exec(self.table_reports.viewport().mapToGlobal(pos))

    def _gen_context_sync_report_db(self):
        row = self.table_reports.currentRow()
        if row < 0:
            return
        r = self.table_reports.item(row, 0).data(Qt.UserRole)
        if not r:
            return

        acc_id = r.get("account_id")
        label = str(r.get("account_label") or r.get("account") or "Hesap")

        if acc_id:
            self._db_sync_worker = DBSyncReportWorker(self, label, [{"id": acc_id}], parent=self)
            self._db_sync_worker.finished.connect(self._on_db_sync_report_done_gui)
            self._db_sync_worker.failed.connect(self._on_db_sync_report_failed_gui)
            self._db_sync_worker.start()
        else:
            all_accounts = self.engine.list_accounts()
            matched = []
            lbl_lower = label.lower()
            if "grup" in lbl_lower or "group" in lbl_lower:
                grp = label.split(":")[-1].strip()
                matched = [a for a in all_accounts if str(a.get("account_group", "")).lower() == grp.lower()]
            elif "domain" in lbl_lower or "@" in label:
                dom = label.split(":")[-1].strip().replace("@", "").lower()
                dom_prefix = dom.split(".")[0]
                matched = [a for a in all_accounts if dom in a.get("email", "").lower() or dom_prefix in a.get("label", "").lower() or dom_prefix in a.get("email", "").lower()]
            else:
                matched = all_accounts

            if matched:
                self.log_output.append(f"[{label}] Arşiv verilerinden sync raporu oluşturuluyor...")
                self._db_sync_worker = DBSyncReportWorker(self, label, matched, parent=self)
                self._db_sync_worker.finished.connect(self._on_db_sync_report_done_gui)
                self._db_sync_worker.failed.connect(self._on_db_sync_report_failed_gui)
                self._db_sync_worker.start()
            else:
                QMessageBox.information(self, "Bilgi", f"'{label}' için sistemde kayıtlı aktif hesap bulunamadı.")

    def _gen_context_sync_report_live(self):
        row = self.table_reports.currentRow()
        if row < 0:
            return
        r = self.table_reports.item(row, 0).data(Qt.UserRole)
        if not r:
            return

        acc_id = r.get("account_id")
        label = str(r.get("account_label") or r.get("account") or "Hesap")

        acc_list = []
        if acc_id:
            acc_list = [{"id": acc_id}]
        else:
            all_accounts = self.engine.list_accounts()
            lbl_lower = label.lower()
            if "grup" in lbl_lower or "group" in lbl_lower:
                grp = label.split(":")[-1].strip()
                acc_list = [a for a in all_accounts if str(a.get("account_group", "")).lower() == grp.lower()]
            elif "domain" in lbl_lower or "@" in label:
                dom = label.split(":")[-1].strip().replace("@", "").lower()
                dom_prefix = dom.split(".")[0]
                acc_list = [a for a in all_accounts if dom in a.get("email", "").lower() or dom_prefix in a.get("label", "").lower() or dom_prefix in a.get("email", "").lower()]
            else:
                acc_list = all_accounts

        if acc_list:
            self.log_output.append(f"[{label}] Canlı senkronizasyon başlatılıyor...")
            def run_task():
                try:
                    reps = []
                    for a in acc_list:
                        rep_dict = self.engine.sync_account(a["id"])
                        reps.append(rep_dict)
                    if len(reps) == 1:
                        json_p = self._reporter.generate_sync_report(reps[0], output_format="both")
                    else:
                        json_p = self._reporter.generate_batch_sync_report(reps, group_name=label, output_format="both")
                    self._sync_done_signal.emit(str(json_p))
                except Exception as exc:
                    self._sync_err_signal.emit(str(exc))
            import threading
            threading.Thread(target=run_task, daemon=True).start()
        else:
            QMessageBox.information(self, "Bilgi", f"'{label}' için canlı senkronizasyon başlatılacak hesap bulunamadı.")

    def _on_report_selection_changed(self):
        row = self.table_reports.currentRow()
        if row < 0:
            self.btn_open_html.setEnabled(False)
            self.btn_delete_report.setEnabled(False)
            self.btn_fullscreen_preview.setEnabled(False)
            return

        r = self.table_reports.item(row, 0).data(Qt.UserRole)
        if not r:
            return

        is_virtual = r.get("is_virtual", False)
        html_path = r.get("html_path", "")
        
        self.btn_fullscreen_preview.setEnabled(True)
        self.btn_open_html.setEnabled(not is_virtual and bool(html_path) and os.path.exists(html_path))
        self.btn_delete_report.setEnabled(not is_virtual)

    @Slot()
    def _open_fullscreen_preview(self):
        row = self.table_reports.currentRow()
        if row < 0:
            return
        r = self.table_reports.item(row, 0).data(Qt.UserRole)
        if not r:
            return

        is_virtual = r.get("is_virtual", False)
        html_path = r.get("html_path", "")
        html_content = ""

        if not is_virtual and html_path and os.path.exists(html_path):
            try:
                with open(html_path, "r", encoding="utf-8") as f:
                    html_content = f.read()
            except Exception as exc:
                html_content = f"<p style='color:red;'>Rapor okunamadı: {exc}</p>"
        else:
            html_content = self._render_virtual_report_html(r)

        title = str(r.get("account_label") or r.get("account") or r.get("target") or r.get("type", "İşlem Raporu")).upper()
        dialog = ReportPreviewDialog(f"{title} Raporu", html_content, report_data=r, parent=self)
        dialog.exec()

    @Slot()
    def _open_html_report(self):
        row = self.table_reports.currentRow()
        if row < 0:
            return
        r = self.table_reports.item(row, 0).data(Qt.UserRole)
        if r and r.get("html_path"):
            path = r["html_path"]
            if os.path.exists(path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))

    @Slot()
    def _delete_report(self):
        row = self.table_reports.currentRow()
        if row < 0:
            return
        r = self.table_reports.item(row, 0).data(Qt.UserRole)
        if not r or r.get("is_virtual"):
            return

        confirm = QMessageBox.question(
            self, "Rapor Sil", 
            "Seçili raporu diskten silmek istediğinize emin misiniz?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            try:
                if r.get("file_path") and os.path.exists(r["file_path"]):
                    os.unlink(r["file_path"])
                if r.get("html_path") and os.path.exists(r["html_path"]):
                    os.unlink(r["html_path"])
                self.log_output.append("Rapor başarıyla diskten silindi.")
                self._load_reports_history()
            except Exception as exc:
                QMessageBox.critical(self, "Hata", f"Rapor dosyası silinemedi: {exc}")

    @Slot()
    def _clear_filters(self):
        if hasattr(self, "top_input_search"):
            self.top_input_search.clear()
        self.input_search.clear()
        self.combo_filter_type.setCurrentIndex(0)
        self.chk_errors_only.setChecked(False)
        self.chk_date_filter.setChecked(False)
        if self.group_filter_list.count() > 0:
            self.group_filter_list.setCurrentRow(0)
        self._filter_reports()

    # Toggle sidebar slots across all tabs
    @Slot()
    def _toggle_sidebar(self):
        visible = self.sidebar_widget.isVisible()
        self.sidebar_widget.setVisible(not visible)
        self.btn_toggle_sidebar.setText("▶" if visible else "◀")

    @Slot()
    def _toggle_right_sidebar(self):
        visible = self.right_sidebar_widget.isVisible()
        self.right_sidebar_widget.setVisible(not visible)
        self.btn_toggle_right_sidebar.setText("◀" if visible else "▶")

    @Slot()
    def _toggle_custom_sidebar(self):
        visible = self.custom_sidebar_widget.isVisible()
        self.custom_sidebar_widget.setVisible(not visible)
        self.btn_toggle_custom_sidebar.setText("▶" if visible else "◀")

    @Slot()
    def _toggle_custom_right_sidebar(self):
        visible = self.custom_right_sidebar_widget.isVisible()
        self.custom_right_sidebar_widget.setVisible(not visible)
        self.btn_toggle_custom_right_sidebar.setText("◀" if visible else "▶")

    @Slot()
    def _toggle_stats_sidebar(self):
        visible = self.stats_sidebar_widget.isVisible()
        self.stats_sidebar_widget.setVisible(not visible)
        self.btn_toggle_stats_sidebar.setText("▶" if visible else "◀")

    @Slot()
    def _toggle_stats_right_sidebar(self):
        visible = self.stats_right_sidebar_widget.isVisible()
        self.stats_right_sidebar_widget.setVisible(not visible)
        self.btn_toggle_stats_right_sidebar.setText("◀" if visible else "▶")

    @Slot()
    def _toggle_acc_rep_sidebar(self):
        visible = self.acc_rep_sidebar_widget.isVisible()
        self.acc_rep_sidebar_widget.setVisible(not visible)
        self.btn_toggle_acc_rep_sidebar.setText("▶" if visible else "◀")

    @Slot()
    def _toggle_acc_rep_right_sidebar(self):
        visible = self.acc_rep_right_sidebar_widget.isVisible()
        self.acc_rep_right_sidebar_widget.setVisible(not visible)
        self.btn_toggle_acc_rep_right_sidebar.setText("◀" if visible else "▶")

    # ------------------------------------------------------------------
    # Tab 4: Account Reports Implementation
    # ------------------------------------------------------------------

    def _setup_account_report_tab(self):
        main_layout = QHBoxLayout(self.tab_account_reports)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # 1. Left Collapsible Sidebar
        self.acc_rep_sidebar_widget = QWidget()
        self.acc_rep_sidebar_widget.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(self.acc_rep_sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)

        lbl_groups = QLabel("🌐 GRUP / DOMAİN FİLTRESİ")
        lbl_groups.setStyleSheet("font-weight: bold; color: #4361ee; font-size: 11px;")
        sidebar_layout.addWidget(lbl_groups)

        self.acc_rep_group_filter_list = QListWidget()
        self.acc_rep_group_filter_list.setStyleSheet(self.group_filter_list.styleSheet())
        self.acc_rep_group_filter_list.itemSelectionChanged.connect(self._on_acc_rep_sidebar_selection_changed)
        sidebar_layout.addWidget(self.acc_rep_group_filter_list)

        self.btn_toggle_acc_rep_sidebar = QPushButton("◀")
        self.btn_toggle_acc_rep_sidebar.setToolTip("Sol Menüyü Gizle/Göster")
        self.btn_toggle_acc_rep_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_acc_rep_sidebar.setFixedWidth(16)
        self.btn_toggle_acc_rep_sidebar.setStyleSheet(SIDEBAR_BTN_STYLE)
        self.btn_toggle_acc_rep_sidebar.clicked.connect(self._toggle_acc_rep_sidebar)

        main_layout.addWidget(self.acc_rep_sidebar_widget)
        main_layout.addWidget(self.btn_toggle_acc_rep_sidebar)

        # 2. Center Content Area
        content_area = QWidget()
        layout = QVBoxLayout(content_area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        main_layout.addWidget(content_area, stretch=1)

        acc_box = QGroupBox("👤 HESAP METRİKLERİ VE SAĞLIK DURUMU RAPORU")
        acc_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 4px;
                padding-top: 14px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                color: #4361ee;
            }
        """)
        acc_layout = QVBoxLayout(acc_box)
        acc_layout.setContentsMargins(10, 10, 10, 10)

        self.acc_rep_table = QTableWidget()
        self.acc_rep_table.setColumnCount(8)
        self.acc_rep_table.setHorizontalHeaderLabels([
            "Hesap Adı / Etiket", "E-Posta Adresi", "Domain Grubu", "Arşiv Mail", "Boyut", "Son Sync Tarihi", "Hata", "Durum / Sağlık"
        ])
        self.acc_rep_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.acc_rep_table.horizontalHeader().setStretchLastSection(True)
        self.acc_rep_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.acc_rep_table.setSortingEnabled(True)
        self.acc_rep_table.verticalHeader().setVisible(False)
        self.acc_rep_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background-color: #ffffff;
                color: #0f172a;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #f8fafc;
                color: #475569;
                font-weight: bold;
                padding: 8px;
                border: none;
                border-bottom: 2px solid #e2e8f0;
                font-size: 11px;
            }
            QTableWidget::item { padding: 8px 10px; }
            QTableWidget::item:selected { background-color: #e0e7ff; color: #4361ee; font-weight: bold; }
        """)
        acc_layout.addWidget(self.acc_rep_table)
        layout.addWidget(acc_box, stretch=1)

        # 3. Right Collapsible Sidebar
        self.btn_toggle_acc_rep_right_sidebar = QPushButton("▶")
        self.btn_toggle_acc_rep_right_sidebar.setToolTip("Sağ Aksiyon Panelini Gizle/Göster")
        self.btn_toggle_acc_rep_right_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_acc_rep_right_sidebar.setFixedWidth(16)
        self.btn_toggle_acc_rep_right_sidebar.setStyleSheet(SIDEBAR_BTN_STYLE)
        self.btn_toggle_acc_rep_right_sidebar.clicked.connect(self._toggle_acc_rep_right_sidebar)
        main_layout.addWidget(self.btn_toggle_acc_rep_right_sidebar)

        self.acc_rep_right_sidebar_widget = QWidget()
        self.acc_rep_right_sidebar_widget.setFixedWidth(240)
        right_layout = QVBoxLayout(self.acc_rep_right_sidebar_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        filter_box = QGroupBox("⚙️ FİLTRELER & İŞLEMLER")
        filter_box.setStyleSheet("""
            QGroupBox {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        fb_layout = QVBoxLayout(filter_box)
        fb_layout.setSpacing(8)

        fb_layout.addWidget(QLabel("Sağlık / Durum Filtresi:"))
        self.combo_acc_rep_status = QComboBox()
        self.combo_acc_rep_status.addItems(["Tümü", "🟢 Sağlıklı", "🟡 Uyarılı / Senkron Edilmedi", "🔴 Hatalı"])
        self.combo_acc_rep_status.currentIndexChanged.connect(self._load_account_reports)
        fb_layout.addWidget(self.combo_acc_rep_status)

        self.btn_refresh_acc_rep = QPushButton("📈 Raporu Yenile")
        self.btn_refresh_acc_rep.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_refresh_acc_rep.clicked.connect(self._load_account_reports)
        fb_layout.addWidget(self.btn_refresh_acc_rep)

        self.btn_acc_rep_fullscreen = QPushButton("🔍 Tam Ekran Önizleme")
        self.btn_acc_rep_fullscreen.setToolTip("PDF, Excel, Word, CSV, HTML kaydetme ve yazdırma ekranı açar")
        self.btn_acc_rep_fullscreen.setStyleSheet(BTN_STYLE_BLUE)
        self.btn_acc_rep_fullscreen.clicked.connect(self._open_acc_rep_fullscreen_preview)
        fb_layout.addWidget(self.btn_acc_rep_fullscreen)

        right_layout.addWidget(filter_box)
        right_layout.addStretch()
        main_layout.addWidget(self.acc_rep_right_sidebar_widget)

    @Slot()
    def _on_acc_rep_sidebar_selection_changed(self):
        self._load_account_reports()

    @Slot()
    def _load_account_reports(self):
        all_accounts = self.engine.list_accounts()
        selected_items = self.acc_rep_group_filter_list.selectedItems()
        val = selected_items[0].data(Qt.UserRole) if selected_items else "ALL"

        matched = []
        if val == "ALL":
            matched = all_accounts
        elif val.startswith("GROUP:"):
            grp = val.split("GROUP:")[1].lower()
            matched = [
                a for a in all_accounts 
                if grp == str(a.get("account_group", "")).lower() 
                or grp in a.get("email", "").lower()
            ]
        elif val.startswith("DOMAIN:"):
            dom = val.split("DOMAIN:")[1].lower()
            dom_prefix = dom.split(".")[0]
            matched = [
                a for a in all_accounts 
                if a.get("email", "").lower().endswith("@" + dom) 
                or dom in a.get("email", "").lower() 
                or dom_prefix in a.get("email", "").lower()
                or dom in str(a.get("account_group", "")).lower()
                or dom_prefix in str(a.get("account_group", "")).lower()
            ]

        status_filter = self.combo_acc_rep_status.currentText()

        self.acc_rep_table.setRowCount(0)
        self.acc_rep_table.setSortingEnabled(False)
        self.acc_rep_table.setRowCount(len(matched))

        report_rows = []

        try:
            with self.engine.db.get_conn() as conn:
                for idx, acc in enumerate(matched):
                    acc_id = acc["id"]
                    r_stats = conn.execute(
                        "SELECT COUNT(*) as cnt, COALESCE(SUM(size_bytes), 0) as total_size, MAX(date) as max_date FROM mail_metadata WHERE account_id=? AND is_deleted=0",
                        (acc_id,)
                    ).fetchone()
                    
                    r_err = conn.execute(
                        "SELECT COUNT(*) as err_cnt FROM audit_log WHERE account_id=? AND action LIKE '%error%'",
                        (acc_id,)
                    ).fetchone()

                    mail_cnt = r_stats["cnt"] if r_stats else 0
                    total_size = r_stats["total_size"] if r_stats else 0
                    last_date = (r_stats["max_date"] or "-")[:16].replace("T", " ") if r_stats else "-"
                    err_cnt = r_err["err_cnt"] if r_err else 0

                    if err_cnt > 0:
                        status_str = "🔴 Hatalı"
                    elif mail_cnt == 0:
                        status_str = "🟡 Senkron Edilmedi"
                    else:
                        status_str = "🟢 Sağlıklı"

                    if status_filter != "Tümü" and status_filter.split()[0] not in status_str:
                        continue

                    row_data = {
                        "account_id": acc_id,
                        "label": acc.get("label", ""),
                        "email": acc.get("email", ""),
                        "group": acc.get("account_group", "Varsayılan"),
                        "mail_count": mail_cnt,
                        "total_size": self._fmt_size(total_size),
                        "total_bytes": total_size,
                        "last_sync": last_date,
                        "error_count": err_cnt,
                        "status": status_str,
                    }
                    report_rows.append(row_data)

                    self.acc_rep_table.setItem(idx, 0, QTableWidgetItem(acc.get("label", "")))
                    self.acc_rep_table.setItem(idx, 1, QTableWidgetItem(acc.get("email", "")))
                    self.acc_rep_table.setItem(idx, 2, QTableWidgetItem(acc.get("account_group", "Varsayılan")))
                    
                    item_mc = QTableWidgetItem()
                    item_mc.setData(Qt.DisplayRole, mail_cnt)
                    self.acc_rep_table.setItem(idx, 3, item_mc)

                    item_sz = QTableWidgetItem(self._fmt_size(total_size))
                    self.acc_rep_table.setItem(idx, 4, item_sz)

                    self.acc_rep_table.setItem(idx, 5, QTableWidgetItem(last_date))
                    
                    item_err = QTableWidgetItem()
                    item_err.setData(Qt.DisplayRole, err_cnt)
                    self.acc_rep_table.setItem(idx, 6, item_err)

                    self.acc_rep_table.setItem(idx, 7, QTableWidgetItem(status_str))
        except Exception as exc:
            logger.exception("Error loading account reports: %s", exc)

        self._last_acc_rep_data = report_rows
        self.acc_rep_table.setSortingEnabled(True)

    @Slot()
    def _open_acc_rep_fullscreen_preview(self):
        rows = getattr(self, "_last_acc_rep_data", [])
        if not rows:
            self._load_account_reports()
            rows = getattr(self, "_last_acc_rep_data", [])

        table_rows_html = ""
        for r in rows:
            table_rows_html += f"""
            <tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:8px; font-weight:bold; color:#1e293b;">{r['label']}</td>
                <td style="padding:8px; color:#475569;">{r['email']}</td>
                <td style="padding:8px; color:#475569;">{r['group']}</td>
                <td style="padding:8px; font-weight:bold;">{r['mail_count']}</td>
                <td style="padding:8px;">{r['total_size']}</td>
                <td style="padding:8px; color:#64748b;">{r['last_sync']}</td>
                <td style="padding:8px; color:{'#ef4444' if r['error_count'] > 0 else '#475569'}; font-weight:bold;">{r['error_count']}</td>
                <td style="padding:8px; font-weight:bold;">{r['status']}</td>
            </tr>
            """

        html_content = f"""
        <h2>👤 Hesap Metrikleri ve Sağlık Raporu</h2>
        <p style="color:#64748b; font-size:13px;">Sistemde kayıtlı e-posta hesaplarının doluluk oranları, arşiv verisi büyüklüğü ve sağlık durumları aşağıdadır.</p>
        <table class="report-table" style="width:100%; border-collapse:collapse; margin-top:12px;">
            <thead>
                <tr style="background-color:#f1f5f9; font-weight:bold; color:#475569;">
                    <th style="padding:8px; text-align:left;">Hesap Adı</th>
                    <th style="padding:8px; text-align:left;">E-Posta Adresi</th>
                    <th style="padding:8px; text-align:left;">Grup</th>
                    <th style="padding:8px; text-align:left;">Arşiv Mail</th>
                    <th style="padding:8px; text-align:left;">Boyut</th>
                    <th style="padding:8px; text-align:left;">Son Sync</th>
                    <th style="padding:8px; text-align:left;">Hata</th>
                    <th style="padding:8px; text-align:left;">Durum</th>
                </tr>
            </thead>
            <tbody>
                {table_rows_html}
            </tbody>
        </table>
        """
        dialog = ReportPreviewDialog("Hesap Metrikleri Raporu", html_content, report_data=rows, parent=self)
        dialog.exec()

    # ------------------------------------------------------------------
    # Custom Reports & Virtual Reports Renders
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_custom_filter_changed(self, index: int):
        self.combo_custom_account.setVisible(False)
        self.combo_custom_group.setVisible(False)
        self.input_custom_domain.setVisible(False)
        self.input_custom_email.setVisible(False)

        if index == 0:
            self.combo_custom_account.setVisible(True)
        elif index == 1:
            self.combo_custom_group.setVisible(True)
        elif index == 2:
            self.input_custom_domain.setVisible(True)
        elif index == 3:
            self.input_custom_email.setVisible(True)

    @Slot()
    def _on_generate_custom(self):
        index = self.combo_custom_filter.currentIndex()
        account_id = None
        account_group = None
        domain = None
        single_email = None

        if index == 0:
            account_id = self.combo_custom_account.currentData()
            if account_id is None:
                QMessageBox.warning(self, "Hata", "Lütfen önce geçerli bir hesap seçin.")
                return
        elif index == 1:
            account_group = self.combo_custom_group.currentText()
            if not account_group:
                QMessageBox.warning(self, "Hata", "Lütfen geçerli bir domain grubu seçin.")
                return
        elif index == 2:
            domain = self.input_custom_domain.text().strip()
            if not domain:
                QMessageBox.warning(self, "Hata", "Lütfen bir e-posta domaini yazın (Örn: company.com).")
                return
            if domain.startswith("@"):
                domain = domain[1:]
        elif index == 3:
            single_email = self.input_custom_email.text().strip()
            if not single_email:
                QMessageBox.warning(self, "Hata", "Lütfen analiz edilecek e-posta adresini yazın.")
                return

        since_date = None
        if self.chk_custom_since.isChecked():
            since_date = self.date_custom_since.date().toString("yyyy-MM-dd 00:00:00")
            
        before_date = None
        if self.chk_custom_before.isChecked():
            before_date = self.date_custom_before.date().toString("yyyy-MM-dd 23:59:59")

        self.btn_generate_custom.setEnabled(False)
        self.log_output.append("Özel analiz raporu oluşturuluyor...")

        kwargs = {
            "account_id": account_id,
            "account_group": account_group,
            "domain": domain,
            "since_date": since_date,
            "before_date": before_date,
            "single_email": single_email,
        }

        self._custom_worker = CustomReportWorker(self.engine, kwargs, parent=self)
        self._custom_worker.finished.connect(self._on_custom_worker_finished)
        self._custom_worker.failed.connect(self._on_custom_worker_failed)
        self._custom_worker.start()

    @Slot(dict)
    def _on_custom_worker_finished(self, res: dict):
        self.btn_generate_custom.setEnabled(True)
        self._last_custom_report_res = res

        if res.get("total_mails", 0) == 0:
            QMessageBox.information(
                self, "Sonuç Yok",
                "Belirtilen arama kriterlerine uygun arşivlenmiş hiçbir e-posta bulunamadı."
            )
            self.log_output.append("Özel analiz raporu oluşturulamadı: Eşleşen e-posta yok.")
            self.custom_browser_preview.setHtml("<p style='color:#64748b; font-style:italic;'>Belirtilen arama kriterlerine uygun arşivlenmiş e-posta bulunamadı.</p>")
            self.btn_custom_fullscreen.setEnabled(False)
            self.btn_custom_html.setEnabled(False)
        else:
            report_path = res.get("report_path") or res.get("file_path") or ""
            self.log_output.append(f"Özel analiz raporu oluşturuldu: {report_path}")
            self._load_reports_history()

            html_content = ""
            html_path = res.get("html_path", "")
            if not html_path and report_path:
                html_path = str(Path(report_path).with_suffix(".html"))
                res["html_path"] = html_path

            if html_path and os.path.exists(html_path):
                try:
                    with open(html_path, "r", encoding="utf-8") as f:
                        html_content = f.read()
                except Exception:
                    pass
            if not html_content:
                html_content = self._render_virtual_report_html(res)

            # Display directly in Tab 2 body preview!
            self.custom_browser_preview.setHtml(html_content)
            self.btn_custom_fullscreen.setEnabled(True)
            self.btn_custom_html.setEnabled(bool(html_path) and os.path.exists(html_path))

    @Slot()
    def _on_custom_sidebar_selection_changed(self):
        selected_items = self.custom_group_filter_list.selectedItems()
        if not selected_items:
            return
        val = selected_items[0].data(Qt.UserRole)
        
        kwargs = {}
        if val == "ALL":
            kwargs = {}
        elif val.startswith("GROUP:"):
            grp = val.split("GROUP:")[1]
            kwargs = {"account_group": grp}
            self.combo_custom_filter.blockSignals(True)
            self.combo_custom_filter.setCurrentIndex(1)
            self.combo_custom_filter.blockSignals(False)
            self._on_custom_filter_changed(1)
            idx = self.combo_custom_group.findText(grp)
            if idx >= 0:
                self.combo_custom_group.setCurrentIndex(idx)
        elif val.startswith("DOMAIN:"):
            dom = val.split("DOMAIN:")[1]
            kwargs = {"domain": dom}
            self.combo_custom_filter.blockSignals(True)
            self.combo_custom_filter.setCurrentIndex(2)
            self.combo_custom_filter.blockSignals(False)
            self._on_custom_filter_changed(2)
            self.input_custom_domain.setText(dom)

        self.log_output.append("Sol menü seçiminden özel analiz raporu oluşturuluyor...")
        self.custom_browser_preview.setHtml("<p style='color:#4361ee; font-weight:bold;'>⏳ Seçili grup için özel analiz raporu hazırlanıyor...</p>")
        
        self._custom_worker = CustomReportWorker(self.engine, kwargs, parent=self)
        self._custom_worker.finished.connect(self._on_custom_worker_finished)
        self._custom_worker.failed.connect(self._on_custom_worker_failed)
        self._custom_worker.start()

    @Slot()
    def _on_stats_sidebar_selection_changed(self):
        selected_items = self.stats_group_filter_list.selectedItems()
        if not selected_items:
            return
        val = selected_items[0].data(Qt.UserRole)

        all_accounts = self.engine.list_accounts()
        matched_accounts = []
        scope_title = "Tüm Veritabanı"

        if val == "ALL":
            matched_accounts = all_accounts
            scope_title = "Tüm Hesaplar"
        elif val.startswith("GROUP:"):
            grp = val.split("GROUP:")[1]
            scope_title = f"Grup: {grp}"
            matched_accounts = [a for a in all_accounts if str(a.get("account_group", "")).lower() == grp.lower()]
            self.combo_sync_scope.setCurrentIndex(1)
            idx = self.combo_sync_group.findText(grp)
            if idx >= 0:
                self.combo_sync_group.setCurrentIndex(idx)
        elif val.startswith("DOMAIN:"):
            dom = val.split("DOMAIN:")[1].lower()
            dom_prefix = dom.split(".")[0]
            scope_title = f"Domain: @{dom}"
            matched_accounts = [a for a in all_accounts if a.get("email", "").lower().endswith("@" + dom) or dom_prefix in a.get("label", "").lower() or dom_prefix in a.get("email", "").lower()]
            self.combo_sync_scope.setCurrentIndex(1)

        if not matched_accounts:
            self.stats_table.setRowCount(1)
            self.stats_table.setItem(0, 0, QTableWidgetItem("Sistem Metriği"))
            self.stats_table.setItem(0, 1, QTableWidgetItem("Seçilen kritere uygun hesap bulunamadı."))
            return

        acc_ids = [a["id"] for a in matched_accounts]
        
        try:
            with self.engine.db.get_conn() as conn:
                placeholders = ",".join("?" for _ in acc_ids)
                row_mails = conn.execute(
                    f"SELECT COUNT(*) as cnt, COALESCE(SUM(size_bytes), 0) as total_size, MIN(date) as min_date, MAX(date) as max_date FROM mail_metadata WHERE account_id IN ({placeholders}) AND is_deleted=0",
                    acc_ids
                ).fetchone()

                row_del = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM mail_metadata WHERE account_id IN ({placeholders}) AND is_deleted=1",
                    acc_ids
                ).fetchone()

                row_dup = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM mail_metadata WHERE account_id IN ({placeholders}) AND is_duplicate=1",
                    acc_ids
                ).fetchone()

                row_att = conn.execute(
                    f"SELECT COUNT(*) as cnt FROM attachment_links WHERE mail_id IN (SELECT id FROM mail_metadata WHERE account_id IN ({placeholders}))",
                    acc_ids
                ).fetchone()

            stats = {
                "grup_kapsami": scope_title,
                "hesap_sayisi": len(matched_accounts),
                "toplam_mail_sayisi": row_mails["cnt"] if row_mails else 0,
                "toplam_arşiv_boyutu": self._fmt_size(row_mails["total_size"]) if row_mails else "0 B",
                "silinmis_mail_sayisi": row_del["cnt"] if row_del else 0,
                "cift_kayit_sayisi": row_dup["cnt"] if row_dup else 0,
                "ekli_dosya_sayisi": row_att["cnt"] if row_att else 0,
                "en_eski_mail_tarihi": (row_mails["min_date"] or "-")[:10] if row_mails else "-",
                "en_yeni_mail_tarihi": (row_mails["max_date"] or "-")[:10] if row_mails else "-",
            }
            self._on_stats_worker_finished(stats)
            self.log_output.append(f"[{scope_title}] Veritabanı istatistikleri güncellendi.")
        except Exception as exc:
            logger.exception("Group stats calculation error: %s", exc)
            self.log_output.append(f"HATA: {exc}")

    @Slot(str)
    def _on_custom_worker_failed(self, err_msg: str):
        self.btn_generate_custom.setEnabled(True)
        QMessageBox.critical(self, "Hata", f"Analiz raporu oluşturulurken hata oluştu:\n{err_msg}")
        self.log_output.append(f"HATA: {err_msg}")

    @Slot()
    def _open_custom_fullscreen_preview(self):
        if not self._last_custom_report_res:
            return
        res = self._last_custom_report_res
        html_content = self.custom_browser_preview.toHtml()
        dialog = ReportPreviewDialog("Özel Analiz Raporu", html_content, report_data=res, parent=self)
        dialog.exec()

    @Slot()
    def _open_custom_html_report(self):
        if not self._last_custom_report_res:
            return
        html_path = self._last_custom_report_res.get("html_path", "")
        if html_path and os.path.exists(html_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(html_path)))

    def _render_virtual_report_html(self, r: dict) -> str:
        r_type = str(r.get("type", "")).upper()
        ts = str(r.get("timestamp", "")).replace("T", " ")[:19]
        acc_label = r.get("account_label", "Hesap")
        details = r.get("details", {})
        
        html = f"""
        <html>
        <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; padding:10px; color:#1e293b; line-height:1.5;">
            <div style="background-color:#eff6ff; padding:12px; border-radius:6px; border-left:4px solid #3b82f6; margin-bottom:15px;">
                <h3 style="margin:0; color:#1e40af;">🔒 Geçmiş İşlem Kaydı (Veritabanı Audit Log)</h3>
                <p style="margin:4px 0 0 0; font-size:11px; color:#60a5fa;">Bu işlem veritabanı loglarından yüklenmiştir, diskte fiziksel HTML dosyası bulunmamaktadır.</p>
            </div>
            
            <h2 style="color:#1e3a8a; border-bottom:2px solid #cbd5e1; padding-bottom:6px; margin-top:0;">{r_type} İşlem Raporu</h2>
            <table style="width:100%; border-collapse:collapse; margin-top:10px;">
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; width:150px; color:#64748b;">İşlem Zamanı:</td><td style="padding:6px;">{ts}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Hesap/Detay:</td><td style="padding:6px;">{acc_label}</td></tr>
        """
        
        if r_type == "SYNC":
            html += f"""
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Çekilen E-Posta:</td><td style="padding:6px; font-weight:bold; color:#10b981;">{details.get('fetched', 0)}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Mükerrer Silinen:</td><td style="padding:6px;">{details.get('duplicates', 0)}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">İşlem Süresi:</td><td style="padding:6px;">{details.get('duration', 0.0):.1f} saniye</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Hatalar:</td><td style="padding:6px; color:{'#ef4444' if details.get('errors', 0) > 0 else '#1e293b'}; font-weight:bold;">{details.get('errors', 0)}</td></tr>
            """
        elif r_type == "BACKUP":
            html += f"""
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Yedeklenen Mail:</td><td style="padding:6px; font-weight:bold; color:#10b981;">{details.get('mails_backed_up', 0)}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Hedef Depolama:</td><td style="padding:6px;">{details.get('bucket', 'Bulut')}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Veri Boyutu:</td><td style="padding:6px;">{self._fmt_size(details.get('size_bytes', 0))}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Durum:</td><td style="padding:6px; font-weight:bold; color:{'#10b981' if details.get('success', True) else '#ef4444'}">{'BAŞARILI' if details.get('success', True) else 'HATALI'}</td></tr>
            """
        elif r_type == "RESTORE":
            html += f"""
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Kurtarılan Mail:</td><td style="padding:6px; font-weight:bold; color:#10b981;">{details.get('mails_restored', 0)}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Kaynak Dosya:</td><td style="padding:6px;">{details.get('source', 'Bulut Yedek')}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Hatalar:</td><td style="padding:6px; color:{'#ef4444' if details.get('errors', 0) > 0 else '#1e293b'}; font-weight:bold;">{details.get('errors', 0)}</td></tr>
            """
            
        html += """
            </table>
        </body>
        </html>
        """
        return html

    def _fmt_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    # ------------------------------------------------------------------
    # Scope & Sync Report Generator Slots
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_sync_scope_changed(self, index: int):
        if index == 0:
            self.lbl_sync_target.setText("Hesap Seçin:")
            self.lbl_sync_target.setVisible(True)
            self.combo_sync_account.setVisible(True)
            self.combo_sync_group.setVisible(False)
        elif index == 1:
            self.lbl_sync_target.setText("Domain/Grup Seçin:")
            self.lbl_sync_target.setVisible(True)
            self.combo_sync_account.setVisible(False)
            self.combo_sync_group.setVisible(True)
        else:
            self.lbl_sync_target.setVisible(False)
            self.combo_sync_account.setVisible(False)
            self.combo_sync_group.setVisible(False)

    def _build_db_sync_report(self, account_id: int) -> Dict[str, Any]:
        acc_info = self.engine.accounts.get(account_id)
        label = acc_info.get("label", f"Hesap #{account_id}") if acc_info else f"Hesap #{account_id}"
        
        mail_count = 0
        total_bytes = 0
        folders_cnt = 0
        started_at = ""
        finished_at = ""
        
        try:
            with self.engine.db.get_conn() as conn:
                r_stats = conn.execute(
                    "SELECT COUNT(*) as cnt, COALESCE(SUM(size_bytes), 0) as total_size, MIN(date) as min_date, MAX(date) as max_date FROM mail_metadata WHERE account_id=? AND is_deleted=0",
                    (account_id,)
                ).fetchone()
                if r_stats:
                    mail_count = r_stats["cnt"] or 0
                    total_bytes = r_stats["total_size"] or 0
                    started_at = r_stats["min_date"] or ""
                    finished_at = r_stats["max_date"] or ""
                    
                r_fld = conn.execute(
                    "SELECT COUNT(DISTINCT folder) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0",
                    (account_id,)
                ).fetchone()
                if r_fld:
                    folders_cnt = r_fld["cnt"] or 0
        except Exception as exc:
            logger.error("Error building DB sync report for account %s: %s", account_id, exc)
            
        return {
            "account_label": label,
            "account_id": account_id,
            "folders_synced": folders_cnt,
            "mails_fetched": mail_count,
            "mails_already_archived": mail_count,
            "mails_updated": 0,
            "duplicates_found": 0,
            "errors": 0,
            "error_details": [],
            "total_bytes": total_bytes,
            "duration_seconds": 0.0,
            "started_at": started_at or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": finished_at or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _get_accounts_for_scope(self) -> tuple[str, List[Dict[str, Any]]]:
        scope_idx = self.combo_sync_scope.currentIndex()
        all_accounts = self.engine.list_accounts()

        if scope_idx == 0:
            acc_id = self.combo_sync_account.currentData()
            selected = [a for a in all_accounts if a["id"] == acc_id]
            label = selected[0]["label"] if selected else "Hesap"
            return label, selected
        elif scope_idx == 1:
            grp_name = self.combo_sync_group.currentText().strip()
            if grp_name.startswith("@"):
                dom = grp_name[1:].lower()
                matched = [a for a in all_accounts if a.get("email", "").lower().endswith("@" + dom)]
                return f"Domain @{dom}", matched
            else:
                matched = [a for a in all_accounts if str(a.get("account_group", "")).lower() == grp_name.lower()]
                return f"Grup {grp_name}", matched
        else:
            return "Tüm Hesaplar", all_accounts

    def _gen_sync_report_action(self, live_sync: bool = False):
        scope_label, acc_list = self._get_accounts_for_scope()
        if not acc_list:
            QMessageBox.warning(self, "Uyarı", "Seçilen kritere uygun hesap bulunamadı.")
            return

        self.btn_sync_live.setEnabled(False)
        self.btn_sync_db.setEnabled(False)

        if not live_sync:
            self.log_output.append(f"[{scope_label}] Arşiv verilerinden rapor oluşturuluyor...")
            self._db_sync_worker = DBSyncReportWorker(self, scope_label, acc_list, parent=self)
            self._db_sync_worker.finished.connect(self._on_db_sync_report_done_gui)
            self._db_sync_worker.failed.connect(self._on_db_sync_report_failed_gui)
            self._db_sync_worker.start()
        else:
            self.log_output.append(f"[{scope_label}] Canlı senkronizasyon ve rapor oluşturma başlatıldı...")

            def run_task():
                try:
                    reps = []
                    for a in acc_list:
                        r_dict = self.engine.sync_account(a["id"])
                        reps.append(r_dict)

                    if len(reps) == 1:
                        json_p = self._reporter.generate_sync_report(reps[0], output_format="both")
                    else:
                        json_p = self._reporter.generate_batch_sync_report(reps, group_name=scope_label, output_format="both")

                    self._sync_done_signal.emit(str(json_p))
                except Exception as exc:
                    logger.exception("Live sync error: %s", exc)
                    self._sync_err_signal.emit(str(exc))

            import threading
            threading.Thread(target=run_task, daemon=True).start()

    @Slot(str)
    def _on_db_sync_report_done_gui(self, json_path_str: str):
        self.btn_sync_live.setEnabled(True)
        self.btn_sync_db.setEnabled(True)
        self.log_output.append(f"Sync/Arşiv raporu oluşturuldu: {json_path_str}")
        self._load_reports_history()
        self._show_report_preview_by_path(json_path_str)

    @Slot(str)
    def _on_db_sync_report_failed_gui(self, err_msg: str):
        self.btn_sync_live.setEnabled(True)
        self.btn_sync_db.setEnabled(True)
        self.log_output.append(f"HATA: Rapor oluşturulamadı: {err_msg}")
        QMessageBox.critical(self, "Hata", f"Rapor oluşturulamadı: {err_msg}")

    @Slot(str)
    def _on_sync_task_done_gui(self, json_path_str: str):
        self.btn_sync_live.setEnabled(True)
        self.btn_sync_db.setEnabled(True)
        self.log_output.append(f"Sync raporu kaydedildi: {json_path_str}")
        self._load_reports_history()
        self._show_report_preview_by_path(json_path_str)

    @Slot(str)
    def _on_sync_task_err_gui(self, err_msg: str):
        self.btn_sync_live.setEnabled(True)
        self.btn_sync_db.setEnabled(True)
        self.log_output.append(f"HATA: {err_msg}")
        QMessageBox.critical(self, "Hata", f"Senkronizasyon hatası: {err_msg}")

    def _show_report_preview_by_path(self, json_path_str: str):
        p = Path(json_path_str)
        html_path = p.with_suffix(".html")
        html_content = ""
        report_data = {}
        try:
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    report_data = json.load(f)
            if html_path.exists():
                with open(html_path, "r", encoding="utf-8") as f:
                    html_content = f.read()
        except Exception:
            pass

        title = str(report_data.get("account_label") or report_data.get("account") or "Sync Raporu").upper()
        dialog = ReportPreviewDialog(f"{title} Raporu", html_content, report_data=report_data, parent=self)
        dialog.exec()

    @Slot()
    def _gen_sidebar_sync_report(self):
        selected_items = self.group_filter_list.selectedItems()
        val = selected_items[0].data(Qt.UserRole) if selected_items else "ALL"

        if val == "ALL":
            sync_reports = [r for r in self._reports_list if str(r.get("type", "")).lower() == "sync"]
            if sync_reports:
                latest_p = sync_reports[0].get("file_path") or sync_reports[0].get("html_path")
                if latest_p and os.path.exists(latest_p):
                    self._show_report_preview_by_path(str(latest_p))
                    return
                else:
                    html_content = self._render_virtual_report_html(sync_reports[0])
                    dialog = ReportPreviewDialog("Son Senkronizasyon Raporu", html_content, report_data=sync_reports[0], parent=self)
                    dialog.exec()
                    return
            else:
                QMessageBox.warning(
                    self, "Filtre / Rapor Seçilmedi",
                    "Bir grup seçmediniz ve henüz yapılmış bir senkronizasyon işlemi bulunamadı.\n"
                    "Lütfen sol listeden bir grup veya domain seçin ya da senkronizasyon çalıştırın."
                )
                return

        all_accounts = self.engine.list_accounts()
        scope_name = ""
        matched = []

        if val.startswith("GROUP:"):
            grp = val.split("GROUP:")[1]
            scope_name = f"Grup {grp}"
            matched = [a for a in all_accounts if str(a.get("account_group", "")).lower() == grp.lower()]
        elif val.startswith("DOMAIN:"):
            dom = val.split("DOMAIN:")[1].lower()
            dom_prefix = dom.split(".")[0]
            scope_name = f"Domain @{dom}"
            matched = [a for a in all_accounts if a.get("email", "").lower().endswith("@" + dom) or dom_prefix in a.get("email", "").lower() or dom_prefix in a.get("label", "").lower()]

        if not matched:
            QMessageBox.warning(self, "Sonuç Bulunamadı", f"'{scope_name}' için sistemde eşleşen e-posta hesabı bulunamadı.")
            return

        matching_history_reports = []
        matched_ids = set(a["id"] for a in matched)
        matched_labels = set(str(a["label"]).lower() for a in matched)
        matched_emails = set(str(a["email"]).lower() for a in matched)

        for r in self._reports_list:
            if str(r.get("type", "")).lower() != "sync":
                continue
            r_acc_id = r.get("account_id")
            r_label = str(r.get("account_label") or r.get("account") or "").lower()
            r_email = str(r.get("email") or "").lower()
            r_grp = str(r.get("account_group") or "").lower()
            if r_acc_id in matched_ids or any(l in r_label for l in matched_labels) or r_email in matched_emails or any(dom_prefix in r_label or dom_prefix in r_email for a in matched):
                matching_history_reports.append(r)

        if matching_history_reports:
            if len(matching_history_reports) == 1:
                latest_p = matching_history_reports[0].get("file_path") or matching_history_reports[0].get("html_path")
                if latest_p and os.path.exists(latest_p):
                    self._show_report_preview_by_path(str(latest_p))
                    return
                else:
                    html_content = self._render_virtual_report_html(matching_history_reports[0])
                    dialog = ReportPreviewDialog(f"{scope_name} Sync Raporu", html_content, report_data=matching_history_reports[0], parent=self)
                    dialog.exec()
                    return
            else:
                json_p = self._reporter.generate_batch_sync_report(matching_history_reports, group_name=scope_name, output_format="both")
                self._load_reports_history()
                self._show_report_preview_by_path(str(json_p))
                return

        self.log_output.append(f"[{scope_name}] Grup/Domain sync raporu oluşturuluyor...")
        self._db_sync_worker = DBSyncReportWorker(self, scope_name, matched, parent=self)
        self._db_sync_worker.finished.connect(self._on_db_sync_report_done_gui)
        self._db_sync_worker.failed.connect(self._on_db_sync_report_failed_gui)
        self._db_sync_worker.start()

    @Slot()
    def _gen_sync_report(self):
        self._gen_sync_report_action(live_sync=True)

    @Slot()
    def refresh_ui_after_task(self):
        self._load_reports_history()

    @Slot()
    def _gen_stats_report(self):
        self.btn_stats_report.setEnabled(False)
        self.log_output.append("Veritabanı istatistikleri sorgulanıyor...")
        self._stats_worker = StatsWorker(self.engine, parent=self)
        self._stats_worker.finished.connect(self._on_stats_worker_finished)
        self._stats_worker.failed.connect(self._on_stats_worker_failed)
        self._stats_worker.start()

    @Slot(dict)
    def _on_stats_worker_finished(self, stats: dict):
        self.btn_stats_report.setEnabled(True)
        self._last_stats_res = stats
        self.stats_table.setRowCount(len(stats))
        for i, (k, v) in enumerate(stats.items()):
            self.stats_table.setItem(i, 0, QTableWidgetItem(k.replace("_", " ").title()))
            self.stats_table.setItem(i, 1, QTableWidgetItem(str(v)))
        self.stats_table.resizeColumnsToContents()
        self.log_output.append("Veritabanı istatistikleri güncellendi.")

    @Slot(str)
    def _on_stats_worker_failed(self, err_msg: str):
        self.btn_stats_report.setEnabled(True)
        self.log_output.append(f"HATA: {err_msg}")

    @Slot()
    def _open_stats_fullscreen_preview(self):
        stats = getattr(self, "_last_stats_res", None)
        if not stats:
            stats = self.engine.get_stats()
            self._last_stats_res = stats

        rows_html = ""
        for k, v in stats.items():
            fmt_k = str(k).replace("_", " ").title()
            rows_html += f"<tr><td style='padding:8px; font-weight:bold; color:#475569;'>{fmt_k}</td><td style='padding:8px; color:#1e293b;'>{v}</td></tr>"

        html_content = f"""
        <h2>📈 Veritabanı İstatistikleri Raporu</h2>
        <p style="color:#64748b; font-size:13px;">Sistem veritabanı kullanım metrikleri ve kayıt detayları aşağıdadır.</p>
        <table class="report-table" style="width:100%; border-collapse:collapse; margin-top:12px;">
            <thead>
                <tr style="background-color:#f1f5f9; font-weight:bold; color:#475569;">
                    <th style="padding:8px; text-align:left;">Metrik</th>
                    <th style="padding:8px; text-align:left;">Değer</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        """
        dialog = ReportPreviewDialog("Veritabanı İstatistikleri", html_content, report_data=stats, parent=self)
        dialog.exec()

    def refresh(self):
        self.combo_sync_account.clear()
        self.combo_sync_group.clear()
        self.combo_custom_account.clear()
        self.combo_custom_group.clear()
        
        self.group_filter_list.clear()
        self.custom_group_filter_list.clear()
        self.stats_group_filter_list.clear()
        self.acc_rep_group_filter_list.clear()

        item_all1 = QListWidgetItem("🌐 Tümü (Tüm Hesaplar)")
        item_all1.setData(Qt.UserRole, "ALL")
        self.group_filter_list.addItem(item_all1)
        self.group_filter_list.setCurrentItem(item_all1)

        item_all2 = QListWidgetItem("🌐 Tümü (Tüm Hesaplar)")
        item_all2.setData(Qt.UserRole, "ALL")
        self.custom_group_filter_list.addItem(item_all2)
        self.custom_group_filter_list.setCurrentItem(item_all2)

        item_all3 = QListWidgetItem("🌐 Tümü (Tüm Hesaplar)")
        item_all3.setData(Qt.UserRole, "ALL")
        self.stats_group_filter_list.addItem(item_all3)
        self.stats_group_filter_list.setCurrentItem(item_all3)

        item_all4 = QListWidgetItem("🌐 Tümü (Tüm Hesaplar)")
        item_all4.setData(Qt.UserRole, "ALL")
        self.acc_rep_group_filter_list.addItem(item_all4)
        self.acc_rep_group_filter_list.setCurrentItem(item_all4)

        groups_status = {}
        settings_groups = self.settings.get("group_domains", []) if hasattr(self, "settings") and self.settings else []
        for g in settings_groups:
            name = g if isinstance(g, str) else (g.get("name", "") if isinstance(g, dict) else "")
            if name and name.strip():
                groups_status[name.strip()] = True

        try:
            accounts = self.engine.list_accounts()
            for acc in accounts:
                lbl_str = f"{acc['label']} ({acc['email']})"
                self.combo_sync_account.addItem(lbl_str, acc["id"])
                self.combo_custom_account.addItem(lbl_str, acc["id"])

            with self.engine.db.get_conn() as conn:
                rows = conn.execute("SELECT DISTINCT account_group FROM accounts WHERE account_group IS NOT NULL AND account_group != ''").fetchall()
                for r in rows:
                    grp = r["account_group"].strip()
                    if grp:
                        groups_status[grp] = True

            for grp in sorted(groups_status.keys()):
                self.combo_custom_group.addItem(grp)
                self.combo_sync_group.addItem(grp)

                item_grp1 = QListWidgetItem(f"📁 {grp}")
                item_grp1.setData(Qt.UserRole, f"GROUP:{grp}")
                self.group_filter_list.addItem(item_grp1)

                item_grp2 = QListWidgetItem(f"📁 {grp}")
                item_grp2.setData(Qt.UserRole, f"GROUP:{grp}")
                self.custom_group_filter_list.addItem(item_grp2)

                item_grp3 = QListWidgetItem(f"📁 {grp}")
                item_grp3.setData(Qt.UserRole, f"GROUP:{grp}")
                self.stats_group_filter_list.addItem(item_grp3)

                item_grp4 = QListWidgetItem(f"📁 {grp}")
                item_grp4.setData(Qt.UserRole, f"GROUP:{grp}")
                self.acc_rep_group_filter_list.addItem(item_grp4)

            self._load_reports_history()
            self._load_account_reports()
        except Exception as exc:
            logger.error("Refresh error: %s", exc)
