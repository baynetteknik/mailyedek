"""
sync_panel.py — Email synchronization panel with detailed logging.
"""

import logging
import threading
import re
from typing import Optional
from datetime import datetime

from PySide6.QtCore import Qt, Slot, Signal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QDate, QObject, QEventLoop, QThread, QPoint, QTimer
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QGroupBox, QMessageBox, QListWidget, QListWidgetItem,
    QAbstractItemView, QFrame, QTableView, QComboBox, QLineEdit,
    QDialog, QDialogButtonBox, QCheckBox, QDateEdit, QTextEdit,
    QSpinBox, QMenu,
)

from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.widgets.pro_grid_widget import ProHeaderView

logger = logging.getLogger(__name__)

GLOBAL_MSG_STYLE = """
    QMessageBox, QDialog, QProgressDialog {
        background-color: #f8fafc;
    }
    QLabel {
        color: #0f172a;
        font-weight: 600;
        font-size: 13px;
    }
    QPushButton {
        background-color: #2563eb !important;
        color: #ffffff !important;
        font-weight: 700;
        font-size: 12px;
        border: none;
        border-radius: 6px;
        padding: 8px 20px;
        min-width: 95px;
        min-height: 28px;
    }
    QPushButton:hover {
        background-color: #1d4ed8 !important;
        color: #ffffff !important;
    }
    QPushButton:pressed {
        background-color: #1e40af !important;
        color: #ffffff !important;
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
    COLUMNS = ["Time", "Level", "Source", "Message"]

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
                    if self._filter_text.lower() in val.lower():
                        found = True
                        break
                if not found:
                    return False
        return source_row // self._page_size == self._page


# ---------------------------------------------------------------------------
# Stat card widget
# ---------------------------------------------------------------------------

class StatCard(QFrame):
    def __init__(self, title: str, value: str = "\u2014", parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            StatCard {
                background: #ffffff;
                border: 1.5px solid #d0d3d8;
                border-radius: 8px;
                padding: 6px;
            }
        """)
        self.setMinimumHeight(80)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            "font-size:11px;color:#6b7280;font-weight:500;border:none;"
        )
        self.title_label.setAlignment(Qt.AlignCenter)
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(
            "font-size:20px;font-weight:700;color:#1a1a2e;border:none;"
        )
        self.value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, val: str):
        self.value_label.setText(val)


# ---------------------------------------------------------------------------
# Reports popup dialog
# ---------------------------------------------------------------------------

class ReportsDialog(QDialog):
    def __init__(self, reports: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Senkronizasyon Sonuç Raporları")
        self.resize(880, 520)
        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
            }
            QLabel {
                color: #1e293b;
            }
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
            }
            QTableWidget {
                color: #1e293b;
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                gridline-color: #f1f5f9;
                border-radius: 6px;
            }
            QHeaderView::section {
                background-color: #f8fafc;
                color: #475569;
                font-weight: bold;
                padding: 10px;
                border: none;
                border-bottom: 2px solid #e2e8f0;
                font-size: 11px;
            }
            QPushButton {
                background-color: #4361ee;
                color: white;
                font-weight: 600;
                padding: 6px 16px;
                border-radius: 4px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #3a56d4;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # Header Title
        header_title = QLabel("📊 E-Posta Arşivleme Raporu")
        header_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        header_title.setStyleSheet("color: #1e293b; padding-bottom: 4px;")
        layout.addWidget(header_title)
        
        # Calculate Totals for Summary Cards
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
            
        # Horizontal layout for summary cards
        summary_layout = QHBoxLayout()
        summary_layout.setSpacing(10)
        
        cards_data = [
            ("Toplam Hesap", str(total_accounts), "#4361ee"),
            ("Çekilen İletiler", str(total_fetched), "#10b981"),
            ("Mükerrer (Kopya)", str(total_duplicates), "#f59e0b"),
            ("Hatalar", str(total_errors), "#ef4444" if total_errors > 0 else "#64748b"),
            ("Toplam Boyut", self._fmt_bytes(total_bytes), "#7209b7")
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
        
        # Detailed Table
        table = QTableWidget()
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels([
            "Hesap Adı", "Çekilen E-Posta", "Zaten Arşivlenmiş", "Güncellenmiş", 
            "Mükerrer (Kopya)", "Hatalar", "Veri Boyutu", "Süre"
        ])
        
        # Column resizing behavior
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
                
            # Account Label (left aligned, bold)
            item_lbl = QTableWidgetItem(str(g("account_label", "")))
            item_lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
            item_lbl.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            table.setItem(i, 0, item_lbl)
            
            # Fetched (green if > 0)
            fetched = g("mails_fetched", 0)
            item_fetched = QTableWidgetItem(str(fetched))
            if fetched > 0:
                item_fetched.setForeground(QColor("#10b981"))
                item_fetched.setFont(QFont("Segoe UI", 10, QFont.Bold))
            item_fetched.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 1, item_fetched)
            
            # Already Archived
            item_archived = QTableWidgetItem(str(g("mails_already_archived", 0)))
            item_archived.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 2, item_archived)
            
            # Updated
            item_updated = QTableWidgetItem(str(g("mails_updated", 0)))
            item_updated.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 3, item_updated)
            
            # Duplicates (orange/yellow if > 0)
            dupes = g("duplicates_found", 0)
            item_dupes = QTableWidgetItem(str(dupes))
            if dupes > 0:
                item_dupes.setForeground(QColor("#f59e0b"))
                item_dupes.setFont(QFont("Segoe UI", 10, QFont.Bold))
            item_dupes.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 4, item_dupes)
            
            # Errors (red if > 0)
            errors = g("errors", 0)
            item_errors = QTableWidgetItem(str(errors))
            if errors > 0:
                item_errors.setForeground(QColor("#ef4444"))
                item_errors.setFont(QFont("Segoe UI", 10, QFont.Bold))
            item_errors.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 5, item_errors)
            
            # Data bytes
            bv = g("total_bytes", 0)
            item_bytes = QTableWidgetItem(self._fmt_bytes(bv))
            item_bytes.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 6, item_bytes)
            
            # Duration
            dur = g("duration_seconds", 0)
            item_dur = QTableWidgetItem(f"{dur:.1f}s")
            item_dur.setTextAlignment(Qt.AlignCenter)
            table.setItem(i, 7, item_dur)
            
        layout.addWidget(table)

        # Collect error details
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
            err_box.setMaximumHeight(120)
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
                err_box.setPlainText(f"• Toplam {total_errors} adet senkronizasyon hatası oluştu. Ayrıntılar için sunucu bağlantınızı ve klasör izinlerini kontrol edin.")
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
        self.setWindowTitle("Detailed Diagnostics & Folder Report")
        self.resize(720, 500)
        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
            }
            QLabel {
                color: #1e293b;
            }
            QTextEdit {
                background-color: #ffffff;
                border: 1.5px solid #d0d3d8;
                border-radius: 6px;
                font-family: Consolas, Monaco, monospace;
                font-size: 11px;
                color: #334155;
            }
            QPushButton {
                background-color: #4361ee;
                color: white;
                font-weight: 600;
                padding: 8px 18px;
                border-radius: 6px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #3a56d4;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        info_label = QLabel("<b>System Diagnostics & Detailed Folder Report</b>")
        info_label.setStyleSheet("color: #1a1a2e; font-size: 13px;")
        layout.addWidget(info_label)
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setAcceptRichText(False)
        layout.addWidget(self.text_edit)
        
        btn_layout = QHBoxLayout()
        self.btn_copy = QPushButton("📋 Copy Diagnostics to Clipboard")
        self.btn_copy.setStyleSheet(self._btn_style("#2563eb", "#1d4ed8"))
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        
        self.btn_close = QPushButton("Close")
        self.btn_close.setStyleSheet(self._btn_style("#64748b", "#475569"))
        self.btn_close.clicked.connect(self.accept)
        
        btn_layout.addWidget(self.btn_copy)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)
        
        self._generate_report()

    def _generate_report(self):
        # 1. Gather stats
        stats = self.engine.get_stats()
        accounts = self.engine.list_accounts()
        db_path = self.engine.db._db_path
        
        report_lines = []
        report_lines.append("# MAIL ARCHIVE DIAGNOSTICS REPORT")
        report_lines.append(f"Generated At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("---")
        report_lines.append("## 1. System Info & Database Paths")
        report_lines.append(f"- **Database Path:** {db_path}")
        report_lines.append(f"- **Database File Size:** {self._fmt_size(db_path.stat().st_size) if db_path.exists() else 'N/A'}")
        report_lines.append(f"- **Attachments Folder:** {db_path.parent / 'attachments'}")
        
        report_lines.append("\n## 2. Database Stats")
        report_lines.append(f"- **Total Accounts:** {stats.get('total_accounts', len(accounts))}")
        report_lines.append(f"- **Total Emails Archived:** {stats.get('total_emails', 0)}")
        report_lines.append(f"- **Total Attachments:** {stats.get('total_attachments', 0)}")
        report_lines.append(f"- **Total Size of Archived Emails:** {self._fmt_size(stats.get('total_size_bytes', 0))}")
        
        report_lines.append("\n## 3. Account & Folder Detailed Listing")
        for acc in accounts:
            report_lines.append(f"\n### Account: {acc.get('label', '?')} ({acc.get('email', '?')})")
            report_lines.append(f"- **IMAP Host:** {acc.get('imap_host', '?')}:{acc.get('imap_port', 993)}")
            report_lines.append(f"- **Active Status:** {'Active' if acc.get('is_active', 1) else 'Inactive'}")
            
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
                report_lines.append(f"- *Error reading local database folders: {e}*")
            
            if folder_states:
                report_lines.append("| Folder Name | Archived Count | Last UID | UID Validity | Last Sync At |")
                report_lines.append("| --- | --- | --- | --- | --- |")
                for folder, last_uid, uid_validity, last_sync_at in folder_states:
                    count = folder_counts.get(folder, 0)
                    report_lines.append(f"| {folder} | {count} | {last_uid} | {uid_validity} | {last_sync_at} |")
            else:
                report_lines.append("- *No folders synchronized yet or folder states empty in database.*")
        
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
        QMessageBox.information(self, "Copied", "Detailed Diagnostics Report copied to clipboard!")


# ---------------------------------------------------------------------------
# Confirmation dialog
# ---------------------------------------------------------------------------

from PySide6.QtGui import QColor, QFont, QAction, QBrush, QPixmap, QPainter

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
        self.setStyleSheet("QDialog { background-color: #f8fafc; }")
        
        # Connect signal for background folder refreshes
        self._refresh_done_signal.connect(self._on_refresh_done_gui)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        
        # Header Info Displaying Account
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
        
        info_text = QLabel(f"<b>Hesap:</b> {account_label}<br/><span style='color: #64748b; font-size: 11px;'>Bu pencerede yapılacak filtre ayarları yalnızca bu hesaba uygulanacaktır.</span>")
        info_text.setStyleSheet("color: #1e293b; font-size: 13px;")
        header_layout.addWidget(info_text, stretch=1)
        layout.addWidget(header_frame)
        
        # Main body splitter/horizontal layout
        body_layout = QHBoxLayout()
        body_layout.setSpacing(14)
        
        # LEFT COLUMN: Folders Group Box (2/3 width)
        folders_group = QGroupBox("Arşivlenecek Klasörleri Seçin")
        folders_group.setStyleSheet("""
            QGroupBox {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 10px;
                font-weight: bold;
                font-size: 11px;
                color: #4361ee;
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
                color: #1e293b;
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
        
        # Control Buttons under Folder List
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
                color: #4361ee;
                border: 1px solid #cbd5e1;
                font-weight: 600;
                padding: 4px 12px;
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
        
        # RIGHT COLUMN: Advanced Filters Group Box (1/3 width)
        filters_group = QGroupBox("Gelişmiş Arşivleme Filtreleri")
        filters_group.setStyleSheet(folders_group.styleSheet())
        filters_layout = QVBoxLayout(filters_group)
        filters_layout.setContentsMargins(12, 16, 12, 12)
        filters_layout.setSpacing(10)
        
        self.chk_archive_unread = QCheckBox("Okunmamış iletileri de arşivle")
        self.chk_archive_unread.setChecked(archive_unread)
        self.chk_archive_unread.setStyleSheet("color: #1e293b; font-size: 12px;")
        filters_layout.addWidget(self.chk_archive_unread)
        
        since_layout = QVBoxLayout()
        self.chk_since_date = QCheckBox("Şu tarihten yeni iletiler:")
        self.chk_since_date.setChecked(since_date_enabled)
        self.chk_since_date.setStyleSheet("color: #1e293b; font-size: 12px;")
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
        self.chk_before_date.setStyleSheet("color: #1e293b; font-size: 12px;")
        self.date_edit_before = QDateEdit()
        self.date_edit_before.setCalendarPopup(True)
        self.date_edit_before.setDate(before_date)
        self.date_edit_before.setEnabled(before_date_enabled)
        self.chk_before_date.toggled.connect(self.date_edit_before.setEnabled)
        before_layout.addWidget(self.chk_before_date)
        before_layout.addWidget(self.date_edit_before)
        filters_layout.addLayout(before_layout)
        
        timeout_layout = QHBoxLayout()
        self.lbl_timeout = QLabel("Zaman Aşımı:")
        self.lbl_timeout.setStyleSheet("color: #1e293b; font-size: 12px;")
        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(10, 3600)
        self.spin_timeout.setValue(timeout)
        self.spin_timeout.setSuffix(" saniye")
        self.spin_timeout.setStyleSheet("color: #1e293b; font-size: 12px;")
        timeout_layout.addWidget(self.lbl_timeout)
        timeout_layout.addWidget(self.spin_timeout)
        timeout_layout.addStretch()
        filters_layout.addLayout(timeout_layout)
        filters_layout.addStretch()
        
        body_layout.addWidget(filters_group, stretch=1)
        layout.addLayout(body_layout)
        
        # OK / Cancel (Kaydet / Vazgeç) Buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Save).setText("Kaydet")
        btn_box.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        
        btn_box.setStyleSheet("""
            QPushButton {
                background: #4361ee;
                color: white;
                font-weight: 600;
                padding: 8px 20px;
                border-radius: 6px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #3a56d4;
            }
            QPushButton[text="Vazgeç"] {
                background: #64748b;
            }
            QPushButton[text="Vazgeç"]:hover {
                background: #475569;
            }
        """)
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
        
        import threading
        
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
                padding: 4px 10px;
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
            from pathlib import Path
            import re
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
                            
                # Check group/domain
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
            logger.exception("DryRunWorker run method crashed: %s", e)
        finally:
            self.finished_signal.emit(previews)

# ---------------------------------------------------------------------------
# Confirmation dialog
# ---------------------------------------------------------------------------

class SyncConfirmDialog(QDialog):
    def __init__(self, account_previews: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("İşlem Aktarma Raporu")
        self.resize(800, 500)
        self.setMinimumSize(700, 400)
        self.setStyleSheet("QDialog { background-color: #f8fafc; }")
        
        self.previews = account_previews
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        # 1. Header Banner
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(10, 10, 10, 10)
        header_layout.setSpacing(4)
        
        title_lbl = QLabel("İŞLEM AKTARMA RAPOR")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #4361ee; letter-spacing: 1px;")
        
        subtitle_lbl = QLabel("Bu ayarların tamamı Configure Filters (Filtre Ayarları) ekranından alınmıştır.")
        subtitle_lbl.setAlignment(Qt.AlignCenter)
        subtitle_lbl.setStyleSheet("font-size: 12px; color: #64748b;")
        
        header_layout.addWidget(title_lbl)
        header_layout.addWidget(subtitle_lbl)
        layout.addWidget(header_frame)
        
        # 2. Account Selector (Visible only if > 1 accounts are being synced)
        self.selector_layout = QHBoxLayout()
        if len(self.previews) > 1:
            lbl_sel = QLabel("<b>Hesap Seçin:</b>")
            lbl_sel.setStyleSheet("color: #334155; font-size: 13px;")
            self.combo_accounts = QComboBox()
            self.combo_accounts.setStyleSheet("""
                QComboBox {
                    padding: 6px 12px;
                    border: 1px solid #cbd5e1;
                    border-radius: 6px;
                    background-color: white;
                    min-width: 250px;
                }
            """)
            for idx, p in enumerate(self.previews):
                self.combo_accounts.addItem(p.get("label", f"Hesap #{idx+1}"), idx)
            self.combo_accounts.currentIndexChanged.connect(self._on_account_changed)
            self.selector_layout.addWidget(lbl_sel)
            self.selector_layout.addWidget(self.combo_accounts)
            self.selector_layout.addStretch()
            layout.addLayout(self.selector_layout)
            
        # 3. Main Body Horizontal Layout
        body_layout = QHBoxLayout()
        body_layout.setSpacing(15)
        
        # Left Panel - Folder List
        left_group = QGroupBox("Seçilmiş Olan Klasörler")
        left_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #334155;
                font-size: 13px;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        left_layout = QVBoxLayout(left_group)
        self.folder_list_widget = QListWidget()
        self.folder_list_widget.setStyleSheet("""
            QListWidget {
                border: none;
                background-color: transparent;
                font-size: 12px;
                color: #1e293b;
            }
            QListWidget::item {
                padding: 8px 10px;
                border-bottom: 1px solid #f1f5f9;
            }
            QListWidget::item:hover {
                background-color: #f1f5f9;
                border-radius: 4px;
            }
        """)
        left_layout.addWidget(self.folder_list_widget)
        body_layout.addWidget(left_group, stretch=2)
        
        # Right Panel - Stats Panel
        right_group = QGroupBox("Aktarılacak Klasör ve Mail Sayısı")
        right_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #334155;
                font-size: 13px;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        right_layout = QVBoxLayout(right_group)
        right_layout.setSpacing(18)
        right_layout.setContentsMargins(15, 20, 15, 20)
        
        # Labels for stats
        self.lbl_account_name = QLabel("HESAP: -")
        self.lbl_account_name.setStyleSheet("font-size: 12px; color: #64748b; font-weight: 600;")
        
        self.lbl_folder_count = QLabel("0 KLASÖR")
        self.lbl_folder_count.setStyleSheet("font-size: 22px; font-weight: bold; color: #4361ee;")
        
        self.lbl_mail_count = QLabel("0 MAİL")
        self.lbl_mail_count.setStyleSheet("font-size: 22px; font-weight: bold; color: #10b981;")
        
        # Date range section
        date_header = QLabel("AKTARILMA TARİH ARALIĞI")
        date_header.setStyleSheet("font-size: 11px; font-weight: bold; color: #94a3b8; letter-spacing: 0.5px; margin-top: 10px;")
        
        self.lbl_date_range = QLabel("Tüm Zamanlar")
        self.lbl_date_range.setStyleSheet("font-size: 14px; font-weight: 600; color: #4361ee;")
        
        # Add stats elements to layout
        right_layout.addWidget(self.lbl_account_name)
        
        # Horizontal line
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setStyleSheet("background-color: #e2e8f0; max-height: 1px;")
        right_layout.addWidget(line1)
        
        right_layout.addWidget(self.lbl_folder_count)
        right_layout.addWidget(self.lbl_mail_count)
        
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setStyleSheet("background-color: #e2e8f0; max-height: 1px;")
        right_layout.addWidget(line2)
        
        right_layout.addWidget(date_header)
        right_layout.addWidget(self.lbl_date_range)
        
        # Target directory section
        dir_header = QLabel("YEDEKLEME HEDEF DİZİNİ")
        dir_header.setStyleSheet("font-size: 11px; font-weight: bold; color: #94a3b8; letter-spacing: 0.5px; margin-top: 10px;")
        
        self.lbl_target_dir = QLabel("-")
        self.lbl_target_dir.setStyleSheet("font-size: 12px; font-weight: 600; color: #334155;")
        self.lbl_target_dir.setWordWrap(True)
        
        right_layout.addWidget(dir_header)
        right_layout.addWidget(self.lbl_target_dir)
        
        right_layout.addStretch()
        
        body_layout.addWidget(right_group, stretch=1)
        layout.addLayout(body_layout)
        
        # 4. Footer Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = QPushButton("Vazgeç")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background: #64748b;
                color: white;
                font-weight: 600;
                padding: 10px 25px;
                border-radius: 6px;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #475569;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        
        btn_ok = QPushButton("İşlemi Başlat")
        btn_ok.setStyleSheet("""
            QPushButton {
                background: #4361ee;
                color: white;
                font-weight: 600;
                padding: 10px 25px;
                border-radius: 6px;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #3a56d4;
            }
        """)
        btn_ok.clicked.connect(self.accept)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)
        
        # Load first preview by default
        self._load_preview(0)
        
    def _on_account_changed(self, idx):
        if idx >= 0:
            self._load_preview(idx)
            
    def _load_preview(self, idx):
        if idx < 0 or idx >= len(self.previews):
            return
            
        p = self.previews[idx]
        
        # Set account label
        self.lbl_account_name.setText(f"<b>HESAP:</b> {p.get('label', '?')}")
        
        self.folder_list_widget.clear()
        
        folders_list = p.get("folders_list", [])
        if folders_list:
            for f in folders_list:
                folder_name = f.get('folder', '?')
                new_cnt = f.get('new_mails', 0)
                self.folder_list_widget.addItem(f"📁 {folder_name} ({new_cnt} yeni e-posta)")
        else:
            self.folder_list_widget.addItem("📁 (Filtrelenen klasör yok)")
                
        folder_count = len(folders_list) if folders_list else p.get("folder_count", 0)
        self.lbl_folder_count.setText(f"<b>{folder_count} KLASÖR</b>")
        
        new_mails = p.get("new_mails", 0)
        self.lbl_mail_count.setText(f"<b>{new_mails} MAİL</b>")
        
        since_d = p.get("since_date")
        before_d = p.get("before_date")
        
        def fmt_dt(d_str):
            if not d_str:
                return ""
            try:
                dt = datetime.strptime(d_str, "%Y-%m-%d")
                return dt.strftime("%d.%m.%Y")
            except Exception:
                return d_str
                
        since_f = fmt_dt(since_d)
        before_f = fmt_dt(before_d)
        
        if since_f and before_f:
            self.lbl_date_range.setText(f"{since_f} - {before_f}")
        elif since_f:
            self.lbl_date_range.setText(f"{since_f} tarihinden yeni")
        elif before_f:
            self.lbl_date_range.setText(f"{before_f} tarihinden eski")
        else:
            self.lbl_date_range.setText("Tüm Zamanlar")
            
        target_dir = p.get("target_dir", "")
        self.lbl_target_dir.setText(target_dir)


class SyncFinishedDialog(QDialog):
    """Interactive dialog shown when all sync tasks finish.
    Displays a 5-second countdown timer on the Yes button.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("İşlem Tamamlandı")
        self.setMinimumWidth(420)
        self.setStyleSheet(GLOBAL_MSG_STYLE)

        self._remaining_seconds = 5

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header Title
        lbl_title = QLabel("✅ E-Posta Arşivleme İşlemi Tamamlandı!")
        lbl_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_title.setStyleSheet("color: #10b981;")
        layout.addWidget(lbl_title)

        # Message
        lbl_msg = QLabel("Detaylı senkronizasyon raporunu görüntülemek ister misiniz?")
        lbl_msg.setWordWrap(True)
        lbl_msg.setStyleSheet("color: #1e293b; font-size: 12px;")
        layout.addWidget(lbl_msg)

        # Buttons layout
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_no = QPushButton("Hayır (Kapat)")
        self.btn_no.setStyleSheet("""
            QPushButton {
                background-color: #64748b !important;
                color: #ffffff !important;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #475569 !important; }
        """)
        self.btn_no.clicked.connect(self._on_no_clicked)
        btn_layout.addWidget(self.btn_no)

        self.btn_yes = QPushButton(f"Evet ({self._remaining_seconds}sn sonra otomatik açılacak)")
        self.btn_yes.setDefault(True)
        self.btn_yes.setStyleSheet("""
            QPushButton {
                background-color: #2563eb !important;
                color: #ffffff !important;
                font-weight: bold;
                padding: 8px 20px;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #1d4ed8 !important; }
        """)
        self.btn_yes.clicked.connect(self._on_yes_clicked)
        btn_layout.addWidget(self.btn_yes)

        layout.addLayout(btn_layout)

        # QTimer setup (1 second interval)
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
# Main SyncPanel
# ---------------------------------------------------------------------------

_LOG_PARSE_RE = re.compile(r'^\[(\d+:\d+:\d+)\]\s*(.*)')


class SyncPanel(QWidget):
    """Email synchronization panel with detailed logging."""

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

        self._log_model = LogTableModel(self)
        self._log_proxy = LogFilterProxy(self)
        self._log_proxy.setSourceModel(self._log_model)
        
        self._active_syncs = {}  # account_id -> {cancel_event, pause_event, thread, status}
        self._accounts_ui = {}  # account_id -> {chk, lbl_status, progress_bar, btn_start, etc.}

        # Filter settings (stored in panel, configured via pop-up)
        self._filter_folders = None  # None means all folders
        self._filter_archive_unread = True
        self._filter_since_date_enabled = False
        self._filter_since_date = QDate.currentDate().addYears(-1)
        self._filter_before_date_enabled = False
        self._filter_before_date = QDate.currentDate()
        self._filter_timeout = 300

        self._setup_ui()
        
        # Signals
        self._log_signal.connect(self._on_log_message)
        self._account_progress_signal.connect(self._on_account_progress)
        self._account_sync_done_signal.connect(self._on_account_sync_done)
        self._account_sync_error_signal.connect(self._on_account_sync_error)
        self._account_dry_run_done_signal.connect(self._on_account_dry_run_done)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        # ----------------------------------------------------------------
        # Top Control Bar (Toolbar & Panel Toggles)
        # ----------------------------------------------------------------
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        lbl_title = QLabel("📧 E-Mail Synchronization")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #0f172a;")
        top_bar.addWidget(lbl_title)
        top_bar.addStretch()

        self.btn_toggle_stats = QPushButton("📊 İstatistikler")
        self.btn_toggle_stats.setToolTip("İstatistik kartlarını gizle/göster")
        self.btn_toggle_stats.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_stats.setStyleSheet(self._blue_btn_style(bg="#4b5563", hover="#374151", py=5, px=12, fs=11))
        self.btn_toggle_stats.clicked.connect(self._toggle_stats)
        top_bar.addWidget(self.btn_toggle_stats)

        self.btn_toggle_log = QPushButton("📋 Log Kutusu")
        self.btn_toggle_log.setToolTip("Sync log kutusunu gizle/göster")
        self.btn_toggle_log.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_log.setStyleSheet(self._blue_btn_style(bg="#4b5563", hover="#374151", py=5, px=12, fs=11))
        top_bar.addWidget(self.btn_toggle_log)

        self.btn_toggle_drawer = QPushButton("⚙️ İşlem Paneli ◀")
        self.btn_toggle_drawer.setToolTip("Sağ taraftaki işlem butonlarını gizle/göster")
        self.btn_toggle_drawer.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_drawer.setStyleSheet(self._blue_btn_style(bg="#2563eb", hover="#1d4ed8", py=5, px=14, fs=11))
        self.btn_toggle_drawer.clicked.connect(self._toggle_drawer)
        top_bar.addWidget(self.btn_toggle_drawer)

        layout.addLayout(top_bar)

        # ----------------------------------------------------------------
        # Collapsible Stat cards row
        # ----------------------------------------------------------------
        self.stats_widget = QWidget()
        stats_row = QHBoxLayout(self.stats_widget)
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(10)
        self.card_account = StatCard("Current Account", "—")
        self.card_server = StatCard("Server Emails", "—")
        self.card_folders = StatCard("Folders", "—")
        self.card_current = StatCard("Current Folder", "—")
        self.card_remaining = StatCard("Remaining", "—")
        self.card_progress = StatCard("Progress", "—")
        self.card_eta = StatCard("ETA", "—")
        stats_row.addWidget(self.card_account)
        stats_row.addWidget(self.card_server)
        stats_row.addWidget(self.card_folders)
        stats_row.addWidget(self.card_current)
        stats_row.addWidget(self.card_remaining)
        stats_row.addWidget(self.card_progress)
        stats_row.addWidget(self.card_eta)
        layout.addWidget(self.stats_widget)

        # ----------------------------------------------------------------
        # Main Body Split (Accounts Table + Collapsible Right Action Drawer)
        # ----------------------------------------------------------------
        body_split_layout = QHBoxLayout()
        body_split_layout.setSpacing(10)

        # Left/Center: Accounts Table Area
        accounts_group = QGroupBox("Hesap Listesi & Senkronizasyon Durumu")
        accounts_group.setStyleSheet("""
            QGroupBox {
                background: #ffffff;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 2px;
                font-weight: bold;
                font-size: 12px;
                color: #1e293b;
            }
        """)
        ag_layout = QVBoxLayout(accounts_group)
        ag_layout.setContentsMargins(10, 10, 10, 10)

        # DataGrid Top Control Bar (Tablo Üstü Araç Çubuğu)
        table_top_bar = QHBoxLayout()
        table_top_bar.setSpacing(8)

        self.btn_top_select_all = QPushButton("☑️ Tümünü Seç")
        self.btn_top_select_all.setToolTip("Tablodaki tüm hesapları seçer veya seçimleri kaldırır")
        self.btn_top_select_all.setStyleSheet(self._blue_btn_style(py=5, px=12, fs=11, bg="#475569", hover="#334155"))
        self.btn_top_select_all.clicked.connect(self._toggle_select_all)
        table_top_bar.addWidget(self.btn_top_select_all)

        self.btn_top_sync_selected = QPushButton("⚡ Seçilenleri Başlat")
        self.btn_top_sync_selected.setToolTip("Seçili kutucuğu işaretli tüm hesapların senkronizasyonunu başlatır")
        self.btn_top_sync_selected.setStyleSheet(self._blue_btn_style(py=5, px=12, fs=11, bg="#2563eb", hover="#1d4ed8"))
        self.btn_top_sync_selected.clicked.connect(self._sync_selected)
        table_top_bar.addWidget(self.btn_top_sync_selected)

        self.btn_top_sync_group = QPushButton("🚀 Grubu Senkronize Et")
        self.btn_top_sync_group.setToolTip("Seçili olan grubun/domain'in tüm hesaplarını senkronize eder")
        self.btn_top_sync_group.setStyleSheet(self._blue_btn_style(py=5, px=12, fs=11, bg="#10b981", hover="#059669"))
        self.btn_top_sync_group.clicked.connect(self._sync_current_group)
        table_top_bar.addWidget(self.btn_top_sync_group)

        self.lbl_selection_count = QLabel("0 / 0 Hesap Seçili")
        self.lbl_selection_count.setStyleSheet("color: #475569; font-size: 11px; padding-left: 6px;")
        table_top_bar.addWidget(self.lbl_selection_count)

        table_top_bar.addStretch()

        self.input_account_search = QLineEdit()
        self.input_account_search.setPlaceholderText("🔍 Tabloda Hesap / E-Posta Ara...")
        self.input_account_search.setMinimumWidth(200)
        self.input_account_search.setStyleSheet("""
            QLineEdit {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 11px;
                background-color: #ffffff;
            }
            QLineEdit:focus { border-color: #2563eb; }
        """)
        self.input_account_search.textChanged.connect(self._on_account_search_changed)
        table_top_bar.addWidget(self.input_account_search)

        ag_layout.addLayout(table_top_bar)

        main_h_layout = QHBoxLayout()
        main_h_layout.setSpacing(6)
        main_h_layout.setContentsMargins(0, 0, 0, 0)

        # Group/Domain Sidebar widget
        self.sidebar_widget = QWidget()
        self.sidebar_widget.setFixedWidth(180)
        sidebar_layout = QVBoxLayout(self.sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)

        lbl_groups = QLabel("Grup / Domain Filtresi")
        lbl_groups.setStyleSheet("font-weight: bold; color: #4361ee; font-size: 11px;")

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
        self.group_filter_list.itemSelectionChanged.connect(self._on_group_filter_changed)

        sidebar_layout.addWidget(lbl_groups)
        sidebar_layout.addWidget(self.group_filter_list)

        self.btn_toggle_sidebar = QPushButton("◀")
        self.btn_toggle_sidebar.setToolTip("Grup Listesini Gizle/Göster")
        self.btn_toggle_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_sidebar.setFixedWidth(16)
        self.btn_toggle_sidebar.setStyleSheet("""
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
            QPushButton:hover {
                background-color: #cbd5e1;
            }
        """)
        self.btn_toggle_sidebar.clicked.connect(self._toggle_sidebar)

        self.account_table = QTableWidget()
        self.account_table.setColumnCount(4)
        header = ProHeaderView(Qt.Horizontal, self.account_table)
        header.setSectionsMovable(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.save_requested.connect(self._save_grid_state)
        header.reset_requested.connect(self._reset_grid_state)
        self.account_table.setHorizontalHeader(header)
        self.account_table.setHorizontalHeaderLabels([
            "Sync", "Account Details", "Archiving Status & Progress", "Actions"
        ])
        self.account_table.setColumnWidth(0, 70)
        self.account_table.setColumnWidth(1, 400)
        self.account_table.setColumnWidth(2, 320)
        self.account_table.setColumnWidth(3, 150)
        self.account_table.verticalHeader().setDefaultSectionSize(92)
        self.account_table.verticalHeader().setVisible(False)
        self.account_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.account_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.account_table.customContextMenuRequested.connect(self._on_account_table_context_menu)
        self.account_table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                gridline-color: #f1f5f9;
                border: none;
            }
            QHeaderView::section {
                background-color: #f8fafc;
                color: #475569;
                font-weight: bold;
                border: none;
                border-bottom: 1px solid #cbd5e1;
                padding: 6px;
            }
        """)
        self.account_table.itemSelectionChanged.connect(self._on_table_row_click)

        main_h_layout.addWidget(self.sidebar_widget)
        main_h_layout.addWidget(self.btn_toggle_sidebar)
        main_h_layout.addWidget(self.account_table, stretch=1)
        ag_layout.addLayout(main_h_layout)

        body_split_layout.addWidget(accounts_group, stretch=1)

        # ----------------------------------------------------------------
        # Right Side Collapsible Action Drawer (Açılır Kapanır Sağ İşlem Paneli)
        # ----------------------------------------------------------------
        self.action_drawer = QGroupBox("⚙️ İşlemler")
        self.action_drawer.setFixedWidth(220)
        self.action_drawer.setStyleSheet("""
            QGroupBox {
                background: #ffffff;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 2px;
                font-weight: bold;
                font-size: 12px;
                color: #1e293b;
            }
        """)
        drawer_layout = QVBoxLayout(self.action_drawer)
        drawer_layout.setContentsMargins(10, 14, 10, 10)
        drawer_layout.setSpacing(8)

        lbl_sec1 = QLabel("⚡ SENKRONİZASYON")
        lbl_sec1.setStyleSheet("font-size: 10px; font-weight: bold; color: #64748b; letter-spacing: 0.5px;")
        drawer_layout.addWidget(lbl_sec1)

        self.btn_sync = QPushButton("🔄 Sync Selected")
        self.btn_sync.setToolTip("Seçili olan tüm hesapların senkronizasyonunu başlatır")
        self.btn_sync.setStyleSheet(self._blue_btn_style())
        self.btn_sync.setMinimumHeight(34)
        drawer_layout.addWidget(self.btn_sync)

        self.btn_sync_all = QPushButton("⚡ Sync All")
        self.btn_sync_all.setToolTip("Sistemdeki tüm hesapları senkronize eder")
        self.btn_sync_all.setStyleSheet(self._blue_btn_style())
        self.btn_sync_all.setMinimumHeight(34)
        drawer_layout.addWidget(self.btn_sync_all)

        self.btn_dry_run = QPushButton("🔍 Dry Run")
        self.btn_dry_run.setToolTip("Sunucuya bağlanıp taranacak mail sayısını hesaplar")
        self.btn_dry_run.setStyleSheet(self._blue_btn_style())
        self.btn_dry_run.setMinimumHeight(34)
        drawer_layout.addWidget(self.btn_dry_run)

        drawer_layout.addSpacing(6)
        lbl_sec2 = QLabel("⚙️ YAPIŞTIRMA & FİLTRE")
        lbl_sec2.setStyleSheet("font-size: 10px; font-weight: bold; color: #64748b; letter-spacing: 0.5px;")
        drawer_layout.addWidget(lbl_sec2)

        self.btn_filters = QPushButton("⚙️ Configure Filters...")
        self.btn_filters.setToolTip("Arşiv klasörlerini ve filtreleri ayarlar")
        self.btn_filters.setStyleSheet(self._blue_btn_style())
        self.btn_filters.setMinimumHeight(34)
        drawer_layout.addWidget(self.btn_filters)

        lbl_folder_lang = QLabel("🌐 KLASÖR İSİM DİLİ")
        lbl_folder_lang.setStyleSheet("font-size: 10px; font-weight: bold; color: #64748b; letter-spacing: 0.5px;")
        drawer_layout.addWidget(lbl_folder_lang)

        self.combo_folder_lang = QComboBox()
        self.combo_folder_lang.addItem("Orijinal Dilinde Bırak", "original")
        self.combo_folder_lang.addItem("Türkçeleştir (TR)", "tr")
        self.combo_folder_lang.addItem("İngilizceye Çevir (EN)", "en")
        self.combo_folder_lang.setToolTip("Sunucudan çekilen Rusça veya yabancı klasör isimlerinin dönüştürülme modu")
        self.combo_folder_lang.setStyleSheet("""
            QComboBox {
                padding: 6px 10px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background-color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                color: #1e293b;
            }
        """)
        # Set initial value from settings
        current_sync_lang = self.settings.folder_translation_sync()
        idx = self.combo_folder_lang.findData(current_sync_lang)
        if idx >= 0:
            self.combo_folder_lang.setCurrentIndex(idx)
        self.combo_folder_lang.currentIndexChanged.connect(self._on_folder_lang_changed)
        drawer_layout.addWidget(self.combo_folder_lang)

        self.btn_select_all = QPushButton("☑️ Select All")
        self.btn_select_all.setToolTip("Tüm hesapların seçim kutularını işaretler/temizler")
        self.btn_select_all.setStyleSheet(self._blue_btn_style())
        self.btn_select_all.setMinimumHeight(34)
        drawer_layout.addWidget(self.btn_select_all)

        drawer_layout.addSpacing(6)
        lbl_sec3 = QLabel("📊 RAPOR & DİAGNOSTİK")
        lbl_sec3.setStyleSheet("font-size: 10px; font-weight: bold; color: #64748b; letter-spacing: 0.5px;")
        drawer_layout.addWidget(lbl_sec3)

        self.btn_reports = QPushButton("📊 Reports")
        self.btn_reports.setToolTip("Oturum raporlarını görüntüler")
        self.btn_reports.setStyleSheet(self._blue_btn_style())
        self.btn_reports.setMinimumHeight(34)
        drawer_layout.addWidget(self.btn_reports)

        self.btn_detailed_report = QPushButton("🔬 Diagnostics")
        self.btn_detailed_report.setToolTip("Detaylı diagnostik raporunu gösterir")
        self.btn_detailed_report.setStyleSheet(self._blue_btn_style())
        self.btn_detailed_report.setMinimumHeight(34)
        drawer_layout.addWidget(self.btn_detailed_report)

        drawer_layout.addSpacing(6)
        lbl_sec4 = QLabel("⏹️ AKIŞ KONTROLÜ")
        lbl_sec4.setStyleSheet("font-size: 10px; font-weight: bold; color: #64748b; letter-spacing: 0.5px;")
        drawer_layout.addWidget(lbl_sec4)

        self.btn_pause = QPushButton("⏸️ Pause All")
        self.btn_pause.setToolTip("Aktif arşiv işlemlerini duraklatır")
        self.btn_pause.setStyleSheet(
            "QPushButton{background:#f39c12;color:white;font-weight:600;padding:8px 14px;border-radius:6px;font-size:12px; border: none;}"
            "QPushButton:hover{background:#d35400;}"
            "QPushButton:disabled{background:#cbd5e1;color:#94a3b8;}"
        )
        self.btn_pause.setEnabled(False)
        self.btn_pause.setMinimumHeight(34)
        drawer_layout.addWidget(self.btn_pause)

        self.btn_cancel = QPushButton("⏹️ Cancel All")
        self.btn_cancel.setToolTip("Aktif arşiv işlemlerini iptal eder")
        self.btn_cancel.setStyleSheet(
            "QPushButton{background:#e74c3c;color:white;font-weight:600;padding:8px 14px;border-radius:6px;font-size:12px; border: none;}"
            "QPushButton:hover{background:#c0392b;}"
            "QPushButton:disabled{background:#cbd5e1;color:#94a3b8;}"
        )
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setMinimumHeight(34)
        drawer_layout.addWidget(self.btn_cancel)

        drawer_layout.addStretch()

        body_split_layout.addWidget(self.action_drawer)
        layout.addLayout(body_split_layout, stretch=2)

        # ----------------------------------------------------------------
        # Legacy/Hidden controls (preserved to prevent breaking references)
        # ----------------------------------------------------------------
        self.account_list = QListWidget()  # Kept as fallback, hidden
        self.account_list.setVisible(False)
        self.folder_list = QListWidget()  # Kept as fallback, hidden
        self.folder_list.setVisible(False)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.label_status = QLabel("")
        self.label_status.setProperty("status", True)
        self.label_status.setVisible(False)
        layout.addWidget(self.label_status)

    @Slot(int)
    def _on_folder_lang_changed(self, index: int):
        mode = self.combo_folder_lang.itemData(index)
        if mode:
            self.settings.set_folder_translation_sync(mode)
            logger.info("Sync folder translation mode set to: %s", mode)


        # ----------------------------------------------------------------
        # Log table with filter + pagination
        # ----------------------------------------------------------------
        self.log_box = QGroupBox("Sync Log")
        self.log_box.setStyleSheet("""
            QGroupBox {
                background: #ffffff;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 6px;
                font-weight: bold;
                font-size: 12px;
                color: #1e293b;
            }
        """)
        log_layout = QVBoxLayout(self.log_box)
        log_layout.setContentsMargins(12, 16, 12, 12)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter log...")
        self.filter_input.setMinimumWidth(200)
        self.filter_input.setStyleSheet("""
            QLineEdit {
                border: 1.5px solid #cbd5e1;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }
        """)

        self.combo_page_size = QComboBox()
        self.combo_page_size.addItems(["25", "50", "100", "200", "All"])
        self.combo_page_size.setCurrentIndex(1)
        self.combo_page_size.setStyleSheet("""
            QComboBox {
                border: 1.5px solid #cbd5e1;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }
        """)

        self.btn_prev_page = QPushButton("\u25C0 Prev")
        self.btn_prev_page.setStyleSheet(self._blue_btn_style(py=4, px=10, fs=11))
        self.btn_next_page = QPushButton("Next \u25B6")
        self.btn_next_page.setStyleSheet(self._blue_btn_style(py=4, px=10, fs=11))
        self.label_page = QLabel("Page 1 / 1")
        self.label_page.setStyleSheet("font-size:12px;color:#4b5563;")

        self.btn_clear_log = QPushButton("Clear Log")
        self.btn_clear_log.setStyleSheet(self._blue_btn_style(py=4, px=10, fs=11))

        toolbar.addWidget(self.filter_input)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("Rows:"))
        toolbar.addWidget(self.combo_page_size)
        toolbar.addWidget(self.btn_prev_page)
        toolbar.addWidget(self.label_page)
        toolbar.addWidget(self.btn_next_page)
        toolbar.addWidget(self.btn_clear_log)
        log_layout.addLayout(toolbar)

        self.log_table = QTableView()
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setSelectionBehavior(QTableView.SelectRows)
        self.log_table.setSelectionMode(QTableView.NoSelection)
        self.log_table.setShowGrid(False)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.horizontalHeader().setStretchLastSection(True)
        self.log_table.setStyleSheet("""
            QTableView {
                background: #1a1a2e;
                color: #a8d8ea;
                font-family: 'Consolas','Courier New',monospace;
                font-size: 11px;
                border: 1px solid #2d2d44;
                border-radius: 4px;
                padding: 2px;
                gridline-color: #2d2d44;
            }
            QTableView::item { padding: 3px 6px; }
            QTableView::item:alternate { background: #1f1f36; }
            QHeaderView::section {
                background: #252542;
                color: #c4b5e3;
                font-weight: 600;
                font-size: 11px;
                padding: 4px 6px;
                border: none;
                border-bottom: 1px solid #2d2d44;
            }
        """)

        self.log_table.setModel(self._log_proxy)
        self.log_table.setColumnHidden(1, True)
        self.log_table.setColumnHidden(2, True)

        log_layout.addWidget(self.log_table)
        layout.addWidget(self.log_box, stretch=1)

        # ----------------------------------------------------------------
        # Connections
        # ----------------------------------------------------------------
        self.btn_sync.clicked.connect(self._sync_selected)
        self.btn_sync_all.clicked.connect(self._sync_all)
        self.btn_dry_run.clicked.connect(self._dry_run)
        self.btn_filters.clicked.connect(self._open_filters_dialog)
        self.btn_select_all.clicked.connect(self._toggle_select_all)
        self.btn_reports.clicked.connect(self._show_reports)
        self.btn_detailed_report.clicked.connect(self._show_detailed_report)
        self.btn_cancel.clicked.connect(self._cancel_sync)
        self.btn_pause.clicked.connect(self._toggle_pause_sync)
        self.btn_toggle_log.clicked.connect(self._toggle_log_visibility)
        
        self.filter_input.textChanged.connect(self._on_filter_changed)
        self.combo_page_size.currentIndexChanged.connect(self._on_page_size_changed)
        self.btn_prev_page.clicked.connect(self._prev_page)
        self.btn_next_page.clicked.connect(self._next_page)
        self.btn_clear_log.clicked.connect(self._clear_log)

    @staticmethod
    def _blue_btn_style(py=8, px=14, fs=12, bg="#4361ee", hover="#3a56d4"):
        return (
            f"QPushButton{{background:{bg};color:white;font-weight:600;"
            f"padding:{py}px {px}px;border-radius:6px;font-size:{fs}px; border: none;}}"
            f"QPushButton:hover{{background:{hover};}}"
            f"QPushButton:disabled{{background:#cbd5e1;color:#94a3b8;}}"
        )

    @staticmethod
    def _action_btn_style(bg_color: str, hover_color: str):
        return f"""
            QPushButton {{
                background-color: {bg_color};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px;
                min-width: 28px;
                min-height: 24px;
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
            msg.setStandardButtons(QMessageBox.Ok)
            ok_btn = msg.button(QMessageBox.Ok)
            if ok_btn:
                ok_btn.setText("Tamam")
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
    # Stat card updates
    # ------------------------------------------------------------------

    def _update_stats(self, account="\u2014", server_emails="\u2014",
                      folders="\u2014", current="\u2014",
                      remaining="\u2014", progress="\u2014", eta="\u2014"):
        self.card_account.set_value(str(account))
        self.card_server.set_value(str(server_emails))
        self.card_folders.set_value(str(folders))
        self.card_current.set_value(str(current))
        self.card_remaining.set_value(str(remaining))
        self.card_progress.set_value(str(progress))
        self.card_eta.set_value(str(eta))

    # ------------------------------------------------------------------
    # Log Toggling
    # ------------------------------------------------------------------

    @Slot()
    def _toggle_log_visibility(self):
        is_visible = self.log_box.isVisible()
        self.log_box.setVisible(not is_visible)
        if is_visible:
            self.btn_toggle_log.setText("📋 Log Kutusu (Gizli)")
        else:
            self.btn_toggle_log.setText("📋 Log Kutusu")

    @Slot()
    def _toggle_stats(self):
        is_visible = self.stats_widget.isVisible()
        self.stats_widget.setVisible(not is_visible)
        if is_visible:
            self.btn_toggle_stats.setText("📊 İstatistikler (Gizli)")
        else:
            self.btn_toggle_stats.setText("📊 İstatistikler")

    @Slot()
    def _toggle_drawer(self):
        is_visible = self.action_drawer.isVisible()
        self.action_drawer.setVisible(not is_visible)
        if is_visible:
            self.btn_toggle_drawer.setText("⚙️ İşlem Paneli ▶")
        else:
            self.btn_toggle_drawer.setText("⚙️ İşlem Paneli ◀")

    @Slot()
    def _toggle_sidebar(self):
        is_visible = self.sidebar_widget.isVisible()
        self.sidebar_widget.setVisible(not is_visible)
        if is_visible:
            self.btn_toggle_sidebar.setText("▶")
        else:
            self.btn_toggle_sidebar.setText("◀")


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
        if not ids:
            for i in range(self.account_table.rowCount()):
                if not self.account_table.isRowHidden(i):
                    item = self.account_table.item(i, 0)
                    if item:
                        acc_id = item.data(Qt.UserRole)
                        if acc_id is not None:
                            ids.append(acc_id)
        return ids

    def _toggle_select_all(self):
        if self._all_selected_flag:
            for i in range(self.account_table.rowCount()):
                item = self.account_table.item(i, 0)
                if item:
                    item.setCheckState(Qt.Unchecked)
            self.btn_select_all.setText("☑️ Tümünü Seç")
            if hasattr(self, 'btn_top_select_all'):
                self.btn_top_select_all.setText("☑️ Tümünü Seç")
            self._all_selected_flag = False
        else:
            for i in range(self.account_table.rowCount()):
                item = self.account_table.item(i, 0)
                if item:
                    item.setCheckState(Qt.Checked)
            self.btn_select_all.setText("🔳 Seçimleri Kaldır")
            if hasattr(self, 'btn_top_select_all'):
                self.btn_top_select_all.setText("🔳 Seçimleri Kaldır")
            self._all_selected_flag = True
        self._update_selection_count()

    def _update_selection_count(self):
        total = self.account_table.rowCount()
        selected = len(self._get_selected_account_ids())
        if hasattr(self, 'lbl_selection_count'):
            self.lbl_selection_count.setText(f"<b>{selected}</b> / {total} Hesap Seçili")

    @Slot(str)
    def _on_account_search_changed(self, text: str):
        text = text.strip().lower()
        for i in range(self.account_table.rowCount()):
            widget = self.account_table.cellWidget(i, 1)
            match = True
            if text:
                match = False
                if widget:
                    labels = widget.findChildren(QLabel)
                    for lbl in labels:
                        if text in lbl.text().lower():
                            match = True
                            break
            self.account_table.setRowHidden(i, not match)
        self._update_selection_count()

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
            
        # Update stat cards from last cached stats
        status = ui["lbl_status"].text()
        progress_val = ui["progress_bar"].value()
        progress_max = ui["progress_bar"].maximum()
        
        prog_text = "\u2014"
        if progress_max > 0:
            prog_text = f"{int((progress_val / progress_max) * 100)}%"
        elif "Done" in status:
            prog_text = "100%"
            
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

        # Parse account label name
        widget = self.account_table.cellWidget(self.account_table.currentRow(), 1)
        account_name = "\u2014"
        if widget:
            lbl = widget.findChild(QLabel)
            if lbl:
                account_name = lbl.text().replace("<b>", "").replace("</b>", "")

        self._update_stats(
            account=account_name,
            current=status,
            progress=prog_text,
            folders=str(folders_cnt),
            server_emails=f"{local_mails_cnt} (Local)",
            remaining=str(progress_max - progress_val) if progress_max > 0 else "\u2014",
        )

    # ------------------------------------------------------------------
    # Individual Sync Workers (Multi-threaded per account)
    # ------------------------------------------------------------------

    def _start_individual_sync(self, account_id: int):
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
            ui["lbl_status"].setText("Connecting...")
            ui["progress_bar"].setRange(0, 0)
            
        self._active_syncs[account_id] = {
            "cancel_event": cancel_event,
            "pause_event": pause_event,
            "status": "Connecting",
            "thread": None,
        }
        
        # Enabled global cancel/pause
        self.btn_cancel.setEnabled(True)
        self.btn_pause.setEnabled(True)
        
        # Load account-specific filters
        f_data = self.settings.account_sync_filters(account_id) or {}
        folder_filter = f_data.get("folders")
        since_date_enabled = f_data.get("since_date_enabled", False)
        since_date = f_data.get("since_date") if since_date_enabled else None
        before_date_enabled = f_data.get("before_date_enabled", False)
        before_date = f_data.get("before_date") if before_date_enabled else None
        archive_unread = f_data.get("archive_unread", True)
        timeout = f_data.get("timeout", 180)
        
        def progress_cb(aid: int, folder_name: str, current: int, total: int):
            self._account_progress_signal.emit(aid, f"Syncing {folder_name}", current, total)
            
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
            ui["lbl_status"].setText("Resumed")
            self._log_callback(f"Account ID {account_id} sync resumed")
        else:
            pe.set()
            ui["btn_pause"].setText("▶")
            ui["lbl_status"].setText("Paused")
            self._log_callback(f"Account ID {account_id} sync paused — waiting at next item...")

    def _stop_individual_sync(self, account_id: int):
        sync = self._active_syncs.get(account_id)
        ui = self._accounts_ui.get(account_id)
        if not sync or not ui:
            return
            
        sync["cancel_event"].set()
        ui["btn_stop"].setEnabled(False)
        ui["lbl_status"].setText("Stopping...")
        self._log_callback(f"Account ID {account_id} sync cancellation requested")

    def _show_individual_report(self, account_id: int):
        label = ""
        for i in range(self.account_table.rowCount()):
            item = self.account_table.item(i, 0)
            if item and item.data(Qt.UserRole) == account_id:
                widget = self.account_table.cellWidget(i, 1)
                if widget:
                    lbl = widget.findChild(QLabel)
                    if lbl:
                        label = lbl.text().replace("<b>", "").replace("</b>", "")
                break
                
        acc_reports = []
        for r in self._reports:
            r_lbl = r.get("account_label") if isinstance(r, dict) else getattr(r, "account_label", "")
            if r_lbl == label:
                acc_reports.append(r)
                
        if not acc_reports:
            QMessageBox.information(self, "No Reports", "No sync reports available for this account in this session.")
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
            ui["progress_bar"].setRange(0, total)
            ui["progress_bar"].setValue(current)
            
        if account_id in self._active_syncs:
            self._active_syncs[account_id]["status"] = status_text
            
        if self._get_active_row_account_id() == account_id:
            local_mails_cnt = 0
            folders_cnt = 0
            try:
                with self.engine.db.get_conn() as conn:
                    row_mails = conn.execute("SELECT COUNT(*) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (account_id,)).fetchone()
                    local_mails_cnt = row_mails["cnt"] if row_mails else 0
                    row_folders = conn.execute("SELECT COUNT(DISTINCT folder) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (account_id,)).fetchone()
                    folders_cnt = row_folders["cnt"] if row_folders else 0
            except Exception:
                pass
            prog_text = f"{int((current/total)*100)}%" if total > 0 else "0%"
            self.card_current.set_value(status_text)
            self.card_remaining.set_value(str(total - current))
            self.card_progress.set_value(prog_text)
            self.card_folders.set_value(str(folders_cnt))
            self.card_server.set_value(f"{local_mails_cnt + (total - current)} (Local)")
            
            # Simple ETA
            eta_sec = int((total - current) * 0.3)
            if eta_sec > 60:
                self.card_eta.set_value(f"{eta_sec // 60}m {eta_sec % 60}s")
            else:
                self.card_eta.set_value(f"{eta_sec}s")

    @Slot(int, object)
    def _on_account_sync_done(self, account_id: int, report: Any):
        ui = self._accounts_ui.get(account_id)
        if ui:
            ui["btn_start"].setEnabled(True)
            ui["btn_pause"].setEnabled(False)
            ui["btn_stop"].setEnabled(False)
            
            cancelled = account_id in self._active_syncs and self._active_syncs[account_id]["cancel_event"].is_set()
            if cancelled:
                ui["lbl_status"].setText("Cancelled")
                ui["progress_bar"].setRange(0, 100)
                ui["progress_bar"].setValue(0)
            else:
                fetched = report.get("mails_fetched", 0) if isinstance(report, dict) else getattr(report, "mails_fetched", 0)
                ui["lbl_status"].setText(f"Done: {fetched} fetched")
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
        
        if not self._active_syncs:
            self._on_all_syncs_finished()

    @Slot(int, str)
    def _on_account_sync_error(self, account_id: int, err_msg: str):
        ui = self._accounts_ui.get(account_id)
        if ui:
            ui["btn_start"].setEnabled(True)
            ui["btn_pause"].setEnabled(False)
            ui["btn_stop"].setEnabled(False)
            ui["lbl_status"].setText(f"Error: {err_msg}")
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
        
        if not self._active_syncs:
            self._on_all_syncs_finished()



    def _on_all_syncs_finished(self):
        self.btn_cancel.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸️ Pause All")
        self._log_callback("All background sync tasks finished.")
        
        if self._reports:
            try:
                if len(self._reports) > 1:
                    self.engine.reporter.generate_batch_sync_report(self._reports, group_name="Toplu Sync Raporu", output_format="both")
                elif len(self._reports) == 1:
                    r = self._reports[0]
                    r_dict = r if isinstance(r, dict) else (r.__dict__ if hasattr(r, "__dict__") else {})
                    self.engine.reporter.generate_sync_report(r_dict, output_format="both")
            except Exception as e:
                logger.error("Failed to save sync report in reporter: %s", e)

            dialog = SyncFinishedDialog(self)
            if dialog.exec() == QDialog.Accepted:
                rep_dialog = ReportsDialog(self._reports, self)
                rep_dialog.exec()

    # ------------------------------------------------------------------
    # Log callback & parsing
    # ------------------------------------------------------------------

    def _log_callback(self, msg: str):
        self._log_signal.emit(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _log_callback_unsafe(self, msg: str):
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
            self._log_model.append_entry(entry)
            if getattr(self, '_log_proxy', None) is not None:
                self._update_pagination()
                self._log_proxy.set_page(self._log_proxy.total_pages() - 1)
                self._update_pagination()

        # Clean parsing for Current Folder stat card
        if "Syncing folder" in message:
            folder_start_match = re.search(r'Syncing folder \'([^\']+)\'', message)
            if folder_start_match:
                fld = folder_start_match.group(1)
                self.card_current.set_value(fld)
        elif "Fetching UID" in message:
            progress_match = re.search(r'\[([^\]]+)\]\s+Fetching UID \d+\s+\((\d+)/(\d+)\)', message)
            if progress_match:
                fld = progress_match.group(1)
                curr = int(progress_match.group(2))
                tot = int(progress_match.group(3))
                self.card_current.set_value(fld)
                self.card_remaining.set_value(str(tot - curr))
                self.card_progress.set_value(f"{int((curr/tot)*100)}%")
                
                # Simple ETA
                eta_sec = int((tot - curr) * 0.3)
                if eta_sec > 60:
                    self.card_eta.set_value(f"{eta_sec // 60}m {eta_sec % 60}s")
                else:
                    self.card_eta.set_value(f"{eta_sec}s")
        elif "Folder done" in message:
            folder_done_match = re.search(r'\[([^\]]+)\]\s*===\s*Folder done', message)
            if folder_done_match:
                fld = folder_done_match.group(1)
                self.card_current.set_value(f"{fld} (Done)")
                self.card_remaining.set_value("0")
                self.card_progress.set_value("100%")
                self.card_eta.set_value("0s")
        elif source != "sync" and "Syncing" in message:
            self.card_account.set_value(source)

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _update_pagination(self):
        if hasattr(self, 'label_page') and self.label_page and getattr(self, '_log_proxy', None) is not None:
            total = self._log_proxy.total_pages()
            cur = self._log_proxy.current_page() + 1
            self.label_page.setText(f"Page {cur} / {total}")
            if hasattr(self, 'btn_prev_page') and self.btn_prev_page:
                self.btn_prev_page.setEnabled(cur > 1)
            if hasattr(self, 'btn_next_page') and self.btn_next_page:
                self.btn_next_page.setEnabled(cur < total)

    def _on_filter_changed(self, text: str):
        self._log_proxy.set_filter_text(text)
        self._update_pagination()

    def _on_page_size_changed(self, idx: int):
        val = self.combo_page_size.currentText()
        if val == "All":
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
        """Run dry-run on selected accounts in a background thread, show confirmation, return True if OK."""
        from PySide6.QtWidgets import QProgressDialog, QApplication
        
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
        progress.setStyleSheet("QProgressDialog { background-color: #f8fafc; } QLabel { color: #1e293b; }")
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


    def _on_account_table_context_menu(self, pos: QPoint):
        row = self.account_table.rowAt(pos.y())
        acc_id = None
        acc = None

        if row >= 0:
            item = self.account_table.item(row, 0)
            if item:
                acc_id = item.data(Qt.UserRole)
                acc = self.engine.accounts.get(acc_id)

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 6px; }
            QMenu::item { padding: 8px 24px; font-size: 12px; color: #1e293b; border-radius: 4px; font-weight: 500; }
            QMenu::item:selected { background-color: #2563eb; color: #ffffff; font-weight: bold; }
            QMenu::separator { height: 1px; background: #e2e8f0; margin: 4px 8px; }
        """)

        act_sync_selected = menu.addAction("⚡ Seçili Hesapları Senkronize Et (Sync Selected)")
        act_sync_group = menu.addAction("🚀 Seçili Grubu Senkronize Et (Sync Group)")
        act_sync_all = menu.addAction("🌐 Tüm Hesapları Senkronize Et (Sync All)")
        menu.addSeparator()
        act_select_all = menu.addAction("☑️ Tümünü Seç (Select All)")
        act_deselect_all = menu.addAction("🔳 Seçimleri Kaldır (Deselect All)")
        menu.addSeparator()

        act_sync_this = None
        act_pause_this = None
        act_stop_this = None
        act_dry = None
        act_flt = None
        act_rep = None
        act_copy = None

        if acc_id is not None and acc:
            acc_label = acc.get("label", f"Hesap #{acc_id}")
            act_sync_this = menu.addAction(f"▶ '{acc_label}' İçin Senkronizasyonu Başlat")
            act_pause_this = menu.addAction(f"⏸ Duraklat / Sürdür")
            act_stop_this = menu.addAction(f"⏹ İptal Et / Durdur")
            menu.addSeparator()
            act_dry = menu.addAction("🔍 Kuru Çalıştırma / Önizleme (Dry Run)")
            act_flt = menu.addAction("⚙️ Klasör & Filtre Ayarları...")
            act_rep = menu.addAction("📊 Raporları Göster")
            act_copy = menu.addAction("📋 E-Posta Adresini Kopyala")

        action = menu.exec(self.account_table.viewport().mapToGlobal(pos))
        if not action:
            return

        if action == act_sync_selected:
            self._sync_selected()
        elif action == act_sync_group:
            self._sync_current_group()
        elif action == act_sync_all:
            self._sync_all()
        elif action == act_select_all:
            if not self._all_selected_flag:
                self._toggle_select_all()
        elif action == act_deselect_all:
            if self._all_selected_flag:
                self._toggle_select_all()
        elif action == act_sync_this and acc_id is not None:
            self._trigger_individual_sync_direct(acc_id)
        elif action == act_pause_this and acc_id is not None:
            self._toggle_individual_pause(acc_id)
        elif action == act_stop_this and acc_id is not None:
            self._stop_individual_sync(acc_id)
        elif action == act_dry and acc_id is not None:
            self._confirm_sync([acc_id])
        elif action == act_flt and acc_id is not None:
            self._open_filters_dialog_for_account(acc_id)
        elif action == act_rep:
            self._show_reports()
        elif action == act_copy and acc:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(acc.get("email", ""))

    # ------------------------------------------------------------------
    # Sync operations (Global Actions)
    # ------------------------------------------------------------------

    def _trigger_individual_sync_direct(self, acc_id: int):
        self._start_individual_sync(acc_id)

    def _trigger_sync_for_accounts(self, ids: list):
        if not ids:
            return
        self._reports.clear()
        for acc_id in ids:
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
        if hasattr(self, 'btn_top_select_all'):
            self.btn_top_select_all.setText("🔳 Seçimleri Kaldır")
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
        if hasattr(self, 'btn_top_select_all'):
            self.btn_top_select_all.setText("🔳 Seçimleri Kaldır")
        self._update_selection_count()

        if ids:
            self._trigger_sync_for_accounts(ids)
        else:
            QMessageBox.warning(self, "Hesap Bulunamadı", "Seçili grupta senkronize edilecek hesap bulunamadı.")


    @Slot()
    def _cancel_sync(self):
        self._log_callback("Global cancellation requested — stopping all account syncs...")
        for aid in list(self._active_syncs.keys()):
            self._stop_individual_sync(aid)

    @Slot()
    def _toggle_pause_sync(self):
        any_running = False
        for aid in self._active_syncs:
            # If pause event is not set, then it is running
            if not self._active_syncs[aid]["cancel_event"].is_set() and not self._active_syncs[aid]["pause_event"].is_set():
                any_running = True
                break
                
        if any_running:
            self._log_callback("Global pause requested...")
            for aid in self._active_syncs:
                if not self._active_syncs[aid]["pause_event"].is_set():
                    self._toggle_individual_pause(aid)
            self.btn_pause.setText("▶️ Resume All")
        else:
            self._log_callback("Global resume requested...")
            for aid in self._active_syncs:
                if self._active_syncs[aid]["pause_event"].is_set():
                    self._toggle_individual_pause(aid)
            self.btn_pause.setText("⏸️ Pause All")

    # ------------------------------------------------------------------
    # Dry Run
    # ------------------------------------------------------------------

    @Slot()
    def _dry_run(self):
        ids = self._get_selected_account_ids()
        if not ids:
            QMessageBox.warning(self, "No Selection", "Select at least one account from the list.")
            return
            
        self._log_callback(f"--- Dry Run (Estimation) for {len(ids)} account(s) ---")

        # Check filters for dry run too
        for acc_id in ids:
            f_data = self.settings.account_sync_filters(acc_id)
            if not f_data:
                acc = self.engine.accounts.get(acc_id)
                acc_label = acc.get("label", f"Hesap #{acc_id}") if acc else f"Hesap #{acc_id}"
                
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Information)
                msg.setWindowTitle("Filtre Ayarı Eksik")
                msg.setText(f"'{acc_label}' hesabı için arşivleme filtreleri henüz ayarlanmamış.\n\nLütfen arşivlenecek klasörleri seçin.")
                msg.setStyleSheet("QMessageBox { background-color: #f8fafc; } QLabel { color: #1e293b; }")
                msg.exec()
                
                self._open_filters_dialog_for_account(acc_id, force_prompt=True)
                f_data = self.settings.account_sync_filters(acc_id)
                if not f_data:
                    self._log_callback(f"[{acc_label}] Klasör eşleştirme/filtre ayarı iptal edildi.")
                    return

        def task(acc_id):
            ui = self._accounts_ui.get(acc_id)
            if ui:
                ui["lbl_status"].setText("Estimating...")
                ui["progress_bar"].setRange(0, 0)
            
            f_data = self.settings.account_sync_filters(acc_id) or {}
            folder_filter = f_data.get("folders")
            since_date_enabled = f_data.get("since_date_enabled", False)
            since_date = f_data.get("since_date") if since_date_enabled else None
            before_date_enabled = f_data.get("before_date_enabled", False)
            before_date = f_data.get("before_date") if before_date_enabled else None
            archive_unread = f_data.get("archive_unread", True)
            
            try:
                result = self.engine.sync_dry_run(
                    acc_id,
                    folder_filter=folder_filter,
                    since_date=since_date,
                    before_date=before_date,
                    archive_unread=archive_unread,
                )
                total = result.get("total_estimated", 0)
                error = result.get("error", None)
                self._account_dry_run_done_signal.emit(acc_id, total, error)
            except Exception as exc:
                self._account_dry_run_done_signal.emit(acc_id, 0, str(exc))

        for aid in ids:
            threading.Thread(target=task, args=(aid,), daemon=True).start()

    @Slot(int, int, object)
    def _on_account_dry_run_done(self, account_id: int, total: int, error: Optional[str]):
        ui = self._accounts_ui.get(account_id)
        if ui:
            ui["progress_bar"].setRange(0, 100)
            if error:
                ui["lbl_status"].setText(f"Preview error: {error}")
                ui["progress_bar"].setValue(0)
                self._log_callback(f"Preview error for account ID {account_id}: {error}")
            else:
                ui["lbl_status"].setText(f"Preview: ~{total} new mails")
                ui["progress_bar"].setValue(100)
                self._log_callback(f"Preview completed for account ID {account_id}: ~{total} new mails")
                
        # Update global stats if focused
        if self._get_active_row_account_id() == account_id:
            local_mails_cnt = 0
            folders_cnt = 0
            try:
                with self.engine.db.get_conn() as conn:
                    row_mails = conn.execute("SELECT COUNT(*) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (account_id,)).fetchone()
                    local_mails_cnt = row_mails["cnt"] if row_mails else 0
                    row_folders = conn.execute("SELECT COUNT(DISTINCT folder) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (account_id,)).fetchone()
                    folders_cnt = row_folders["cnt"] if row_folders else 0
            except Exception:
                pass
            total_server = local_mails_cnt + total
            self._update_stats(
                server_emails=f"{total_server} (Server)",
                folders=str(folders_cnt),
                remaining=str(total),
                progress="0%" if total > 0 else "100%",
            )

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
                msg.setStandardButtons(QMessageBox.Ok)
                ok_btn = msg.button(QMessageBox.Ok)
                if ok_btn:
                    ok_btn.setText("Tamam")
                msg.setStyleSheet(GLOBAL_MSG_STYLE)
                msg.exec()
                return
        dialog = ReportsDialog(self._reports, self)
        dialog.exec()

    @Slot()
    def _show_detailed_report(self):
        dialog = DetailedReportDialog(self.engine, self)
        dialog.exec()

    def _get_since_date(self) -> Optional[str]:
        if not self._filter_since_date_enabled:
            return None
        qdate = self._filter_since_date
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        day = qdate.day()
        month_str = months[qdate.month() - 1]
        year = qdate.year()
        return f"{day:02d}-{month_str}-{year}"

    def _get_before_date(self) -> Optional[str]:
        if not self._filter_before_date_enabled:
            return None
        qdate = self._filter_before_date
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        day = qdate.day()
        month_str = months[qdate.month() - 1]
        year = qdate.year()
        return f"{day:02d}-{month_str}-{year}"

    def _get_archive_unread(self) -> bool:
        return self._filter_archive_unread

    def _get_timeout(self) -> int:
        return self._filter_timeout

    def _set_buttons_enabled(self, enabled: bool):
        # Retained for legacy compatibility but not strictly needed anymore
        for btn in (self.btn_sync, self.btn_sync_all, self.btn_dry_run,
                    self.btn_select_all, self.btn_reports, self.btn_detailed_report):
            btn.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self):
        self._refresh_groups_sidebar()

        self.account_table.blockSignals(True)
        self.account_table.setRowCount(0)
        self._accounts_ui.clear()

        selected_item = self.group_filter_list.currentItem()
        selected_group = selected_item.data(Qt.UserRole) if selected_item else "__ALL__"

        try:
            accounts = self.engine.list_accounts()
            # Filter accounts by selected group
            if selected_group != "__ALL__":
                filtered_accounts = []
                for acc in accounts:
                    g_val = acc.get("account_group", "").strip()
                    if not g_val and "@" in acc.get("email", ""):
                        g_val = acc["email"].split("@")[-1]
                    if g_val == selected_group:
                        filtered_accounts.append(acc)
                accounts = filtered_accounts

            self.account_table.setRowCount(len(accounts))
            for i, acc in enumerate(accounts):
                acc_id = acc["id"]
                
                # Column 0: Sync Checkbox
                chk_item = QTableWidgetItem()
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                chk_item.setCheckState(Qt.Unchecked)
                chk_item.setData(Qt.UserRole, acc_id)
                self.account_table.setItem(i, 0, chk_item)
                
                # Query local stats
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

                # Column 1: Account details (name + email + stats in 3 distinct well-spaced lines)
                info_widget = QWidget()
                info_layout = QVBoxLayout(info_widget)
                info_layout.setContentsMargins(10, 8, 10, 8)
                info_layout.setSpacing(6)
                
                g_val = acc.get("account_group", "").strip()
                if not g_val and "@" in acc.get("email", ""):
                    g_val = acc["email"].split("@")[-1]
                
                group_badge = f"<span style='background-color:#e0e7ff; color:#4361ee; font-weight:bold; font-size:10px; padding:2px 6px; border-radius:4px;'>📁 {g_val}</span>" if g_val else ""

                lbl_label = QLabel(f"<b>{acc['label']}</b>  {group_badge}")
                lbl_label.setStyleSheet("color: #0f172a; font-size: 13px; font-weight: 700; padding-bottom: 2px;")
                
                lbl_email = QLabel(f"✉️ {acc['email']}")
                lbl_email.setStyleSheet("color: #334155; font-size: 11.5px; font-weight: 500; padding-bottom: 2px;")
                
                lbl_stats = QLabel(f"📂 <b>{folders_cnt}</b> Klasör   •   📧 <b>{local_mails_cnt:,}</b> Arşivlenmiş Mail")
                lbl_stats.setStyleSheet("color: #64748b; font-size: 10.5px; font-weight: 500;")
                
                info_layout.addWidget(lbl_label)
                info_layout.addWidget(lbl_email)
                info_layout.addWidget(lbl_stats)
                self.account_table.setCellWidget(i, 1, info_widget)
                
                # Column 2: Progress status + progress bar
                prog_widget = QWidget()
                prog_layout = QVBoxLayout(prog_widget)
                prog_layout.setContentsMargins(6, 4, 6, 4)
                prog_layout.setSpacing(2)
                
                lbl_status = QLabel("Idle")
                lbl_status.setStyleSheet("color: #475569; font-size: 11px;")
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
                    }
                    QProgressBar::chunk {
                        background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0, stop: 0 #4361ee, stop: 1 #7209b7);
                        border-radius: 4px;
                    }
                """)
                prog_layout.addWidget(lbl_status)
                prog_layout.addWidget(progress_bar)
                self.account_table.setCellWidget(i, 2, prog_widget)
                
                # Column 3: Row Actions
                actions_widget = QWidget()
                actions_layout = QHBoxLayout(actions_widget)
                actions_layout.setContentsMargins(4, 2, 4, 2)
                actions_layout.setSpacing(4)
                
                btn_start = QPushButton("▶")
                btn_start.setToolTip("Start archiving for this account")
                btn_start.setStyleSheet(self._action_btn_style("#10b981", "#059669"))
                btn_start.clicked.connect(lambda checked, aid=acc_id: self._trigger_individual_sync_direct(aid))
                
                btn_pause = QPushButton("⏸")
                btn_pause.setToolTip("Pause/Resume archiving")
                btn_pause.setStyleSheet(self._action_btn_style("#f59e0b", "#d97706"))
                btn_pause.setEnabled(False)
                btn_pause.clicked.connect(lambda checked, aid=acc_id: self._toggle_individual_pause(aid))
                
                btn_stop = QPushButton("⏹")
                btn_stop.setToolTip("Stop archiving")
                btn_stop.setStyleSheet(self._action_btn_style("#ef4444", "#dc2626"))
                btn_stop.setEnabled(False)
                btn_stop.clicked.connect(lambda checked, aid=acc_id: self._stop_individual_sync(aid))
                
                btn_report = QPushButton("📊")
                btn_report.setToolTip("View sync reports for this account")
                btn_report.setStyleSheet(self._action_btn_style("#4361ee", "#3a56d4"))
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
        except Exception as exc:
            logger.error("Refresh error: %s", exc)
        finally:
            self.account_table.blockSignals(False)
            self._update_selection_count()

        # Restore active sync UI states after rebuild
        for acc_id, sync_info in list(self._active_syncs.items()):
            ui = self._accounts_ui.get(acc_id)
            if not ui:
                continue
            is_paused = sync_info["pause_event"].is_set()
            is_cancelled = sync_info["cancel_event"].is_set()
            if is_cancelled:
                ui["lbl_status"].setText("Cancelled")
                ui["progress_bar"].setRange(0, 100)
                ui["progress_bar"].setValue(0)
                ui["btn_start"].setEnabled(True)
                ui["btn_pause"].setEnabled(False)
                ui["btn_stop"].setEnabled(False)
            elif is_paused:
                ui["lbl_status"].setText("Paused")
                ui["progress_bar"].setRange(0, 0)
                ui["btn_start"].setEnabled(False)
                ui["btn_pause"].setEnabled(True)
                ui["btn_pause"].setText("▶")
                ui["btn_stop"].setEnabled(True)
            else:
                ui["lbl_status"].setText("Running...")
                ui["progress_bar"].setRange(0, 0)
                ui["btn_start"].setEnabled(False)
                ui["btn_pause"].setEnabled(True)
                ui["btn_pause"].setText("⏸")
                ui["btn_stop"].setEnabled(True)
            self.btn_cancel.setEnabled(True)
            self.btn_pause.setEnabled(True)

        self._load_grid_state()

    def _save_grid_state(self):
        if not self.settings:
            return
        state = {
            "hidden_columns": [c for c in range(self.account_table.columnCount()) if self.account_table.isColumnHidden(c)],
            "column_widths": [self.account_table.columnWidth(c) for c in range(self.account_table.columnCount())]
        }
        self.settings.set("grid_state_sync_account_table", state)
        self.settings.save()
        QMessageBox.information(self, "Grid Düzeni Kaydedildi", "Hesap tablosu sütun görünürlük ve genişlik tercihleri başarıyla kaydedildi.")

    def _load_grid_state(self):
        if not self.settings:
            return
        state = self.settings.get("grid_state_sync_account_table", None)
        if state and isinstance(state, dict):
            hidden = state.get("hidden_columns", [])
            widths = state.get("column_widths", [])
            for c in range(self.account_table.columnCount()):
                if c < len(widths) and widths[c] > 10:
                    self.account_table.setColumnWidth(c, widths[c])
                self.account_table.setColumnHidden(c, c in hidden)

    def _reset_grid_state(self):
        for c in range(self.account_table.columnCount()):
            self.account_table.setColumnHidden(c, False)
        self.account_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.account_table.setColumnWidth(0, 70)
        self.account_table.setColumnWidth(1, 400)
        self.account_table.setColumnWidth(2, 320)
        self.account_table.setColumnWidth(3, 150)
        if self.settings:
            self.settings.set("grid_state_sync_account_table", None)
            self.settings.save()
        QMessageBox.information(self, "Grid Sıfırlandı", "Tablo sütunları varsayılan genişlik ve görünürlüğe sıfırlandı.")

    # ------------------------------------------------------------------
    # Group Sidebar Filtering Slots & Helpers
    # ------------------------------------------------------------------

    def _refresh_groups_sidebar(self):
        # Store currently selected group to restore it
        selected_item = self.group_filter_list.currentItem()
        current_group = selected_item.data(Qt.UserRole) if selected_item else "__ALL__"

        self.group_filter_list.blockSignals(True)
        self.group_filter_list.clear()

        groups_status = {}

        # 1. From settings
        settings_groups = self.settings.get("group_domains", [])
        for g in settings_groups:
            if isinstance(g, str):
                name = g.strip()
                is_active = True
            elif isinstance(g, dict):
                name = g.get("name", "").strip()
                is_active = g.get("is_active", True)
            else:
                continue
            if name:
                groups_status[name] = is_active

        # 2. From database
        try:
            with self.engine.db.get_conn() as conn:
                rows = conn.execute("SELECT DISTINCT account_group FROM accounts").fetchall()
                for r in rows:
                    if r["account_group"] and r["account_group"].strip():
                        name = r["account_group"].strip()
                        if name not in groups_status:
                            groups_status[name] = True
                # Fallback email domains
                rows_email = conn.execute("SELECT DISTINCT email FROM accounts").fetchall()
                for r in rows_email:
                    if r["email"] and "@" in r["email"]:
                        domain = r["email"].split("@")[-1].strip()
                        if domain and domain not in groups_status:
                            groups_status[domain] = True
        except Exception as e:
            logger.error("Failed to query database groups: %s", e)

        # Add All groups item
        all_item = QListWidgetItem("📁 Tüm Gruplar")
        all_item.setData(Qt.UserRole, "__ALL__")
        self.group_filter_list.addItem(all_item)

        # Sort and add other groups
        for g in sorted(groups_status.keys()):
            is_active = groups_status[g]
            label = f"📁 {g}" if is_active else f"📁 {g} (Pasif)"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, g)
            if not is_active:
                item.setForeground(Qt.gray)
            self.group_filter_list.addItem(item)

        # Restore selection
        found_item = None
        for i in range(self.group_filter_list.count()):
            item = self.group_filter_list.item(i)
            if item.data(Qt.UserRole) == current_group:
                found_item = item
                break
        if found_item:
            self.group_filter_list.setCurrentItem(found_item)
        else:
            self.group_filter_list.setCurrentRow(0)

        self.group_filter_list.blockSignals(False)

    @Slot()
    def _on_group_filter_changed(self):
        self._all_selected_flag = False
        self.btn_select_all.setText("☑️ Tümünü Seç")
        if hasattr(self, 'btn_top_select_all'):
            self.btn_top_select_all.setText("☑️ Tümünü Seç")
        self.refresh()

    @Slot()
    def _toggle_sidebar(self):
        is_visible = self.sidebar_widget.isVisible()
        self.sidebar_widget.setVisible(not is_visible)
        if not is_visible:
            self.btn_toggle_sidebar.setText("◀")
        else:
            self.btn_toggle_sidebar.setText("▶")
