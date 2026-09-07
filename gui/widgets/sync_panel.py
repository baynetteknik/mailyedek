"""
sync_panel.py — Email synchronization panel with detailed logging,
asynchronous (lazy load) disk & database scanner, multi-account background workers,
live row progress bars, and comprehensive reporting.
"""

import logging
import threading
import re
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
    QSpinBox, QMenu, QScrollArea, QApplication, QInputDialog,
    QRadioButton
)

from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.widgets.view_profile_widget import ViewProfileWidget, SaveLayoutProfileDialog, ColumnManagerDialog
from gui.widgets.account_group_sidebar_widget import AccountGroupSidebarWidget, CollapsibleSection
from gui.widgets.sync_right_sidebar_widget import SyncRightSidebarWidget

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

class SyncDataLoaderWorker(QThread):
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
            logger.debug("SyncDataLoaderWorker DB read exception: %s", e)
        finally:
            self.finished_signal.emit(results)


# ---------------------------------------------------------------------------
# Multi-Server Selection Dialog for Sync
# ---------------------------------------------------------------------------

class SelectSyncServerDialog(QDialog):
    """Modal dialog prompting the user to choose which server profile to synchronize from."""
    def __init__(self, account: Dict[str, Any], profiles: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.account = account
        self.profiles = profiles
        self.selected_profile_id: Optional[int] = None
        self.make_default: bool = False
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Sunucu Seçimi — Çoklu Sunucu Profili")
        self.resize(580, 360)
        self.setMinimumWidth(520)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
            }
            QLabel {
                color: #0f172a;
            }
            QGroupBox {
                font-weight: 600;
                color: #1e293b;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 16px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #2563eb;
            }
            QRadioButton {
                font-size: 12.5px;
                font-weight: 500;
                color: #1e293b;
                padding: 8px 10px;
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
            }
            QRadioButton:hover {
                background-color: #f1f5f9;
                border-color: #93c5fd;
            }
            QRadioButton:checked {
                background-color: #eff6ff;
                border-color: #3b82f6;
                font-weight: bold;
                color: #1d4ed8;
            }
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                font-weight: 700;
                font-size: 13px;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                min-width: 100px;
                min-height: 32px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            QPushButton#btn_cancel {
                background-color: #64748b;
            }
            QPushButton#btn_cancel:hover {
                background-color: #475569;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header Info
        header_layout = QHBoxLayout()
        icon_lbl = QLabel("🌐")
        icon_lbl.setStyleSheet("font-size: 32px; padding-right: 4px;")
        header_layout.addWidget(icon_lbl)

        acc_label = self.account.get("label", "Hesap")
        acc_email = self.account.get("email", "")
        title_lbl = QLabel(
            f"<b>{acc_label}</b> ({acc_email})<br>"
            "<span style='color: #64748b; font-size: 12px; font-weight: normal;'>"
            "Bu hesaba ait birden fazla sunucu profili bulunmaktadır. Hangi sunucudan senkronize olmak istiyorsunuz?</span>"
        )
        title_lbl.setStyleSheet("font-size: 13.5px; color: #0f172a;")
        title_lbl.setWordWrap(True)
        header_layout.addWidget(title_lbl, stretch=1)
        layout.addLayout(header_layout)

        # Profiles group
        group = QGroupBox("Kullanılabilir Sunucu Profilleri")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(12, 14, 12, 12)
        group_layout.setSpacing(8)

        self.radio_buttons = []
        for i, p in enumerate(self.profiles):
            is_default = bool(p.get("is_default"))
            host = p.get("imap_host", "")
            port = p.get("imap_port", 993)
            ssl_str = "SSL/TLS" if p.get("use_ssl") else "Plain"
            prof_name = p.get("profile_name", f"Sunucu #{p.get('id')}")

            def_badge = " [★ Varsayılan / Aktif]" if is_default else ""
            radio = QRadioButton()
            radio.setText(f"{prof_name} ({host}:{port} — {ssl_str}){def_badge}")
            radio.setProperty("profile_id", p.get("id"))

            # Default selection
            if is_default or (self.selected_profile_id is None and i == 0):
                radio.setChecked(True)
                self.selected_profile_id = p.get("id")

            radio.toggled.connect(self._on_radio_toggled)
            group_layout.addWidget(radio)
            self.radio_buttons.append(radio)

        layout.addWidget(group)

        # Make default checkbox
        self.chk_make_default = QCheckBox("⭐ Seçilen sunucuyu bu hesap için varsayılan (aktif) sunucu yap")
        self.chk_make_default.setStyleSheet("font-size: 12px; font-weight: 600; color: #1e293b; margin-top: 4px;")
        layout.addWidget(self.chk_make_default)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("İptal")
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_ok = QPushButton("⚡ Bu Sunucudan Senkronize Et")
        self.btn_ok.clicked.connect(self._on_accept)
        btn_layout.addWidget(self.btn_ok)

        layout.addLayout(btn_layout)

    def _on_radio_toggled(self, checked: bool):
        if checked:
            radio = self.sender()
            if radio:
                self.selected_profile_id = radio.property("profile_id")

    def _on_accept(self):
        for r in self.radio_buttons:
            if r.isChecked():
                self.selected_profile_id = r.property("profile_id")
                break
        self.make_default = self.chk_make_default.isChecked()
        self.accept()


# ---------------------------------------------------------------------------
# Reports popup dialog
# ---------------------------------------------------------------------------

class ReportsDialog(QDialog):
    def __init__(self, reports: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Senkronizasyon Sonuç Raporları")
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
        
        header_title = QLabel("📊 E-Posta Arşivleme ve Senkronizasyon Raporu")
        header_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        header_title.setStyleSheet("color: #0f172a;")
        layout.addWidget(header_title)
        
        total_accounts = len(reports)
        total_fetched = 0
        total_archived = 0
        total_updated = 0
        total_duplicates = 0
        total_errors = 0
        total_bytes = 0
        
        for r in reports:
            def g(k, d=None):
                return r.get(k, d) if isinstance(r, dict) else getattr(r, k, d)
            total_fetched += g("mails_fetched", 0)
            total_archived += g("mails_already_archived", 0)
            total_updated += g("mails_updated", 0)
            total_duplicates += g("duplicates_found", 0)
            total_errors += g("errors", 0)
            total_bytes += g("total_bytes", 0)
            
        summary_layout = QHBoxLayout()
        summary_layout.setSpacing(10)
        
        cards_data = [
            ("Toplam Hesap", str(total_accounts), "#2563eb"),
            ("Çekilen İletiler", str(total_fetched), "#10b981"),
            ("Mükerrer (Kopya)", str(total_duplicates), "#f59e0b"),
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
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels([
            "Hesap Adı", "Çekilen E-Posta", "Mevcut / Güncel", "Güncellenmiş", 
            "Mükerrer (Kopya)", "Hatalar", "Veri Boyutu", "Süre"
        ])
        
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 8):
            table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
            
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setRowCount(len(reports))
        
        for i, r in enumerate(reports):
            def g(k, d=None):
                return r.get(k, d) if isinstance(r, dict) else getattr(r, k, d)
                
            item_lbl = QTableWidgetItem(str(g("account_label", "")))
            item_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
            table.setItem(i, 0, item_lbl)
            
            fetched = g("mails_fetched", 0)
            item_fetched = QTableWidgetItem(str(fetched))
            if fetched > 0:
                item_fetched.setForeground(QColor("#10b981"))
                item_fetched.setFont(QFont("Segoe UI", 10, QFont.Bold))
            item_fetched.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 1, item_fetched)
            
            item_archived = QTableWidgetItem(str(g("mails_already_archived", 0)))
            item_archived.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 2, item_archived)
            
            item_updated = QTableWidgetItem(str(g("mails_updated", 0)))
            item_updated.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 3, item_updated)
            
            dupes = g("duplicates_found", 0)
            item_dupes = QTableWidgetItem(str(dupes))
            if dupes > 0:
                item_dupes.setForeground(QColor("#f59e0b"))
                item_dupes.setFont(QFont("Segoe UI", 10, QFont.Bold))
            item_dupes.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 4, item_dupes)
            
            errors = g("errors", 0)
            item_errors = QTableWidgetItem(str(errors))
            if errors > 0:
                item_errors.setForeground(QColor("#ef4444"))
                item_errors.setFont(QFont("Segoe UI", 10, QFont.Bold))
            item_errors.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 5, item_errors)
            
            bv = g("total_bytes", 0)
            item_bytes = QTableWidgetItem(self._fmt_bytes(bv))
            item_bytes.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 6, item_bytes)
            
            dur = g("duration_seconds", 0)
            item_dur = QTableWidgetItem(f"{dur:.1f}s")
            item_dur.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 7, item_dur)
            
        layout.addWidget(table)

        all_error_details = []
        for r in reports:
            def g(k, d=None):
                return r.get(k, d) if isinstance(r, dict) else getattr(r, k, d)
            details = g("error_details", [])
            if details:
                if isinstance(details, list):
                    all_error_details.extend(details)
                elif isinstance(details, str):
                    all_error_details.append(details)
            err_single = g("error", None)
            if err_single:
                all_error_details.append(str(err_single))

        if all_error_details or total_errors > 0:
            lbl_err_title = QLabel(f"⚠️ Hata Detayları ({len(all_error_details) or total_errors} Adet):")
            lbl_err_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
            lbl_err_title.setStyleSheet("color: #dc2626; margin-top: 4px;")
            layout.addWidget(lbl_err_title)

            err_box = QTextEdit()
            err_box.setReadOnly(True)
            err_box.setMaximumHeight(100)
            err_box.setStyleSheet("""
                QTextEdit {
                    background-color: #fef2f2;
                    color: #991b1b;
                    border: 1px solid #fca5a5;
                    border-radius: 6px;
                    font-size: 11px;
                    padding: 6px;
                }
            """)
            if all_error_details:
                err_box.setPlainText("\n".join(f"• {e}" for e in all_error_details))
            else:
                err_box.setPlainText(f"• Toplam {total_errors} adet senkronizasyon hatası oluştu.")
            layout.addWidget(err_box)
        
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
# Detailed diagnostics report popup dialog
# ---------------------------------------------------------------------------

class DetailedReportDialog(QDialog):
    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Detaylı Sistem ve Klasör Teşhis Raporu")
        self.resize(780, 540)
        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
            }
            QLabel {
                color: #0f172a;
            }
            QTextEdit {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-family: Consolas, Monaco, monospace;
                font-size: 11.5px;
                color: #1e293b;
            }
            QPushButton {
                background-color: #2563eb;
                color: white;
                font-weight: 600;
                padding: 8px 18px;
                border-radius: 6px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        info_label = QLabel("<b>Sistem Teşhisi & Klasör İstatistik Raporu</b>")
        info_label.setStyleSheet("color: #0f172a; font-size: 13px;")
        layout.addWidget(info_label)
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setAcceptRichText(False)
        layout.addWidget(self.text_edit)
        
        btn_layout = QHBoxLayout()
        self.btn_copy = QPushButton("📋 Raporu Panoya Kopyala")
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        
        self.btn_close = QPushButton("Kapat")
        self.btn_close.setStyleSheet("background-color: #64748b;")
        self.btn_close.clicked.connect(self.accept)
        
        btn_layout.addWidget(self.btn_copy)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)
        
        self._generate_report()

    def _generate_report(self):
        stats = self.engine.get_stats()
        accounts = self.engine.list_accounts()
        db_path = self.engine.db._db_path
        
        report_lines = []
        report_lines.append("# MAIL ARCHIVE DIAGNOSTICS REPORT")
        report_lines.append(f"Oluşturulma Zamanı: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("---")
        report_lines.append("## 1. Sistem ve Veritabanı Yolları")
        report_lines.append(f"- Veritabanı Dosyası: {db_path}")
        report_lines.append(f"- Veritabanı Boyutu: {self._fmt_size(db_path.stat().st_size) if db_path.exists() else 'N/A'}")
        report_lines.append(f"- Ek Dosyalar Klasörü: {db_path.parent / 'attachments'}")
        
        report_lines.append("\n## 2. Genel İstatistikler")
        report_lines.append(f"- Toplam Hesap: {stats.get('total_accounts', len(accounts))}")
        report_lines.append(f"- Arşivlenmiş Toplam E-Posta: {stats.get('total_emails', 0):,}")
        report_lines.append(f"- Toplam Ek Dosya Sayısı: {stats.get('total_attachments', 0):,}")
        report_lines.append(f"- Arşiv Boyutu: {self._fmt_size(stats.get('total_size_bytes', 0))}")
        
        report_lines.append("\n## 3. Hesap ve Klasör Dağılımı")
        for acc in accounts:
            report_lines.append(f"\n### Hesap: {acc.get('label', '?')} ({acc.get('email', '?')})")
            report_lines.append(f"- Sunucu: {acc.get('imap_host', '?')}:{acc.get('imap_port', 993)}")
            report_lines.append(f"- Durum: {'Aktif' if acc.get('is_active', 1) else 'Pasif'}")
            
            try:
                with self.engine.db.get_conn() as conn:
                    folder_states = conn.execute(
                        "SELECT folder, last_uid, uid_validity, last_sync_at FROM sync_state WHERE account_id=?",
                        (acc["id"],)
                    ).fetchall()
                    
                    folder_counts = {}
                    counts_cursor = conn.execute(
                        "SELECT folder, COUNT(*) FROM mail_metadata WHERE account_id=? AND is_deleted=0 GROUP BY folder",
                        (acc["id"],)
                    ).fetchall()
                    for f, c in counts_cursor:
                        folder_counts[f] = c
            except Exception as e:
                folder_states = []
                folder_counts = {}
                report_lines.append(f"- Klasörler okunamadı: {e}")
            
            if folder_states:
                report_lines.append("| Klasör Adı | Arşivlenmiş Adet | Son UID | UID Geçerlilik | Son Senkronizasyon |")
                report_lines.append("| --- | --- | --- | --- | --- |")
                for folder, last_uid, uid_validity, last_sync_at in folder_states:
                    count = folder_counts.get(folder, 0)
                    report_lines.append(f"| {folder} | {count} | {last_uid} | {uid_validity} | {last_sync_at} |")
            else:
                report_lines.append("- Henüz senkronize edilmiş klasör bulunmuyor.")
        
        self.text_edit.setPlainText("\n".join(report_lines))

    def _fmt_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.2f} GB"

    def _copy_to_clipboard(self):
        from PySide6.QtGui import QGuiApplication
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.text_edit.toPlainText())
        QMessageBox.information(self, "Kopyalandı", "Teşhis raporu panoya kopyalandı!")


# ---------------------------------------------------------------------------
# Folders & Advanced Filters Dialog (Pop-up)
# ---------------------------------------------------------------------------

class FiltersDialog(QDialog):
    _refresh_done_signal = Signal(list, object)

    def __init__(self, account_label: str, folders: list, selected_folders: list, archive_unread: bool,
                 since_date_enabled: bool, since_date: QDate,
                 before_date_enabled: bool, before_date: QDate,
                 timeout: int, engine: MailEngine = None, account_id: int = None, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.account_id = account_id
        
        self.setWindowTitle(f"Arşivleme Filtreleri: {account_label}")
        self.resize(920, 600)
        self.setStyleSheet("QDialog { background-color: #f8fafc; color: #0f172a; }")
        
        self._refresh_done_signal.connect(self._on_refresh_done_gui)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        
        # Header Info
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(16, 12, 16, 12)
        
        info_icon = QLabel("⚙️")
        info_icon.setStyleSheet("font-size: 24px;")
        header_layout.addWidget(info_icon)
        
        info_text = QLabel(
            f"<b>Hesap:</b> <span style='color:#2563eb;'>{account_label}</span><br/>"
            f"<span style='color: #64748b; font-size: 11.5px;'>Bu pencerede yapılacak filtre ayarları yalnızca bu hesaba uygulanacaktır.</span>"
        )
        info_text.setStyleSheet("color: #1e293b; font-size: 13px;")
        header_layout.addWidget(info_text, stretch=1)
        layout.addWidget(header_frame)
        
        body_layout = QHBoxLayout()
        body_layout.setSpacing(14)
        
        # LEFT COLUMN: Folders
        folders_group = QGroupBox("Arşivlenecek Klasörleri Seçin")
        folders_group.setStyleSheet("""
            QGroupBox {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 10px;
                font-weight: bold;
                font-size: 11.5px;
                color: #1e3a8a;
            }
        """)
        fg_layout = QVBoxLayout(folders_group)
        fg_layout.setContentsMargins(12, 16, 12, 12)
        fg_layout.setSpacing(8)
        
        self.folder_list = QListWidget()
        self.folder_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.folder_list.setStyleSheet("""
            QListWidget {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-size: 12px;
                color: #0f172a;
            }
            QListWidget::item {
                padding: 6px 8px;
            }
        """)
        
        for f in folders:
            item = QListWidgetItem(f)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            if f in selected_folders:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.folder_list.addItem(item)
            
        fg_layout.addWidget(self.folder_list)
        
        btns_folder = QHBoxLayout()
        btn_sel_all = QPushButton("Tümünü Seç")
        btn_sel_all.setStyleSheet(self._filter_btn_style())
        btn_sel_all.clicked.connect(self._select_all_folders)
        
        btn_sel_none = QPushButton("Seçimi Temizle")
        btn_sel_none.setStyleSheet(self._filter_btn_style())
        btn_sel_none.clicked.connect(self._select_none_folders)
        
        self.btn_refresh_server = QPushButton("🔄 Sunucudan Yenile")
        self.btn_refresh_server.setStyleSheet("""
            QPushButton {
                background: #f1f5f9;
                color: #2563eb;
                border: 1px solid #cbd5e1;
                font-weight: 600;
                padding: 5px 12px;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #e2e8f0;
            }
        """)
        self.btn_refresh_server.clicked.connect(self._refresh_folders_from_server)
        
        btns_folder.addWidget(btn_sel_all)
        btns_folder.addWidget(btn_sel_none)
        btns_folder.addStretch()
        btns_folder.addWidget(self.btn_refresh_server)
        fg_layout.addLayout(btns_folder)
        
        body_layout.addWidget(folders_group, stretch=2)
        
        # RIGHT COLUMN: Advanced Filters
        filters_group = QGroupBox("Gelişmiş Arşivleme Filtreleri")
        filters_group.setStyleSheet(folders_group.styleSheet())
        filters_layout = QVBoxLayout(filters_group)
        filters_layout.setContentsMargins(14, 18, 14, 14)
        filters_layout.setSpacing(12)
        
        self.chk_archive_unread = QCheckBox("Okunmamış iletileri de arşivle")
        self.chk_archive_unread.setChecked(archive_unread)
        self.chk_archive_unread.setStyleSheet("color: #0f172a; font-size: 12px; font-weight: 500;")
        filters_layout.addWidget(self.chk_archive_unread)
        
        since_layout = QVBoxLayout()
        self.chk_since_date = QCheckBox("Şu tarihten yeni iletiler:")
        self.chk_since_date.setChecked(since_date_enabled)
        self.chk_since_date.setStyleSheet("color: #0f172a; font-size: 12px; font-weight: 500;")
        self.date_edit_since = QDateEdit()
        self.date_edit_since.setCalendarPopup(True)
        self.date_edit_since.setDate(since_date)
        self.date_edit_since.setEnabled(since_date_enabled)
        self.chk_since_date.toggled.connect(self.date_edit_since.setEnabled)
        since_layout.addWidget(self.chk_since_date)
        since_layout.addWidget(self.date_edit_since)
        filters_layout.addLayout(since_layout)
        
        before_layout = QVBoxLayout()
        self.chk_before_date = QCheckBox("Şu tarihten eski iletiler:")
        self.chk_before_date.setChecked(before_date_enabled)
        self.chk_before_date.setStyleSheet("color: #0f172a; font-size: 12px; font-weight: 500;")
        self.date_edit_before = QDateEdit()
        self.date_edit_before.setCalendarPopup(True)
        self.date_edit_before.setDate(before_date)
        self.date_edit_before.setEnabled(before_date_enabled)
        self.chk_before_date.toggled.connect(self.date_edit_before.setEnabled)
        before_layout.addWidget(self.chk_before_date)
        before_layout.addWidget(self.date_edit_before)
        filters_layout.addLayout(before_layout)
        
        timeout_layout = QVBoxLayout()
        lbl_timeout = QLabel("Zaman Aşımı Süresi (Saniye):")
        lbl_timeout.setStyleSheet("color: #0f172a; font-size: 11.5px; font-weight: 500;")
        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(30, 3600)
        self.spin_timeout.setValue(timeout)
        timeout_layout.addWidget(lbl_timeout)
        timeout_layout.addWidget(self.spin_timeout)
        filters_layout.addLayout(timeout_layout)
        
        filters_layout.addStretch()
        body_layout.addWidget(filters_group, stretch=1)
        layout.addLayout(body_layout)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        
    def _select_all_folders(self):
        for i in range(self.folder_list.count()):
            self.folder_list.item(i).setCheckState(Qt.Checked)
            
    def _select_none_folders(self):
        for i in range(self.folder_list.count()):
            self.folder_list.item(i).setCheckState(Qt.Unchecked)
            
    def get_selected_folders(self) -> list:
        folders = []
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            if item.checkState() == Qt.Checked:
                folders.append(item.text())
        return folders

    def _refresh_folders_from_server(self):
        if not self.engine or not self.account_id:
            return
            
        self.btn_refresh_server.setEnabled(False)
        self.btn_refresh_server.setText("⏳ Yükleniyor...")
        
        def task():
            try:
                acc = self.engine.accounts.get(self.account_id)
                if not acc:
                    self._refresh_done_signal.emit([], "Hesap bulunamadı.")
                    return
                    
                from plugins.provider_registry import ProviderRegistry
                from infrastructure.imap_client import ImapClient
                
                provider = ProviderRegistry().get_mail_provider(acc.get("provider_type", "imap")) or ImapClient()
                username = self.engine.crypto.decrypt(acc["username_enc"])
                password = self.engine.crypto.decrypt(acc["password_enc"])
                
                if provider.connect(acc["imap_host"], acc["imap_port"], bool(acc["use_ssl"]), username, password):
                    raw_folders = provider.list_folders()
                    provider.disconnect()
                    folder_names = [name for flags, name in raw_folders]
                    self._refresh_done_signal.emit(folder_names, None)
                else:
                    self._refresh_done_signal.emit([], "Sunucuya bağlanılamadı.")
            except Exception as e:
                self._refresh_done_signal.emit([], str(e))
                
        threading.Thread(target=task, daemon=True).start()

    @Slot(list, object)
    def _on_refresh_done_gui(self, folder_names, error):
        self.btn_refresh_server.setEnabled(True)
        self.btn_refresh_server.setText("🔄 Sunucudan Yenile")
        
        if error:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Bağlantı Hatası")
            msg.setText(f"Klasör listesi sunucudan alınamadı:\n{error}")
            msg.setStyleSheet(GLOBAL_MSG_STYLE)
            msg.exec()
            return
            
        if not folder_names:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Information)
            msg.setWindowTitle("Bilgi")
            msg.setText("Sunucuda hiç klasör bulunamadı.")
            msg.setStyleSheet(GLOBAL_MSG_STYLE)
            msg.exec()
            return
            
        self.folder_list.clear()
        for f in folder_names:
            item = QListWidgetItem(f)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.folder_list.addItem(item)
            
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Başarılı")
        msg.setText(f"Sunucudan {len(folder_names)} klasör başarıyla yüklendi!")
        msg.setStyleSheet(GLOBAL_MSG_STYLE)
        msg.exec()

    @staticmethod
    def _filter_btn_style():
        return """
            QPushButton {
                background: #e2e8f0;
                color: #334155;
                font-weight: 600;
                padding: 5px 10px;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #cbd5e1;
            }
        """


# ---------------------------------------------------------------------------
# Background Dry Run Worker
# ---------------------------------------------------------------------------

class DryRunWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(list)
    
    def __init__(self, engine, settings, ids, table_data, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings
        self.ids = ids
        self.table_data = table_data
        self.is_cancelled = False
        
    def run(self):
        previews = []
        try:
            for acc_id in self.ids:
                if self.is_cancelled:
                    break
                    
                acc_data = self.table_data.get(acc_id, f"Hesap #{acc_id}")
                acc = self.engine.accounts.get(acc_id) or {}
                
                db_path = str(self.engine.db._db_path)
                stor_name = self.settings.account_storage(acc_id)
                base_path = self.engine.db._db_path.parent
                if stor_name:
                    for loc in self.settings.storage_locations():
                        if loc.name == stor_name:
                            base_path = Path(loc.path)
                            break
                            
                group_val = acc.get("account_group", "").strip()
                if not group_val and "@" in acc.get("email", ""):
                    group_val = acc["email"].split("@")[-1]
                group_clean = re.sub(r'[\/:*?"<>|]', '_', group_val).strip()

                raw_sub = acc.get("export_subfolder") or ""
                subfolder = re.sub(r'[\/:*?"<>|]', '_', raw_sub).strip()
                
                parts = [base_path, "attachments"]
                if group_clean:
                    parts.append(group_clean)
                if subfolder and subfolder != ".":
                    parts.append(subfolder)
                attachments_dir = str(Path(*parts))

                f_data = self.settings.account_sync_filters(acc_id) or {}
                folder_filter = f_data.get("folders")
                since_date_enabled = f_data.get("since_date_enabled", False)
                since_date = f_data.get("since_date") if since_date_enabled else None
                before_date_enabled = f_data.get("before_date_enabled", False)
                before_date = f_data.get("before_date") if before_date_enabled else None
                archive_unread = f_data.get("archive_unread", True)

                self.progress_signal.emit(f"<b>{acc_data}:</b><br/>Bağlantı kuruluyor...")

                def log_cb(msg):
                    if self.is_cancelled:
                        raise InterruptedError("Cancelled")
                    clean_msg = msg.replace("  Checking folder", "Klasör kontrol ediliyor:").replace("Connected. Listing folders...", "Bağlanıldı, klasörler listeleniyor...")
                    self.progress_signal.emit(f"<b>{acc_data}:</b><br/>{clean_msg}")

                try:
                    result = self.engine.sync_dry_run(
                        acc_id,
                        log_callback=log_cb,
                        folder_filter=folder_filter,
                        since_date=since_date,
                        before_date=before_date,
                        archive_unread=archive_unread,
                        timeout=15
                    )
                    if self.is_cancelled:
                        break
                        
                    folders = result.get("folders", [])
                    new_mails = result.get("total_estimated", 0)
                    err = result.get("error")
                    
                    folder_details = ", ".join(f"{f['folder']} ({f['new_mails']})" for f in folders if f.get("new_mails", 0) > 0)
                    if not folder_details:
                        folder_details = "Yeni mail yok (Tüm klasörler güncel)"
                    
                    previews.append({
                        "label": result.get("account", acc_data),
                        "folder_count": len(folders),
                        "folder_details": folder_details,
                        "db_path": db_path,
                        "attachments_dir": attachments_dir,
                        "new_mails": new_mails,
                        "error": err,
                        "since_date": since_date,
                        "before_date": before_date,
                        "archive_unread": archive_unread,
                        "folders_list": folders,
                        "email": result.get("email", ""),
                        "target_dir": result.get("target_dir", ""),
                    })
                except InterruptedError:
                    break
                except Exception as exc:
                    previews.append({
                        "label": acc_data,
                        "folder_count": 0,
                        "folder_details": "Bağlantı hatası",
                        "db_path": db_path,
                        "attachments_dir": attachments_dir,
                        "new_mails": 0,
                        "error": str(exc),
                        "since_date": since_date,
                        "before_date": before_date,
                        "archive_unread": archive_unread,
                        "folders_list": [],
                    })
        except Exception as e:
            logger.exception("DryRunWorker error: %s", e)
        finally:
            self.finished_signal.emit(previews)


# ---------------------------------------------------------------------------
# High Contrast, Modern Sync Confirmation Dialog
# ---------------------------------------------------------------------------

class SyncConfirmDialog(QDialog):
    def __init__(self, account_previews: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Senkronizasyon & Arşivleme Önizleme Raporu")
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
        
        header_icon = QLabel("🚀")
        header_icon.setStyleSheet("font-size: 28px; background: transparent; border: none;")
        header_layout.addWidget(header_icon)
        
        header_text_vbox = QVBoxLayout()
        header_text_vbox.setSpacing(2)
        
        title_lbl = QLabel("SENKRONİZASYON & ARŞİVLEME ÖNİZLEME RAPORU")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #1e3a8a; background: transparent; border: none;")
        
        subtitle_lbl = QLabel("Aşağıdaki hesap ve klasör ayarları sunucu ile eşleştirilecek ve yeni e-postalar yerel arşive indirilecektir.")
        subtitle_lbl.setStyleSheet("font-size: 11.5px; color: #64748b; background: transparent; border: none;")
        
        header_text_vbox.addWidget(title_lbl)
        header_text_vbox.addWidget(subtitle_lbl)
        header_layout.addLayout(header_text_vbox, stretch=1)
        layout.addWidget(header_frame)
        
        # 2. Summary KPI Cards
        total_accounts = len(self.previews)
        total_estimated_mails = sum(p.get("new_mails", 0) for p in self.previews)
        total_folders = sum(len(p.get("folders_list", [])) or p.get("folder_count", 0) for p in self.previews)
        
        kpi_layout = QHBoxLayout()
        kpi_layout.setSpacing(10)
        
        kpi_data = [
            ("Seçilen Hesap", f"{total_accounts} Adet", "#2563eb", "👥"),
            ("Taranacak Klasör", f"{total_folders} Klasör", "#0284c7", "📁"),
            ("Tahmini Yeni Mail", f"{total_estimated_mails:,} E-Posta", "#10b981", "✉️"),
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
            new_cnt = p.get("new_mails", 0)
            item = QListWidgetItem(f"👤 {lbl_text} ({new_cnt} yeni)")
            item.setData(Qt.UserRole, idx)
            self.account_list_widget.addItem(item)
            
        self.account_list_widget.currentRowChanged.connect(self._load_preview)
        left_layout.addWidget(self.account_list_widget)
        body_layout.addWidget(left_box, stretch=1)
        
        right_box = QGroupBox("Seçili Hesap Klasör ve Hedef Detayları")
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
        
        self.lbl_date_range_details = QLabel("<b>Tarih Filtresi:</b> Tüm Zamanlar   •   <b>Okunmamış:</b> Dahil")
        self.lbl_date_range_details.setStyleSheet("font-size: 11.5px; color: #334155; background: transparent; border: none;")
        
        self.lbl_target_path_details = QLabel("<b>Yedekleme Dizini:</b> —")
        self.lbl_target_path_details.setStyleSheet("font-size: 11.5px; color: #334155; background: transparent; border: none;")
        self.lbl_target_path_details.setWordWrap(True)
        
        info_bar_lyt.addWidget(self.lbl_acc_name_details)
        info_bar_lyt.addWidget(self.lbl_date_range_details)
        info_bar_lyt.addWidget(self.lbl_target_path_details)
        right_layout.addWidget(info_bar)
        
        self.folders_table = QTableWidget()
        self.folders_table.setColumnCount(3)
        self.folders_table.setHorizontalHeaderLabels(["Klasör Adı", "Tahmini Yeni Mail", "Durum"])
        self.folders_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.folders_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.folders_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.folders_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.folders_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.folders_table.setAlternatingRowColors(True)
        self.folders_table.verticalHeader().setVisible(False)
        right_layout.addWidget(self.folders_table)
        
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
        
        btn_ok = QPushButton("⚡ Senkronizasyonu Başlat")
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
        email = p.get("email", "")
        
        self.lbl_acc_name_details.setText(f"<b>Hesap:</b> <span style='color:#2563eb;'>{acc_label}</span> ({email})")
        
        since_d = p.get("since_date")
        before_d = p.get("before_date")
        unread = "Dahil" if p.get("archive_unread", True) else "Yalnızca Okunmuş"
        
        date_str = "Tüm Zamanlar"
        if since_d and before_d:
            date_str = f"{since_d} ile {before_d} Arası"
        elif since_d:
            date_str = f"{since_d} Sonrası"
        elif before_d:
            date_str = f"{before_d} Öncesi"
            
        self.lbl_date_range_details.setText(f"<b>Tarih Filtresi:</b> {date_str}   •   <b>Okunmamış Mailler:</b> {unread}")
        self.lbl_target_path_details.setText(f"<b>Yedekleme Dizini:</b> <span style='color:#0f172a;'>{p.get('attachments_dir') or p.get('target_dir') or 'Varsayılan Depolama Alanı'}</span>")
        
        folders_list = p.get("folders_list", [])
        self.folders_table.setRowCount(len(folders_list))
        
        for row, f in enumerate(folders_list):
            f_name = f.get("folder", "?")
            new_cnt = f.get("new_mails", 0)
            
            it_name = QTableWidgetItem(f"📁 {f_name}")
            it_name.setFont(QFont("Segoe UI", 10, QFont.Bold))
            self.folders_table.setItem(row, 0, it_name)
            
            it_cnt = QTableWidgetItem(f"{new_cnt} Yeni Mail" if new_cnt > 0 else "0 (Güncel)")
            if new_cnt > 0:
                it_cnt.setForeground(QColor("#16a34a"))
                it_cnt.setFont(QFont("Segoe UI", 10, QFont.Bold))
            else:
                it_cnt.setForeground(QColor("#64748b"))
            it_cnt.setTextAlignment(Qt.AlignCenter)
            self.folders_table.setItem(row, 1, it_cnt)
            
            status_str = "Aktarılacak" if new_cnt > 0 else "Tamamı Yedekli"
            it_status = QTableWidgetItem(status_str)
            it_status.setTextAlignment(Qt.AlignCenter)
            self.folders_table.setItem(row, 2, it_status)


class SyncFinishedDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("İşlem Tamamlandı")
        self.setMinimumWidth(440)
        self.setStyleSheet(GLOBAL_MSG_STYLE)

        self._remaining_seconds = 5

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        lbl_title = QLabel("✅ E-Posta Arşivleme İşlemi Tamamlandı!")
        lbl_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_title.setStyleSheet("color: #10b981;")
        layout.addWidget(lbl_title)

        lbl_msg = QLabel("Detaylı senkronizasyon raporunu görüntülemek ister misiniz?")
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
# Main SyncPanel (Default 88px row height & Async Lazy Load)
# ---------------------------------------------------------------------------

_LOG_PARSE_RE = re.compile(r'^\[(\d+:\d+:\d+)\]\s*(.*)')


class SyncPanel(QWidget):
    """Email synchronization panel with detailed logging, lazy loading, and ergonomic UX."""

    _log_signal = Signal(str)
    _folders_signal = Signal(list)
    _account_progress_signal = Signal(int, str, int, int)
    _account_sync_done_signal = Signal(int, object)
    _account_sync_error_signal = Signal(int, str)
    _account_dry_run_done_signal = Signal(int, int, object)

    def __init__(self, engine: MailEngine, parent=None, settings: AppSettings = None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings or AppSettings()
        self._reports: list = []
        self._all_selected_flag = False
        self._current_row_height = 88  # Default 88px as requested
        self._is_refreshing = False
        self._selected_group = "__ALL__"
        self._data_loader: Optional[SyncDataLoaderWorker] = None
        self._stats_labels_map: Dict[int, QLabel] = {}

        self._log_model = LogTableModel(self)
        self._log_proxy = LogFilterProxy(self)
        self._log_proxy.setSourceModel(self._log_model)
        
        self._active_syncs = {}  # account_id -> {cancel_event, pause_event, thread, status}
        self._accounts_ui = {}   # account_id -> {chk, lbl_status, progress_bar, btn_start, etc.}

        self._setup_ui()
        self._connect_signals()
        
        # Internal Signals
        self._log_signal.connect(self._on_log_message)
        self._account_progress_signal.connect(self._on_account_progress)
        self._account_sync_done_signal.connect(self._on_account_sync_done)
        self._account_sync_error_signal.connect(self._on_account_sync_error)
        self._account_dry_run_done_signal.connect(self._on_account_dry_run_done)

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
        self.txt_search_sync = QLineEdit()
        self.txt_search_sync.setPlaceholderText("🔍 Hesap Adı, E-Posta veya Domain Grubu Ara...")
        self.txt_search_sync.setClearButtonEnabled(True)
        self.txt_search_sync.setStyleSheet("""
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
        self.txt_search_sync.textChanged.connect(self._filter_table_rows)
        top_layout.addWidget(self.txt_search_sync, stretch=1)

        # Statistics Badges
        self.lbl_stat_total = QLabel("📊 0 Hesap")
        self.lbl_stat_total.setStyleSheet(self._badge_style(bg="#e0e7ff", fg="#1e3a8a"))
        top_layout.addWidget(self.lbl_stat_total)

        self.lbl_stat_selected = QLabel("☑️ 0 Seçili")
        self.lbl_stat_selected.setStyleSheet(self._badge_style(bg="#fef3c7", fg="#b45309"))
        top_layout.addWidget(self.lbl_stat_selected)

        self.lbl_stat_active = QLabel("🟢 0 Çalışıyor")
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
        center_container = QGroupBox("🔄 E-Posta Senkronizasyon & Arşivleme Havuzu")
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
        self.card_current = StatCard("Mevcut Klasör", "—", "📁")
        self.card_remaining = StatCard("Kalan E-Posta", "—", "⏳")
        self.card_progress = StatCard("İlerleme", "—", "📈")
        self.card_eta = StatCard("Tahmini Süre", "—", "⏱️")
        self.card_server = StatCard("Yerel Arşiv", "—", "💾")

        stats_lyt.addWidget(self.card_account)
        stats_lyt.addWidget(self.card_current)
        stats_lyt.addWidget(self.card_remaining)
        stats_lyt.addWidget(self.card_progress)
        stats_lyt.addWidget(self.card_eta)
        stats_lyt.addWidget(self.card_server)
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

        self.btn_sync = QPushButton("⚡ Seçilenleri Başlat")
        self.btn_sync.setToolTip("Seçili kutucuğu işaretli tüm hesapların senkronizasyonunu başlatır")
        self.btn_sync.setCursor(Qt.PointingHandCursor)
        self.btn_sync.setStyleSheet(self._blue_btn_style(bg="#2563eb", hover="#1d4ed8", py=5, px=10, fs=11))
        self.btn_sync.clicked.connect(self._sync_selected)
        actions_bar_lyt.addWidget(self.btn_sync)

        self.btn_sync_all = QPushButton("🚀 Tümünü Başlat")
        self.btn_sync_all.setToolTip("Sistemdeki tüm hesapları senkronize eder")
        self.btn_sync_all.setCursor(Qt.PointingHandCursor)
        self.btn_sync_all.setStyleSheet(self._blue_btn_style(bg="#059669", hover="#047857", py=5, px=10, fs=11))
        self.btn_sync_all.clicked.connect(self._sync_all)
        actions_bar_lyt.addWidget(self.btn_sync_all)

        self.btn_pause = QPushButton("⏸️ Duraklat")
        self.btn_pause.setToolTip("Aktif arşiv işlemlerini duraklatır")
        self.btn_pause.setCursor(Qt.PointingHandCursor)
        self.btn_pause.setStyleSheet(self._blue_btn_style(bg="#f59e0b", hover="#d97706", py=5, px=10, fs=11))
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._toggle_pause_sync)
        actions_bar_lyt.addWidget(self.btn_pause)

        self.btn_cancel = QPushButton("⏹️ İptal Et")
        self.btn_cancel.setToolTip("Aktif arşiv işlemlerini iptal eder")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setStyleSheet(self._blue_btn_style(bg="#dc2626", hover="#b91c1c", py=5, px=10, fs=11))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_sync)
        actions_bar_lyt.addWidget(self.btn_cancel)

        self.btn_dry_run = QPushButton("🔍 Kuru Çalıştırma")
        self.btn_dry_run.setToolTip("Sunucuya bağlanıp taranacak tahmini mail sayısını hesaplar")
        self.btn_dry_run.setCursor(Qt.PointingHandCursor)
        self.btn_dry_run.setStyleSheet(self._blue_btn_style(bg="#475569", hover="#334155", py=5, px=10, fs=11))
        self.btn_dry_run.clicked.connect(self._dry_run)
        actions_bar_lyt.addWidget(self.btn_dry_run)

        self.btn_filters = QPushButton("⚙️ Klasör & Filtreler...")
        self.btn_filters.setToolTip("Hesap için arşivlenecek klasörleri ve filtreleri ayarlar")
        self.btn_filters.setCursor(Qt.PointingHandCursor)
        self.btn_filters.setStyleSheet(self._blue_btn_style(bg="#0284c7", hover="#0369a1", py=5, px=10, fs=11))
        self.btn_filters.clicked.connect(self._open_filters_dialog)
        actions_bar_lyt.addWidget(self.btn_filters)

        self.btn_reports = QPushButton("📊 Raporlar")
        self.btn_reports.setToolTip("Senkronizasyon sonuç raporlarını görüntüler")
        self.btn_reports.setCursor(Qt.PointingHandCursor)
        self.btn_reports.setStyleSheet(self._blue_btn_style(bg="#7c3aed", hover="#6d28d9", py=5, px=10, fs=11))
        self.btn_reports.clicked.connect(self._show_reports)
        actions_bar_lyt.addWidget(self.btn_reports)

        actions_bar_lyt.addStretch()

        # Log toggle button
        self.btn_toggle_log = QPushButton("📋 Log Kutusu")
        self.btn_toggle_log.setToolTip("Senkronizasyon canlı log tablosunu gizler/gösterir")
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

        self.lbl_disk_status_text = QLabel("Yedekleme diski durumu kontrol ediliyor...")
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
            "☑️ Seç", "Hesap Bilgileri & Domain", "Arşiv Durumu & İlerleme", "İşlemler"
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
        self.log_box = QGroupBox("📋 Senkronizasyon Canlı Logu")
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
        self.right_sidebar = SyncRightSidebarWidget(self)
        self.right_sidebar.setFixedWidth(260)
        split_layout.addWidget(self.right_sidebar)

        main_vbox.addLayout(split_layout, stretch=1)

        # Alias properties for external compatibility
        self.btn_sync_all = self.right_sidebar.btn_sync_all
        self.btn_sync_group = self.right_sidebar.btn_sync_group
        self.btn_select_all = self.right_sidebar.btn_select_all
        self.btn_export_excel = self.right_sidebar.btn_export_excel
        self.btn_copy_all_emails = self.right_sidebar.btn_copy_all_emails
        self.combo_folder_lang = self.right_sidebar.combo_folder_lang
        self.btn_detailed_report = self.right_sidebar.btn_detailed_report
        self.view_profile_widget = self.right_sidebar.view_profile_widget

    def _connect_signals(self):
        # Left sidebar signals
        self.left_sidebar.group_selected.connect(self._on_group_filter_changed)
        self.left_sidebar.group_mgmt_requested.connect(self._open_group_management)

        # Right sidebar signals
        self.right_sidebar.sync_selected_requested.connect(self._sync_selected)
        self.right_sidebar.sync_all_requested.connect(self._sync_all)
        self.right_sidebar.dry_run_requested.connect(self._dry_run)
        self.right_sidebar.sync_group_requested.connect(self._sync_current_group)
        self.right_sidebar.select_all_requested.connect(self._toggle_select_all)
        self.right_sidebar.export_excel_requested.connect(self._export_grid_to_csv)
        self.right_sidebar.copy_emails_requested.connect(self._copy_all_emails)
        self.right_sidebar.filters_requested.connect(self._open_filters_dialog)
        self.right_sidebar.folder_lang_changed.connect(self._on_folder_lang_changed)
        self.right_sidebar.reports_requested.connect(self._show_reports)
        self.right_sidebar.detailed_report_requested.connect(self._show_detailed_report)
        self.right_sidebar.toggle_log_requested.connect(self._toggle_log_visibility)
        self.right_sidebar.pause_requested.connect(self._toggle_pause_sync)
        self.right_sidebar.cancel_requested.connect(self._cancel_sync)
        self.right_sidebar.row_height_changed.connect(lambda h: self.set_row_height(h, auto_save=True))

        # View profiles
        self.right_sidebar.profile_selected.connect(self._on_grid_profile_selected)
        self.right_sidebar.save_profile_requested.connect(self._save_grid_profile)
        self.right_sidebar.columns_requested.connect(self._open_column_manager_dialog)

        # Log table toolbar
        self.filter_input.textChanged.connect(self._on_filter_changed)
        self.combo_page_size.currentIndexChanged.connect(self._on_page_size_changed)
        self.btn_prev_page.clicked.connect(self._prev_page)
        self.btn_next_page.clicked.connect(self._next_page)
        self.btn_clear_log.clicked.connect(self._clear_log)

    @Slot(QTableWidgetItem)
    def _on_table_item_changed(self, item: QTableWidgetItem):
        if item and item.column() == 0:
            self._update_selection_count()

    @staticmethod
    def _blue_btn_style(py=6, px=12, fs=11, bg="#2563eb", hover="#1d4ed8", text_color="#ffffff", border="none"):
        border_css = f"border: 1px solid {border};" if border != "none" else "border: none;"
        return (
            f"QPushButton {{ background-color: {bg}; color: {text_color}; font-weight: 700; "
            f"padding: {py}px {px}px; border-radius: 6px; font-size: {fs}px; {border_css} }}"
            f"QPushButton:hover {{ background-color: {hover}; }}"
            f"QPushButton:disabled {{ background-color: #cbd5e1; color: #94a3b8; border: none; }}"
        )

    @staticmethod
    def _toggle_btn_style(active: bool = False) -> str:
        bg = "#e0e7ff" if active else "#ffffff"
        border = "#2563eb" if active else "#cbd5e1"
        fg = "#1e3a8a" if active else "#334155"
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: 1.5px solid {border};
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 11.5px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: #f1f5f9;
                border-color: #2563eb;
                color: #1e3a8a;
            }}
        """

    @staticmethod
    def _badge_style(bg: str = "#e2e8f0", fg: str = "#1e293b") -> str:
        return f"""
            QLabel {{
                background-color: {bg};
                color: {fg};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 700;
            }}
        """

    @staticmethod
    def _action_btn_style(bg_color: str, hover_color: str):
        return f"""
            QPushButton {{
                background-color: {bg_color};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px;
                min-width: 26px;
                min-height: 22px;
                font-weight: bold;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:disabled {{
                background-color: #e2e8f0;
                color: #cbd5e1;
            }}
        """

    # -------------------------------------------------------------
    # Sidebar Toggles & Helpers
    # -------------------------------------------------------------

    def _toggle_left_sidebar(self):
        is_hidden = self.left_sidebar.isHidden()
        self.left_sidebar.setHidden(not is_hidden)
        
        if not is_hidden:
            self.btn_toggle_left.setText("▶ Grupları Aç")
            self.btn_middle_toggle_left.setText("▶")
            self.btn_toggle_left.setStyleSheet(self._toggle_btn_style(active=True))
        else:
            self.btn_toggle_left.setText("◀ Grupları Gizle")
            self.btn_middle_toggle_left.setText("◀")
            self.btn_toggle_left.setStyleSheet(self._toggle_btn_style(active=False))

    def _toggle_right_sidebar(self):
        is_hidden = self.right_sidebar.isHidden()
        self.right_sidebar.setHidden(not is_hidden)
        self.btn_toggle_right.setText("⚙️ İşlemleri Aç ▶" if not is_hidden else "⚙️ İşlemleri Gizle ◀")
        self.btn_middle_toggle_right.setText("▶" if not is_hidden else "◀")

    @Slot()
    def _filter_table_rows(self):
        query = self.txt_search_sync.text().strip().lower()
        for i in range(self.account_table.rowCount()):
            if not query:
                self.account_table.setRowHidden(i, False)
                continue
            
            info_widget = self.account_table.cellWidget(i, 1)
            row_text = ""
            if info_widget:
                for lbl in info_widget.findChildren(QLabel):
                    row_text += " " + lbl.text().lower()
            
            self.account_table.setRowHidden(i, query not in row_text)
        self._update_selection_count()

    def _open_group_management(self):
        from gui.dialogs.group_domain_dialog import GroupDomainDialog
        dialog = GroupDomainDialog(self.engine, self.settings, self)
        dialog.exec()
        self.refresh()

    # -------------------------------------------------------------
    # Grid Layout Profile & Row Height Managers
    # -------------------------------------------------------------

    def set_row_height(self, height: int, auto_save: bool = True):
        self._current_row_height = max(24, min(140, height))
        self.account_table.verticalHeader().setDefaultSectionSize(self._current_row_height)
        for r in range(self.account_table.rowCount()):
            self.account_table.setRowHeight(r, self._current_row_height)
        if auto_save:
            self._auto_save_current_layout()

    def _prompt_custom_row_height(self):
        val, ok = QInputDialog.getInt(
            self, "Satır Yüksekliği Ayarla",
            "Lütfen satır yüksekliğini piksel (px) cinsinden girin (24 - 140):",
            self._current_row_height, 24, 140, 1
        )
        if ok:
            self.set_row_height(val, auto_save=True)

    def _toggle_column_visibility(self, col: int, visible: bool):
        self.account_table.setColumnHidden(col, not visible)
        self._auto_save_current_layout()

    def _open_column_manager_dialog(self):
        columns = [self.account_table.horizontalHeaderItem(col).text() for col in range(self.account_table.columnCount())]
        hidden = [col for col in range(self.account_table.columnCount()) if self.account_table.isColumnHidden(col)]
        dlg = ColumnManagerDialog(columns, hidden, parent=self)
        if dlg.exec() == QDialog.Accepted:
            new_hidden = set(dlg.get_hidden_columns())
            for col in range(self.account_table.columnCount()):
                self.account_table.setColumnHidden(col, col in new_hidden)
            self._auto_save_current_layout()

    def _get_current_layout_state(self) -> dict:
        return {
            "hidden_columns": [c for c in range(self.account_table.columnCount()) if self.account_table.isColumnHidden(c)],
            "column_widths": [self.account_table.columnWidth(c) for c in range(self.account_table.columnCount())],
            "row_height": self._current_row_height,
        }

    def _auto_save_current_layout(self, *args):
        if self._is_refreshing or not hasattr(self, 'right_sidebar') or not hasattr(self.right_sidebar, 'view_profile_widget'):
            return
        active_profile = self.right_sidebar.view_profile_widget.get_current_profile_name()
        state = self._get_current_layout_state()
        self.right_sidebar.view_profile_widget.manager.save_profile(active_profile, state, set_active=True)

    def _save_grid_profile(self, profile_name: str):
        state = self._get_current_layout_state()
        self.right_sidebar.view_profile_widget.manager.save_profile(profile_name, state, set_active=True)
        self.right_sidebar.view_profile_widget.reload_profiles()
        QMessageBox.information(self, "Profil Kaydedildi", f"'{profile_name}' görünüm düzeni başarıyla kaydedildi.")

    def _save_current_layout_dialog(self):
        current_name = self.right_sidebar.view_profile_widget.get_current_profile_name()
        existing_names = self.right_sidebar.view_profile_widget.manager.get_profile_names()
        dialog = SaveLayoutProfileDialog(
            existing_profiles=existing_names,
            current_profile=current_name,
            parent=self
        )
        if dialog.exec() == QDialog.Accepted and dialog.selected_profile_name:
            chosen_name = dialog.selected_profile_name
            self._save_grid_profile(chosen_name)
            self.right_sidebar.view_profile_widget.reload_profiles()
            idx = self.right_sidebar.view_profile_widget.combo_profiles.findText(chosen_name)
            if idx >= 0:
                self.right_sidebar.view_profile_widget.combo_profiles.setCurrentIndex(idx)

    def _apply_named_profile(self, name: str):
        state = self.right_sidebar.view_profile_widget.manager.get_profile(name)
        if state:
            hidden = state.get("hidden_columns", [])
            widths = state.get("column_widths", [])
            row_h = state.get("row_height", 88)
            for c in range(self.account_table.columnCount()):
                if c < len(widths) and widths[c] > 10:
                    self.account_table.setColumnWidth(c, widths[c])
                self.account_table.setColumnHidden(c, c in hidden)
            self.set_row_height(row_h, auto_save=False)
            idx = self.right_sidebar.view_profile_widget.combo_profiles.findText(name)
            if idx >= 0:
                self.right_sidebar.view_profile_widget.combo_profiles.setCurrentIndex(idx)

    @Slot(str, dict)
    def _on_grid_profile_selected(self, name: str, state: dict):
        if state:
            hidden = state.get("hidden_columns", [])
            widths = state.get("column_widths", [])
            row_h = state.get("row_height", 88)
            for c in range(self.account_table.columnCount()):
                if c < len(widths) and widths[c] > 10:
                    self.account_table.setColumnWidth(c, widths[c])
                self.account_table.setColumnHidden(c, c in hidden)
            self.set_row_height(row_h, auto_save=False)
        elif name == "Kompakt Düzen":
            self.set_row_height(40, auto_save=True)
        elif name == "Geniş Görünüm":
            self.set_row_height(110, auto_save=True)
        elif name == "Varsayılan":
            self.set_row_height(88, auto_save=True)
            self.account_table.setColumnWidth(0, 55)
            self.account_table.setColumnWidth(1, 420)
            self.account_table.setColumnWidth(2, 340)
            self.account_table.setColumnWidth(3, 150)
            for c in range(self.account_table.columnCount()):
                self.account_table.setColumnHidden(c, False)

    def _reset_grid_layout_to_default(self):
        for c in range(self.account_table.columnCount()):
            self.account_table.setColumnHidden(c, False)
        self.account_table.setColumnWidth(0, 55)
        self.account_table.setColumnWidth(1, 420)
        self.account_table.setColumnWidth(2, 340)
        self.account_table.setColumnWidth(3, 150)
        self.set_row_height(88, auto_save=True)
        QMessageBox.information(self, "Grid Sıfırlandı", "Tablo sütunları ve satır yüksekliği varsayılan düzene (88px) sıfırlandı.")

    @Slot(str)
    def _on_folder_lang_changed(self, mode: str):
        if mode:
            self.settings.set_folder_translation_sync(mode)
            logger.info("Sync folder translation mode set to: %s", mode)

    @Slot()
    def _export_grid_to_csv(self):
        import csv
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, "Hesap Listesini Excel / CSV Olarak Kaydet",
            "eposta_hesap_listesi.csv", "CSV Dosyaları (*.csv);;Tüm Dosyalar (*.*)"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["ID", "Hesap Adı", "E-Posta Adresi", "Grup / Domain", "Durum"])
                for i in range(self.account_table.rowCount()):
                    if self.account_table.isRowHidden(i):
                        continue
                    item = self.account_table.item(i, 0)
                    acc_id = item.data(Qt.UserRole) if item else ""

                    info_widget = self.account_table.cellWidget(i, 1)
                    label_text, email_text = "", ""
                    if info_widget:
                        labels = info_widget.findChildren(QLabel)
                        if len(labels) >= 1:
                            label_text = labels[0].text().replace("<b>", "").replace("</b>", "").strip()
                        if len(labels) >= 2:
                            email_text = labels[1].text().replace("✉️", "").strip()

                    ui = self._accounts_ui.get(acc_id, {})
                    status_text = ui.get("lbl_status", QLabel("Idle")).text() if ui else "Idle"
                    writer.writerow([acc_id, label_text, email_text, "", status_text])

            QMessageBox.information(self, "Dışa Aktarma Başarılı", f"Hesap tablosu başarıyla dışa aktarıldı:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Dışa aktarma sırasında hata oluştu:\n{e}")

    @Slot()
    def _copy_all_emails(self):
        emails = []
        for i in range(self.account_table.rowCount()):
            if not self.account_table.isRowHidden(i):
                info_widget = self.account_table.cellWidget(i, 1)
                if info_widget:
                    labels = info_widget.findChildren(QLabel)
                    if len(labels) >= 2:
                        em = labels[1].text().replace("✉️", "").strip()
                        if em:
                            emails.append(em)
        if emails:
            QApplication.clipboard().setText("\n".join(emails))
            QMessageBox.information(self, "Kopyalandı", f"{len(emails)} adet e-posta adresi panoya kopyalandı.")
        else:
            QMessageBox.warning(self, "Bulunamadı", "Tabloda kopyalanacak e-posta adresi bulunamadı.")

    # ------------------------------------------------------------------
    # Filters Pop-up Dialog
    # ------------------------------------------------------------------

    @Slot()
    def _open_filters_dialog(self):
        checked_ids = self._get_selected_account_ids()
        if checked_ids:
            acc_id = checked_ids[0]
        else:
            acc_id = self._get_active_row_account_id()
            
        if not acc_id and self.account_table.rowCount() > 0:
            item = self.account_table.item(0, 0)
            if item:
                acc_id = item.data(Qt.UserRole)

        if not acc_id:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Hesap Seçilmedi")
            msg.setText("Lütfen filtrelerini düzenlemek istediğiniz hesabı tabloda seçin veya solundaki kutucuğu işaretleyin.")
            msg.setStyleSheet(GLOBAL_MSG_STYLE)
            msg.exec()
            return
        self._open_filters_dialog_for_account(acc_id)

    def _open_filters_dialog_for_account(self, acc_id: int, force_prompt: bool = False):
        acc = self.engine.accounts.get(acc_id)
        if not acc:
            return

        f_data = self.settings.account_sync_filters(acc_id) or {}
        folders = f_data.get("all_folders", [])
        
        if not folders:
            try:
                with self.engine.db.get_conn() as conn:
                    rows = conn.execute(
                        "SELECT folder FROM sync_state WHERE account_id = ? ORDER BY folder",
                        (acc_id,)
                    ).fetchall()
                    folders = [r["folder"] for r in rows]
                if not folders:
                    with self.engine.db.get_conn() as conn:
                        rows = conn.execute(
                            "SELECT DISTINCT folder FROM mail_metadata WHERE account_id = ? ORDER BY folder",
                            (acc_id,)
                        ).fetchall()
                        folders = [r["folder"] for r in rows]
            except Exception:
                pass
                
            if not folders:
                self._log_callback(f"[{acc.get('label')}] Sunucudan klasör listesi çekiliyor...")
                try:
                    res = self.engine.sync_dry_run(acc_id)
                    folders = [f["folder"] for f in res.get("folders", [])]
                except Exception as e:
                    logger.error("Failed to fetch folders for filters: %s", e)
                    
            if not folders:
                folders = ["INBOX"]

        selected_folders = f_data.get("folders", folders)
        archive_unread = f_data.get("archive_unread", True)
        since_date_enabled = f_data.get("since_date_enabled", False)
        since_date_str = f_data.get("since_date", "")
        before_date_enabled = f_data.get("before_date_enabled", False)
        before_date_str = f_data.get("before_date", "")
        timeout = f_data.get("timeout", 180)
        
        since_date = QDate.fromString(since_date_str, Qt.ISODate) if since_date_str else QDate.currentDate()
        before_date = QDate.fromString(before_date_str, Qt.ISODate) if before_date_str else QDate.currentDate()

        dialog = FiltersDialog(
            account_label=acc.get("label", "Hesap"),
            folders=folders,
            selected_folders=selected_folders,
            archive_unread=archive_unread,
            since_date_enabled=since_date_enabled,
            since_date=since_date,
            before_date_enabled=before_date_enabled,
            before_date=before_date,
            timeout=timeout,
            engine=self.engine,
            account_id=acc_id,
            parent=self
        )
        
        if dialog.exec() == QDialog.Accepted:
            new_f_data = {
                "folders": dialog.get_selected_folders(),
                "all_folders": [dialog.folder_list.item(i).text() for i in range(dialog.folder_list.count())],
                "archive_unread": dialog.chk_archive_unread.isChecked(),
                "since_date_enabled": dialog.chk_since_date.isChecked(),
                "since_date": dialog.date_edit_since.date().toString(Qt.ISODate),
                "before_date_enabled": dialog.chk_before_date.isChecked(),
                "before_date": dialog.date_edit_before.date().toString(Qt.ISODate),
                "timeout": dialog.spin_timeout.value(),
            }
            self.settings.set_account_sync_filters(acc_id, new_f_data)
            self._log_callback(f"[{acc.get('label')}] Filtreler kaydedildi: {len(new_f_data['folders'])} klasör seçildi.")

    # ------------------------------------------------------------------
    # Stat card updates & UI toggles
    # ------------------------------------------------------------------

    def _update_stats(self, account="—", server_emails="—",
                      folders="—", current="—",
                      remaining="—", progress="—", eta="—"):
        self.card_account.set_value(str(account))
        self.card_server.set_value(str(server_emails))
        self.card_current.set_value(str(current))
        self.card_remaining.set_value(str(remaining))
        self.card_progress.set_value(str(progress))
        self.card_eta.set_value(str(eta))

    @Slot()
    def _toggle_log_visibility(self):
        is_visible = self.log_box.isVisible()
        self.log_box.setVisible(not is_visible)
        if is_visible:
            self.btn_toggle_log.setText("📋 Log Kutusu (Gizli)")
        else:
            self.btn_toggle_log.setText("📋 Log Kutusu")

    # ------------------------------------------------------------------
    # Account selection helpers
    # ------------------------------------------------------------------

    def _get_selected_account_ids(self) -> list:
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

    def _toggle_select_all(self):
        if self._all_selected_flag:
            for i in range(self.account_table.rowCount()):
                item = self.account_table.item(i, 0)
                if item:
                    item.setCheckState(Qt.Unchecked)
            self.btn_select_all.setText("☑️ Tümünü Seç")
            self._all_selected_flag = False
        else:
            for i in range(self.account_table.rowCount()):
                item = self.account_table.item(i, 0)
                if item:
                    item.setCheckState(Qt.Checked)
            self.btn_select_all.setText("🔳 Seçimleri Kaldır")
            self._all_selected_flag = True
        self._update_selection_count()

    def _update_selection_count(self):
        total = self.account_table.rowCount()
        selected = len(self._get_selected_account_ids())
        self.lbl_stat_total.setText(f"📊 {total} Hesap")
        self.lbl_stat_selected.setText(f"☑️ {selected} Seçili")
        self.lbl_stat_active.setText(f"🟢 {len(self._active_syncs)} Çalışıyor")

    def _get_active_row_account_id(self) -> Optional[int]:
        row = self.account_table.currentRow()
        if row >= 0:
            item = self.account_table.item(row, 0)
            if item:
                return item.data(Qt.UserRole)
        return None

    @Slot()
    def _on_table_row_click(self):
        acc_id = self._get_active_row_account_id()
        if acc_id is None:
            return
            
        ui = self._accounts_ui.get(acc_id)
        if not ui:
            return
            
        status = ui["lbl_status"].text()
        progress_val = ui["progress_bar"].value()
        progress_max = ui["progress_bar"].maximum()
        
        prog_text = "—"
        if progress_max > 0:
            prog_text = f"{int((progress_val / progress_max) * 100)}%"
        elif "Done" in status or "Tamamlandı" in status:
            prog_text = "100%"
            
        widget = self.account_table.cellWidget(self.account_table.currentRow(), 1)
        account_name = "—"
        stats_text = ""
        if widget:
            lbls = widget.findChildren(QLabel)
            if len(lbls) >= 1:
                account_name = lbls[0].text().replace("<b>", "").replace("</b>", "")
            if len(lbls) >= 3:
                stats_text = lbls[2].text()

        self._update_stats(
            account=account_name,
            current=status,
            progress=prog_text,
            folders="—",
            server_emails=stats_text or "—",
            remaining=str(progress_max - progress_val) if progress_max > 0 else "—",
        )

    # ------------------------------------------------------------------
    # Multi-threaded Individual Sync Workers
    # ------------------------------------------------------------------

    def _start_individual_sync(self, account_id: int):
        if not self.settings.is_configured_data_path_available():
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Yedekleme Diski Takılı Değil")
            msg.setText(
                f"Yapılandırılmış arşiv diski (<b>{self.settings.configured_data_path_str()}</b>) şu anda takılı veya erişilebilir değil.\n\n"
                "Senkronizasyon yapabilmek için lütfen harici diskinizi bilgisayara takınız."
            )
            msg.setStyleSheet(GLOBAL_MSG_STYLE)
            msg.exec()
            return

        if account_id in self._active_syncs:
            return
            
        cancel_event = threading.Event()
        pause_event = threading.Event()
        
        ui = self._accounts_ui.get(account_id)
        if ui:
            ui["btn_start"].setEnabled(False)
            ui["btn_pause"].setEnabled(True)
            ui["btn_pause"].setText("⏸")
            ui["btn_stop"].setEnabled(True)
            ui["lbl_status"].setText("Bağlanıyor...")
            ui["progress_bar"].setRange(0, 0)
            
        self._active_syncs[account_id] = {
            "cancel_event": cancel_event,
            "pause_event": pause_event,
            "status": "Bağlanıyor...",
            "thread": None,
        }
        
        self.btn_cancel.setEnabled(True)
        self.btn_pause.setEnabled(True)
        self._update_selection_count()
        
        f_data = self.settings.account_sync_filters(account_id) or {}
        folder_filter = f_data.get("folders")
        since_date_enabled = f_data.get("since_date_enabled", False)
        since_date = f_data.get("since_date") if since_date_enabled else None
        before_date_enabled = f_data.get("before_date_enabled", False)
        before_date = f_data.get("before_date") if before_date_enabled else None
        archive_unread = f_data.get("archive_unread", True)
        timeout = f_data.get("timeout", 180)
        
        def progress_cb(aid: int, folder_name: str, current: int, total: int):
            self._account_progress_signal.emit(aid, f"Arşivleniyor: {folder_name}", current, total)
            
        def log_cb(msg: str):
            self._log_signal.emit(msg)
            
        def run_sync():
            try:
                report_dict = self.engine.sync_account(
                    account_id=account_id,
                    log_callback=log_cb,
                    cancel_event=cancel_event,
                    folder_filter=folder_filter,
                    pause_event=pause_event,
                    since_date=since_date,
                    before_date=before_date,
                    archive_unread=archive_unread,
                    timeout=timeout,
                    progress_callback=progress_cb
                )
                self._account_sync_done_signal.emit(account_id, report_dict)
            except Exception as e:
                self._account_sync_error_signal.emit(account_id, str(e))
                
        thread = threading.Thread(target=run_sync, daemon=True)
        self._active_syncs[account_id]["thread"] = thread
        thread.start()

    def _toggle_individual_pause(self, account_id: int):
        sync = self._active_syncs.get(account_id)
        ui = self._accounts_ui.get(account_id)
        if not sync or not ui:
            return
            
        pe = sync["pause_event"]
        if pe.is_set():
            pe.clear()
            ui["btn_pause"].setText("⏸")
            ui["lbl_status"].setText("Devam Ediyor")
            self._log_callback(f"Hesap ID {account_id} senkronizasyonu devam ettirildi.")
        else:
            pe.set()
            ui["btn_pause"].setText("▶")
            ui["lbl_status"].setText("Duraklatıldı")
            self._log_callback(f"Hesap ID {account_id} senkronizasyonu duraklatıldı.")

    def _stop_individual_sync(self, account_id: int):
        sync = self._active_syncs.get(account_id)
        ui = self._accounts_ui.get(account_id)
        if not sync or not ui:
            return
            
        sync["cancel_event"].set()
        ui["btn_stop"].setEnabled(False)
        ui["lbl_status"].setText("Durduruluyor...")
        self._log_callback(f"Hesap ID {account_id} senkronizasyonu durdurma isteği gönderildi.")

    def _show_individual_report(self, account_id: int):
        acc = self.engine.accounts.get(account_id)
        label = acc.get("label", f"Hesap #{account_id}") if acc else f"Hesap #{account_id}"
                
        acc_reports = []
        for r in self._reports:
            r_lbl = r.get("account_label") if isinstance(r, dict) else getattr(r, "account_label", "")
            if r_lbl == label:
                acc_reports.append(r)
                
        if not acc_reports:
            QMessageBox.information(self, "Rapor Bulunamadı", "Bu oturumda bu hesap için tamamlanmış rapor bulunamadı.")
            return
            
        dialog = ReportsDialog(acc_reports, self)
        dialog.exec()

    # ------------------------------------------------------------------
    # Signals/Slots for UI Updates
    # ------------------------------------------------------------------

    @Slot(int, str, int, int)
    def _on_account_progress(self, account_id: int, status_text: str, current: int, total: int):
        ui = self._accounts_ui.get(account_id)
        if ui:
            ui["lbl_status"].setText(f"{status_text} ({current}/{total})")
            ui["progress_bar"].setRange(0, total if total > 0 else 100)
            ui["progress_bar"].setValue(current)
            
        if account_id in self._active_syncs:
            self._active_syncs[account_id]["status"] = status_text
            
        if self._get_active_row_account_id() == account_id:
            prog_text = f"{int((current/total)*100)}%" if total > 0 else "0%"
            self.card_current.set_value(status_text)
            self.card_remaining.set_value(str(total - current) if total >= current else "0")
            self.card_progress.set_value(prog_text)
            
            eta_sec = int((total - current) * 0.3)
            if eta_sec > 60:
                self.card_eta.set_value(f"{eta_sec // 60}dk {eta_sec % 60}sn")
            else:
                self.card_eta.set_value(f"{eta_sec}sn")

    @Slot(int, object)
    def _on_account_sync_done(self, account_id: int, report: Any):
        ui = self._accounts_ui.get(account_id)
        cancelled = account_id in self._active_syncs and self._active_syncs[account_id]["cancel_event"].is_set()
        
        if ui:
            ui["btn_start"].setEnabled(True)
            ui["btn_pause"].setEnabled(False)
            ui["btn_stop"].setEnabled(False)
            
            if cancelled:
                ui["lbl_status"].setText("İptal Edildi")
                ui["progress_bar"].setRange(0, 100)
                ui["progress_bar"].setValue(0)
            else:
                fetched = report.get("mails_fetched", 0) if isinstance(report, dict) else getattr(report, "mails_fetched", 0)
                ui["lbl_status"].setText(f"Tamamlandı: {fetched} mail çekildi")
                ui["progress_bar"].setRange(0, 100)
                ui["progress_bar"].setValue(100)
                
        if account_id in self._active_syncs:
            self._reports.append(report)
            if not cancelled:
                try:
                    self.engine.reporter.generate_sync_report(report, "both")
                except Exception as e:
                    logger.error("Failed to generate sync report: %s", e)
            
        self._active_syncs.pop(account_id, None)
        self._update_selection_count()
        
        if not self._active_syncs:
            self._on_all_syncs_finished()

    @Slot(int, str)
    def _on_account_sync_error(self, account_id: int, err_msg: str):
        ui = self._accounts_ui.get(account_id)
        if ui:
            ui["btn_start"].setEnabled(True)
            ui["btn_pause"].setEnabled(False)
            ui["btn_stop"].setEnabled(False)
            ui["lbl_status"].setText(f"Hata: {err_msg}")
            ui["progress_bar"].setRange(0, 100)
            ui["progress_bar"].setValue(0)
            
        acc = self.engine.accounts.get(account_id)
        label = acc.get("label", f"Hesap #{account_id}") if acc else f"Hesap #{account_id}"
        
        error_report = {
            "account_label": label,
            "status": "Failed",
            "error": err_msg,
            "mails_fetched": 0,
            "folders_processed": 0,
            "total_size_bytes": 0,
            "details": f"Hata Oluştu: {err_msg}",
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._reports.append(error_report)
        self._active_syncs.pop(account_id, None)
        self._update_selection_count()
        
        if not self._active_syncs:
            self._on_all_syncs_finished()

    def _on_all_syncs_finished(self):
        self.btn_cancel.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸️ Duraklat")
        self._log_callback("Tüm arka plan senkronizasyon işlemleri tamamlandı.")
        self._update_selection_count()
        
        if self._reports:
            try:
                if len(self._reports) > 1:
                    self.engine.reporter.generate_batch_sync_report(self._reports, group_name="Toplu Sync Raporu", output_format="both")
                elif len(self._reports) == 1:
                    r = self._reports[0]
                    r_dict = r if isinstance(r, dict) else (r.__dict__ if hasattr(r, "__dict__") else {})
                    self.engine.reporter.generate_sync_report(r_dict, output_format="both")
            except Exception as e:
                logger.error("Failed to save sync report: %s", e)

            dialog = SyncFinishedDialog(self)
            if dialog.exec() == QDialog.Accepted:
                rep_dialog = ReportsDialog(self._reports, self)
                rep_dialog.exec()

    # ------------------------------------------------------------------
    # Log callback & parsing
    # ------------------------------------------------------------------

    def _log_callback(self, msg: str):
        self._log_signal.emit(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    @Slot(str)
    def _on_log_message(self, msg: str):
        m = _LOG_PARSE_RE.match(msg)
        if m:
            ts = m.group(1)
            rest = m.group(2)
        else:
            ts = datetime.now().strftime("%H:%M:%S")
            rest = msg
        upper = rest.upper()
        if upper.startswith("ERROR") or "ERROR" in upper[:30]:
            level = "ERROR"
        elif upper.startswith("WARN") or "WARNING" in upper[:30]:
            level = "WARN"
        else:
            level = "INFO"
        src_match = re.match(r'\[([^\]]+)\]\s*', rest)
        source = src_match.group(1) if src_match else "sync"
        message = rest[src_match.end():] if src_match else rest
        entry = LogEntry(ts, level, source, message)
        
        if getattr(self, '_log_model', None) is not None:
            self._log_model.append(entry) if hasattr(self._log_model, 'append') else self._log_model.append_entry(entry)
            if getattr(self, '_log_proxy', None) is not None:
                self._update_pagination()
                self._log_proxy.set_page(self._log_proxy.total_pages() - 1)
                self._update_pagination()

        if "Syncing folder" in message or "Arşivleniyor" in message:
            fld_match = re.search(r'[\'"]([^\'"]+)[\'"]', message)
            if fld_match:
                self.card_current.set_value(fld_match.group(1))

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _update_pagination(self):
        if hasattr(self, 'label_page') and self.label_page and getattr(self, '_log_proxy', None) is not None:
            total = self._log_proxy.total_pages()
            cur = self._log_proxy.current_page() + 1
            self.label_page.setText(f"Sayfa {cur} / {total}")
            if hasattr(self, 'btn_prev_page') and self.btn_prev_page:
                self.btn_prev_page.setEnabled(cur > 1)
            if hasattr(self, 'btn_next_page') and self.btn_next_page:
                self.btn_next_page.setEnabled(cur < total)

    def _on_filter_changed(self, text: str):
        self._log_proxy.set_filter_text(text)
        self._update_pagination()

    def _on_page_size_changed(self, idx: int):
        val = self.combo_page_size.currentText()
        if val in ("Tümü", "All"):
            self._log_proxy.set_page_size(999999)
        else:
            self._log_proxy.set_page_size(int(val))
        self._update_pagination()

    def _prev_page(self):
        self._log_proxy.set_page(self._log_proxy.current_page() - 1)
        self._update_pagination()

    def _next_page(self):
        self._log_proxy.set_page(self._log_proxy.current_page() + 1)
        self._update_pagination()

    def _clear_log(self):
        self._log_model.clear_entries()
        self._update_pagination()

    # ------------------------------------------------------------------
    # Confirmation dialog
    # ------------------------------------------------------------------

    def _confirm_sync(self, ids: list) -> bool:
        from PySide6.QtWidgets import QProgressDialog
        
        table_data = {}
        for acc_id in ids:
            acc_data = f"Hesap #{acc_id}"
            for i in range(self.account_table.rowCount()):
                item = self.account_table.item(i, 0)
                if item and item.data(Qt.UserRole) == acc_id:
                    widget = self.account_table.cellWidget(i, 1)
                    if widget:
                        lbl = widget.findChild(QLabel)
                        if lbl:
                            acc_data = lbl.text().replace("<b>", "").replace("</b>", "")
                    break
            table_data[acc_id] = acc_data
            
        progress = QProgressDialog("Sunucu bağlantısı kuruluyor ve mail sayıları hesaplanıyor...", "İptal", 0, len(ids), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setWindowTitle("Senkronizasyon Hazırlığı")
        progress.setMinimumDuration(0)
        progress.setStyleSheet("QProgressDialog { background-color: #f8fafc; } QLabel { color: #1e293b; font-size:12px; }")
        progress.setValue(0)
        
        worker = DryRunWorker(self.engine, self.settings, ids, table_data, parent=self)
        progress.canceled.connect(lambda: setattr(worker, 'is_cancelled', True))
        
        loop = QEventLoop()
        previews_result = []
        
        def on_progress(msg):
            progress.setLabelText(msg)
            
        def on_finished(previews):
            nonlocal previews_result
            previews_result = previews
            loop.quit()
            
        worker.progress_signal.connect(on_progress)
        worker.finished_signal.connect(on_finished)
        worker.finished_signal.connect(worker.deleteLater)
        worker.start()
        
        progress.show()
        loop.exec()
        
        try:
            progress.canceled.disconnect()
        except Exception:
            pass
        progress.close()
        
        if worker.is_cancelled or not previews_result:
            return False
            
        dialog = SyncConfirmDialog(previews_result, self)
        return dialog.exec() == QDialog.Accepted

    @Slot(QPoint)
    def _show_toya_grid_context_menu(self, pos: QPoint):
        sender = self.sender()
        is_header = (sender == self.account_table.horizontalHeader())
        global_pos = sender.mapToGlobal(pos) if sender else QCursor.pos()
        row = self.account_table.rowAt(pos.y()) if not is_header else -1

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e3a8a;
                color: #ffffff;
                border: 1.5px solid #1e40af;
                border-radius: 8px;
                padding: 6px;
                font-weight: 600;
                font-size: 11.5px;
            }
            QMenu::item {
                padding: 6px 22px 6px 12px;
                border-radius: 4px;
                color: #ffffff;
            }
            QMenu::item:selected {
                background-color: #2563eb;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background-color: #3b82f6;
                margin: 4px 6px;
            }
        """)

        acc_id = None
        acc = None
        if row >= 0 and not is_header:
            item = self.account_table.item(row, 0)
            if item:
                acc_id = item.data(Qt.UserRole)
                acc = self.engine.accounts.get(acc_id)

        if acc_id is not None and acc:
            acc_label = acc.get("label", f"Hesap #{acc_id}")
            act_sync_this = menu.addAction(f"▶ '{acc_label}' İçin Senkronizasyonu Başlat")
            act_sync_this.triggered.connect(lambda chk=False, aid=acc_id: self._trigger_individual_sync_direct(aid))

            act_pause_this = menu.addAction("⏸ Duraklat / Sürdür")
            act_pause_this.triggered.connect(lambda chk=False, aid=acc_id: self._toggle_individual_pause(aid))

            act_stop_this = menu.addAction("⏹ İptal Et / Durdur")
            act_stop_this.triggered.connect(lambda chk=False, aid=acc_id: self._stop_individual_sync(aid))

            menu.addSeparator()
            act_dry = menu.addAction("🔍 Kuru Çalıştırma (Önizleme)")
            act_dry.triggered.connect(lambda chk=False, aid=acc_id: self._confirm_sync([aid]))

            act_flt = menu.addAction("⚙️ Klasör & Filtre Ayarları...")
            act_flt.triggered.connect(lambda chk=False, aid=acc_id: self._open_filters_dialog_for_account(aid))

            act_rep = menu.addAction("📊 Bu Hesabın Raporu")
            act_rep.triggered.connect(lambda chk=False, aid=acc_id: self._show_individual_report(aid))

            act_copy = menu.addAction("📋 E-Posta Adresini Kopyala")
            act_copy.triggered.connect(lambda chk=False, em=acc.get("email", ""): QApplication.clipboard().setText(em))
            menu.addSeparator()

        act_sync_sel = menu.addAction("⚡ Seçili Hesapları Senkronize Et")
        act_sync_sel.triggered.connect(self._sync_selected)

        act_sync_grp = menu.addAction("🚀 Seçili Grubu Senkronize Et")
        act_sync_grp.triggered.connect(self._sync_current_group)

        act_sync_all = menu.addAction("🌐 Tüm Hesapları Senkronize Et")
        act_sync_all.triggered.connect(self._sync_all)

        menu.addSeparator()
        act_save_layout = menu.addAction("💾 Görünüm Düzenini Kaydet")
        act_save_layout.triggered.connect(self._save_current_layout_dialog)

        menu_profiles = menu.addMenu("📂 Kayıtlı Görünüm Düzenleri")
        menu_profiles.setStyleSheet(menu.styleSheet())
        profile_names = self.right_sidebar.view_profile_widget.manager.get_profile_names()
        active_prof = self.right_sidebar.view_profile_widget.get_current_profile_name()

        for p_name in profile_names:
            p_prefix = "✔ " if p_name == active_prof else "  "
            act_p = menu_profiles.addAction(f"{p_prefix}{p_name}")
            act_p.triggered.connect(lambda chk=False, name=p_name: self._apply_named_profile(name))

        menu.addSeparator()
        act_reset = menu.addAction("🔄 Varsayılan Düzene (88px) Sıfırla")
        act_reset.triggered.connect(self._reset_grid_layout_to_default)

        menu.exec(global_pos)

    # ------------------------------------------------------------------
    # Sync Operations
    # ------------------------------------------------------------------

    def _prompt_server_profile_if_needed(self, account_id: int) -> bool:
        """If account has multiple server profiles, prompt user to select which one to sync from."""
        try:
            profiles = self.engine.db.get_server_profiles(account_id)
        except Exception:
            profiles = []

        if len(profiles) > 1:
            acc = self.engine.accounts.get(account_id) or {"id": account_id, "label": f"Hesap #{account_id}"}
            dialog = SelectSyncServerDialog(account=acc, profiles=profiles, parent=self)
            if dialog.exec() == QDialog.Accepted and dialog.selected_profile_id:
                try:
                    self.engine.set_default_server_profile(account_id, dialog.selected_profile_id)
                    updated_acc = self.engine.db.get_account(account_id)
                    if updated_acc:
                        self.engine.accounts[account_id] = updated_acc
                except Exception as e:
                    logger.warning("Failed to set default server profile before sync: %s", e)
                return True
            else:
                return False
        return True

    def _trigger_individual_sync_direct(self, acc_id: int):
        if not self._prompt_server_profile_if_needed(acc_id):
            return
        self._start_individual_sync(acc_id)

    def _trigger_sync_for_accounts(self, ids: list):
        if not ids:
            return
        if not self.settings.is_configured_data_path_available():
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Yedekleme Diski Takılı Değil")
            msg.setText(
                f"Yapılandırılmış arşiv diski (<b>{self.settings.configured_data_path_str()}</b>) şu anda takılı veya erişilebilir değil.\n\n"
                "Senkronizasyon yapabilmek için lütfen harici diskinizi takınız."
            )
            msg.setStyleSheet(GLOBAL_MSG_STYLE)
            msg.exec()
            return

        valid_ids = []
        for acc_id in ids:
            if self._prompt_server_profile_if_needed(acc_id):
                valid_ids.append(acc_id)

        if not valid_ids:
            return

        if not self._confirm_sync(valid_ids):
            return

        self._reports.clear()
        for acc_id in valid_ids:
            self._start_individual_sync(acc_id)

    @Slot()
    def _sync_selected(self):
        ids = self._get_selected_account_ids()
        if not ids:
            QMessageBox.warning(
                self, "Hesap Seçilmedi",
                "Lütfen senkronize etmek istediğiniz hesapların solundaki kutucukları işaretleyin."
            )
            return
        self._trigger_sync_for_accounts(ids)

    @Slot()
    def _sync_all(self):
        for i in range(self.account_table.rowCount()):
            item = self.account_table.item(i, 0)
            if item:
                item.setCheckState(Qt.Checked)
        self.btn_select_all.setText("🔳 Seçimleri Kaldır")
        self._all_selected_flag = True
        self._update_selection_count()
        
        ids = self._get_selected_account_ids()
        if ids:
            self._trigger_sync_for_accounts(ids)

    @Slot()
    def _sync_current_group(self):
        ids = []
        for i in range(self.account_table.rowCount()):
            if not self.account_table.isRowHidden(i):
                item = self.account_table.item(i, 0)
                if item:
                    item.setCheckState(Qt.Checked)
                    acc_id = item.data(Qt.UserRole)
                    if acc_id is not None:
                        ids.append(acc_id)
        self._all_selected_flag = True
        self.btn_select_all.setText("🔳 Seçimleri Kaldır")
        self._update_selection_count()

        if ids:
            self._trigger_sync_for_accounts(ids)
        else:
            QMessageBox.warning(self, "Hesap Bulunamadı", "Seçili grupta senkronize edilecek hesap bulunamadı.")

    @Slot()
    def _cancel_sync(self):
        self._log_callback("Tüm senkronizasyon işlemleri durduruluyor...")
        for aid in list(self._active_syncs.keys()):
            self._stop_individual_sync(aid)

    @Slot()
    def _toggle_pause_sync(self):
        any_running = False
        for aid in self._active_syncs:
            if not self._active_syncs[aid]["cancel_event"].is_set() and not self._active_syncs[aid]["pause_event"].is_set():
                any_running = True
                break
                
        if any_running:
            self._log_callback("Tüm işlemler duraklatılıyor...")
            for aid in self._active_syncs:
                if not self._active_syncs[aid]["pause_event"].is_set():
                    self._toggle_individual_pause(aid)
            self.btn_pause.setText("▶️ Devam Et")
        else:
            self._log_callback("Tüm işlemler devam ettiriliyor...")
            for aid in self._active_syncs:
                if self._active_syncs[aid]["pause_event"].is_set():
                    self._toggle_individual_pause(aid)
            self.btn_pause.setText("⏸️ Duraklat")

    @Slot()
    def _dry_run(self):
        ids = self._get_selected_account_ids()
        if not ids:
            QMessageBox.warning(self, "Seçim Yapılmadı", "Lütfen önizleme yapmak için en az bir hesap seçin.")
            return

        self._confirm_sync(ids)

    @Slot(int, int, object)
    def _on_account_dry_run_done(self, account_id: int, total: int, error: Optional[str]):
        ui = self._accounts_ui.get(account_id)
        if ui:
            ui["progress_bar"].setRange(0, 100)
            if error:
                ui["lbl_status"].setText(f"Önizleme Hatası: {error}")
                ui["progress_bar"].setValue(0)
            else:
                ui["lbl_status"].setText(f"Önizleme: ~{total} yeni mail")
                ui["progress_bar"].setValue(100)

    def _load_recent_reports_from_db(self) -> list:
        reports = []
        try:
            with self.engine.db.get_conn() as conn:
                rows = conn.execute(
                    "SELECT account_id, details, timestamp FROM audit_logs WHERE action='sync.completed' ORDER BY id DESC LIMIT 50"
                ).fetchall()
                for r in rows:
                    acc_id = r["account_id"]
                    acc = self.engine.accounts.get(acc_id) if acc_id else None
                    label = acc.get("label", f"Hesap #{acc_id}") if acc else f"Hesap #{acc_id}"
                    
                    details = {}
                    if r["details"]:
                        try:
                            import json
                            details = json.loads(r["details"])
                        except Exception:
                            pass
                    
                    reports.append({
                        "account_label": label,
                        "mails_fetched": details.get("fetched", 0),
                        "duplicates_found": details.get("duplicates", 0),
                        "errors": details.get("errors", 0),
                        "duration_seconds": details.get("duration", 0),
                        "error_details": details.get("error_details", []),
                        "finished_at": r["timestamp"],
                    })
        except Exception as e:
            logger.error("Failed to load reports from audit logs: %s", e)
        return reports

    @Slot()
    def _show_reports(self):
        if not self._reports:
            reports = self._load_recent_reports_from_db()
            if reports:
                self._reports = reports
            else:
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Information)
                msg.setWindowTitle("Rapor Bulunamadı")
                msg.setText("Henüz kayıtlı senkronizasyon raporu bulunmuyor.\n\nLütfen önce en az bir hesabı senkronize edin.")
                msg.setStyleSheet(GLOBAL_MSG_STYLE)
                msg.exec()
                return
        dialog = ReportsDialog(self._reports, self)
        dialog.exec()

    @Slot()
    def _show_detailed_report(self):
        dialog = DetailedReportDialog(self.engine, self)
        dialog.exec()

    # ------------------------------------------------------------------
    # Refresh & Asynchronous Lazy Load
    # ------------------------------------------------------------------

    @Slot()
    def _check_disk_and_refresh(self):
        if self.settings.is_configured_data_path_available():
            db_path = self.settings.db_path()
            key_path = self.settings.key_file_path()
            if db_path.exists() and getattr(self.engine.db, "_db_path", None) != db_path:
                try:
                    from core.database import DatabaseManager
                    from core.crypto_utils import CryptoManager
                    km = CryptoManager(key_file=key_path) if key_path.exists() else getattr(self.engine, "crypto", None)
                    decrypt_fn = km.decrypt if km else None
                    self.engine.db = DatabaseManager(db_path=db_path)
                    self.engine.accounts = {a["id"]: a for a in self.engine.db.list_accounts(decrypt_fn=decrypt_fn)}
                    logger.info("Successfully reconnected to database on %s", db_path)
                except Exception as e:
                    logger.error("Failed to re-bind db to newly connected disk: %s", e)
        self.refresh()

    def refresh(self):
        """Asynchronously load accounts and render rows immediately in <5ms."""
        self._is_refreshing = True
        is_disk_online = self.settings.is_configured_data_path_available()
        disk_path_str = self.settings.configured_data_path_str()

        self._refresh_groups_sidebar()

        self.account_table.blockSignals(True)
        self.account_table.setRowCount(0)
        self._accounts_ui.clear()
        self._stats_labels_map.clear()

        selected_group = self._selected_group

        try:
            if is_disk_online:
                accounts = self.engine.list_accounts()
                if accounts:
                    self.settings.save_account_cache(accounts)
                
                self.disk_status_banner.setStyleSheet("""
                    QFrame#diskStatusBanner {
                        background-color: #ecfdf5;
                        border: 1px solid #10b981;
                        border-radius: 6px;
                    }
                """)
                self.lbl_disk_status_icon.setText("🟢")
                self.lbl_disk_status_text.setText(
                    f"<b>Aktif Yedekleme Diski Bağlı:</b> <span style='color:#065f46;'>{disk_path_str}</span> "
                    f"({len(accounts)} Hesap Kayıtlı — İstatistikler taranıyor...)"
                )
            else:
                accounts = self.settings.load_account_cache()
                if not accounts:
                    accounts = self.engine.list_accounts()
                
                self.disk_status_banner.setStyleSheet("""
                    QFrame#diskStatusBanner {
                        background-color: #fffbeb;
                        border: 1px solid #f59e0b;
                        border-radius: 6px;
                    }
                """)
                self.lbl_disk_status_icon.setText("🟠")
                self.lbl_disk_status_text.setText(
                    f"<b>⚠️ Yedekleme Diski ({disk_path_str}) Bağlı Değil — Çevrimdışı Mod</b><br/>"
                    f"<span style='font-size:11px; color:#92400e;'>{len(accounts)} adet hesap listelenmektedir. Hesap verilerine ve yeni senkronizasyona disk takılana kadar ulaşılamaz.</span>"
                )

            if selected_group != "__ALL__":
                filtered_accounts = []
                for acc in accounts:
                    email = acc.get("email", "").strip()
                    dom = email.split("@")[-1].strip().lower() if "@" in email else (acc.get("account_group", "").strip() or "Diğer")
                    if dom == selected_group.lower():
                        filtered_accounts.append(acc)
                accounts = filtered_accounts

            # Build UI rows immediately
            self.account_table.setRowCount(len(accounts))
            for i, acc in enumerate(accounts):
                acc_id = acc.get("id", i + 1)
                
                # Column 0: Checkbox
                chk_item = QTableWidgetItem()
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                chk_item.setCheckState(Qt.Unchecked)
                chk_item.setData(Qt.UserRole, acc_id)
                self.account_table.setItem(i, 0, chk_item)

                # Column 1: Account Info Widget
                info_widget = QWidget()
                info_layout = QVBoxLayout(info_widget)
                info_layout.setContentsMargins(8, 4, 8, 4)
                info_layout.setSpacing(2)
                
                email = acc.get("email", "").strip()
                dom = email.split("@")[-1].strip().lower() if "@" in email else (acc.get("account_group", "").strip() or "Diğer")
                group_badge = f"<span style='background-color:#e0e7ff; color:#2563eb; font-weight:bold; font-size:10px; padding:1px 5px; border-radius:4px;'>🌐 {dom}</span>" if dom else ""

                host = acc.get("imap_host", "")
                port = acc.get("imap_port", 993)
                try:
                    p_list = self.engine.db.get_server_profiles(acc_id)
                except Exception:
                    p_list = []

                if len(p_list) > 1:
                    active_p = next((p for p in p_list if p.get("is_default")), None)
                    p_name = active_p.get("profile_name", host) if active_p else host
                    server_badge = f"<span style='background-color:#dcfce7; color:#15803d; font-weight:bold; font-size:10px; padding:1px 6px; border-radius:4px;'>🔌 Aktif Sunucu: {p_name} ({host}) [{len(p_list)} Sunucu Tanımlı]</span>"
                else:
                    server_badge = f"<span style='color:#64748b; font-size:10px;'>🖥️ {host}:{port}</span>"

                lbl_label = QLabel(f"<b>{acc.get('label', 'Hesap')}</b>  {group_badge}")
                lbl_label.setStyleSheet("color: #0f172a; font-size: 12.5px; font-weight: 700;")
                
                lbl_email = QLabel(f"✉️ {acc.get('email', '')} &nbsp;&nbsp; {server_badge}")
                lbl_email.setStyleSheet("color: #334155; font-size: 11px; font-weight: 500;")
                
                if is_disk_online:
                    lbl_stats = QLabel("📂 <i>İstatistikler yükleniyor...</i>")
                    lbl_stats.setStyleSheet("color: #64748b; font-size: 10.5px; font-weight: 500;")
                else:
                    lbl_stats = QLabel("⚠️ <i>Yedekleme diski bekleniyor (Arşiv verileri çevrimdışı)</i>")
                    lbl_stats.setStyleSheet("color: #d97706; font-size: 10.5px; font-weight: 500;")
                self._stats_labels_map[acc_id] = lbl_stats
                
                info_layout.addWidget(lbl_label)
                info_layout.addWidget(lbl_email)
                info_layout.addWidget(lbl_stats)
                self.account_table.setCellWidget(i, 1, info_widget)
                
                # Column 2: Status & Row Progress Bar
                prog_widget = QWidget()
                prog_layout = QVBoxLayout(prog_widget)
                prog_layout.setContentsMargins(6, 4, 6, 4)
                prog_layout.setSpacing(3)
                
                status_text = "Hazır" if is_disk_online else "Çevrimdışı"
                lbl_status = QLabel(status_text)
                lbl_status.setStyleSheet("color: #475569; font-size: 11px; font-weight: 600;")
                
                progress_bar = QProgressBar()
                progress_bar.setRange(0, 100)
                progress_bar.setValue(0)
                progress_bar.setTextVisible(True)
                progress_bar.setStyleSheet("""
                    QProgressBar {
                        background: #e2e8f0;
                        border: none;
                        border-radius: 4px;
                        height: 14px;
                        font-size: 9px;
                        text-align: center;
                        color: #1e293b;
                        font-weight: bold;
                    }
                    QProgressBar::chunk {
                        background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #2563eb, stop: 1 #7c3aed);
                        border-radius: 4px;
                    }
                """)
                prog_layout.addWidget(lbl_status)
                prog_layout.addWidget(progress_bar)
                self.account_table.setCellWidget(i, 2, prog_widget)
                
                # Column 3: Row Action Buttons
                actions_widget = QWidget()
                actions_layout = QHBoxLayout(actions_widget)
                actions_layout.setContentsMargins(4, 2, 4, 2)
                actions_layout.setSpacing(4)
                
                btn_start = QPushButton("▶")
                btn_start.setToolTip("Bu hesap için arşivlemeyi başlat")
                btn_start.setCursor(Qt.PointingHandCursor)
                btn_start.setStyleSheet(self._action_btn_style("#10b981", "#059669"))
                btn_start.clicked.connect(lambda checked, aid=acc_id: self._trigger_individual_sync_direct(aid))
                
                btn_pause = QPushButton("⏸")
                btn_pause.setToolTip("Arşivlemeyi duraklat / sürdür")
                btn_pause.setCursor(Qt.PointingHandCursor)
                btn_pause.setStyleSheet(self._action_btn_style("#f59e0b", "#d97706"))
                btn_pause.setEnabled(False)
                btn_pause.clicked.connect(lambda checked, aid=acc_id: self._toggle_individual_pause(aid))
                
                btn_stop = QPushButton("⏹")
                btn_stop.setToolTip("Arşivlemeyi durdur")
                btn_stop.setCursor(Qt.PointingHandCursor)
                btn_stop.setStyleSheet(self._action_btn_style("#ef4444", "#dc2626"))
                btn_stop.setEnabled(False)
                btn_stop.clicked.connect(lambda checked, aid=acc_id: self._stop_individual_sync(aid))
                
                btn_report = QPushButton("📊")
                btn_report.setToolTip("Bu hesabın raporunu göster")
                btn_report.setCursor(Qt.PointingHandCursor)
                btn_report.setStyleSheet(self._action_btn_style("#2563eb", "#1d4ed8"))
                btn_report.clicked.connect(lambda checked, aid=acc_id: self._show_individual_report(aid))
                
                actions_layout.addWidget(btn_start)
                actions_layout.addWidget(btn_pause)
                actions_layout.addWidget(btn_stop)
                actions_layout.addWidget(btn_report)
                self.account_table.setCellWidget(i, 3, actions_widget)
                
                self._accounts_ui[acc_id] = {
                    "chk": chk_item,
                    "lbl_status": lbl_status,
                    "progress_bar": progress_bar,
                    "btn_start": btn_start,
                    "btn_pause": btn_pause,
                    "btn_stop": btn_stop,
                    "btn_report": btn_report,
                }
                
            self.set_row_height(self._current_row_height, auto_save=False)

            # Start Async Background Stats Loader
            if is_disk_online and accounts:
                acc_ids = [a["id"] for a in accounts if "id" in a]
                if self._data_loader and self._data_loader.isRunning():
                    self._data_loader.terminate()
                parent_mw = self.parent() if hasattr(self, "parent") else None
                if parent_mw and hasattr(parent_mw, "notify_disk_reading"):
                    parent_mw.notify_disk_reading("💾 Disk Okunuyor", "Senkronizasyon veritabanı ve klasör istatistikleri diskten taranıyor...")
                self._data_loader = SyncDataLoaderWorker(self.engine, acc_ids, parent=self)
                self._data_loader.account_loaded_signal.connect(self._on_account_stat_loaded)
                self._data_loader.finished_signal.connect(self._on_all_stats_loaded)
                self._data_loader.start()

        except Exception as exc:
            logger.error("Refresh error: %s", exc)
        finally:
            self.account_table.blockSignals(False)
            self._update_selection_count()
            self._is_refreshing = False

    @Slot(int, int, int)
    def _on_account_stat_loaded(self, acc_id: int, mails_cnt: int, folders_cnt: int):
        lbl = self._stats_labels_map.get(acc_id)
        if lbl:
            lbl.setText(f"📂 <b>{folders_cnt}</b> Klasör   •   📧 <b>{mails_cnt:,}</b> Arşivlenmiş Mail")

    @Slot(dict)
    def _on_all_stats_loaded(self, all_stats: dict):
        disk_path_str = self.settings.configured_data_path_str()
        total_accounts = len(self._accounts_ui)
        total_mails = sum(s.get("mails", 0) for s in all_stats.values())
        self.lbl_disk_status_text.setText(
            f"<b>Aktif Yedekleme Diski Bağlı:</b> <span style='color:#065f46;'>{disk_path_str}</span> "
            f"({total_accounts} Hesap, Toplam {total_mails:,} E-Posta Arşivli)"
        )
        self.card_server.set_value(f"{total_mails:,} Mail")
        parent_mw = self.parent() if hasattr(self, "parent") else None
        if parent_mw and hasattr(parent_mw, "notify_disk_ready"):
            parent_mw.notify_disk_ready("✅ Senkronizasyon Hazır", f"Toplam {total_mails:,} e-posta arşivi doğrulandı.", auto_dismiss_seconds=3)

    # ------------------------------------------------------------------
    # Group Sidebar Integration
    # ------------------------------------------------------------------

    def _refresh_groups_sidebar(self):
        domains_status = {}
        all_accounts = self.settings.load_account_cache() or self.engine.list_accounts()
        for acc in all_accounts:
            email = acc.get("email", "").strip()
            dom = email.split("@")[-1].strip().lower() if "@" in email else (acc.get("account_group", "").strip() or "Diğer")
            if not dom:
                dom = "Diğer"
            domains_status.setdefault(dom, {"is_active": True, "count": 0})
            domains_status[dom]["count"] += 1

        selected_domain = self.left_sidebar.get_selected_domain()
        self.left_sidebar.populate_domains(domains_status, total_accounts_count=len(all_accounts), preserve_selection=selected_domain)

    @Slot(str)
    def _on_group_filter_changed(self, group_name: str):
        self._selected_group = group_name or "__ALL__"
        self._all_selected_flag = False
        self.btn_select_all.setText("☑️ Tümünü Seç")
        self.refresh()
