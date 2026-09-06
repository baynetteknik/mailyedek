"""
export_panel.py — Email export & server migration panel with detailed logging,
asynchronous (lazy load) disk & database scanner, multi-account background workers,
live row progress bars, view profiles, and comprehensive reporting.
"""

import os
import re
import imaplib
import logging
import threading
import time
from typing import Optional, Any, Dict, List
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    Qt, Slot, Signal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
    QDate, QObject, QEventLoop, QThread, QPoint, QTimer, QSize
)
from PySide6.QtGui import QFont, QColor, QIcon, QAction, QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QGroupBox, QMessageBox, QListWidget, QListWidgetItem,
    QAbstractItemView, QFrame, QTableView, QComboBox, QLineEdit,
    QDialog, QDialogButtonBox, QCheckBox, QDateEdit, QTextEdit,
    QSpinBox, QMenu, QScrollArea, QApplication, QInputDialog, QFileDialog
)

from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.widgets.view_profile_widget import ViewProfileWidget, SaveLayoutProfileDialog, ColumnManagerDialog
from gui.widgets.account_group_sidebar_widget import AccountGroupSidebarWidget, CollapsibleSection
from gui.widgets.export_right_sidebar_widget import ExportRightSidebarWidget
from infrastructure.imap_client import format_folder_display_name, decode_imap_utf7

logger = logging.getLogger(__name__)

GLOBAL_MSG_STYLE = """
    QMessageBox, QDialog, QProgressDialog {
        background-color: #f8fafc;
        color: #0f172a;
    }
    QMessageBox QLabel, QInputDialog QLabel, QProgressDialog QLabel {
        color: #0f172a;
        font-weight: 500;
        font-size: 13px;
    }
    QMessageBox QPushButton, QDialog QPushButton {
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
    QMessageBox QPushButton:hover, QDialog QPushButton:hover {
        background-color: #1d4ed8;
    }
"""


# ---------------------------------------------------------------------------
# Structured log entry model
# ---------------------------------------------------------------------------

class LogEntry:
    __slots__ = ('time', 'level', 'source', 'message')

    def __init__(self, time: str, level: str, source: str, message: str):
        self.time = time
        self.level = level
        self.source = source
        self.message = message


class LogTableModel(QAbstractTableModel):
    COLUMNS = ["Saat", "Seviye", "Kaynak", "Mesaj"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[LogEntry] = []

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

    def append_entry(self, entry: LogEntry):
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
# Proxy model with text filtering + pagination
# ---------------------------------------------------------------------------

class LogFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_text = ""
        self._page = 0
        self._page_size = 50
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setFilterKeyColumn(-1)

    def set_filter_text(self, text: str):
        self._filter_text = text
        self.invalidateFilter()
        self._page = 0

    def set_page_size(self, size: int):
        self._page_size = size
        self._page = 0
        self.invalidateFilter()

    def total_pages(self) -> int:
        total = self.sourceModel().rowCount() if self.sourceModel() else 0
        if total == 0:
            return 1
        return (total + self._page_size - 1) // self._page_size

    def current_page(self) -> int:
        return self._page

    def set_page(self, page: int):
        total = self.total_pages()
        self._page = max(0, min(page, total - 1))
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        if self._filter_text:
            model = self.sourceModel()
            if model:
                found = False
                for col in range(model.columnCount()):
                    idx = model.index(source_row, col, source_parent)
                    val = idx.data(Qt.DisplayRole) or ""
                    if self._filter_text.lower() in str(val).lower():
                        found = True
                        break
                if not found:
                    return False
        return source_row // self._page_size == self._page


# ---------------------------------------------------------------------------
# Stat card widget
# ---------------------------------------------------------------------------

class StatCard(QFrame):
    def __init__(self, title: str, value: str = "—", icon: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            StatCard {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 4px;
            }
        """)
        self.setMinimumHeight(64)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        
        self.title_label = QLabel(f"{icon} {title}" if icon else title)
        self.title_label.setStyleSheet(
            "font-size: 10.5px; color: #64748b; font-weight: 600; border: none;"
        )
        self.title_label.setAlignment(Qt.AlignCenter)
        
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(
            "font-size: 14px; font-weight: 700; color: #1e293b; border: none;"
        )
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setWordWrap(True)
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, val: str):
        self.value_label.setText(val)


# ---------------------------------------------------------------------------
# Asynchronous Lazy Load Worker for Database Stats
# ---------------------------------------------------------------------------

class ExportDataLoaderWorker(QThread):
    """Background worker to query folder and email statistics without freezing GUI."""
    progress_signal = Signal(int, int)  # current, total
    account_loaded_signal = Signal(int, int, int)  # account_id, mails_cnt, folders_cnt
    finished_signal = Signal(object)  # all stats dict

    def __init__(self, engine: MailEngine, account_ids: List[int], parent=None):
        super().__init__(parent)
        self.engine = engine
        self.account_ids = account_ids

    def run(self):
        results = {}
        total = len(self.account_ids)
        try:
            with self.engine.db.get_conn() as conn:
                for idx, aid in enumerate(self.account_ids):
                    self.progress_signal.emit(idx + 1, total)
                    try:
                        row_m = conn.execute(
                            "SELECT COUNT(*) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (aid,)
                        ).fetchone()
                        m_cnt = row_m["cnt"] if row_m else 0
                        row_f = conn.execute(
                            "SELECT COUNT(DISTINCT folder) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (aid,)
                        ).fetchone()
                        f_cnt = row_f["cnt"] if row_f else 0
                        results[aid] = {"mails": m_cnt, "folders": f_cnt}
                        self.account_loaded_signal.emit(aid, m_cnt, f_cnt)
                    except Exception:
                        results[aid] = {"mails": 0, "folders": 0}
        except Exception as e:
            logger.debug("ExportDataLoaderWorker DB read exception: %s", e)
        finally:
            self.finished_signal.emit(results)


# ---------------------------------------------------------------------------
# Export Reports popup dialog
# ---------------------------------------------------------------------------

class ExportReportsDialog(QDialog):
    def __init__(self, reports: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dışa Aktarım ve Sunucu Göçü Sonuç Raporları")
        self.resize(920, 560)
        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
            }
            QLabel {
                color: #1e293b;
            }
            QFrame {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
            }
            QTableWidget {
                color: #1e293b;
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                gridline-color: #f1f5f9;
                border-radius: 6px;
            }
            QHeaderView::section {
                background-color: #1e3a8a;
                color: #ffffff !important;
                font-weight: bold;
                padding: 8px;
                border: 1px solid #1e40af;
                font-size: 11px;
            }
            QPushButton {
                background-color: #2563eb;
                color: white;
                font-weight: 600;
                padding: 8px 20px;
                border-radius: 6px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        
        header_title = QLabel("📊 E-Posta Dışa Aktarım ve Sunucu Göçü Raporu")
        header_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        header_title.setStyleSheet("color: #0f172a;")
        layout.addWidget(header_title)
        
        total_accounts = len(reports)
        total_exported = 0
        total_errors = 0
        total_bytes = 0
        
        for r in reports:
            def g(k, d=None):
                return r.get(k, d) if isinstance(r, dict) else getattr(r, k, d)
            total_exported += g("exported", 0) or g("mails_exported", 0)
            total_errors += g("errors", 0)
            total_bytes += g("total_bytes", 0) or g("size_bytes", 0)
            
        summary_layout = QHBoxLayout()
        summary_layout.setSpacing(10)
        
        cards_data = [
            ("Toplam Hesap", str(total_accounts), "#2563eb"),
            ("Aktarılan İletiler", str(total_exported), "#10b981"),
            ("Hatalar", str(total_errors), "#ef4444" if total_errors > 0 else "#64748b"),
            ("Toplam Boyut", self._fmt_bytes(total_bytes), "#7c3aed")
        ]
        
        for label_text, val_text, color in cards_data:
            card = QFrame()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(2)
            
            lbl_title = QLabel(label_text.upper())
            lbl_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
            lbl_title.setStyleSheet("color: #64748b; background: transparent;")
            lbl_title.setAlignment(Qt.AlignCenter)
            
            lbl_val = QLabel(val_text)
            lbl_val.setFont(QFont("Segoe UI", 15, QFont.Bold))
            lbl_val.setStyleSheet(f"color: {color}; background: transparent;")
            lbl_val.setAlignment(Qt.AlignCenter)
            
            card_layout.addWidget(lbl_title)
            card_layout.addWidget(lbl_val)
            summary_layout.addWidget(card)
            
        layout.addLayout(summary_layout)
        
        table = QTableWidget()
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels([
            "Hesap Adı", "Biçim / Hedef", "Aktarılan E-Posta", "Hatalar", "Veri Boyutu", "Süre"
        ])
        
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for col in range(2, 6):
            table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
            
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setRowCount(len(reports))
        
        for i, r in enumerate(reports):
            def g(k, d=None):
                return r.get(k, d) if isinstance(r, dict) else getattr(r, k, d)
                
            item_lbl = QTableWidgetItem(str(g("account_label", "") or g("label", "")))
            item_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
            table.setItem(i, 0, item_lbl)
            
            target_info = str(g("target_path", "") or g("format", ""))
            item_tgt = QTableWidgetItem(target_info)
            table.setItem(i, 1, item_tgt)
            
            exported = g("exported", 0) or g("mails_exported", 0)
            item_exp = QTableWidgetItem(str(exported))
            if exported > 0:
                item_exp.setForeground(QColor("#10b981"))
                item_exp.setFont(QFont("Segoe UI", 10, QFont.Bold))
            item_exp.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 2, item_exp)
            
            errors = g("errors", 0)
            item_errors = QTableWidgetItem(str(errors))
            if errors > 0:
                item_errors.setForeground(QColor("#ef4444"))
                item_errors.setFont(QFont("Segoe UI", 10, QFont.Bold))
            item_errors.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 3, item_errors)
            
            bv = g("total_bytes", 0) or g("size_bytes", 0)
            item_bytes = QTableWidgetItem(self._fmt_bytes(bv))
            item_bytes.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 4, item_bytes)
            
            dur = g("duration_seconds", 0)
            item_dur = QTableWidgetItem(f"{dur:.1f}s")
            item_dur.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 5, item_dur)
            
        layout.addWidget(table)

        btn_box = QDialogButtonBox(QDialogButtonBox.Close)
        btn_box.rejected.connect(self.accept)
        layout.addWidget(btn_box)

    @staticmethod
    def _fmt_bytes(size: int) -> str:
        for unit in ["B", "KB", "MB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.2f} GB"


# ---------------------------------------------------------------------------
# Dynamic Export Configuration Dialog (Pop-up)
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
                color: #2563eb;
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
                border: 1px solid #2563eb;
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # 1. Profile Manager Header
        prof_frame = QFrame()
        prof_frame.setStyleSheet("background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 4px;")
        prof_layout = QHBoxLayout(prof_frame)
        prof_layout.setContentsMargins(8, 6, 8, 6)
        
        lbl_prof = QLabel("Profil Seç:")
        self.combo_profile = QComboBox()
        self.combo_profile.setMinimumWidth(200)
        self.combo_profile.currentIndexChanged.connect(self._on_profile_selection_changed)
        
        self.input_profile_name = QLineEdit()
        self.input_profile_name.setPlaceholderText("Yeni Profil Adı...")
        
        self.btn_save_profile = QPushButton("💾 Profili Kaydet")
        self.btn_save_profile.setStyleSheet("background-color: #2563eb; color: white;")
        self.btn_save_profile.clicked.connect(self._save_current_profile)

        self.btn_copy_profile = QPushButton("📋 Kopyasını Oluştur")
        self.btn_copy_profile.clicked.connect(self._copy_current_profile)

        self.btn_delete_profile = QPushButton("🗑️ Profili Sil")
        self.btn_delete_profile.setStyleSheet("background-color: #fee2e2; color: #dc2626; border-color: #fca5a5;")
        self.btn_delete_profile.clicked.connect(self._delete_selected_profile)

        prof_layout.addWidget(lbl_prof)
        prof_layout.addWidget(self.combo_profile)
        prof_layout.addWidget(self.input_profile_name)
        prof_layout.addWidget(self.btn_save_profile)
        prof_layout.addWidget(self.btn_copy_profile)
        prof_layout.addWidget(self.btn_delete_profile)
        prof_layout.addStretch()
        layout.addWidget(prof_frame)

        # 2. Main Config Splitter
        main_split = QHBoxLayout()
        main_split.setSpacing(12)

        # Left Column: Format & Filters
        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        format_group = QGroupBox("1. Dışa Aktarım Biçimi ve Hedef Dizin")
        fg_layout = QVBoxLayout(format_group)
        
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Format:"))
        self.combo_format = QComboBox()
        self.combo_format.addItem("📦 ZIP Arşivi (.zip)", "ZIP")
        self.combo_format.addItem("📁 Dizin / EML Klasörleri", "DIRECTORY")
        self.combo_format.addItem("📄 JSON Veri Dosyası (.json)", "JSON")
        self.combo_format.addItem("📬 Standart MBOX (.mbox)", "MBOX")
        self.combo_format.addItem("🗃️ Outlook PST (.pst)", "PST")
        self.combo_format.addItem("🌐 IMAP Sunucu Göçü (Doğrudan)", "IMAP_SERVER")
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)
        fmt_row.addWidget(self.combo_format, 1)
        fg_layout.addLayout(fmt_row)

        path_row = QHBoxLayout()
        self.path_label = QLabel("Hedef Dizin / Dosya:")
        self.input_path = QLineEdit()
        self.input_path.setText(str(Path("data/exports").resolve()))
        self.btn_browse = QPushButton("Gözat...")
        self.btn_browse.clicked.connect(self._on_browse)
        path_row.addWidget(self.path_label)
        path_row.addWidget(self.input_path, 1)
        path_row.addWidget(self.btn_browse)
        fg_layout.addLayout(path_row)

        left_col.addWidget(format_group)

        # Filter Group
        filter_group = QGroupBox("2. Zaman ve Durum Filtreleri")
        flt_layout = QVBoxLayout(filter_group)
        
        d_row = QHBoxLayout()
        self.chk_since = QCheckBox("Başlangıç Tarihi:")
        self.date_since = QDateEdit()
        self.date_since.setCalendarPopup(True)
        self.date_since.setDate(QDate.currentDate().addMonths(-6))
        self.date_since.setEnabled(False)
        self.chk_since.toggled.connect(self.date_since.setEnabled)
        d_row.addWidget(self.chk_since)
        d_row.addWidget(self.date_since)

        self.chk_before = QCheckBox("Bitiş Tarihi:")
        self.date_before = QDateEdit()
        self.date_before.setCalendarPopup(True)
        self.date_before.setDate(QDate.currentDate())
        self.date_before.setEnabled(False)
        self.chk_before.toggled.connect(self.date_before.setEnabled)
        d_row.addWidget(self.chk_before)
        d_row.addWidget(self.date_before)
        flt_layout.addLayout(d_row)

        left_col.addWidget(filter_group)

        # Folder selection
        folder_group = QGroupBox("3. Klasör Seçimi")
        fld_layout = QVBoxLayout(folder_group)
        
        self.lbl_folder_summary = QLabel("Arşivlenecek Klasörler: Tümü Seçili")
        fld_layout.addWidget(self.lbl_folder_summary)

        self.folder_list = QListWidget()
        self.folder_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.folder_list.itemChanged.connect(self._on_folder_item_changed)
        fld_layout.addWidget(self.folder_list)

        fld_btns = QHBoxLayout()
        btn_all = QPushButton("Tümünü Seç")
        btn_all.clicked.connect(self._select_all_folders)
        btn_none = QPushButton("Seçimi Kaldır")
        btn_none.clicked.connect(self._select_none_folders)
        fld_btns.addWidget(btn_all)
        fld_btns.addWidget(btn_none)
        fld_btns.addStretch()
        fld_layout.addLayout(fld_btns)

        left_col.addWidget(folder_group)
        main_split.addLayout(left_col, 1)

        # Right Column: IMAP Target Server Setup
        self.server_group = QGroupBox("4. Hedef IMAP Sunucusu ve Göç Ayarları")
        sg_layout = QVBoxLayout(self.server_group)

        # Saved Target Servers Combo
        saved_srv_row = QHBoxLayout()
        saved_srv_row.addWidget(QLabel("Kayıtlı Sunucular:"))
        self.combo_saved_servers = QComboBox()
        self.combo_saved_servers.currentIndexChanged.connect(self._on_saved_server_changed)
        saved_srv_row.addWidget(self.combo_saved_servers, 1)
        
        self.btn_save_server = QPushButton("💾 Sunucuyu Kaydet")
        self.btn_save_server.clicked.connect(self._save_target_server)
        saved_srv_row.addWidget(self.btn_save_server)

        self.btn_delete_server = QPushButton("🗑️")
        self.btn_delete_server.setStyleSheet("color: #dc2626;")
        self.btn_delete_server.clicked.connect(self._delete_target_server)
        saved_srv_row.addWidget(self.btn_delete_server)
        sg_layout.addLayout(saved_srv_row)

        srv_grid = QVBoxLayout()
        
        h_row = QHBoxLayout()
        h_row.addWidget(QLabel("Sunucu Adresi (Host):"))
        self.input_host = QLineEdit()
        self.input_host.setPlaceholderText("mail.example.com")
        h_row.addWidget(self.input_host, 2)
        h_row.addWidget(QLabel("Port:"))
        self.input_port = QLineEdit("993")
        self.input_port.setMaximumWidth(60)
        h_row.addWidget(self.input_port)
        self.chk_ssl = QCheckBox("SSL/TLS")
        self.chk_ssl.setChecked(True)
        h_row.addWidget(self.chk_ssl)
        srv_grid.addLayout(h_row)

        u_row = QHBoxLayout()
        u_row.addWidget(QLabel("Kullanıcı Adı:"))
        self.input_username = QLineEdit()
        self.input_username.setPlaceholderText("user@example.com")
        u_row.addWidget(self.input_username)
        srv_grid.addLayout(u_row)

        p_row = QHBoxLayout()
        p_row.addWidget(QLabel("Şifre:"))
        self.input_password = QLineEdit()
        self.input_password.setEchoMode(QLineEdit.Password)
        p_row.addWidget(self.input_password)
        srv_grid.addLayout(p_row)

        sg_layout.addLayout(srv_grid)

        # Connection test
        test_row = QHBoxLayout()
        self.btn_test_target = QPushButton("🔌 Bağlantıyı Test Et")
        self.btn_test_target.clicked.connect(self._test_target_connection)
        self.lbl_target_test_status = QLabel("Durum: Test edilmedi")
        self.lbl_target_test_status.setStyleSheet("color: #64748b;")
        test_row.addWidget(self.btn_test_target)
        test_row.addWidget(self.lbl_target_test_status, 1)
        sg_layout.addLayout(test_row)

        # Folder auto match
        match_box = QFrame()
        match_box.setStyleSheet("background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 6px; padding: 6px;")
        mb_layout = QVBoxLayout(match_box)
        mb_layout.addWidget(QLabel("<b>Sunucu Klasörlerini Algıla & Eşleştir:</b>"))
        lbl_m_info = QLabel("Hedef sunucunun klasör ağacını okur ve aynı isimdeki standart klasörleri (Gelen, Giden vb.) otomatik seçer.")
        lbl_m_info.setWordWrap(True)
        lbl_m_info.setStyleSheet("color: #64748b; font-size: 10px;")
        mb_layout.addWidget(lbl_m_info)
        
        self.btn_fetch_server_folders = QPushButton("🔍 Sunucudan Oku ve Eşleştir")
        self.btn_fetch_server_folders.clicked.connect(self._fetch_server_folders_and_recommend)
        mb_layout.addWidget(self.btn_fetch_server_folders)
        sg_layout.addWidget(match_box)

        sg_layout.addStretch()
        main_split.addWidget(self.server_group, 1)
        layout.addLayout(main_split)

        # Footer Dialog Buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._load_profiles()
        self._load_saved_servers()
        self._load_folders_from_db()
        self._on_format_changed()
        self._is_loading = False

    def _load_profiles(self):
        self.combo_profile.blockSignals(True)
        self.combo_profile.clear()
        self.combo_profile.addItem("Özel / Yeni Profil...", None)
        profiles = self.settings.get("export_profiles", [])
        for p in profiles:
            if isinstance(p, dict) and p.get("name"):
                self.combo_profile.addItem(p["name"], p)
        self.combo_profile.blockSignals(False)

    def _load_saved_servers(self):
        self.combo_saved_servers.blockSignals(True)
        self.combo_saved_servers.clear()
        self.combo_saved_servers.addItem("Sunucu Seçiniz...", None)
        servers = self.settings.get("saved_target_servers", [])
        for s in servers:
            if isinstance(s, dict) and s.get("name"):
                self.combo_saved_servers.addItem(s["name"], s)
        self.combo_saved_servers.blockSignals(False)

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
                    item.setForeground(QColor("#15803d"))
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
            item.setForeground(QColor("#15803d"))
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
            item.setForeground(QColor("#15803d"))
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
        elif fmt == "PST":
            path, _ = QFileDialog.getSaveFileName(self, "Hedef PST Dosyasını Seçin", "", "Outlook PST Files (*.pst)")
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
    def _test_target_connection(self):
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
        self.lbl_target_test_status.setStyleSheet("color: #2563eb;")

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

                success_msg = f"✅ Bağlantı Başarılı ({duration_ms} ms) | Port: {port} (SSL: {'Aktif' if use_ssl else 'Pasif'})"
                self.lbl_target_test_status.setText(success_msg)
                self.lbl_target_test_status.setStyleSheet("color: #15803d;")

            except Exception as e:
                err_msg = str(e)
                if "AUTHENTICATIONFAILED" in err_msg.upper() or "LOGIN" in err_msg.upper():
                    err_text = "❌ Kimlik Doğrulama Başarısız (Kullanıcı adı veya şifre hatalı)"
                else:
                    err_text = f"❌ Bağlantı Hatası: {err_msg[:50]}"
                self.lbl_target_test_status.setText(err_text)
                self.lbl_target_test_status.setStyleSheet("color: #dc2626;")
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
                item.setForeground(QColor("#15803d"))
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


# ---------------------------------------------------------------------------
# High Contrast, Modern Export Confirmation Dialog
# ---------------------------------------------------------------------------

class ExportConfirmDialog(QDialog):
    def __init__(self, account_previews: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dışa Aktarım & Sunucu Göçü Önizleme Raporu")
        self.resize(980, 620)
        self.setMinimumSize(850, 520)
        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
            }
            QLabel {
                color: #0f172a;
            }
            QFrame {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
            }
            QTableWidget {
                color: #0f172a;
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                gridline-color: #f1f5f9;
                border-radius: 6px;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #1e3a8a;
                color: #ffffff !important;
                font-weight: 700;
                padding: 8px 10px;
                border: 1px solid #1e40af;
                font-size: 11.5px;
            }
        """)
        
        self.previews = account_previews
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        
        # 1. Header Frame
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(16, 10, 16, 10)
        header_layout.setSpacing(12)
        
        header_icon = QLabel("📤")
        header_icon.setStyleSheet("font-size: 28px; background: transparent; border: none;")
        header_layout.addWidget(header_icon)
        
        header_text_vbox = QVBoxLayout()
        header_text_vbox.setSpacing(2)
        
        title_lbl = QLabel("DIŞA AKTARIM & SUNUCU GÖÇÜ ÖNİZLEME RAPORU")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #1e3a8a; background: transparent; border: none;")
        
        subtitle_lbl = QLabel("Aşağıdaki hesap ve klasör verileri seçilen biçimde dışa aktarılacak veya hedef IMAP sunucusuna taşınacaktır.")
        subtitle_lbl.setStyleSheet("font-size: 11.5px; color: #64748b; background: transparent; border: none;")
        
        header_text_vbox.addWidget(title_lbl)
        header_text_vbox.addWidget(subtitle_lbl)
        header_layout.addLayout(header_text_vbox, stretch=1)
        layout.addWidget(header_frame)
        
        # 2. Summary KPI Cards
        total_accounts = len(self.previews)
        total_estimated_mails = sum(p.get("mails", 0) for p in self.previews)
        total_folders = sum(p.get("folders", 0) for p in self.previews)
        
        kpi_layout = QHBoxLayout()
        kpi_layout.setSpacing(10)
        
        kpi_data = [
            ("Seçilen Hesap", f"{total_accounts} Adet", "#2563eb", "👥"),
            ("Aktarılacak Klasör", f"{total_folders} Klasör", "#0284c7", "📁"),
            ("Aktarılacak Mail", f"{total_estimated_mails:,} E-Posta", "#10b981", "✉️"),
        ]
        
        for k_title, k_val, k_color, k_icon in kpi_data:
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background-color: #ffffff;
                    border: 1px solid #cbd5e1;
                    border-radius: 8px;
                }
            """)
            c_lyt = QVBoxLayout(card)
            c_lyt.setContentsMargins(12, 8, 12, 8)
            c_lyt.setSpacing(2)
            
            lbl_t = QLabel(f"{k_icon} {k_title.upper()}")
            lbl_t.setStyleSheet("font-size: 10.5px; font-weight: 700; color: #64748b; background: transparent; border: none;")
            lbl_t.setAlignment(Qt.AlignCenter)
            
            lbl_v = QLabel(k_val)
            lbl_v.setStyleSheet(f"font-size: 16px; font-weight: 800; color: {k_color}; background: transparent; border: none;")
            lbl_v.setAlignment(Qt.AlignCenter)
            
            c_lyt.addWidget(lbl_t)
            c_lyt.addWidget(lbl_v)
            kpi_layout.addWidget(card)
            
        layout.addLayout(kpi_layout)
        
        # 3. Main Body Splitter Layout
        body_layout = QHBoxLayout()
        body_layout.setSpacing(12)
        
        left_box = QGroupBox(f"Hesap Listesi ({len(self.previews)})")
        left_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #1e3a8a;
                font-size: 12px;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 14px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(8, 8, 8, 8)
        
        self.account_list_widget = QListWidget()
        self.account_list_widget.setStyleSheet("""
            QListWidget {
                border: 1px solid #e2e8f0;
                background-color: #f8fafc;
                border-radius: 6px;
                color: #0f172a;
            }
            QListWidget::item {
                padding: 8px 10px;
                border-bottom: 1px solid #e2e8f0;
                border-radius: 4px;
                margin-bottom: 2px;
            }
            QListWidget::item:hover {
                background-color: #e0e7ff;
            }
            QListWidget::item:selected {
                background-color: #2563eb;
                color: #ffffff !important;
                font-weight: bold;
            }
        """)
        
        for idx, p in enumerate(self.previews):
            lbl_text = p.get("label", f"Hesap #{idx+1}")
            mail_cnt = p.get("mails", 0)
            item = QListWidgetItem(f"👤 {lbl_text} ({mail_cnt} mail)")
            item.setData(Qt.UserRole, idx)
            self.account_list_widget.addItem(item)
            
        self.account_list_widget.currentRowChanged.connect(self._load_preview)
        left_layout.addWidget(self.account_list_widget)
        body_layout.addWidget(left_box, stretch=1)
        
        right_box = QGroupBox("Seçili Hesap Aktarım ve Hedef Detayları")
        right_box.setStyleSheet(left_box.styleSheet())
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(8)
        
        info_bar = QFrame()
        info_bar.setStyleSheet("background-color: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px;")
        info_bar_lyt = QVBoxLayout(info_bar)
        info_bar_lyt.setContentsMargins(8, 6, 8, 6)
        info_bar_lyt.setSpacing(4)
        
        self.lbl_acc_name_details = QLabel("<b>Hesap:</b> —")
        self.lbl_acc_name_details.setStyleSheet("font-size: 12px; color: #1e293b; background: transparent; border: none;")
        
        self.lbl_format_details = QLabel("<b>Biçim:</b> ZIP   •   <b>Hedef:</b> data/exports")
        self.lbl_format_details.setStyleSheet("font-size: 11.5px; color: #334155; background: transparent; border: none;")
        self.lbl_format_details.setWordWrap(True)
        
        info_bar_lyt.addWidget(self.lbl_acc_name_details)
        info_bar_lyt.addWidget(self.lbl_format_details)
        right_layout.addWidget(info_bar)
        
        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(3)
        self.summary_table.setHorizontalHeaderLabels(["Özellik", "Değer", "Durum"])
        self.summary_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.summary_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.summary_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.summary_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.verticalHeader().setVisible(False)
        right_layout.addWidget(self.summary_table)
        
        body_layout.addWidget(right_box, stretch=2)
        layout.addLayout(body_layout)
        
        # 4. Footer Buttons
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.setSpacing(10)
        
        btn_cancel = QPushButton("✕ Vazgeç")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #64748b;
                color: #ffffff;
                font-weight: 700;
                padding: 9px 22px;
                border-radius: 6px;
                font-size: 12px;
                border: none;
            }
            QPushButton:hover {
                background-color: #475569;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        
        btn_ok = QPushButton("⚡ Dışa Aktarımı Başlat")
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #16a34a;
                color: #ffffff;
                font-weight: 800;
                padding: 9px 28px;
                border-radius: 6px;
                font-size: 12.5px;
                border: none;
            }
            QPushButton:hover {
                background-color: #15803d;
            }
        """)
        btn_ok.clicked.connect(self.accept)
        
        footer_layout.addStretch()
        footer_layout.addWidget(btn_cancel)
        footer_layout.addWidget(btn_ok)
        layout.addLayout(footer_layout)
        
        if self.previews:
            self.account_list_widget.setCurrentRow(0)
            self._load_preview(0)
            
    def _load_preview(self, idx: int):
        if idx < 0 or idx >= len(self.previews):
            return
            
        p = self.previews[idx]
        acc_label = p.get("label", "?")
        fmt = p.get("format", "ZIP")
        tgt = p.get("resolved_target", "data/exports")
        mails = p.get("mails", 0)
        folders = p.get("folders", 0)
        
        self.lbl_acc_name_details.setText(f"<b>Hesap:</b> <span style='color:#2563eb;'>{acc_label}</span>")
        self.lbl_format_details.setText(f"<b>Biçim:</b> <span style='color:#059669;'>{fmt}</span>   •   <b>Hedef:</b> <span style='color:#0f172a;'>{tgt}</span>")
        
        rows_data = [
            ("Biçim / Hedef Türü", fmt, "Hazır"),
            ("Hedef Yol / Sunucu", tgt, "Geçerli"),
            ("Arşivdeki Toplam E-Posta", f"{mails:,} Adet", "Aktarılacak" if mails > 0 else "Boş"),
            ("Toplam Klasör Sayısı", f"{folders} Klasör", "Hazır"),
        ]
        
        self.summary_table.setRowCount(len(rows_data))
        for row, (prop, val, st) in enumerate(rows_data):
            self.summary_table.setItem(row, 0, QTableWidgetItem(prop))
            self.summary_table.setItem(row, 1, QTableWidgetItem(val))
            st_item = QTableWidgetItem(st)
            st_item.setTextAlignment(Qt.AlignCenter)
            if "Aktarılacak" in st or "Hazır" in st or "Geçerli" in st:
                st_item.setForeground(QColor("#16a34a"))
            self.summary_table.setItem(row, 2, st_item)


# ---------------------------------------------------------------------------
# Export Finished Dialog (with countdown)
# ---------------------------------------------------------------------------

class ExportFinishedDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("İşlem Tamamlandı")
        self.setMinimumWidth(440)
        self.setStyleSheet(GLOBAL_MSG_STYLE)

        self._remaining_seconds = 5

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        lbl_title = QLabel("✅ E-Posta Dışa Aktarım İşlemi Tamamlandı!")
        lbl_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_title.setStyleSheet("color: #10b981;")
        layout.addWidget(lbl_title)

        lbl_msg = QLabel("Detaylı aktarım raporunu görüntülemek ister misiniz?")
        lbl_msg.setWordWrap(True)
        lbl_msg.setStyleSheet("color: #1e293b; font-size: 12px;")
        layout.addWidget(lbl_msg)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_no = QPushButton("Hayır (Kapat)")
        self.btn_no.setStyleSheet("background-color: #64748b; color: white; font-weight: bold; border-radius: 6px; padding: 6px 14px;")
        self.btn_no.clicked.connect(self._on_no_clicked)
        btn_layout.addWidget(self.btn_no)

        self.btn_yes = QPushButton(f"Evet ({self._remaining_seconds}sn sonra otomatik açılacak)")
        self.btn_yes.setDefault(True)
        self.btn_yes.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; border-radius: 6px; padding: 6px 16px;")
        self.btn_yes.clicked.connect(self._on_yes_clicked)
        btn_layout.addWidget(self.btn_yes)

        layout.addLayout(btn_layout)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_timer_tick)
        self._timer.start()

    def _on_timer_tick(self):
        self._remaining_seconds -= 1
        if self._remaining_seconds <= 0:
            self._timer.stop()
            self.accept()
        else:
            self.btn_yes.setText(f"Evet ({self._remaining_seconds}sn sonra otomatik açılacak)")

    def _on_yes_clicked(self):
        self._timer.stop()
        self.accept()

    def _on_no_clicked(self):
        self._timer.stop()
        self.reject()


# ---------------------------------------------------------------------------
# Main ExportPanel (Unified 3-Section Ergonomic Layout matching SyncPanel)
# ---------------------------------------------------------------------------

class ExportPanel(QWidget):
    """
    Email export & server migration panel with asynchronous background scanning,
    default 88px row height, live row progress bars, collapsible log drawer,
    and modular sidebar integration.
    """

    _log_signal = Signal(str)
    _account_progress_signal = Signal(int, str, int, int, object)
    _account_export_done_signal = Signal(int, object)
    _account_export_error_signal = Signal(int, str)
    _export_all_finished_signal = Signal()

    def __init__(self, engine: MailEngine, parent=None, settings: AppSettings = None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings or AppSettings()
        
        # Active workers tracking
        self._active_exports: Dict[int, Any] = {}
        self._accounts_ui: Dict[int, Dict[str, Any]] = {}
        self._stats_labels_map: Dict[int, QLabel] = {}
        self._session_reports: List[Dict[str, Any]] = []
        self._selected_group = "__ALL__"
        self._all_selected_flag = False
        self._is_paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._cancel_event = threading.Event()

        # Row Height State
        saved_h = self.settings.get("export_panel_row_height", 88)
        self._current_row_height = int(saved_h) if saved_h else 88

        # Log Model Setup
        self._log_model = LogTableModel(self)
        self._log_proxy = LogFilterProxy(self)
        self._log_proxy.setSourceModel(self._log_model)

        # Background worker ref
        self._loader_worker: Optional[ExportDataLoaderWorker] = None
        self._is_refreshing = False

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
        self._connect_signals()
        
        # Internal Signals
        self._log_signal.connect(self._on_log_message)
        self._account_progress_signal.connect(self._on_account_progress)
        self._account_export_done_signal.connect(self._on_account_export_done)
        self._account_export_error_signal.connect(self._on_account_export_error)
        self._export_all_finished_signal.connect(self._on_export_all_finished)

        self.refresh()

    def _setup_ui(self):
        main_vbox = QVBoxLayout(self)
        main_vbox.setContentsMargins(8, 6, 8, 6)
        main_vbox.setSpacing(6)

        # ----------------------------------------------------------------
        # 1. TOP TOOLBAR: Minimalist, Search & Quick Stats
        # ----------------------------------------------------------------
        self.top_bar = QFrame()
        self.top_bar.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 2px;
            }
        """)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(8, 4, 8, 4)
        top_layout.setSpacing(8)

        # Left Sidebar Toggle Button
        self.btn_toggle_left = QPushButton("◀ Grupları Gizle")
        self.btn_toggle_left.setToolTip("Sol Grup/Domain filtre panelini gizler/gösterir")
        self.btn_toggle_left.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_left.setStyleSheet(self._toggle_btn_style())
        self.btn_toggle_left.clicked.connect(self._toggle_left_sidebar)
        top_layout.addWidget(self.btn_toggle_left)

        # Search Input
        self.txt_search_export = QLineEdit()
        self.txt_search_export.setPlaceholderText("🔍 Hesap Adı, E-Posta veya Domain Grubu Ara...")
        self.txt_search_export.setClearButtonEnabled(True)
        self.txt_search_export.setStyleSheet("""
            QLineEdit {
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px 8px;
                background-color: #f8fafc;
                color: #0f172a;
                font-size: 11.5px;
            }
            QLineEdit:focus {
                border-color: #2563eb;
                background-color: #ffffff;
            }
        """)
        self.txt_search_export.textChanged.connect(self._filter_table_rows)
        top_layout.addWidget(self.txt_search_export, stretch=1)

        # Statistics Badges
        self.lbl_stat_total = QLabel("📊 0 Hesap")
        self.lbl_stat_total.setStyleSheet(self._badge_style(bg="#e0e7ff", fg="#1e3a8a"))
        top_layout.addWidget(self.lbl_stat_total)

        self.lbl_stat_selected = QLabel("☑️ 0 Seçili")
        self.lbl_stat_selected.setStyleSheet(self._badge_style(bg="#fef3c7", fg="#b45309"))
        top_layout.addWidget(self.lbl_stat_selected)

        self.lbl_stat_active = QLabel("🟢 0 Aktarılıyor")
        self.lbl_stat_active.setStyleSheet(self._badge_style(bg="#dcfce7", fg="#15803d"))
        top_layout.addWidget(self.lbl_stat_active)

        # Refresh button
        self.btn_refresh = QPushButton("🔄 Yenile")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #1e3a8a;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11.5px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #f1f5f9; border-color: #2563eb; }
        """)
        self.btn_refresh.clicked.connect(self._check_disk_and_refresh)
        top_layout.addWidget(self.btn_refresh)

        # Right Sidebar Toggle Button
        self.btn_toggle_right = QPushButton("⚙️ İşlemler ▶")
        self.btn_toggle_right.setToolTip("Sağ işlem ve ayar çekmecesini gizler/gösterir")
        self.btn_toggle_right.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_right.setStyleSheet(self._toggle_btn_style())
        self.btn_toggle_right.clicked.connect(self._toggle_right_sidebar)
        top_layout.addWidget(self.btn_toggle_right)

        main_vbox.addWidget(self.top_bar)

        # ----------------------------------------------------------------
        # 2. 3-COLUMN SPLIT LAYOUT
        # ----------------------------------------------------------------
        split_layout = QHBoxLayout()
        split_layout.setSpacing(2)
        split_layout.setContentsMargins(0, 0, 0, 0)

        # 1. Left Sidebar: Account Group Widget
        self.left_sidebar = AccountGroupSidebarWidget(self)
        self.left_sidebar.setFixedWidth(230)
        split_layout.addWidget(self.left_sidebar)

        # Middle Arrow Toggle for Left Sidebar
        self.btn_middle_toggle_left = QPushButton("◀")
        self.btn_middle_toggle_left.setToolTip("Sol Filtre Panelini Gizle / Göster")
        self.btn_middle_toggle_left.setFixedWidth(16)
        self.btn_middle_toggle_left.setCursor(Qt.PointingHandCursor)
        self.btn_middle_toggle_left.setStyleSheet("""
            QPushButton {
                background-color: #e2e8f0;
                color: #334155;
                border: 1px solid #cbd5e1;
                border-left: none;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                font-weight: bold;
                font-size: 10px;
                padding: 0px;
                min-height: 50px;
                max-height: 50px;
            }
            QPushButton:hover {
                background-color: #2563eb;
                color: #ffffff;
                border-color: #1d4ed8;
            }
        """)
        self.btn_middle_toggle_left.clicked.connect(self._toggle_left_sidebar)
        split_layout.addWidget(self.btn_middle_toggle_left)

        # 2. Center: DBGrid Container + Stats Header + Ergonomic Action Buttons + Table + Collapsible Log
        center_container = QGroupBox("📤 E-Posta Dışa Aktarma & Sunucu Göçü Havuzu")
        center_container.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #1e3a8a;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 12px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 2px 8px;
                background-color: #1e3a8a;
                color: #ffffff !important;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        center_layout = QVBoxLayout(center_container)
        center_layout.setContentsMargins(6, 6, 6, 6)
        center_layout.setSpacing(6)

        # Top Live Stats Cards
        stats_frame = QFrame()
        stats_frame.setStyleSheet("background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;")
        stats_lyt = QHBoxLayout(stats_frame)
        stats_lyt.setContentsMargins(6, 4, 6, 4)
        stats_lyt.setSpacing(6)

        self.card_account = StatCard("Mevcut Hesap", "—", "👤")
        self.card_format = StatCard("Hedef Biçim", "ZIP", "📦")
        self.card_remaining = StatCard("Kalan E-Posta", "—", "⏳")
        self.card_progress = StatCard("İlerleme", "—", "📈")
        self.card_eta = StatCard("Tahmini Süre", "—", "⏱️")
        self.card_size = StatCard("Aktarılan Boyut", "—", "💾")

        stats_lyt.addWidget(self.card_account)
        stats_lyt.addWidget(self.card_format)
        stats_lyt.addWidget(self.card_remaining)
        stats_lyt.addWidget(self.card_progress)
        stats_lyt.addWidget(self.card_eta)
        stats_lyt.addWidget(self.card_size)
        center_layout.addWidget(stats_frame)

        # Quick Action Buttons Bar directly under Current Account stats
        actions_bar = QFrame()
        actions_bar.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 2px;
            }
        """)
        actions_bar_lyt = QHBoxLayout(actions_bar)
        actions_bar_lyt.setContentsMargins(6, 4, 6, 4)
        actions_bar_lyt.setSpacing(6)

        self.btn_export = QPushButton("⚡ Seçilenleri Başlat")
        self.btn_export.setToolTip("Seçili kutucuğu işaretli tüm hesapların dışa aktarımını başlatır")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.setStyleSheet(self._blue_btn_style(bg="#2563eb", hover="#1d4ed8", py=5, px=10, fs=11))
        self.btn_export.clicked.connect(self._export_selected)
        actions_bar_lyt.addWidget(self.btn_export)

        self.btn_export_all = QPushButton("🚀 Tümünü Başlat")
        self.btn_export_all.setToolTip("Sistemdeki tüm hesapları dışa aktarır")
        self.btn_export_all.setCursor(Qt.PointingHandCursor)
        self.btn_export_all.setStyleSheet(self._blue_btn_style(bg="#059669", hover="#047857", py=5, px=10, fs=11))
        self.btn_export_all.clicked.connect(self._export_all)
        actions_bar_lyt.addWidget(self.btn_export_all)

        self.btn_pause = QPushButton("⏸️ Duraklat")
        self.btn_pause.setToolTip("Aktif aktarım işlemlerini duraklatır")
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_pause.setStyleSheet(self._blue_btn_style(bg="#f59e0b", hover="#d97706", py=5, px=10, fs=11))
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._toggle_pause_export)
        actions_bar_lyt.addWidget(self.btn_pause)

        self.btn_cancel = QPushButton("⏹️ İptal Et")
        self.btn_cancel.setToolTip("Aktif aktarım işlemlerini iptal eder")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setStyleSheet(self._blue_btn_style(bg="#dc2626", hover="#b91c1c", py=5, px=10, fs=11))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_export)
        actions_bar_lyt.addWidget(self.btn_cancel)

        self.btn_dry_run = QPushButton("🔍 Inode / Önizleme")
        self.btn_dry_run.setToolTip("Seçili hesaplar için aktarım önizlemesi ve inode kontrollerini hesaplar")
        self.btn_dry_run.setCursor(Qt.PointingHandCursor)
        self.btn_dry_run.setStyleSheet(self._blue_btn_style(bg="#475569", hover="#334155", py=5, px=10, fs=11))
        self.btn_dry_run.clicked.connect(self._dry_run_preview)
        actions_bar_lyt.addWidget(self.btn_dry_run)

        self.btn_config = QPushButton("⚙️ Hedef & Filtreler...")
        self.btn_config.setToolTip("Dışa aktarım biçimi, hedef dizin, IMAP sunucu ve filtrelerini ayarlar")
        self.btn_config.setCursor(Qt.PointingHandCursor)
        self.btn_config.setStyleSheet(self._blue_btn_style(bg="#0284c7", hover="#0369a1", py=5, px=10, fs=11))
        self.btn_config.clicked.connect(self._open_config_dialog)
        actions_bar_lyt.addWidget(self.btn_config)

        self.btn_reports = QPushButton("📊 Raporlar")
        self.btn_reports.setToolTip("Dışa aktarım sonuç raporlarını görüntüler")
        self.btn_reports.setCursor(Qt.PointingHandCursor)
        self.btn_reports.setStyleSheet(self._blue_btn_style(bg="#7c3aed", hover="#6d28d9", py=5, px=10, fs=11))
        self.btn_reports.clicked.connect(self._show_reports)
        actions_bar_lyt.addWidget(self.btn_reports)

        actions_bar_lyt.addStretch()

        # Log toggle button
        self.btn_toggle_log = QPushButton("📋 Log Kutusu")
        self.btn_toggle_log.setToolTip("Canlı dışa aktarım log tablosunu gizler/gösterir")
        self.btn_toggle_log.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_log.setStyleSheet(self._blue_btn_style(bg="#334155", hover="#1e293b", py=5, px=10, fs=11))
        self.btn_toggle_log.clicked.connect(self._toggle_log_visibility)
        actions_bar_lyt.addWidget(self.btn_toggle_log)

        center_layout.addWidget(actions_bar)

        # Disk Connection Banner with Loading indicator
        self.disk_status_banner = QFrame()
        self.disk_status_banner.setObjectName("diskStatusBanner")
        self.disk_status_banner.setStyleSheet("""
            QFrame#diskStatusBanner {
                background-color: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 2px;
            }
        """)
        banner_layout = QHBoxLayout(self.disk_status_banner)
        banner_layout.setContentsMargins(8, 4, 8, 4)
        banner_layout.setSpacing(6)

        self.lbl_disk_status_icon = QLabel("💾")
        self.lbl_disk_status_icon.setStyleSheet("font-size: 14px; background: transparent;")
        banner_layout.addWidget(self.lbl_disk_status_icon)

        self.lbl_disk_status_text = QLabel("Dışa aktarım depolama ve veritabanı durumu kontrol ediliyor...")
        self.lbl_disk_status_text.setStyleSheet("font-size: 11px; font-weight: 600; color: #1e293b; background: transparent;")
        banner_layout.addWidget(self.lbl_disk_status_text, stretch=1)

        self.btn_disk_reconnect = QPushButton("🔄 Yeniden Tara")
        self.btn_disk_reconnect.setCursor(Qt.PointingHandCursor)
        self.btn_disk_reconnect.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #1e293b;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 10.5px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #f1f5f9; }
        """)
        self.btn_disk_reconnect.clicked.connect(self._check_disk_and_refresh)
        banner_layout.addWidget(self.btn_disk_reconnect)
        center_layout.addWidget(self.disk_status_banner)

        # Main Table: Select Accounts
        self.account_table = QTableWidget()
        self.account_table.setColumnCount(4)
        self.account_table.setHorizontalHeaderLabels([
            "☑️ Seç", "Hesap Bilgileri & Domain", "Aktarım Durumu & İlerleme", "İşlemler"
        ])
        self.account_table.setAlternatingRowColors(True)
        self.account_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.account_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.account_table.verticalHeader().setVisible(False)
        self.account_table.verticalHeader().setDefaultSectionSize(self._current_row_height)

        self.account_table.setColumnWidth(0, 55)
        self.account_table.setColumnWidth(1, 420)
        self.account_table.setColumnWidth(2, 340)
        self.account_table.setColumnWidth(3, 150)
        self.account_table.horizontalHeader().setStretchLastSection(False)
        self.account_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        self.account_table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #f8fafc;
                gridline-color: #e2e8f0;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                color: #0f172a;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
                font-size: 11.5px;
            }
            QTableWidget::item {
                padding: 4px 8px;
                border-bottom: 1px solid #f1f5f9;
                color: #0f172a;
            }
            QTableWidget::item:selected {
                background-color: #2563eb;
                color: #ffffff !important;
            }
            QHeaderView::section {
                background-color: #1e3a8a;
                color: #ffffff !important;
                font-weight: 700;
                font-size: 11.5px;
                border: 1px solid #1e40af;
                padding: 6px 8px;
                min-height: 30px;
            }
        """)

        self.account_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.account_table.customContextMenuRequested.connect(self._show_toya_grid_context_menu)
        self.account_table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.account_table.horizontalHeader().customContextMenuRequested.connect(self._show_toya_grid_context_menu)
        self.account_table.horizontalHeader().sectionResized.connect(self._auto_save_current_layout)
        self.account_table.itemChanged.connect(self._on_table_item_changed)
        self.account_table.itemSelectionChanged.connect(self._on_table_row_click)

        center_layout.addWidget(self.account_table, stretch=2)

        # 3. Collapsible Live Log Box
        self.log_box = QGroupBox("📋 Dışa Aktarım Canlı Logu")
        self.log_box.setStyleSheet("""
            QGroupBox {
                background: #ffffff;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 4px;
                font-weight: bold;
                font-size: 11.5px;
                color: #1e293b;
            }
        """)
        log_layout = QVBoxLayout(self.log_box)
        log_layout.setContentsMargins(8, 12, 8, 8)
        log_layout.setSpacing(6)

        log_toolbar = QHBoxLayout()
        log_toolbar.setSpacing(6)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("🔍 Log içinde filtrele...")
        self.filter_input.setMinimumWidth(180)
        self.filter_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 11px;
            }
        """)

        self.combo_page_size = QComboBox()
        self.combo_page_size.addItems(["25", "50", "100", "200", "Tümü"])
        self.combo_page_size.setCurrentIndex(1)
        self.combo_page_size.setStyleSheet("font-size: 11px; padding: 2px 6px;")

        self.btn_prev_page = QPushButton("◀ Önceki")
        self.btn_prev_page.setStyleSheet(self._blue_btn_style(py=3, px=8, fs=10))
        self.btn_next_page = QPushButton("Sonraki ▶")
        self.btn_next_page.setStyleSheet(self._blue_btn_style(py=3, px=8, fs=10))
        self.label_page = QLabel("Sayfa 1 / 1")
        self.label_page.setStyleSheet("font-size:11px;color:#4b5563;")

        self.btn_clear_log = QPushButton("🧹 Temizle")
        self.btn_clear_log.setStyleSheet(self._blue_btn_style(py=3, px=8, fs=10, bg="#ef4444", hover="#dc2626"))

        log_toolbar.addWidget(self.filter_input)
        log_toolbar.addStretch()
        log_toolbar.addWidget(QLabel("Satır:"))
        log_toolbar.addWidget(self.combo_page_size)
        log_toolbar.addWidget(self.btn_prev_page)
        log_toolbar.addWidget(self.label_page)
        log_toolbar.addWidget(self.btn_next_page)
        log_toolbar.addWidget(self.btn_clear_log)
        log_layout.addLayout(log_toolbar)

        self.log_table = QTableView()
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setSelectionBehavior(QTableView.SelectRows)
        self.log_table.setSelectionMode(QTableView.NoSelection)
        self.log_table.setShowGrid(False)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.horizontalHeader().setStretchLastSection(True)
        self.log_table.setMaximumHeight(150)
        self.log_table.setStyleSheet("""
            QTableView {
                background: #1a1a2e;
                color: #a8d8ea;
                font-family: 'Consolas','Courier New',monospace;
                font-size: 10.5px;
                border: 1px solid #2d2d44;
                border-radius: 4px;
                padding: 2px;
                gridline-color: #2d2d44;
            }
            QTableView::item { padding: 2px 4px; }
            QTableView::item:alternate { background: #1f1f36; }
            QHeaderView::section {
                background: #252542;
                color: #c4b5e3;
                font-weight: 600;
                font-size: 10.5px;
                padding: 3px 4px;
                border: none;
                border-bottom: 1px solid #2d2d44;
            }
        """)
        self.log_table.setModel(self._log_proxy)
        self.log_table.setColumnHidden(1, True)
        self.log_table.setColumnHidden(2, True)
        log_layout.addWidget(self.log_table)

        center_layout.addWidget(self.log_box, stretch=1)
        split_layout.addWidget(center_container, stretch=1)

        # Middle Arrow Toggle for Right Sidebar
        self.btn_middle_toggle_right = QPushButton("▶")
        self.btn_middle_toggle_right.setToolTip("Sağ İşlem Çekmecesini Gizle / Göster")
        self.btn_middle_toggle_right.setFixedWidth(16)
        self.btn_middle_toggle_right.setCursor(Qt.PointingHandCursor)
        self.btn_middle_toggle_right.setStyleSheet("""
            QPushButton {
                background-color: #e2e8f0;
                color: #334155;
                border: 1px solid #cbd5e1;
                border-right: none;
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                font-weight: bold;
                font-size: 10px;
                padding: 0px;
                min-height: 50px;
                max-height: 50px;
            }
            QPushButton:hover {
                background-color: #2563eb;
                color: #ffffff;
                border-color: #1d4ed8;
            }
        """)
        self.btn_middle_toggle_right.clicked.connect(self._toggle_right_sidebar)
        split_layout.addWidget(self.btn_middle_toggle_right)

        # 3. Right Sidebar: Actions & Profile Drawer
        self.right_sidebar = ExportRightSidebarWidget(self)
        self.right_sidebar.setFixedWidth(320)
        split_layout.addWidget(self.right_sidebar)

        main_vbox.addLayout(split_layout)

    def _connect_signals(self):
        # Left Sidebar Signal Connect
        self.left_sidebar.group_selected.connect(self._on_left_sidebar_group_selected)

        # Right Sidebar Action Signals Connect
        self.right_sidebar.export_selected_requested.connect(self._export_selected)
        self.right_sidebar.export_all_requested.connect(self._export_all)
        self.right_sidebar.pause_requested.connect(self._toggle_pause_export)
        self.right_sidebar.cancel_requested.connect(self._cancel_export)
        self.right_sidebar.dry_run_requested.connect(self._dry_run_preview)
        self.right_sidebar.export_group_requested.connect(self._export_selected_group)
        self.right_sidebar.select_all_requested.connect(self._toggle_select_all_checkboxes)
        self.right_sidebar.format_changed.connect(self._on_sidebar_format_changed)
        self.right_sidebar.config_dialog_requested.connect(self._open_config_dialog)
        self.right_sidebar.export_excel_requested.connect(self._export_to_excel)
        self.right_sidebar.copy_emails_requested.connect(self._copy_all_emails_to_clipboard)
        self.right_sidebar.reports_requested.connect(self._show_reports)
        self.right_sidebar.toggle_log_requested.connect(self._toggle_log_visibility)
        self.right_sidebar.row_height_changed.connect(self.set_row_height)

        # Right Sidebar View Profile Signals Connect
        self.right_sidebar.profile_selected.connect(self._apply_view_profile)
        self.right_sidebar.save_profile_requested.connect(self._save_view_profile)
        self.right_sidebar.columns_requested.connect(self._open_column_manager)

        # Log Toolbar Signals
        self.filter_input.textChanged.connect(self._on_log_filter_changed)
        self.combo_page_size.currentIndexChanged.connect(self._on_log_page_size_changed)
        self.btn_prev_page.clicked.connect(self._on_log_prev_page)
        self.btn_next_page.clicked.connect(self._on_log_next_page)
        self.btn_clear_log.clicked.connect(self._on_log_clear)

    # -----------------------------------------------------------------------
    # Row Height & Profile Management
    # -----------------------------------------------------------------------

    @Slot(int)
    def set_row_height(self, height: int, auto_save: bool = True):
        self._current_row_height = max(35, min(height, 200))
        self.account_table.verticalHeader().setDefaultSectionSize(self._current_row_height)
        for r in range(self.account_table.rowCount()):
            self.account_table.setRowHeight(r, self._current_row_height)
        if auto_save:
            self.settings.set("export_panel_row_height", self._current_row_height)
            self.settings.save()
            self._auto_save_current_layout()

    @Slot()
    def _open_custom_row_height_dialog(self):
        val, ok = QInputDialog.getInt(
            self, "Özel Satır Yüksekliği",
            "Lütfen satır yüksekliğini piksel (px) olarak giriniz (35 - 200):",
            value=self._current_row_height, min=35, max=200, step=2
        )
        if ok:
            self.set_row_height(val, auto_save=True)

    def _auto_save_current_layout(self):
        if not hasattr(self, 'right_sidebar') or self._is_refreshing:
            return
        layout_data = {
            "col_widths": [self.account_table.columnWidth(c) for c in range(self.account_table.columnCount())],
            "col_hidden": [self.account_table.isColumnHidden(c) for c in range(self.account_table.columnCount())],
            "row_height": self._current_row_height,
            "left_visible": self.left_sidebar.isVisible(),
            "right_visible": self.right_sidebar.isVisible(),
            "log_visible": self.log_box.isVisible(),
        }
        self.settings.set("export_panel_layout_auto", layout_data)
        self.settings.save()

    @Slot(str, dict)
    def _apply_view_profile(self, name: str, profile_data: dict):
        if not profile_data:
            if name in ("Varsayılan (Default)", "Varsayılan"):
                self.account_table.setColumnWidth(0, 55)
                self.account_table.setColumnWidth(1, 420)
                self.account_table.setColumnWidth(2, 340)
                self.account_table.setColumnWidth(3, 150)
                for c in range(4):
                    self.account_table.setColumnHidden(c, False)
                self.set_row_height(88, auto_save=True)
                self.left_sidebar.setVisible(True)
                self.right_sidebar.setVisible(True)
                self.log_box.setVisible(True)
            elif name in ("Kompakt (Compact)", "Kompakt Düzen"):
                self.set_row_height(40, auto_save=True)
                self.log_box.setVisible(False)
            elif name in ("Detaylı (Detailed)", "Geniş Görünüm"):
                self.set_row_height(110, auto_save=True)
                self.log_box.setVisible(True)
            elif name in ("Yönetici (Admin)", "Yönetici"):
                self.set_row_height(88, auto_save=True)
                self.log_box.setVisible(True)
            return

        widths = profile_data.get("col_widths", [])
        for c, w in enumerate(widths):
            if c < self.account_table.columnCount():
                self.account_table.setColumnWidth(c, w)

        hidden = profile_data.get("col_hidden", [])
        for c, h in enumerate(hidden):
            if c < self.account_table.columnCount():
                self.account_table.setColumnHidden(c, h)

        rh = profile_data.get("row_height")
        if rh:
            self.set_row_height(int(rh), auto_save=True)

        if "left_visible" in profile_data:
            self.left_sidebar.setVisible(profile_data["left_visible"])
        if "right_visible" in profile_data:
            self.right_sidebar.setVisible(profile_data["right_visible"])
        if "log_visible" in profile_data:
            self.log_box.setVisible(profile_data["log_visible"])

    @Slot(str)
    def _save_view_profile(self, name: str):
        layout_data = {
            "col_widths": [self.account_table.columnWidth(c) for c in range(self.account_table.columnCount())],
            "col_hidden": [self.account_table.isColumnHidden(c) for c in range(self.account_table.columnCount())],
            "row_height": self._current_row_height,
            "left_visible": self.left_sidebar.isVisible(),
            "right_visible": self.right_sidebar.isVisible(),
            "log_visible": self.log_box.isVisible(),
        }
        profiles = self.settings.get("view_profiles_export_panel_grid", {})
        profiles[name] = layout_data
        self.settings.set("view_profiles_export_panel_grid", profiles)
        self.settings.save()
        self.right_sidebar.view_profile_widget.load_profiles()
        QMessageBox.information(self, "Profil Kaydedildi", f"'{name}' görünüm profili başarıyla kaydedildi.")

    @Slot()
    def _open_column_manager(self):
        col_names = [self.account_table.horizontalHeaderItem(c).text() for c in range(self.account_table.columnCount())]
        hidden_states = [self.account_table.isColumnHidden(c) for c in range(self.account_table.columnCount())]
        
        dlg = ColumnManagerDialog(col_names, hidden_states, self)
        if dlg.exec() == QDialog.Accepted:
            new_hidden = dlg.get_hidden_states()
            for c, is_h in enumerate(new_hidden):
                self.account_table.setColumnHidden(c, is_h)
            self._auto_save_current_layout()

    # -----------------------------------------------------------------------
    # Asynchronous Data Refresh & Grid Rendering
    # -----------------------------------------------------------------------

    def _check_disk_and_refresh(self):
        self.refresh()

    def _refresh_groups_sidebar(self):
        groups_status = {}
        all_accounts = self.settings.load_account_cache() or self.engine.list_accounts()
        for acc in all_accounts:
            g_name = acc.get("account_group", "").strip()
            if not g_name and "@" in acc.get("email", ""):
                g_name = acc["email"].split("@")[-1].strip()
            if g_name:
                groups_status.setdefault(g_name, {"is_active": True, "count": 0})
                groups_status[g_name]["count"] += 1

        self.left_sidebar.populate_groups(groups_status, total_accounts_count=len(all_accounts))

    def refresh(self):
        self._is_refreshing = True
        self._refresh_groups_sidebar()

        self.account_table.blockSignals(True)
        self.account_table.setRowCount(0)
        self._accounts_ui.clear()
        self._stats_labels_map.clear()

        try:
            accounts = self.engine.list_accounts()
            self.account_table.setRowCount(len(accounts))
            self.account_table.verticalHeader().setDefaultSectionSize(self._current_row_height)

            account_ids = []
            for i, acc in enumerate(accounts):
                acc_id = acc["id"]
                account_ids.append(acc_id)
                label = acc.get("label", "")
                email = acc.get("email", "")
                group_val = acc.get("account_group", "").strip() or "Genel"

                # 1. Col 0: Checkbox (Native QTableWidgetItem)
                chk_item = QTableWidgetItem()
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                chk_item.setCheckState(Qt.Unchecked)
                chk_item.setData(Qt.UserRole, acc_id)
                self.account_table.setItem(i, 0, chk_item)

                # 2. Col 1: Account Information & Domain Card
                info_widget = QWidget()
                info_widget.setStyleSheet("background: transparent;")
                info_lyt = QVBoxLayout(info_widget)
                info_lyt.setContentsMargins(6, 4, 6, 4)
                info_lyt.setSpacing(2)

                top_info_row = QHBoxLayout()
                lbl_name = QLabel(f"<b>{label}</b>")
                lbl_name.setStyleSheet("font-size: 12.5px; color: #0f172a; font-weight: 700; background: transparent;")
                top_info_row.addWidget(lbl_name)

                badge_grp = QLabel(f" {group_val} ")
                badge_grp.setStyleSheet("""
                    background-color: #eff6ff;
                    color: #1d4ed8;
                    border: 1px solid #bfdbfe;
                    border-radius: 4px;
                    font-size: 10px;
                    font-weight: 600;
                    padding: 1px 4px;
                """)
                top_info_row.addWidget(badge_grp)
                top_info_row.addStretch()
                info_lyt.addLayout(top_info_row)

                lbl_email = QLabel(f"✉️ {email}")
                lbl_email.setStyleSheet("font-size: 11px; color: #475569; background: transparent;")
                info_lyt.addWidget(lbl_email)

                lbl_disk_stat = QLabel("📁 Klasörler taranıyor...  •  📧 Yerel Mailler: —")
                lbl_disk_stat.setStyleSheet("font-size: 10.5px; color: #059669; font-weight: 600; background: transparent;")
                self._stats_labels_map[acc_id] = lbl_disk_stat
                info_lyt.addWidget(lbl_disk_stat)
                self.account_table.setCellWidget(i, 1, info_widget)

                # 3. Col 2: Export Status & Progress Bar
                prog_widget = QWidget()
                prog_widget.setStyleSheet("background: transparent;")
                prog_lyt = QVBoxLayout(prog_widget)
                prog_lyt.setContentsMargins(6, 4, 6, 4)
                prog_lyt.setSpacing(3)

                status_row = QHBoxLayout()
                lbl_status = QLabel("⏳ Bekliyor")
                lbl_status.setStyleSheet("font-size: 11px; color: #334155; font-weight: 600; background: transparent;")
                status_row.addWidget(lbl_status)
                status_row.addStretch()
                prog_lyt.addLayout(status_row)

                progress_bar = QProgressBar()
                progress_bar.setRange(0, 100)
                progress_bar.setValue(0)
                progress_bar.setTextVisible(True)
                progress_bar.setFormat("0 / 0")
                progress_bar.setStyleSheet("""
                    QProgressBar {
                        background-color: #e2e8f0;
                        border: none;
                        border-radius: 4px;
                        height: 14px;
                        font-size: 9.5px;
                        font-weight: bold;
                        text-align: center;
                        color: #0f172a;
                    }
                    QProgressBar::chunk {
                        background-color: #2563eb;
                        border-radius: 4px;
                    }
                """)
                prog_lyt.addWidget(progress_bar)
                self.account_table.setCellWidget(i, 2, prog_widget)

                # 4. Col 3: Actions
                act_widget = QWidget()
                act_widget.setStyleSheet("background: transparent;")
                act_lyt = QHBoxLayout(act_widget)
                act_lyt.setContentsMargins(4, 4, 4, 4)
                act_lyt.setSpacing(4)

                btn_start = QPushButton("▶ Başlat")
                btn_start.setToolTip("Yalnızca bu hesabın dışa aktarımını başlat")
                btn_start.setCursor(Qt.PointingHandCursor)
                btn_start.setStyleSheet(self._blue_btn_style(bg="#16a34a", hover="#15803d", py=4, px=8, fs=10.5))
                btn_start.clicked.connect(lambda checked, aid=acc_id: self._export_single_account(aid))
                act_lyt.addWidget(btn_start)

                btn_config_row = QPushButton("⚙️ Ayar")
                btn_config_row.setToolTip("Bu hesap için hedef ve filtre yapılandırması")
                btn_config_row.setCursor(Qt.PointingHandCursor)
                btn_config_row.setStyleSheet(self._blue_btn_style(bg="#0284c7", hover="#0369a1", py=4, px=8, fs=10.5))
                btn_config_row.clicked.connect(lambda checked, aid=acc_id: self._open_config_dialog(aid))
                act_lyt.addWidget(btn_config_row)

                self.account_table.setCellWidget(i, 3, act_widget)

                self._accounts_ui[acc_id] = {
                    "row": i,
                    "chk": chk_item,
                    "lbl_disk_stat": lbl_disk_stat,
                    "lbl_status": lbl_status,
                    "progress_bar": progress_bar,
                    "btn_start": btn_start,
                    "btn_config": btn_config_row,
                }

            self.lbl_stat_total.setText(f"📊 {len(accounts)} Hesap")
            self.lbl_stat_selected.setText("☑️ 0 Seçili")

            # Banner updating
            self.lbl_disk_status_icon.setText("⏳")
            self.lbl_disk_status_text.setText("💾 Diskten ve veritabanından istatistikler asenkron okunuyor... (Lütfen bekleyin)")

            # Launch Asynchronous Lazy Loader Worker (No UI Freeze)
            if self._loader_worker and self._loader_worker.isRunning():
                self._loader_worker.quit()
                self._loader_worker.wait()

            self._loader_worker = ExportDataLoaderWorker(self.engine, account_ids, self)
            self._loader_worker.account_loaded_signal.connect(self._on_worker_account_loaded)
            self._loader_worker.finished_signal.connect(self._on_worker_finished)
            self._loader_worker.start()

        except Exception as e:
            logger.exception("ExportPanel refresh error: %s", e)
        finally:
            self.account_table.blockSignals(False)
            self._is_refreshing = False

    @Slot(int, int, int)
    def _on_worker_account_loaded(self, aid: int, mails_cnt: int, folders_cnt: int):
        lbl = self._stats_labels_map.get(aid)
        if lbl:
            lbl.setText(f"📁 {folders_cnt} Klasör  •  📧 Yerel Arşiv: {mails_cnt:,} E-Posta")

    @Slot(dict)
    def _on_worker_finished(self, results: dict):
        total_mails = sum(r.get("mails", 0) for r in results.values())
        self.lbl_disk_status_icon.setText("✅")
        self.lbl_disk_status_text.setText(f"Veritabanı ve yerel arşiv hazır. Toplam {total_mails:,} arşivlenmiş e-posta.")
        self.card_size.set_value(f"{total_mails:,} E-Posta")

    # -----------------------------------------------------------------------
    # Filtering & Selection Handling
    # -----------------------------------------------------------------------

    @Slot()
    def _filter_table_rows(self):
        query = self.txt_search_export.text().strip().lower()
        active_group = self.left_sidebar.get_selected_group()
        total_cnt = self.account_table.rowCount()
        visible_cnt = 0

        for r in range(total_cnt):
            info_widget = self.account_table.cellWidget(r, 1)
            row_text = ""
            if info_widget:
                for lbl in info_widget.findChildren(QLabel):
                    row_text += " " + lbl.text().lower()

            matches_search = (not query) or (query in row_text)
            matches_group = (not active_group) or (active_group == "__ALL__") or (active_group == "Tümü") or (active_group.lower() in row_text)

            is_visible = matches_search and matches_group
            self.account_table.setRowHidden(r, not is_visible)
            if is_visible:
                visible_cnt += 1

        self.lbl_stat_total.setText(f"📊 {visible_cnt} / {total_cnt} Hesap")
        self._update_selection_count()

    @Slot(str)
    def _on_left_sidebar_group_selected(self, group_name: str):
        self._selected_group = group_name or "__ALL__"
        self._filter_table_rows()

    @Slot(QTableWidgetItem)
    def _on_table_item_changed(self, item: Optional[QTableWidgetItem] = None):
        self._update_selection_count()

    def _update_selection_count(self):
        selected_cnt = 0
        for i in range(self.account_table.rowCount()):
            item = self.account_table.item(i, 0)
            if item and item.checkState() == Qt.Checked:
                selected_cnt += 1
        self.lbl_stat_selected.setText(f"☑️ {selected_cnt} Seçili")

    def _get_active_row_account_id(self) -> Optional[int]:
        row = self.account_table.currentRow()
        if row >= 0:
            item = self.account_table.item(row, 0)
            if item:
                return item.data(Qt.UserRole)
        return None

    @Slot()
    def _on_table_row_click(self):
        rows = self.account_table.selectionModel().selectedRows()
        if rows:
            r = rows[0].row()
            info_widget = self.account_table.cellWidget(r, 1)
            if info_widget:
                labels = info_widget.findChildren(QLabel)
                if labels:
                    clean_text = labels[0].text().replace("<b>", "").replace("</b>", "").strip()
                    self.card_account.set_value(clean_text)

    # -----------------------------------------------------------------------
    # Layout Toggle Functions
    # -----------------------------------------------------------------------

    @Slot()
    def _toggle_left_sidebar(self):
        is_visible = self.left_sidebar.isVisible()
        self.left_sidebar.setVisible(not is_visible)
        self.btn_toggle_left.setText("▶ Grupları Göster" if is_visible else "◀ Grupları Gizle")
        self.btn_middle_toggle_left.setText("▶" if is_visible else "◀")
        self._auto_save_current_layout()

    @Slot()
    def _toggle_right_sidebar(self):
        is_visible = self.right_sidebar.isVisible()
        self.right_sidebar.setVisible(not is_visible)
        self.btn_toggle_right.setText("◀ İşlemler" if is_visible else "⚙️ İşlemler ▶")
        self.btn_middle_toggle_right.setText("◀" if is_visible else "▶")
        self._auto_save_current_layout()

    @Slot()
    def _toggle_log_visibility(self):
        is_vis = self.log_box.isVisible()
        self.log_box.setVisible(not is_vis)
        self.btn_toggle_log.setText("📋 Logu Aç" if is_vis else "📋 Log Kutusu")
        self._auto_save_current_layout()

    # -----------------------------------------------------------------------
    # Context Menu
    # -----------------------------------------------------------------------

    @Slot(QPoint)
    def _show_toya_grid_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px;
                font-size: 11.5px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2563eb;
                color: #ffffff;
            }
        """)

        act_export_sel = menu.addAction("⚡ Seçilenleri Dışa Aktar")
        act_export_sel.triggered.connect(self._export_selected)

        act_dry_run = menu.addAction("🔍 Inode / Önizleme Raporu...")
        act_dry_run.triggered.connect(self._dry_run_preview)

        menu.addSeparator()

        act_check_all = menu.addAction("☑️ Tümünü Seç")
        act_check_all.triggered.connect(lambda: self._set_all_checkboxes(True))

        act_uncheck_all = menu.addAction("⬜ Seçimleri Temizle")
        act_uncheck_all.triggered.connect(lambda: self._set_all_checkboxes(False))

        menu.addSeparator()

        act_config = menu.addAction("⚙️ Hedef & Filtreleri Yapılandır...")
        act_config.triggered.connect(self._open_config_dialog)

        h_menu = menu.addMenu("📏 Satır Yüksekliği")
        for h in [40, 60, 88, 110]:
            h_act = h_menu.addAction(f"{h} px {'(Varsayılan)' if h == 88 else ''}")
            h_act.triggered.connect(lambda chk=False, val=h: self.set_row_height(val))
        
        act_custom_h = h_menu.addAction("Özel Yükseklik...")
        act_custom_h.triggered.connect(self._open_custom_row_height_dialog)

        menu.addSeparator()

        act_cols = menu.addAction("👁️ Sütun Görünürlüğü (Kolon Aç/Kapa)...")
        act_cols.triggered.connect(self._open_column_manager)

        menu.exec(QCursor.pos())

    # -----------------------------------------------------------------------
    # Logging Operations
    # -----------------------------------------------------------------------

    @Slot(str)
    def _on_log_message(self, msg: str):
        now_str = datetime.now().strftime("%H:%M:%S")
        entry = LogEntry(now_str, "INFO", "Export", msg)
        self._log_model.append_entry(entry)
        self.label_page.setText(f"Sayfa {self._log_proxy.current_page() + 1} / {self._log_proxy.total_pages()}")

    @Slot(str)
    def _on_log_filter_changed(self, text: str):
        self._log_proxy.set_filter_text(text)
        self.label_page.setText(f"Sayfa {self._log_proxy.current_page() + 1} / {self._log_proxy.total_pages()}")

    @Slot(int)
    def _on_log_page_size_changed(self, idx: int):
        val = self.combo_page_size.currentText()
        size = 999999 if val == "Tümü" else int(val)
        self._log_proxy.set_page_size(size)
        self.label_page.setText(f"Sayfa {self._log_proxy.current_page() + 1} / {self._log_proxy.total_pages()}")

    @Slot()
    def _on_log_prev_page(self):
        curr = self._log_proxy.current_page()
        self._log_proxy.set_page(curr - 1)
        self.label_page.setText(f"Sayfa {self._log_proxy.current_page() + 1} / {self._log_proxy.total_pages()}")

    @Slot()
    def _on_log_next_page(self):
        curr = self._log_proxy.current_page()
        self._log_proxy.set_page(curr + 1)
        self.label_page.setText(f"Sayfa {self._log_proxy.current_page() + 1} / {self._log_proxy.total_pages()}")

    @Slot()
    def _on_log_clear(self):
        self._log_model.clear_entries()
        self.label_page.setText("Sayfa 1 / 1")

    # -----------------------------------------------------------------------
    # Export Operations & Background Workers
    # -----------------------------------------------------------------------

    def _get_selected_account_ids(self) -> List[int]:
        ids = []
        for i in range(self.account_table.rowCount()):
            item = self.account_table.item(i, 0)
            if item and item.checkState() == Qt.Checked:
                acc_id = item.data(Qt.UserRole)
                if acc_id is not None:
                    ids.append(acc_id)
        if not ids:
            active_id = self._get_active_row_account_id()
            if active_id is not None:
                ids.append(active_id)
        return ids

    def _set_all_checkboxes(self, state: bool):
        self.account_table.blockSignals(True)
        for r in range(self.account_table.rowCount()):
            if not self.account_table.isRowHidden(r):
                item = self.account_table.item(r, 0)
                if item:
                    item.setCheckState(Qt.Checked if state else Qt.Unchecked)
        self.account_table.blockSignals(False)
        self._update_selection_count()

    @Slot()
    def _toggle_select_all_checkboxes(self):
        self._all_selected_flag = not self._all_selected_flag
        self._set_all_checkboxes(self._all_selected_flag)

    @Slot(str)
    def _on_sidebar_format_changed(self, fmt: str):
        self._current_config["format"] = fmt
        self.card_format.set_value(fmt)
        self._on_log_message(f"Hedef aktarım biçimi değiştirildi: {fmt}")

    @Slot()
    def _open_config_dialog(self, account_id: Optional[int] = None):
        if account_id is None:
            checked = self._get_selected_account_ids()
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
            self.card_format.set_value(fmt)
            self._on_log_message("Dışa aktarım ayarları başarıyla güncellendi.")

    def _get_export_stats_for_checked(self, account_ids: List[int]) -> list:
        stats = []
        c = self._current_config
        folders = c.get("folders")
        since_date = c.get("since_date")
        before_date = c.get("before_date")
        fmt = c.get("format") or "ZIP"
        raw_path = c.get("target_path") or "data/exports"

        for aid in account_ids:
            acc = self.engine.accounts.get(aid)
            account_label = acc.get("label", f"Hesap #{aid}") if acc else f"Hesap #{aid}"

            conditions = ["account_id = ?", "is_deleted = 0"]
            params = [aid]
            
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

            raw_sub = acc.get("export_subfolder") or "" if acc else ""
            subfolder = re.sub(r'[\/:*?"<>|]', '_', raw_sub).strip()
            
            if fmt == "IMAP_SERVER":
                target_host = c.get("imap_host") or "Target IMAP"
                resolved_target = f"IMAP: {target_host} ({subfolder})" if subfolder else f"IMAP: {target_host}"
            else:
                path = Path(raw_path)
                if fmt == "DIRECTORY":
                    resolved_target = str(path / subfolder) if subfolder else str(path)
                else:
                    if path.suffix == "":
                        ext_map = {"ZIP": ".zip", "JSON": ".json", "MBOX": ".mbox", "PST": ".pst"}
                        filename = f"mails_{aid}{ext_map.get(fmt, '.zip')}"
                        path = path / filename
                    resolved_target = str(path.parent / subfolder / path.name) if subfolder else str(path)

            stats.append({
                "account_id": aid,
                "label": account_label,
                "folders": total_folders,
                "mails": total_mails,
                "format": fmt,
                "resolved_target": resolved_target,
                "config": c
            })
        return stats

    @Slot()
    def _dry_run_preview(self):
        checked = self._get_selected_account_ids()
        if not checked:
            checked = list(self._accounts_ui.keys())
        if not checked:
            QMessageBox.warning(self, "Hesap Bulunamadı", "Sistemde önizlenecek hesap bulunamadı.")
            return

        previews = self._get_export_stats_for_checked(checked)
        dlg = ExportConfirmDialog(previews, self)
        dlg.exec()

    @Slot()
    def _export_selected(self):
        checked = self._get_selected_account_ids()
        if not checked:
            QMessageBox.warning(self, "Hesap Seçilmedi", "Lütfen tablodan en az bir hesap işaretleyin.")
            return
        self._start_export_batch(checked)

    @Slot()
    def _export_all(self):
        all_ids = list(self._accounts_ui.keys())
        if not all_ids:
            QMessageBox.warning(self, "Hesap Yok", "Dışa aktarılacak hesap bulunamadı.")
            return
        self._start_export_batch(all_ids)

    @Slot()
    def _export_selected_group(self):
        active_group = self.left_sidebar.get_selected_group()
        if not active_group or active_group == "__ALL__" or active_group == "Tümü":
            self._export_selected()
            return
        
        group_ids = []
        for aid, ui in self._accounts_ui.items():
            if not self.account_table.isRowHidden(ui["row"]):
                group_ids.append(aid)
        
        if not group_ids:
            QMessageBox.warning(self, "Hesap Yok", f"'{active_group}' grubunda hesap bulunamadı.")
            return
        self._start_export_batch(group_ids)

    def _export_single_account(self, account_id: int):
        self._start_export_batch([account_id])

    def _start_export_batch(self, account_ids: List[int]):
        stats = self._get_export_stats_for_checked(account_ids)
        
        dialog = ExportConfirmDialog(stats, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        tasks = []
        for st in stats:
            aid = st["account_id"]
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
                    self._on_log_message(f"⚠️ Hesap ID {aid} atlanıyor: IMAP kimlik bilgileri eksik.")
                    continue
                try:
                    imap_port = int(port_str) if port_str else 993
                except ValueError:
                    self._on_log_message(f"⚠️ Hesap ID {aid} atlanıyor: Port biçim hatası.")
                    continue

            folders = c.get("folders")
            since_date = c.get("since_date")
            before_date = c.get("before_date")

            tasks.append({
                "acc_id": aid,
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

        self._session_reports.clear()
        self._is_paused = False
        self._pause_event.set()
        self._cancel_event.clear()

        self.btn_export.setEnabled(False)
        self.btn_export_all.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.right_sidebar.btn_pause.setEnabled(True)
        self.right_sidebar.btn_cancel.setEnabled(True)

        self.lbl_stat_active.setText(f"🟢 {len(tasks)} Aktarılıyor")
        self._on_log_message(f"=== {len(tasks)} adet hesap için dışa aktarım başlatılıyor ===")

        def run_all():
            try:
                for idx, task in enumerate(tasks):
                    if self._cancel_event.is_set():
                        break
                    
                    self._pause_event.wait()
                    aid = task["acc_id"]
                    
                    def make_cb(acc_id):
                        def cb(current, total, email_meta=None):
                            self._account_progress_signal.emit(acc_id, "Dışa Aktarılıyor", current, total, email_meta)
                        return cb

                    try:
                        report = self.engine.export_mails(
                            account_id=aid,
                            format_type=task["fmt"],
                            output_path=task["target_path"],
                            folders=task["folders"],
                            since_date=task["since_date"],
                            before_date=task["before_date"],
                            progress_callback=make_cb(aid),
                            imap_host=task["imap_host"],
                            imap_port=task["imap_port"],
                            imap_ssl=task["imap_ssl"],
                            imap_username=task["imap_username"],
                            imap_password=task["imap_password"],
                        )
                        self._account_export_done_signal.emit(aid, report)
                    except Exception as exc:
                        logger.exception("Export failed for account %d: %s", aid, exc)
                        self._account_export_error_signal.emit(aid, str(exc))

            finally:
                self._export_all_finished_signal.emit()

        threading.Thread(target=run_all, daemon=True).start()

    @Slot(int, str, int, int, object)
    def _on_account_progress(self, aid: int, status_text: str, current: int, total: int, email_meta: object):
        ui = self._accounts_ui.get(aid)
        if ui:
            ui["lbl_status"].setText(f"⏳ {status_text} ({current}/{total})")
            ui["progress_bar"].setRange(0, total if total > 0 else 100)
            ui["progress_bar"].setValue(current)
            left = max(0, total - current)
            ui["progress_bar"].setFormat(f"{current} / {left} Kaldı")
            self.card_progress.set_value(f"{current} / {total}")
            self.card_remaining.set_value(f"{left}")

        if email_meta and isinstance(email_meta, dict):
            subj = str(email_meta.get('subject', '') or '')[:30]
            self._on_log_message(f"[{aid}] Aktarıldı: {subj}")

    @Slot(int, object)
    def _on_account_export_done(self, aid: int, report: dict):
        ui = self._accounts_ui.get(aid)
        if ui:
            ui["lbl_status"].setText("✅ Tamamlandı")
            ui["progress_bar"].setRange(0, 100)
            ui["progress_bar"].setValue(100)
            ui["progress_bar"].setFormat("Tamamlandı")
        
        self._session_reports.append(report)
        exported = report.get('exported', 0) if isinstance(report, dict) else getattr(report, 'exported', 0)
        self._on_log_message(f"✅ Hesap ID {aid} aktarımı tamamlandı ({exported} e-posta).")

    @Slot(int, str)
    def _on_account_export_error(self, aid: int, err_msg: str):
        ui = self._accounts_ui.get(aid)
        if ui:
            ui["lbl_status"].setText("❌ Hata")
            ui["lbl_status"].setStyleSheet("color: #dc2626; font-weight: bold;")
        self._on_log_message(f"❌ Hesap ID {aid} aktarım hatası: {err_msg}")

    @Slot()
    def _on_export_all_finished(self):
        self.btn_export.setEnabled(True)
        self.btn_export_all.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.right_sidebar.btn_pause.setEnabled(False)
        self.right_sidebar.btn_cancel.setEnabled(False)
        self.lbl_stat_active.setText("🟢 0 Aktarılıyor")
        self.card_progress.set_value("Tamamlandı")

        if self._session_reports:
            dlg = ExportFinishedDialog(self)
            if dlg.exec() == QDialog.Accepted:
                self._show_reports()

    @Slot()
    def _toggle_pause_export(self):
        self._is_paused = not self._is_paused
        if self._is_paused:
            self._pause_event.clear()
            self.btn_pause.setText("▶️ Devam Et")
            self.right_sidebar.btn_pause.setText("▶️ Devam Et")
            self._on_log_message("⏸️ Aktarım işlemleri kullanıcı tarafından duraklatıldı.")
        else:
            self._pause_event.set()
            self.btn_pause.setText("⏸️ Duraklat")
            self.right_sidebar.btn_pause.setText("⏸️ Tümünü Duraklat")
            self._on_log_message("▶️ Aktarım işlemleri devam ettiriliyor.")

    @Slot()
    def _cancel_export(self):
        reply = QMessageBox.question(self, "İptal Et", "Aktif dışa aktarım işlemlerini iptal etmek istiyor musunuz?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._cancel_event.set()
            self._pause_event.set()
            self._on_log_message("⏹️ Aktarım iptal isteği gönderildi...")

    @Slot()
    def _show_reports(self):
        if not self._session_reports:
            QMessageBox.information(self, "Rapor Yok", "Bu oturumda henüz tamamlanmış bir dışa aktarım raporu bulunmuyor.")
            return
        dlg = ExportReportsDialog(self._session_reports, self)
        dlg.exec()

    @Slot()
    def _export_to_excel(self):
        path, _ = QFileDialog.getSaveFileName(self, "Excel / CSV Olarak Kaydet", "export_accounts.csv", "CSV Files (*.csv);;Excel Files (*.xlsx)")
        if not path:
            return
        try:
            import csv
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["Hesap ID", "Hesap Etiketi", "E-Posta", "Domain/Grup", "Klasör Sayısı", "Mail Sayısı"])
                accounts = self.engine.list_accounts()
                with self.engine.db.get_conn() as conn:
                    for acc in accounts:
                        aid = acc["id"]
                        row_m = conn.execute("SELECT COUNT(*) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (aid,)).fetchone()
                        row_f = conn.execute("SELECT COUNT(DISTINCT folder) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (aid,)).fetchone()
                        m_cnt = row_m["cnt"] if row_m else 0
                        f_cnt = row_f["cnt"] if row_f else 0
                        writer.writerow([aid, acc.get("label", ""), acc.get("email", ""), acc.get("account_group", ""), f_cnt, m_cnt])
            QMessageBox.information(self, "Başarılı", f"Hesap listesi başarıyla kaydedildi:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Dosya kaydedilemedi: {e}")

    @Slot()
    def _copy_all_emails_to_clipboard(self):
        accounts = self.engine.list_accounts()
        emails = [acc.get("email", "") for acc in accounts if acc.get("email")]
        if emails:
            QApplication.clipboard().setText("\n".join(emails))
            QMessageBox.information(self, "Kopyalandı", f"Toplam {len(emails)} adet e-posta adresi panoya kopyalandı.")
        else:
            QMessageBox.warning(self, "Bulunamadı", "Kopyalanacak e-posta adresi bulunamadı.")

    # -----------------------------------------------------------------------
    # Helper Button Styles
    # -----------------------------------------------------------------------

    @staticmethod
    def _toggle_btn_style() -> str:
        return """
            QPushButton {
                background-color: #f1f5f9;
                color: #1e293b;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11.5px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #e2e8f0; border-color: #94a3b8; }
        """

    @staticmethod
    def _badge_style(bg: str = "#e0e7ff", fg: str = "#1e3a8a") -> str:
        return f"""
            QLabel {{
                background-color: {bg};
                color: {fg};
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 700;
            }}
        """

    @staticmethod
    def _blue_btn_style(bg: str = "#2563eb", hover: str = "#1d4ed8", py: int = 4, px: int = 8, fs: float = 11) -> str:
        return f"""
            QPushButton {{
                background-color: {bg};
                color: #ffffff;
                font-weight: 700;
                font-size: {fs}px;
                padding: {py}px {px}px;
                border-radius: 6px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QPushButton:disabled {{
                background-color: #cbd5e1;
                color: #94a3b8;
            }}
        """
