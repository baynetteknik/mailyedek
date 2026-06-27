"""
sync_panel.py — Email synchronization panel with detailed logging.
"""

import logging
import threading
import re
from typing import Optional
from datetime import datetime

from PySide6.QtCore import Qt, Slot, Signal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QDate
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QGroupBox, QMessageBox, QListWidget, QListWidgetItem,
    QAbstractItemView, QFrame, QTableView, QComboBox, QLineEdit,
    QDialog, QDialogButtonBox, QCheckBox, QDateEdit, QTextEdit,
    QSpinBox,
)

from core.mail_engine import MailEngine

logger = logging.getLogger(__name__)


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
        self.setWindowTitle("Sync Reports")
        self.resize(720, 350)
        layout = QVBoxLayout(self)
        table = QTableWidget()
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels([
            "Account", "Fetched", "Already Archived", "Updated", "Duplicates", "Errors",
            "Data", "Duration"
        ])
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setStyleSheet("color: #1a1a2e; background: #ffffff;")
        table.setRowCount(len(reports))
        for i, r in enumerate(reports):
            def g(k, d=None):
                return r.get(k, d) if isinstance(r, dict) else getattr(r, k, d)
            table.setItem(i, 0, QTableWidgetItem(str(g("account_label", ""))))
            table.setItem(i, 1, QTableWidgetItem(str(g("mails_fetched", 0))))
            table.setItem(i, 2, QTableWidgetItem(str(g("mails_already_archived", 0))))
            table.setItem(i, 3, QTableWidgetItem(str(g("mails_updated", 0))))
            table.setItem(i, 4, QTableWidgetItem(str(g("duplicates_found", 0))))
            table.setItem(i, 5, QTableWidgetItem(str(g("errors", 0))))
            bv = g("total_bytes", 0)
            table.setItem(i, 6, QTableWidgetItem(self._fmt_bytes(bv)))
            dur = g("duration_seconds", 0)
            table.setItem(i, 7, QTableWidgetItem(f"{dur:.1f}s"))
        table.resizeColumnsToContents()
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
# Detailed diagnostics report popup dialog
# ---------------------------------------------------------------------------

class DetailedReportDialog(QDialog):
    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Detailed Diagnostics & Folder Report")
        self.resize(720, 500)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        info_label = QLabel("<b>System Diagnostics & Detailed Folder Report</b>")
        info_label.setStyleSheet("color: #1a1a2e; font-size: 13px;")
        layout.addWidget(info_label)
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setAcceptRichText(False)
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background: #f8fafc;
                border: 1.5px solid #d0d3d8;
                border-radius: 6px;
                font-family: Consolas, Monaco, monospace;
                font-size: 11px;
                color: #334155;
            }
        """)
        layout.addWidget(self.text_edit)
        
        btn_layout = QHBoxLayout()
        self.btn_copy = QPushButton("Copy to Clipboard")
        self.btn_copy.setStyleSheet("""
            QPushButton {
                background: #10b981;
                color: white;
                font-weight: 600;
                padding: 8px 18px;
                border-radius: 6px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #059669;
            }
        """)
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        
        self.btn_close = QPushButton("Close")
        self.btn_close.setStyleSheet("""
            QPushButton {
                background: #64748b;
                color: white;
                font-weight: 600;
                padding: 8px 18px;
                border-radius: 6px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #475569;
            }
        """)
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
    def __init__(self, folders: list, selected_folders: list, archive_unread: bool,
                 since_date_enabled: bool, since_date: QDate,
                 before_date_enabled: bool, before_date: QDate,
                 timeout: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Folders & Advanced Archiving Filters")
        self.resize(550, 520)
        self.setStyleSheet("QDialog { background-color: #f8fafc; }")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        
        # 1. Folders Group Box
        folders_group = QGroupBox("Select Folders to Sync")
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
                padding: 4px 6px;
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
        
        # Select all/none buttons
        btns_folder = QHBoxLayout()
        btn_sel_all = QPushButton("Select All")
        btn_sel_all.setStyleSheet(self._filter_btn_style())
        btn_sel_all.clicked.connect(self._select_all_folders)
        
        btn_sel_none = QPushButton("Clear Selection")
        btn_sel_none.setStyleSheet(self._filter_btn_style())
        btn_sel_none.clicked.connect(self._select_none_folders)
        
        btns_folder.addWidget(btn_sel_all)
        btns_folder.addWidget(btn_sel_none)
        btns_folder.addStretch()
        fg_layout.addLayout(btns_folder)
        
        layout.addWidget(folders_group, stretch=2)
        
        # 2. Advanced Filters Group Box
        filters_group = QGroupBox("Advanced Archiving Filters")
        filters_group.setStyleSheet(folders_group.styleSheet())
        filters_layout = QVBoxLayout(filters_group)
        filters_layout.setContentsMargins(12, 16, 12, 12)
        filters_layout.setSpacing(8)
        
        self.chk_archive_unread = QCheckBox("Okunmamış iletileri de arşivle")
        self.chk_archive_unread.setChecked(archive_unread)
        self.chk_archive_unread.setStyleSheet("color: #1e293b; font-size: 12px;")
        filters_layout.addWidget(self.chk_archive_unread)
        
        since_layout = QHBoxLayout()
        self.chk_since_date = QCheckBox("Yalnızca şu tarihten yeni iletileri arşivle:")
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
        
        before_layout = QHBoxLayout()
        self.chk_before_date = QCheckBox("Sadece şu tarihten eski iletileri arşivle:")
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
        
        layout.addWidget(filters_group, stretch=1)
        
        # OK / Cancel
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.setStyleSheet("""
            QPushButton {
                background: #4361ee;
                color: white;
                font-weight: 600;
                padding: 6px 18px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #3a56d4;
            }
            QPushButton[text="Cancel"] {
                background: #64748b;
            }
            QPushButton[text="Cancel"]:hover {
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
# Confirmation dialog
# ---------------------------------------------------------------------------

class SyncConfirmDialog(QDialog):
    def __init__(self, account_previews: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Synchronization")
        self.resize(750, 450)
        self.setMinimumSize(600, 350)
        self.setStyleSheet("QDialog { background-color: #f8fafc; }")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Header Info
        header_layout = QHBoxLayout()
        header_icon = QLabel("📊")
        header_icon.setStyleSheet("font-size: 24px;")
        header_layout.addWidget(header_icon)
        
        header_title = QLabel(f"<b>Confirm Synchronization Plan</b><br/>{len(account_previews)} account(s) will be synchronized sequentially:")
        header_title.setStyleSheet("font-size: 13px; color: #1e293b;")
        header_layout.addWidget(header_title, 1)
        layout.addLayout(header_layout)

        # Table
        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Account Name / Email", "Folders Count", "New Emails Estimate", "Status"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
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
            }
            QHeaderView::section {
                background-color: #f1f5f9;
                color: #475569;
                font-weight: bold;
                border: none;
                border-bottom: 2px solid #cbd5e1;
            }
        """)
        table.setRowCount(len(account_previews))
        for i, p in enumerate(account_previews):
            table.setItem(i, 0, QTableWidgetItem(p.get("label", "?")))
            table.setItem(i, 1, QTableWidgetItem(str(p.get("folder_count", 0))))
            
            new_mails = p.get("new_mails", 0)
            new_mails_item = QTableWidgetItem(str(new_mails))
            if new_mails > 0:
                new_mails_item.setForeground(QColor("#10b981"))
                new_mails_item.setFont(QFont("Segoe UI", 10, QFont.Bold))
            table.setItem(i, 2, new_mails_item)
            
            err = p.get("error")
            status_item = QTableWidgetItem(err if err else "Ready")
            if err:
                status_item.setForeground(QColor("#ef4444"))
            else:
                status_item.setForeground(QColor("#64748b"))
            table.setItem(i, 3, status_item)
            
        layout.addWidget(table)

        # Summary box
        total = sum(p.get("new_mails", 0) for p in account_previews)
        summary_frame = QFrame()
        summary_frame.setStyleSheet("""
            QFrame {
                background-color: #f0fdf4;
                border: 1px dashed #bbf7d0;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(12, 8, 12, 8)
        
        summary_lbl = QLabel("<b>Total Estimated New Emails to Fetch:</b>")
        summary_lbl.setStyleSheet("color: #166534; font-size: 13px;")
        total_val = QLabel(str(total))
        total_val.setStyleSheet("color: #15803d; font-size: 16px; font-weight: bold;")
        
        summary_layout.addWidget(summary_lbl)
        summary_layout.addStretch()
        summary_layout.addWidget(total_val)
        layout.addWidget(summary_frame)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.setStyleSheet("""
            QPushButton {
                background: #4361ee;
                color: white;
                font-weight: 600;
                padding: 8px 20px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: #3a56d4;
            }
            QPushButton[text="Cancel"] {
                background: #64748b;
            }
            QPushButton[text="Cancel"]:hover {
                background: #475569;
            }
        """)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)


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

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._reports: list = []
        self._all_selected_flag = False
        
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
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # ----------------------------------------------------------------
        # Stat cards row
        # ----------------------------------------------------------------
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.card_account = StatCard("Current Account", "\u2014")
        self.card_server = StatCard("Server Emails", "\u2014")
        self.card_folders = StatCard("Folders", "\u2014")
        self.card_current = StatCard("Current Folder", "\u2014")
        self.card_remaining = StatCard("Remaining", "\u2014")
        self.card_progress = StatCard("Progress", "\u2014")
        self.card_eta = StatCard("ETA", "\u2014")
        stats_row.addWidget(self.card_account)
        stats_row.addWidget(self.card_server)
        stats_row.addWidget(self.card_folders)
        stats_row.addWidget(self.card_current)
        stats_row.addWidget(self.card_remaining)
        stats_row.addWidget(self.card_progress)
        stats_row.addWidget(self.card_eta)
        layout.addLayout(stats_row)

        # ----------------------------------------------------------------
        # Horizontal Action Button Bar (Under Stats)
        # ----------------------------------------------------------------
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)

        self.btn_sync = QPushButton("🔄 Sync Selected")
        self.btn_sync.setToolTip("Start sync for selected checked accounts")
        self.btn_sync.setStyleSheet(self._blue_btn_style())
        self.btn_sync.setMinimumHeight(34)

        self.btn_sync_all = QPushButton("⚡ Sync All")
        self.btn_sync_all.setToolTip("Sync all accounts")
        self.btn_sync_all.setStyleSheet(self._blue_btn_style())
        self.btn_sync_all.setMinimumHeight(34)

        self.btn_dry_run = QPushButton("🔍 Dry Run")
        self.btn_dry_run.setToolTip("Estimate new mails without fetching")
        self.btn_dry_run.setStyleSheet(self._blue_btn_style())
        self.btn_dry_run.setMinimumHeight(34)

        self.btn_filters = QPushButton("⚙️ Configure Filters...")
        self.btn_filters.setToolTip("Manage folders and advanced archiving filters")
        self.btn_filters.setStyleSheet(self._blue_btn_style())
        self.btn_filters.setMinimumHeight(34)

        self.btn_select_all = QPushButton("☑️ Select All")
        self.btn_select_all.setToolTip("Toggle checking all accounts")
        self.btn_select_all.setStyleSheet(self._blue_btn_style())
        self.btn_select_all.setMinimumHeight(34)

        self.btn_reports = QPushButton("📊 Reports")
        self.btn_reports.setToolTip("Show session reports in popup window")
        self.btn_reports.setStyleSheet(self._blue_btn_style())
        self.btn_reports.setMinimumHeight(34)

        self.btn_detailed_report = QPushButton("🔬 Diagnostics")
        self.btn_detailed_report.setToolTip("Show copyable diagnostics and detailed folder counts")
        self.btn_detailed_report.setStyleSheet(self._blue_btn_style())
        self.btn_detailed_report.setMinimumHeight(34)

        self.btn_pause = QPushButton("⏸️ Pause All")
        self.btn_pause.setToolTip("Pause all active sync threads")
        self.btn_pause.setStyleSheet(
            "QPushButton{background:#f39c12;color:white;font-weight:600;padding:8px 14px;border-radius:6px;font-size:12px;}"
            "QPushButton:hover{background:#d35400;}"
            "QPushButton:disabled{background:#cbd5e1;color:#94a3b8;}"
        )
        self.btn_pause.setEnabled(False)
        self.btn_pause.setMinimumHeight(34)

        self.btn_cancel = QPushButton("⏹️ Cancel All")
        self.btn_cancel.setToolTip("Cancel all active sync threads")
        self.btn_cancel.setStyleSheet(
            "QPushButton{background:#e74c3c;color:white;font-weight:600;padding:8px 14px;border-radius:6px;font-size:12px;}"
            "QPushButton:hover{background:#c0392b;}"
            "QPushButton:disabled{background:#cbd5e1;color:#94a3b8;}"
        )
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setMinimumHeight(34)

        self.btn_toggle_log = QPushButton("📋 Hide Log")
        self.btn_toggle_log.setToolTip("Show/Hide the sync log box to save space")
        self.btn_toggle_log.setStyleSheet(self._blue_btn_style(bg="#4b5563", hover="#374151"))
        self.btn_toggle_log.setMinimumHeight(34)

        buttons_layout.addWidget(self.btn_sync)
        buttons_layout.addWidget(self.btn_sync_all)
        buttons_layout.addWidget(self.btn_dry_run)
        buttons_layout.addWidget(self.btn_filters)
        buttons_layout.addWidget(self.btn_select_all)
        buttons_layout.addWidget(self.btn_reports)
        buttons_layout.addWidget(self.btn_detailed_report)
        buttons_layout.addWidget(self.btn_pause)
        buttons_layout.addWidget(self.btn_cancel)
        buttons_layout.addWidget(self.btn_toggle_log)
        layout.addLayout(buttons_layout)

        # ----------------------------------------------------------------
        # Accounts Table (Select Accounts) - Main Area
        # ----------------------------------------------------------------
        accounts_group = QGroupBox("Select & Manage Accounts")
        accounts_group.setStyleSheet("""
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
        ag_layout = QVBoxLayout(accounts_group)
        ag_layout.setContentsMargins(12, 16, 12, 12)

        self.account_table = QTableWidget()
        self.account_table.setColumnCount(4)
        self.account_table.setHorizontalHeaderLabels([
            "Sync", "Account Details", "Archiving Status & Progress", "Actions"
        ])
        self.account_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.account_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.account_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.account_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.account_table.verticalHeader().setDefaultSectionSize(54)
        self.account_table.verticalHeader().setVisible(False)
        self.account_table.setSelectionBehavior(QTableWidget.SelectRows)
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
        ag_layout.addWidget(self.account_table)
        
        layout.addWidget(accounts_group, stretch=2)

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

        self._log_model = LogTableModel(self)
        self._log_proxy = LogFilterProxy(self)
        self._log_proxy.setSourceModel(self._log_model)
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
        selected_ids = self._get_selected_account_ids()
        
        # Gather all folders from selected accounts
        folders = []
        if not selected_ids:
            # Query all folders from db
            try:
                with self.engine.db.get_conn() as conn:
                    rows = conn.execute("SELECT DISTINCT folder FROM sync_state ORDER BY folder").fetchall()
                    folders = [r["folder"] for r in rows]
                if not folders:
                    with self.engine.db.get_conn() as conn:
                        rows = conn.execute("SELECT DISTINCT folder FROM mail_metadata ORDER BY folder").fetchall()
                        folders = [r["folder"] for r in rows]
            except Exception:
                pass
        else:
            for acc_id in selected_ids:
                try:
                    with self.engine.db.get_conn() as conn:
                        rows = conn.execute(
                            "SELECT folder FROM sync_state WHERE account_id = ? ORDER BY folder",
                            (acc_id,)
                        ).fetchall()
                        acc_folders = [r["folder"] for r in rows]
                    if not acc_folders:
                        with self.engine.db.get_conn() as conn:
                            rows = conn.execute(
                                "SELECT DISTINCT folder FROM mail_metadata WHERE account_id = ? ORDER BY folder",
                                (acc_id,)
                            ).fetchall()
                            acc_folders = [r["folder"] for r in rows]
                    for f in acc_folders:
                        if f not in folders:
                            folders.append(f)
                except Exception:
                    pass
                    
        if not folders:
            folders = ["INBOX"]
            
        current_selected = self._filter_folders if self._filter_folders is not None else folders
        
        dialog = FiltersDialog(
            folders=folders,
            selected_folders=current_selected,
            archive_unread=self._filter_archive_unread,
            since_date_enabled=self._filter_since_date_enabled,
            since_date=self._filter_since_date,
            before_date_enabled=self._filter_before_date_enabled,
            before_date=self._filter_before_date,
            timeout=self._filter_timeout,
            parent=self
        )
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._filter_folders = dialog.get_selected_folders()
            self._filter_archive_unread = dialog.chk_archive_unread.isChecked()
            self._filter_since_date_enabled = dialog.chk_since_date.isChecked()
            self._filter_since_date = dialog.date_edit_since.date()
            self._filter_before_date_enabled = dialog.chk_before_date.isChecked()
            self._filter_before_date = dialog.date_edit_before.date()
            self._filter_timeout = dialog.spin_timeout.value()
            self._log_callback(f"Filters updated: {len(self._filter_folders)} folder(s) selected")

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
        if not is_visible:
            self.btn_toggle_log.setText("📋 Hide Log")
        else:
            self.btn_toggle_log.setText("📋 Show Log")

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
        return ids

    def _toggle_select_all(self):
        if self._all_selected_flag:
            for i in range(self.account_table.rowCount()):
                item = self.account_table.item(i, 0)
                if item:
                    item.setCheckState(Qt.Unchecked)
            self.btn_select_all.setText("☑️ Select All")
            self._all_selected_flag = False
        else:
            for i in range(self.account_table.rowCount()):
                item = self.account_table.item(i, 0)
                if item:
                    item.setCheckState(Qt.Checked)
            self.btn_select_all.setText("⬜ Deselect All")
            self._all_selected_flag = True

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
        
        folder_filter = self._filter_folders
        since_date = self._get_since_date()
        before_date = self._get_before_date()
        archive_unread = self._get_archive_unread()
        timeout = self._get_timeout()
        
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
            
        self._active_syncs.pop(account_id, None)
        
        if not self._active_syncs:
            self._on_all_syncs_finished()

    def _on_all_syncs_finished(self):
        self.btn_cancel.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸️ Pause All")
        self._log_callback("All background sync tasks finished.")

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
        self._log_model.append_entry(entry)
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
        total = self._log_proxy.total_pages()
        cur = self._log_proxy.current_page() + 1
        self.label_page.setText(f"Page {cur} / {total}")
        self.btn_prev_page.setEnabled(cur > 1)
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
        """Run dry-run on selected accounts, show confirmation, return True if OK."""
        previews = []
        folder_filter = self._filter_folders
        since_date = self._get_since_date()
        before_date = self._get_before_date()
        archive_unread = self._get_archive_unread()
        
        for acc_id in ids:
            acc_data = None
            for i in range(self.account_table.rowCount()):
                item = self.account_table.item(i, 0)
                if item and item.data(Qt.UserRole) == acc_id:
                    # Get label from row cell widget
                    widget = self.account_table.cellWidget(i, 1)
                    if widget:
                        lbl = widget.findChild(QLabel)
                        if lbl:
                            acc_data = lbl.text().replace("<b>", "").replace("</b>", "")
                    break
            try:
                result = self.engine.sync_dry_run(
                    acc_id,
                    folder_filter=folder_filter,
                    since_date=since_date,
                    before_date=before_date,
                    archive_unread=archive_unread
                )
                folders = result.get("folders", [])
                new_mails = result.get("total_estimated", 0)
                err = result.get("error")
                previews.append({
                    "label": result.get("account", acc_data or f"ID {acc_id}"),
                    "folder_count": len(folders),
                    "new_mails": new_mails,
                    "error": err,
                })
            except Exception as exc:
                previews.append({
                    "label": acc_data or f"ID {acc_id}",
                    "folder_count": 0,
                    "new_mails": 0,
                    "error": str(exc),
                })
        dialog = SyncConfirmDialog(previews, self)
        return dialog.exec() == QDialog.DialogCode.Accepted

    # ------------------------------------------------------------------
    # Sync operations (Global Actions)
    # ------------------------------------------------------------------

    @Slot()
    def _sync_selected(self):
        ids = self._get_selected_account_ids()
        if not ids:
            QMessageBox.warning(self, "No Selection", "Select at least one account from the list by checking the checkbox.")
            return
        if not self._confirm_sync(ids):
            self._log_callback("Sync cancelled by user (confirmation declined)")
            return
        for aid in ids:
            self._start_individual_sync(aid)

    @Slot()
    def _sync_all(self):
        # Check all accounts
        for i in range(self.account_table.rowCount()):
            item = self.account_table.item(i, 0)
            if item:
                item.setCheckState(Qt.Checked)
        self.btn_select_all.setText("⬜ Deselect All")
        self._all_selected_flag = True
        
        self._sync_selected()

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
        folder_filter = self._filter_folders
        since_date = self._get_since_date()
        before_date = self._get_before_date()
        archive_unread = self._get_archive_unread()

        def task(acc_id):
            ui = self._accounts_ui.get(acc_id)
            if ui:
                ui["lbl_status"].setText("Estimating...")
                ui["progress_bar"].setRange(0, 0)
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

    # ------------------------------------------------------------------
    # Reports popup
    # ------------------------------------------------------------------

    @Slot()
    def _show_reports(self):
        if not self._reports:
            QMessageBox.information(self, "No Reports", "Run a sync first to generate reports.")
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
        self.account_table.blockSignals(True)
        self.account_table.setRowCount(0)
        self._accounts_ui.clear()
        try:
            accounts = self.engine.list_accounts()
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

                # Column 1: Account details (name + email)
                info_widget = QWidget()
                info_layout = QVBoxLayout(info_widget)
                info_layout.setContentsMargins(6, 4, 6, 4)
                info_layout.setSpacing(2)
                
                lbl_label = QLabel(f"<b>{acc['label']}</b>")
                lbl_label.setStyleSheet("color: #1e293b; font-size: 12px;")
                lbl_email = QLabel(f"{acc['email']}  |  📁 {folders_cnt} folders  |  📧 {local_mails_cnt} archived")
                lbl_email.setStyleSheet("color: #64748b; font-size: 11px;")
                
                info_layout.addWidget(lbl_label)
                info_layout.addWidget(lbl_email)
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
                btn_start.clicked.connect(lambda checked, aid=acc_id: self._start_individual_sync(aid))
                
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
