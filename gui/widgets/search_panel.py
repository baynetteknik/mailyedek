"""
search_panel.py — Full-text search panel with ToyaDbGrid, per-column filters,
integrated pagination, asynchronous query execution, and rich email preview.
"""

import email
import logging
import mimetypes
import re
import os
import tempfile
from datetime import datetime
from email.header import decode_header
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Slot, Signal, QThread, QDate, QUrl, QEvent
from PySide6.QtGui import QFont, QColor, QDesktopServices, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QGroupBox, QTextBrowser, QMessageBox, QComboBox, QDateEdit,
    QCheckBox, QSplitter, QFrame, QListWidget, QListWidgetItem,
    QAbstractItemView, QListView, QFileDialog
)

from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.widgets.toya_grid_widget import ToyaDbGrid

logger = logging.getLogger(__name__)

GLOBAL_MSG_STYLE = """
    QMessageBox, QDialog, QFileDialog {
        background-color: #ffffff;
        color: #0f172a;
    }
    QMessageBox QLabel, QDialog QLabel, QFileDialog QLabel {
        color: #0f172a;
        font-weight: 500;
        font-size: 13px;
    }
    QMessageBox QPushButton, QDialog QPushButton, QFileDialog QPushButton {
        background-color: #2563eb;
        color: #ffffff;
        font-weight: 600;
        font-size: 12px;
        border: none;
        border-radius: 6px;
        padding: 6px 16px;
        min-width: 85px;
        min-height: 28px;
    }
    QMessageBox QPushButton:hover, QDialog QPushButton:hover, QFileDialog QPushButton:hover {
        background-color: #1d4ed8;
    }
"""


class CheckableComboBox(QComboBox):
    """Custom QComboBox with checkable items to support multi-select in compact height."""

    def __init__(self, placeholder="Tüm Klasörler", parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self.setModel(QStandardItemModel(self))
        self.setView(QListView(self))
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.view().viewport().installEventFilter(self)
        self.model().dataChanged.connect(self._on_data_changed)
        self.on_selection_changed = None

        self.setStyleSheet("""
            QComboBox {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
                color: #0f172a;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #0f172a;
                selection-background-color: #e2e8f0;
                selection-color: #0f172a;
                border: 1px solid #cbd5e1;
                outline: none;
                font-size: 11px;
            }
            QLineEdit {
                border: none;
                background: transparent;
                font-size: 11px;
                color: #0f172a;
                font-weight: bold;
            }
        """)
        self._update_display_text()

    def eventFilter(self, widget, event):
        if widget == self.view().viewport() and event.type() == QEvent.MouseButtonRelease:
            index = self.view().indexAt(event.pos())
            if index.isValid():
                item = self.model().itemFromIndex(index)
                if item.checkState() == Qt.Checked:
                    item.setCheckState(Qt.Unchecked)
                else:
                    item.setCheckState(Qt.Checked)
                return True
        return super().eventFilter(widget, event)

    def hidePopup(self):
        super().hidePopup()
        self._update_display_text()

    def _on_data_changed(self, top_left=None, bottom_right=None, roles=None):
        self._update_display_text()
        if callable(self.on_selection_changed):
            self.on_selection_changed()

    def _update_display_text(self):
        checked_items = self.get_checked_items()
        total = self.model().rowCount()
        if not checked_items or len(checked_items) == total:
            self.setEditText(f"📁 {self._placeholder}")
        elif len(checked_items) == 1:
            self.setEditText(f"📁 {checked_items[0]}")
        else:
            self.setEditText(f"📁 {len(checked_items)} Klasör Seçili")

    def get_checked_items(self) -> List[str]:
        items = []
        for row in range(self.model().rowCount()):
            item = self.model().item(row)
            if item and item.checkState() == Qt.Checked:
                orig = item.data(Qt.UserRole)
                items.append(orig if orig is not None else item.text())
        return items

    def set_all_checked(self, checked: bool = True):
        self.model().blockSignals(True)
        for row in range(self.model().rowCount()):
            item = self.model().item(row)
            if item:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.model().blockSignals(False)
        self._update_display_text()
        if callable(self.on_selection_changed):
            self.on_selection_changed()


BTN_STYLE_BLUE = """
    QPushButton {
        background-color: #2563eb;
        color: white;
        font-weight: 600;
        padding: 5px 12px;
        border-radius: 6px;
        font-size: 12px;
        border: none;
    }
    QPushButton:hover {
        background-color: #1d4ed8;
    }
"""

BTN_STYLE_OUTLINE = """
    QPushButton {
        background-color: transparent;
        color: #4b5563;
        border: 1px solid #cbd5e1;
        font-weight: 600;
        padding: 5px 12px;
        border-radius: 6px;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: #f1f5f9;
        border-color: #94a3b8;
    }
"""


class SearchDataLoaderWorker(QThread):
    """Background worker to query accounts, domains, distinct folders, and mail counts."""
    data_loaded_signal = Signal(object, object, object, object)  # accounts, domains, folders, mail_counts
    error_signal = Signal(str)

    def __init__(self, engine: MailEngine, account_id: Optional[int] = None, sel_domain: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.account_id = account_id
        self.sel_domain = sel_domain

    def run(self):
        try:
            accounts = self.engine.list_accounts()
            domains = set()
            for acc in accounts:
                email_str = acc.get("email", "")
                dom = email_str.split("@")[-1].strip().lower() if "@" in email_str else (acc.get("account_group", "").strip() or "Diğer")
                if dom:
                    domains.add(dom)

            # Query distinct folders and account mail counts
            from infrastructure.imap_client import format_folder_display_name
            folders = []
            mail_counts = {}
            with self.engine.db.get_conn() as conn:
                count_rows = conn.execute(
                    "SELECT account_id, COUNT(*) as cnt FROM mail_metadata WHERE is_deleted = 0 GROUP BY account_id"
                ).fetchall()
                for cr in count_rows:
                    mail_counts[cr["account_id"]] = cr["cnt"]

                params = []
                where_clauses = ["is_deleted = 0"]

                if self.account_id:
                    where_clauses.append("account_id = ?")
                    params.append(self.account_id)
                elif self.sel_domain:
                    matching_ids = []
                    for acc in accounts:
                        email_str = acc.get("email", "")
                        acc_dom = email_str.split("@")[-1].strip().lower() if "@" in email_str else (acc.get("account_group", "").strip() or "Diğer")
                        if self.sel_domain and acc_dom == self.sel_domain.lower():
                            matching_ids.append(acc.get("id"))
                    if matching_ids:
                        placeholders = ", ".join("?" for _ in matching_ids)
                        where_clauses.append(f"account_id IN ({placeholders})")
                        params.extend(matching_ids)

                where_sql = " AND ".join(where_clauses)
                rows = conn.execute(
                    f"SELECT DISTINCT folder FROM mail_metadata WHERE {where_sql} ORDER BY folder ASC",
                    params
                ).fetchall()
                for r in rows:
                    orig = r["folder"]
                    disp = format_folder_display_name(orig)
                    folders.append((orig, disp))

            self.data_loaded_signal.emit(accounts, sorted(domains), folders, mail_counts)
        except Exception as e:
            logger.exception("SearchDataLoaderWorker error: %s", e)
            self.error_signal.emit(str(e))


class SearchExecutionWorker(QThread):
    """Background worker to execute FTS5 search queries asynchronously."""
    results_ready_signal = Signal(list)
    error_signal = Signal(str)

    def __init__(self, engine: MailEngine, search_params: dict, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.params = search_params

    def run(self):
        try:
            results = self.engine.search(
                query=self.params.get("query", ""),
                limit=self.params.get("limit", 1000),
                account_id=self.params.get("account_id"),
                folder=self.params.get("folder"),
                since_date=self.params.get("since_date"),
                before_date=self.params.get("before_date"),
                has_attachments=self.params.get("has_attachments"),
                unread_only=self.params.get("unread_only")
            )

            sel_domain = self.params.get("sel_domain")
            if sel_domain and sel_domain != "__ALL__":
                accounts_map = {a["id"]: a for a in self.engine.list_accounts()}
                filtered_results = []
                for r in results:
                    acc_id = r.get("account_id")
                    acc = accounts_map.get(acc_id) if acc_id else None
                    if acc:
                        email_str = acc.get("email", "")
                        acc_dom = email_str.split("@")[-1].strip().lower() if "@" in email_str else (acc.get("account_group", "").strip() or "Diğer")
                        if acc_dom != sel_domain.lower():
                            continue
                    filtered_results.append(r)
                results = filtered_results

            self.results_ready_signal.emit(results)
        except Exception as e:
            logger.exception("SearchExecutionWorker error: %s", e)
            self.error_signal.emit(str(e))


class SearchPanel(QWidget):
    """Full-text search panel with ToyaDbGrid, per-column filtering, pagination, and preview."""

    COLUMNS = ["Tarih", "Hesap", "Kimden", "Alıcı", "Konu", "Klasör", "Boyut", "Ek"]
    DEFAULT_WIDTHS = [95, 110, 120, 120, 160, 75, 55, 35]

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.settings = AppSettings()
        
        self._all_accounts: List[Dict[str, Any]] = []
        self._accounts_by_id: Dict[int, Dict[str, Any]] = {}
        self._account_mail_counts: Dict[int, int] = {}
        self._all_results: List[Dict[str, Any]] = []
        self._filtered_results: List[Dict[str, Any]] = []
        self._column_filters: Dict[int, str] = {}
        self._current_attachments: List[Dict[str, Any]] = []
        self._raw_mode = False

        self._loader_worker: Optional[SearchDataLoaderWorker] = None
        self._search_worker: Optional[SearchExecutionWorker] = None

        self._setup_ui()
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "db_grid") and hasattr(self.db_grid, "filter_bar"):
            self.db_grid.filter_bar.adjust_positions()

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "db_grid") and hasattr(self.db_grid, "filter_bar"):
            self.db_grid.filter_bar.adjust_positions()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        from gui.templates.three_panel_workspace import ThreePanelWorkspaceTemplate
        self.workspace = ThreePanelWorkspaceTemplate(title="🔍 Detaylı E-Posta Arama Paneli", parent=self)
        main_layout.addWidget(self.workspace)

        ws = self.workspace
        ws.btn_toggle_left.setText("🌐 Sol Filtre Paneli")
        ws.btn_toggle_right.setText("📧 Sağ Önizleme Paneli")

        # -------------------------------------------------------------------
        # 1. SOL PANEL: Domain, Hesap, Klasör ve Tarih Filtreleri
        # -------------------------------------------------------------------
        ws.left_group.setTitle("🌐 Domain & Filtre Seçenekleri")
        left_layout = ws.left_inner_layout

        left_layout.addWidget(QLabel("🌐 Domain Filtresi:"))
        self.combo_domain = QComboBox()
        self.combo_domain.currentIndexChanged.connect(self._on_domain_filter_changed)
        left_layout.addWidget(self.combo_domain)

        left_layout.addWidget(QLabel("👤 Hesap Seçimi:"))
        self.combo_account = QComboBox()
        self.combo_account.currentIndexChanged.connect(self._on_account_filter_changed)
        left_layout.addWidget(self.combo_account)

        left_layout.addWidget(QLabel("📁 Klasör Filtresi (Açılır Çoklu Seçim):"))
        self.combo_folder = CheckableComboBox(placeholder="Tüm Klasörler", parent=self)
        self.combo_folder.on_selection_changed = self._search
        left_layout.addWidget(self.combo_folder)

        f_ctrls = QHBoxLayout()
        btn_all_f = QPushButton("Tümünü Seç")
        btn_all_f.setCursor(Qt.PointingHandCursor)
        btn_all_f.setStyleSheet("background-color: #2563eb; color: #ffffff; font-weight: bold; padding: 4px 8px; font-size: 10px; border-radius: 3px;")
        btn_all_f.clicked.connect(self._select_all_folders)

        btn_none_f = QPushButton("Seçimleri Temizle")
        btn_none_f.setCursor(Qt.PointingHandCursor)
        btn_none_f.setStyleSheet("background-color: #475569; color: #ffffff; font-weight: bold; padding: 4px 8px; font-size: 10px; border-radius: 3px;")
        btn_none_f.clicked.connect(self._clear_all_folders)

        f_ctrls.addWidget(btn_all_f)
        f_ctrls.addWidget(btn_none_f)
        f_ctrls.addStretch()
        left_layout.addLayout(f_ctrls)

        left_layout.addWidget(QLabel("📎 Ek Dosya Durumu:"))
        self.combo_attachments = QComboBox()
        self.combo_attachments.addItems(["Tümü", "Ekli Olanlar", "Eksiz Olanlar"])
        self.combo_attachments.currentIndexChanged.connect(self._apply_filters)
        left_layout.addWidget(self.combo_attachments)

        left_layout.addWidget(QLabel("📩 Okuma Durumu:"))
        self.combo_read = QComboBox()
        self.combo_read.addItems(["Tümü", "Yalnızca Okunmamış", "Yalnızca Okunmuş"])
        self.combo_read.currentIndexChanged.connect(self._apply_filters)
        left_layout.addWidget(self.combo_read)

        left_layout.addSpacing(6)
        self.chk_since = QCheckBox("Şu tarihten yeni:")
        self.chk_since.setStyleSheet("font-weight: bold; color: #1e293b;")
        self.date_since = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_since.setCalendarPopup(True)
        self.date_since.setEnabled(False)
        self.chk_since.toggled.connect(self.date_since.setEnabled)
        self.chk_since.toggled.connect(self._apply_filters)
        left_layout.addWidget(self.chk_since)
        left_layout.addWidget(self.date_since)

        self.chk_before = QCheckBox("Şu tarihten eski:")
        self.chk_before.setStyleSheet("font-weight: bold; color: #1e293b;")
        self.date_before = QDateEdit(QDate.currentDate())
        self.date_before.setCalendarPopup(True)
        self.date_before.setEnabled(False)
        self.chk_before.toggled.connect(self.date_before.setEnabled)
        self.chk_before.toggled.connect(self._apply_filters)
        left_layout.addWidget(self.chk_before)
        left_layout.addWidget(self.date_before)

        left_layout.addSpacing(10)
        btn_reset_filters = QPushButton("🔄 Filtreleri Sıfırla")
        btn_reset_filters.setCursor(Qt.PointingHandCursor)
        btn_reset_filters.setStyleSheet(BTN_STYLE_OUTLINE)
        btn_reset_filters.clicked.connect(self._reset_filters)
        left_layout.addWidget(btn_reset_filters)

        left_layout.addStretch()

        # -------------------------------------------------------------------
        # 2. ORTA PANEL: Arama Girişi & ToyaDbGrid
        # -------------------------------------------------------------------
        center_layout = ws.center_layout

        search_box = QFrame()
        search_box.setStyleSheet("QFrame { background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; }")
        search_bar_layout = QHBoxLayout(search_box)
        search_bar_layout.setContentsMargins(10, 8, 10, 8)
        search_bar_layout.setSpacing(8)

        self.input_query = QLineEdit()
        self.input_query.setPlaceholderText("Metin ara... (Örn: fatura, acil, rapor, 'proje x')")
        self.input_query.setMinimumHeight(34)
        self.input_query.setStyleSheet("font-size: 13px; border: 1px solid #cbd5e1; border-radius: 4px; padding: 4px 8px;")
        search_bar_layout.addWidget(self.input_query, stretch=1)

        self.btn_search = QPushButton("🔍 Ara")
        self.btn_search.setCursor(Qt.PointingHandCursor)
        self.btn_search.setStyleSheet(BTN_STYLE_BLUE)
        self.btn_search.setMinimumHeight(34)
        search_bar_layout.addWidget(self.btn_search)

        self.btn_rebuild = QPushButton("Dizini Yeniden Kur")
        self.btn_rebuild.setCursor(Qt.PointingHandCursor)
        self.btn_rebuild.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_rebuild.setMinimumHeight(34)
        search_bar_layout.addWidget(self.btn_rebuild)

        center_layout.addWidget(search_box)

        # TOYA DBGRID Component (Table + Per-Column Search Row + Pagination Bar)
        self.db_grid = ToyaDbGrid(parent=self, enable_pagination=True)
        self.db_grid.set_columns(self.COLUMNS, self.DEFAULT_WIDTHS)
        self.table = self.db_grid.table

        self.db_grid.filter_bar.filter_changed.connect(self._on_column_filter_changed)
        self.db_grid.page_changed.connect(self._on_page_changed)
        self.db_grid.selection_changed.connect(self._on_table_selection_changed)

        center_layout.addWidget(self.db_grid, stretch=1)

        # -------------------------------------------------------------------
        # 3. SAĞ PANEL: Önizleme & Hızlı Dışa Aktarım İşlemleri
        # -------------------------------------------------------------------
        ws.right_group.setTitle("📧 Önizleme & Dışa Aktar")
        right_layout = ws.right_inner_layout

        self.preview_header_frame = QFrame()
        self.preview_header_frame.setFrameShape(QFrame.StyledPanel)
        self.preview_header_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
            }
            QLabel {
                border: none;
                background: transparent;
                color: #334155;
            }
        """)
        header_grid = QVBoxLayout(self.preview_header_frame)
        header_grid.setContentsMargins(10, 10, 10, 10)
        header_grid.setSpacing(4)

        self.lbl_subject = QLabel("(Konu Yok)")
        self.lbl_subject.setStyleSheet("font-size: 13px; font-weight: bold; color: #1e3a8a;")
        header_grid.addWidget(self.lbl_subject)

        self.lbl_from = QLabel("Kimden: —")
        self.lbl_from.setStyleSheet("font-size: 11px;")
        header_grid.addWidget(self.lbl_from)

        self.lbl_to = QLabel("Kime: —")
        self.lbl_to.setStyleSheet("font-size: 11px;")
        header_grid.addWidget(self.lbl_to)

        self.lbl_date = QLabel("Tarih: —")
        self.lbl_date.setStyleSheet("font-size: 11px;")
        header_grid.addWidget(self.lbl_date)

        preview_toolbar = QHBoxLayout()
        preview_toolbar.setSpacing(6)

        self.btn_save_eml = QPushButton("📥 .EML Dışa Aktar")
        self.btn_save_eml.setCursor(Qt.PointingHandCursor)
        self.btn_save_eml.setStyleSheet(BTN_STYLE_BLUE)
        self.btn_save_eml.setEnabled(False)
        preview_toolbar.addWidget(self.btn_save_eml)

        self.btn_print = QPushButton("🖨️ Yazdır")
        self.btn_print.setCursor(Qt.PointingHandCursor)
        self.btn_print.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_print.setEnabled(False)
        preview_toolbar.addWidget(self.btn_print)

        self.btn_toggle_raw = QPushButton("📄 Ham Kaynak")
        self.btn_toggle_raw.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_raw.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_toggle_raw.setEnabled(False)
        self.btn_toggle_raw.setCheckable(True)
        preview_toolbar.addWidget(self.btn_toggle_raw)

        preview_toolbar.addStretch()
        header_grid.addLayout(preview_toolbar)

        right_layout.addWidget(self.preview_header_frame)

        self.preview_browser = QTextBrowser()
        self.preview_browser.setOpenLinks(False)
        self.preview_browser.setStyleSheet("""
            QTextBrowser {
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                background-color: #ffffff;
                padding: 10px;
                font-size: 11px;
            }
        """)
        right_layout.addWidget(self.preview_browser, stretch=1)

        self.attach_box = QGroupBox("Ekli Dosyalar")
        self.attach_box.setStyleSheet(ws._group_box_style())
        attach_layout = QVBoxLayout(self.attach_box)
        attach_layout.setContentsMargins(8, 8, 8, 8)

        self.attach_list = QListWidget()
        self.attach_list.setMaximumHeight(80)
        self.attach_list.setStyleSheet("border: 1px solid #cbd5e1; border-radius: 4px;")
        attach_layout.addWidget(self.attach_list)

        attach_btns = QHBoxLayout()
        self.btn_open_attach = QPushButton("📂 Aç")
        self.btn_open_attach.setCursor(Qt.PointingHandCursor)
        self.btn_open_attach.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_save_attach = QPushButton("📥 Kaydet")
        self.btn_save_attach.setCursor(Qt.PointingHandCursor)
        self.btn_save_attach.setStyleSheet(BTN_STYLE_BLUE)
        attach_btns.addWidget(self.btn_open_attach)
        attach_btns.addWidget(self.btn_save_attach)
        attach_btns.addStretch()
        attach_layout.addLayout(attach_btns)

        self.attach_box.setVisible(False)
        right_layout.addWidget(self.attach_box)

        # Load persisted layout splitter state
        ws.load_splitter_state(self.settings, "search_workspace")
        ws.splitter.splitterMoved.connect(lambda *args: (ws.save_splitter_state(self.settings, "search_workspace"), self.db_grid.filter_bar.adjust_positions()))

        def _on_search_panel_toggled(panel_name: str, visible: bool):
            self.settings.set(f"search_{panel_name}_visible", visible)
            self.settings.save()
            ws.save_splitter_state(self.settings, "search_workspace")
            self.db_grid.filter_bar.adjust_positions()

        ws.panel_toggled.connect(_on_search_panel_toggled)

        # Connections
        self.btn_search.clicked.connect(self._search)
        self.btn_rebuild.clicked.connect(self._rebuild_index)
        self.input_query.returnPressed.connect(self._search)
        
        self.btn_save_eml.clicked.connect(self._save_eml)
        self.btn_print.clicked.connect(self._print_mail)
        self.btn_toggle_raw.toggled.connect(self._toggle_raw_mode)

        self.btn_open_attach.clicked.connect(self._open_selected_attachment)
        self.btn_save_attach.clicked.connect(self._save_selected_attachment)

    # ------------------------------------------------------------------
    # Data loading / Refresh account filters
    # ------------------------------------------------------------------

    def refresh(self):
        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_reading"):
            parent_mw.notify_disk_reading("💾 Disk Okunuyor", "Arama filtreleri ve hesap klasörleri taranıyor...")

        if self._loader_worker and self._loader_worker.isRunning():
            self._loader_worker.quit()
            self._loader_worker.wait()

        account_id = self.combo_account.currentData() if hasattr(self, "combo_account") else None
        sel_domain = self.combo_domain.currentData() if hasattr(self, "combo_domain") else None

        self._loader_worker = SearchDataLoaderWorker(self.engine, account_id, sel_domain, self)
        self._loader_worker.data_loaded_signal.connect(self._on_filters_loaded)
        self._loader_worker.start()

    @Slot(object, object, object, object)
    def _on_filters_loaded(self, accounts: list, domains: list, folders: list, mail_counts: dict = None):
        self._all_accounts = accounts
        self._accounts_by_id = {a["id"]: a for a in accounts if "id" in a}
        self._account_mail_counts = mail_counts or {}

        self.combo_domain.blockSignals(True)
        cur_dom = self.combo_domain.currentData()
        self.combo_domain.clear()
        self.combo_domain.addItem("🌐 Tüm Domainler", None)
        for d in domains:
            self.combo_domain.addItem(f"🌐 {d}", d)
        if cur_dom is not None:
            idx = self.combo_domain.findData(cur_dom)
            if idx >= 0:
                self.combo_domain.setCurrentIndex(idx)
        self.combo_domain.blockSignals(False)

        self._populate_accounts_for_current_domain()
        self._populate_folder_items(folders)

        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_ready"):
            parent_mw.notify_disk_ready("Arama filtreleri ve hesaplar hazır.")

        self._search()

    def _populate_accounts_for_current_domain(self):
        """Filters self.combo_account to show only accounts for the currently selected domain."""
        if not hasattr(self, "combo_account") or not hasattr(self, "combo_domain"):
            return

        sel_domain = self.combo_domain.currentData()
        cur_acc = self.combo_account.currentData()

        # Filter accounts matching selected domain
        matching_accounts = []
        for acc in self._all_accounts:
            email_str = acc.get("email", "")
            dom = email_str.split("@")[-1].strip().lower() if "@" in email_str else (acc.get("account_group", "").strip() or "Diğer")
            if not sel_domain or dom == sel_domain.lower():
                matching_accounts.append(acc)

        self.combo_account.blockSignals(True)
        self.combo_account.clear()
        
        if sel_domain:
            self.combo_account.addItem(f"👤 Tüm Hesaplar ({len(matching_accounts)})", None)
        else:
            self.combo_account.addItem("👤 Tüm Hesaplar", None)

        for acc in matching_accounts:
            acc_id = acc.get("id")
            email_str = acc.get("email", "")
            lbl = acc.get("label", "").strip()
            mail_cnt = self._account_mail_counts.get(acc_id, 0)
            status_prefix = "⚠️ " if mail_cnt == 0 else "👤 "
            if lbl and lbl.lower() != email_str.lower():
                display_label = f"{status_prefix}{lbl} <{email_str}>"
            else:
                display_label = f"{status_prefix}{email_str or f'Hesap #{acc_id}'}"
            if mail_cnt == 0:
                display_label += " (Senkronize Edilmedi)"
            self.combo_account.addItem(display_label, acc_id)

        # Restore previously selected account if it belongs to this domain
        if cur_acc is not None:
            idx = self.combo_account.findData(cur_acc)
            if idx >= 0:
                self.combo_account.setCurrentIndex(idx)
            else:
                self.combo_account.setCurrentIndex(0)
        else:
            self.combo_account.setCurrentIndex(0)

        self.combo_account.blockSignals(False)

    def _populate_folder_items(self, folders: list):
        if not hasattr(self, "combo_folder"):
            return
        model = self.combo_folder.model()
        model.clear()
        for orig_folder, display_name in folders:
            item = QStandardItem(display_name)
            item.setData(orig_folder, Qt.UserRole)
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            standard_keywords = ["inbox", "sent", "draft", "spam", "junk", "trash", "archive", 
                               "gelen", "giden", "gönderilen", "taslak", "çöp", "arşiv", "istenmeyen"]
            is_standard = any(w in display_name.lower() for w in standard_keywords)
            item.setCheckState(Qt.Checked if is_standard else Qt.Unchecked)
            model.appendRow(item)
        self.combo_folder._update_display_text()

    @Slot()
    def _on_domain_filter_changed(self):
        self._populate_accounts_for_current_domain()
        self._load_folders_for_selected_account()
        self._search()

    @Slot()
    def _on_account_filter_changed(self):
        account_id = self.combo_account.currentData() if hasattr(self, "combo_account") else None
        if account_id:
            mail_cnt = self._account_mail_counts.get(account_id, 0)
            if mail_cnt == 0:
                acc = self._accounts_by_id.get(account_id, {})
                label = acc.get("label") or acc.get("email") or f"Hesap #{account_id}"
                email_str = acc.get("email", "")
                reply = QMessageBox.question(
                    self,
                    "⚠️ E-Postalar Senkronize Edilmemiş",
                    f"'{label}' ({email_str}) hesabı ile ilgili mailler henüz sunucudan senkronize edilmemiştir.\n\n"
                    "Arama yapabilmek ve e-postaları arşive dahil etmek için şimdi senkronizasyon (eşitleme) işlemini başlatmak ister misiniz?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    parent_mw = self.window()
                    if parent_mw and hasattr(parent_mw, "_navigate"):
                        parent_mw._navigate("sync")
                        return

        self._load_folders_for_selected_account()
        self._search()

    def _load_folders_for_selected_account(self):
        account_id = self.combo_account.currentData() if hasattr(self, "combo_account") else None
        sel_domain = self.combo_domain.currentData() if hasattr(self, "combo_domain") else None

        if self._loader_worker and self._loader_worker.isRunning():
            self._loader_worker.quit()
            self._loader_worker.wait()

        self._loader_worker = SearchDataLoaderWorker(self.engine, account_id, sel_domain, self)
        self._loader_worker.data_loaded_signal.connect(lambda accs, doms, flds, counts: self._populate_folder_items(flds))
        self._loader_worker.start()

    def _select_all_folders(self):
        if hasattr(self, "combo_folder"):
            self.combo_folder.set_all_checked(True)
            self._search()

    def _clear_all_folders(self):
        if hasattr(self, "combo_folder"):
            self.combo_folder.set_all_checked(False)
            self._search()

    def _get_selected_folders(self) -> Optional[List[str]]:
        if not hasattr(self, "combo_folder"):
            return None
        checked = self.combo_folder.get_checked_items()
        total = self.combo_folder.model().rowCount()
        if total == 0 or len(checked) == total or len(checked) == 0:
            return None
        return checked

    @Slot()
    def _apply_filters(self):
        self._search()

    @Slot()
    def _reset_filters(self):
        self.combo_domain.blockSignals(True)
        self.combo_account.blockSignals(True)
        
        self.combo_domain.setCurrentIndex(0)
        self._populate_accounts_for_current_domain()
        self.combo_account.setCurrentIndex(0)
        self.combo_attachments.setCurrentIndex(0)
        self.combo_read.setCurrentIndex(0)
        self.chk_since.setChecked(False)
        self.chk_before.setChecked(False)
        self.input_query.clear()

        self.combo_domain.blockSignals(False)
        self.combo_account.blockSignals(False)

        self._load_folders_for_selected_account()
        self._search()

    # ------------------------------------------------------------------
    # Search implementation & Pagination Slicing
    # ------------------------------------------------------------------

    @Slot()
    def _search(self):
        query = self.input_query.text().strip()
        
        account_id = self.combo_account.currentData() if hasattr(self, "combo_account") else None
        folder = self._get_selected_folders()
        
        since_date = None
        if hasattr(self, "chk_since") and self.chk_since.isChecked():
            since_date = self.date_since.date().toString("yyyy-MM-dd 00:00:00")
            
        before_date = None
        if hasattr(self, "chk_before") and self.chk_before.isChecked():
            before_date = self.date_before.date().toString("yyyy-MM-dd 23:59:59")

        att_idx = self.combo_attachments.currentIndex() if hasattr(self, "combo_attachments") else 0
        has_attachments = None
        if att_idx == 1:
            has_attachments = True
        elif att_idx == 2:
            has_attachments = False

        read_idx = self.combo_read.currentIndex() if hasattr(self, "combo_read") else 0
        unread_only = None
        if read_idx == 1:
            unread_only = True
        elif read_idx == 2:
            unread_only = False

        sel_domain = self.combo_domain.currentData() if hasattr(self, "combo_domain") else None

        search_params = {
            "query": query,
            "limit": 1000,
            "account_id": account_id,
            "folder": folder,
            "since_date": since_date,
            "before_date": before_date,
            "has_attachments": has_attachments,
            "unread_only": unread_only,
            "sel_domain": sel_domain,
        }

        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_reading"):
            parent_mw.notify_disk_reading("💾 Disk Okunuyor", "FTS5 arama veritabanında taranıyor...")

        if hasattr(self, "btn_search"):
            self.btn_search.setEnabled(False)
            self.btn_search.setText("⏳ Aranıyor...")

        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.quit()
            self._search_worker.wait()

        self._search_worker = SearchExecutionWorker(self.engine, search_params, self)
        self._search_worker.results_ready_signal.connect(self._on_search_results_ready)
        self._search_worker.error_signal.connect(self._on_search_error)
        self._search_worker.start()

    @Slot(list)
    def _on_search_results_ready(self, results: list):
        if hasattr(self, "btn_search"):
            self.btn_search.setEnabled(True)
            self.btn_search.setText("🔍 Ara")

        self._all_results = results
        
        self.table.blockSignals(True)
        self.table.setRowCount(len(results))

        for i, r in enumerate(results):
            # Column 0: Date
            date_val = (r.get("date") or "")[:19]
            self.table.setItem(i, 0, QTableWidgetItem(date_val))

            # Column 1: Account
            acc_id = r.get("account_id")
            acc_label = f"#{acc_id}" if acc_id else "—"
            acc = self._accounts_by_id.get(acc_id) if acc_id else None
            if acc:
                email_str = acc.get("email", "").strip()
                lbl = acc.get("label", "").strip()
                if lbl and lbl.lower() != email_str.lower():
                    acc_label = f"{lbl} <{email_str}>"
                else:
                    acc_label = email_str or acc_label
            self.table.setItem(i, 1, QTableWidgetItem(acc_label))

            # Column 2: Sender
            self.table.setItem(i, 2, QTableWidgetItem(r.get("sender") or ""))

            # Column 3: Recipients
            self.table.setItem(i, 3, QTableWidgetItem(r.get("recipients") or ""))

            # Column 4: Subject
            self.table.setItem(i, 4, QTableWidgetItem(r.get("subject") or "(Konu Yok)"))

            # Column 5: Folder
            self.table.setItem(i, 5, QTableWidgetItem(r.get("folder", "")))

            # Column 6: Size
            size_str = self._fmt_size(r.get("size_bytes", 0))
            self.table.setItem(i, 6, QTableWidgetItem(size_str))

            # Column 7: Attachment
            has_att = bool(r.get("has_attachments", 0))
            att_item = QTableWidgetItem("📎" if has_att else "")
            att_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 7, att_item)

            # Store metadata dictionary on row items
            for col in range(len(self.COLUMNS)):
                item = self.table.item(i, col)
                if item:
                    item.setData(Qt.UserRole, r)

        self.table.blockSignals(False)
        self.db_grid._apply_row_filters()

        if results:
            self.table.selectRow(0)
            self._on_table_selection_changed()
        else:
            self._clear_preview()

        parent_mw = self.window()
        if parent_mw and hasattr(parent_mw, "notify_disk_ready"):
            parent_mw.notify_disk_ready(f"{len(results)} e-posta bulundu.", auto_dismiss_seconds=3)

    @Slot(int, str)
    def _on_column_filter_changed(self, col_idx: int, filter_text: str):
        pass

    @Slot(int, int)
    def _on_page_changed(self, current_page: int, page_size: int):
        pass

    @Slot(str)
    def _on_search_error(self, err_msg: str):
        if hasattr(self, "btn_search"):
            self.btn_search.setEnabled(True)
            self.btn_search.setText("🔍 Ara")
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Arama Hatası")
        msg.setText(f"Arama işlemi gerçekleştirilirken bir hata oluştu:\n\n{err_msg}")
        msg.setStyleSheet(GLOBAL_MSG_STYLE)
        msg.exec()

    @Slot()
    def _rebuild_index(self):
        try:
            self.engine.db.rebuild_fts_index()
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Information)
            msg.setWindowTitle("Başarılı")
            msg.setText("FTS5 Arama İndeksi başarıyla yeniden oluşturuldu.")
            msg.setStyleSheet(GLOBAL_MSG_STYLE)
            msg.exec()
        except Exception as exc:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("Hata")
            msg.setText(str(exc))
            msg.setStyleSheet(GLOBAL_MSG_STYLE)
            msg.exec()

    # ------------------------------------------------------------------
    # Selection & Preview Renderer
    # ------------------------------------------------------------------

    def _clear_preview(self):
        self.lbl_subject.setText("(Konu Yok)")
        self.lbl_from.setText("Kimden: —")
        self.lbl_to.setText("Kime: —")
        self.lbl_date.setText("Tarih: —")
        self.preview_browser.clear()
        self.attach_box.setVisible(False)
        self.btn_save_eml.setEnabled(False)
        self.btn_print.setEnabled(False)
        self.btn_toggle_raw.setEnabled(False)
        self._current_attachments.clear()

    @Slot()
    def _on_table_selection_changed(self):
        row = self.table.currentRow()
        if row < 0 or row >= self.table.rowCount():
            self._clear_preview()
            return

        item = self.table.item(row, 0)
        if not item:
            return

        r = item.data(Qt.UserRole)
        if not r:
            return

        self._load_mail_preview(r)

    def _load_mail_preview(self, r: dict):
        self.btn_save_eml.setEnabled(True)
        self.btn_print.setEnabled(True)
        self.btn_toggle_raw.setEnabled(True)
        self._current_attachments.clear()

        # Update headers
        self.lbl_subject.setText(r.get("subject") or "(Konu Yok)")
        self.lbl_from.setText(f"Kimden:  <b>{r.get('sender', '—')}</b>")
        self.lbl_to.setText(f"Kime:    {r.get('recipients', '—')}")
        self.lbl_date.setText(f"Tarih:   {r.get('date', '—')}")

        if self._raw_mode:
            self._show_raw(r["id"])
            return

        # Fetch Raw Message body
        raw_data = None
        try:
            raw_data = self.engine.mails.get_raw(r["id"])
        except Exception:
            pass

        if raw_data:
            try:
                msg = email.message_from_bytes(raw_data)
                self._render_message(msg)
            except Exception as e:
                self.preview_browser.setHtml(f"<p style='color:red;'>Ham e-posta ayrıştırılamadı: {e}</p>")
        else:
            self.preview_browser.setHtml(
                "<div style='text-align:center;padding:40px;color:#64748b;'>"
                "<h3>⚠️ E-Posta Önizlemesi Çevrimdışı</h3>"
                "<p>Bu e-postanın tam gövde metni ve ekleri arşiv diskinde saklanmaktadır.<br/>"
                "İçeriği görüntülemek için lütfen yapılandırılmış harici yedekleme diskinizi takınız.</p>"
                "</div>"
            )

    def _render_message(self, msg):
        html_parts = []
        text_parts = []
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disp = str(part.get("Content-Disposition", ""))
                
                # Check if it's attachment
                if "attachment" in content_disp or (part.get_filename() and content_type not in ("text/plain", "text/html")):
                    attachments.append(self._extract_attachment_info(part))
                    continue
                    
                payload = self._decode_payload(part)
                if payload is not None:
                    if content_type == "text/html":
                        html_parts.append(payload)
                    elif content_type == "text/plain":
                        text_parts.append(payload)
        else:
            content_type = msg.get_content_type()
            payload = self._decode_payload(msg)
            if payload:
                if content_type == "text/html":
                    html_parts.append(payload)
                else:
                    text_parts.append(payload)

        # Populate preview browser
        if html_parts:
            html_body = "<hr>".join(html_parts)
            self.preview_browser.setHtml(html_body)
        elif text_parts:
            text_body = "\n\n".join(text_parts)
            escaped = text_body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            self.preview_browser.setHtml(f"<pre style='font-family:inherit;white-space:pre-wrap;'>{escaped}</pre>")
        else:
            self.preview_browser.setHtml("<p style='color:#999; font-style:italic;'>İçerik bulunamadı.</p>")

        # Populate attachments widget
        if attachments:
            self._current_attachments = attachments
            self.attach_box.setVisible(True)
            self.attach_list.clear()
            for a in attachments:
                size_str = self._fmt_size(a["size"])
                item = QListWidgetItem(f"📎  {a['filename']}  ({size_str})")
                item.setData(Qt.UserRole, a)
                self.attach_list.addItem(item)
            self.attach_list.setCurrentRow(0)
        else:
            self.attach_box.setVisible(False)

    def _show_raw(self, mail_id: int):
        raw_data = None
        try:
            raw_data = self.engine.mails.get_raw(mail_id)
        except Exception:
            pass
        if raw_data:
            try:
                text = raw_data.decode("utf-8", errors="replace")
            except Exception:
                text = str(raw_data)
            self.preview_browser.setPlainText(text[:60000])
        else:
            self.preview_browser.setPlainText("Ham veri bulunamadı (Yedekleme diski takılı olmayabilir).")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @Slot()
    def _save_eml(self):
        row = self.table.currentRow()
        if row < 0 or row >= self.table.rowCount():
            return
        item = self.table.item(row, 0)
        if not item:
            return
        r = item.data(Qt.UserRole)
        if not r:
            return

        try:
            raw_data = self.engine.mails.get_raw(r["id"])
            if not raw_data:
                disk_str = self.settings.configured_data_path_str()
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Warning)
                msg.setWindowTitle("Ham Veri Bulunamadı")
                msg.setText(
                    f"E-postanın ham içeriği (.eml) yerel veritabanında veya arşiv diskinde bulunamadı.\n\n"
                    f"Arşiv diskiniz (<b>{disk_str}</b>) takılı değil veya e-posta gövdesi henüz senkronize edilmemiş olabilir."
                )
                msg.setStyleSheet(GLOBAL_MSG_STYLE)
                msg.exec()
                return

            cleaned_subj = re.sub(r'[\\/*?:"<>|]', "", r.get("subject") or "mail")[:50]
            default_name = f"{r.get('uid', 'mail')}_{cleaned_subj}.eml"

            path, _ = QFileDialog.getSaveFileName(
                self, "E-postayı EML Olarak Kaydet", default_name, "EML Dosyaları (*.eml);;Tüm Dosyalar (*.*)"
            )
            if path:
                Path(path).write_bytes(raw_data)
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Information)
                msg.setWindowTitle("Başarılı")
                msg.setText("E-posta (.eml) başarıyla dışa aktarıldı.")
                msg.setStyleSheet(GLOBAL_MSG_STYLE)
                msg.exec()
        except Exception as e:
            logger.exception("EML export error: %s", e)
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("Kaydetme Başarısız")
            msg.setText(f"E-posta kaydedilirken bir hata oluştu:\n{e}")
            msg.setStyleSheet(GLOBAL_MSG_STYLE)
            msg.exec()

    @Slot()
    def _print_mail(self):
        try:
            from PySide6.QtPrintSupport import QPrinter, QPrintDialog
            printer = QPrinter()
            dialog = QPrintDialog(printer, self)
            dialog.setStyleSheet(GLOBAL_MSG_STYLE)
            if dialog.exec() == QPrintDialog.Accepted:
                self.preview_browser.print_(printer)
        except Exception as e:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("Yazdırma Hatası")
            msg.setText(f"Yazdırılamadı:\n{e}")
            msg.setStyleSheet(GLOBAL_MSG_STYLE)
            msg.exec()

    @Slot(bool)
    def _toggle_raw_mode(self, checked: bool):
        self._raw_mode = checked
        row = self.table.currentRow()
        if row >= 0 and row < self.table.rowCount():
            item = self.table.item(row, 0)
            if item:
                r = item.data(Qt.UserRole)
                if r:
                    self._load_mail_preview(r)

    @Slot()
    def _open_selected_attachment(self):
        item = self.attach_list.currentItem()
        if not item:
            return
        att = item.data(Qt.UserRole)
        try:
            temp_dir = Path(tempfile.gettempdir()) / "mail_archive_temp"
            temp_dir.mkdir(exist_ok=True)
            temp_file = temp_dir / att["filename"]
            temp_file.write_bytes(att["data"])
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(temp_file)))
        except Exception as e:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("Hata")
            msg.setText(f"Dosya açılamadı:\n{e}")
            msg.setStyleSheet(GLOBAL_MSG_STYLE)
            msg.exec()

    @Slot()
    def _save_selected_attachment(self):
        item = self.attach_list.currentItem()
        if not item:
            return
        att = item.data(Qt.UserRole)
        path, _ = QFileDialog.getSaveFileName(self, "Eki Kaydet", att["filename"], "*.*")
        if path:
            try:
                Path(path).write_bytes(att["data"])
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Information)
                msg.setWindowTitle("Başarılı")
                msg.setText("Ek başarıyla kaydedildi.")
                msg.setStyleSheet(GLOBAL_MSG_STYLE)
                msg.exec()
            except Exception as e:
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Critical)
                msg.setWindowTitle("Hata")
                msg.setText(str(e))
                msg.setStyleSheet(GLOBAL_MSG_STYLE)
                msg.exec()

    # ------------------------------------------------------------------
    # Static Parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_payload(part) -> Optional[str]:
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                return None
            charset = part.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
        except Exception:
            return None

    @staticmethod
    def _extract_attachment_info(part) -> Dict:
        filename = part.get_filename() or "unnamed"
        try:
            decoded = decode_header(filename)
            filename = "".join(
                p.decode(e or "utf-8", errors="replace") if isinstance(p, bytes) else p
                for p, e in decoded
            )
        except Exception:
            pass
        payload = part.get_payload(decode=True)
        size = len(payload) if payload else 0
        return {
            "filename": filename,
            "mime_type": part.get_content_type(),
            "size": size,
            "data": payload,
        }

    @staticmethod
    def _fmt_size(size: int) -> str:
        if not size:
            return "0 B"
        for unit in ["B", "KB", "MB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.2f} GB"
