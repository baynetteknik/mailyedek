"""
mail_viewer_panel.py — Thunderbird-style 3-pane mail viewer.

Layout:
  ┌─────────────┬──────────────────────┬──────────────────────┐
  │  Folders    │    Mail List         │   Mail Preview       │
  │             │                      │   (Headers + Body    │
  │  Account 1  │  ┌──┬────┬──────┐   │    + Attachments)    │
  │  ├ INBOX    │  │ID│From│Subject│   │                      │
  │  ├ Sent     │  ├──┼────┼──────┤   │                      │
  │  ├ Drafts   │  │  │    │      │   │                      │
  │  └ Trash    │  └──┴────┴──────┘   │                      │
  │             │                      │                      │
  │  Account 2  │                      │                      │
  │  ├ INBOX    │                      │                      │
  └─────────────┴──────────────────────┴──────────────────────┘
"""

import logging
import email
import mimetypes
import threading
from email.header import decode_header
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from PySide6.QtCore import Qt, Signal, Slot, QSize, QDate, QThread
from PySide6.QtGui import QFont, QIcon, QPixmap, QTextDocument, QTextCursor, QColor, QClipboard
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QTextBrowser, QPlainTextEdit, QGroupBox, QFrame, QAbstractItemView,
    QListWidget, QListWidgetItem, QMessageBox, QToolBar,
    QComboBox, QStatusBar, QProgressBar, QDialog, QMenu, QApplication,
)

from core.mail_engine import MailEngine
from infrastructure.imap_client import format_folder_display_name

logger = logging.getLogger(__name__)


class MailBodyLoaderThread(QThread):
    """Background worker for loading and parsing email raw content without UI lag."""
    finished_signal = Signal(object)

    def __init__(self, engine: MailEngine, mail_id: int, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.mail_id = mail_id

    def run(self):
        try:
            raw_data = self.engine.mails.get_raw(self.mail_id)
            if raw_data:
                msg = email.message_from_bytes(raw_data)
                self.finished_signal.emit(msg)
            else:
                self.finished_signal.emit(None)
        except Exception as e:
            logger.debug("Failed to load/parse raw mail bytes: %s", e)
            self.finished_signal.emit(e)


class FolderTree(QTreeWidget):
    """Left panel: account > folder tree from database."""

    folder_selected = Signal(int, str)  # account_id, folder_name

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setHeaderLabel("Folders")
        self.setMinimumWidth(200)
        self.setMaximumWidth(280)
        self.setIndentation(20)
        self.setAnimated(True)
        self.setStyleSheet("""
            QTreeWidget {
                background: #f8f9fa;
                border: 1px solid #e0e3e8;
                border-radius: 6px;
                font-size: 13px;
            }
            QTreeWidget::item {
                padding: 6px 8px;
                border-radius: 4px;
            }
            QTreeWidget::item:selected {
                background: #4361ee;
                color: white;
            }
            QTreeWidget::item:hover:!selected {
                background: #e8ecf8;
            }
        """)
        self.itemClicked.connect(self._on_item_clicked)

    def refresh(self, selected_group: str = "__ALL__"):
        self.clear()
        try:
            all_accounts = self.engine.list_accounts()
            accounts = []
            for acc in all_accounts:
                g_val = acc.get("account_group", "").strip()
                if not g_val and "@" in acc.get("email", ""):
                    g_val = acc["email"].split("@")[-1].strip()
                if selected_group == "__ALL__" or g_val == selected_group:
                    accounts.append(acc)

            if not accounts:
                return

            acc_ids = tuple(acc["id"] for acc in accounts)
            acc_id_clause = f"IN ({','.join('?' for _ in acc_ids)})" if len(acc_ids) > 1 else "= ?"

            # Bulk query sync states and folder counts in 2 fast queries
            synced_dict = {}
            counts_dict = {}
            with self.engine.db.get_conn() as conn:
                state_rows = conn.execute(
                    f"SELECT account_id, folder FROM sync_state WHERE account_id {acc_id_clause}",
                    acc_ids
                ).fetchall()
                for r in state_rows:
                    synced_dict.setdefault(r["account_id"], set()).add(r["folder"])

                count_rows = conn.execute(
                    f"SELECT account_id, folder, COUNT(*) as cnt FROM mail_metadata WHERE is_deleted=0 AND account_id {acc_id_clause} GROUP BY account_id, folder",
                    acc_ids
                ).fetchall()
                for r in count_rows:
                    counts_dict[(r["account_id"], r["folder"])] = r["cnt"]

            for acc in accounts:
                acc_id = acc["id"]
                acc_item = QTreeWidgetItem([f"📁  {acc['label']}  ({acc['email']})"])
                acc_item.setData(0, Qt.UserRole, ("account", acc_id))
                acc_item.setFlags(acc_item.flags() & ~Qt.ItemIsSelectable)
                self.addTopLevelItem(acc_item)

                synced_folders = synced_dict.get(acc_id, set())
                acc_counts = {f: cnt for (aid, f), cnt in counts_dict.items() if aid == acc_id}

                seen = {"INBOX"}
                inbox_cnt = acc_counts.get("INBOX", 0)
                self._add_folder(acc_item, acc_id, "INBOX", inbox_cnt)

                all_folders = sorted(list(synced_folders | set(acc_counts.keys())))
                for folder in all_folders:
                    if folder not in seen:
                        seen.add(folder)
                        cnt = acc_counts.get(folder, 0)
                        self._add_folder(acc_item, acc_id, folder, cnt)

                acc_item.setExpanded(True)
        except Exception as exc:
            logger.error("Folder tree refresh error: %s", exc)

    def _add_folder(self, parent: QTreeWidgetItem, account_id: int, folder: str, count: int):
        display_name = format_folder_display_name(folder)
        item = QTreeWidgetItem([f"  {display_name}  ({count})"])
        item.setData(0, Qt.UserRole, ("folder", account_id, folder))
        parent.addChild(item)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.UserRole)
        if data and data[0] == "folder":
            _, account_id, folder = data
            self.folder_selected.emit(account_id, folder)


class MailListTable(QTableWidget):
    """Center panel: mail list for selected folder with paging."""

    mail_selected = Signal(dict)
    mail_double_clicked = Signal(dict)
    need_more_mails = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(5)
        self.setHorizontalHeaderLabels(["", "From", "Subject", "Date", "Size"])
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setSortingEnabled(False)  # Disabled to prevent sorting conflicts during paging
        self.setMinimumWidth(400)
        self.setStyleSheet("""
            QTableWidget {
                border: 1px solid #e0e3e8;
                border-radius: 6px;
                font-size: 12px;
            }
            QTableWidget::item { padding: 6px 8px; }
            QTableWidget::item:selected {
                background: #d4e0ff;
                color: #1a1a2e;
            }
        """)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.itemSelectionChanged.connect(self._emit_selection)
        self.doubleClicked.connect(self._on_double_click)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        
        self._mails = []
        self._loading = False
        self._has_more = True

    def _on_context_menu(self, pos):
        row = self.rowAt(pos.y())
        if row < 0 or row >= len(self._mails):
            return

        mail = self._mails[row]
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 8px 20px; font-size: 12px; color: #1e293b; border-radius: 4px; }
            QMenu::item:selected { background-color: #2563eb; color: #ffffff; }
        """)

        act_view = menu.addAction("👁️ E-Postayı Pencerede Aç")
        act_raw = menu.addAction("📄 Ham Kaynağı İncele")
        act_save = menu.addAction("💾 .EML Olarak Kaydet")
        menu.addSeparator()
        act_copy_subj = menu.addAction("📋 Konuyu Kopyala")
        act_copy_sender = menu.addAction("👤 Gönderen Adresini Kopyala")

        action = menu.exec(self.viewport().mapToGlobal(pos))
        if action == act_view:
            self.mail_double_clicked.emit(mail)
        elif action == act_raw:
            self.mail_double_clicked.emit(mail)
        elif action == act_save:
            self.mail_double_clicked.emit(mail)
        elif action == act_copy_subj:
            QApplication.clipboard().setText(mail.get("subject", ""))
        elif action == act_copy_sender:
            QApplication.clipboard().setText(mail.get("sender", ""))

    def clear_mails(self):
        self.setRowCount(0)
        self._mails = []
        self._loading = False
        self._has_more = True

    def append_mails(self, mails: List[Dict]):
        start_row = self.rowCount()
        self.setRowCount(start_row + len(mails))
        self._mails.extend(mails)
        
        for i, m in enumerate(mails):
            row = start_row + i
            flags = m.get("flags", "")
            has_att = m.get("has_attachments", False)
            icon = "📎" if has_att else ""
            unread = "🔵" if "\\Seen" not in flags else ""
            self.setItem(row, 0, QTableWidgetItem(f"{unread}{icon}"))
            self.setItem(row, 1, QTableWidgetItem((m.get("sender") or "")[:50]))
            self.setItem(row, 2, QTableWidgetItem((m.get("subject") or "")[:80]))
            date_str = (m.get("date") or "")[:19]
            self.setItem(row, 3, QTableWidgetItem(date_str))
            size = m.get("size_bytes", 0)
            self.setItem(row, 4, QTableWidgetItem(self._fmt_size(size)))

            # Store ID in UserRole
            for col in range(5):
                self.item(row, col).setData(Qt.UserRole, m.get("id"))

        if start_row == 0:
            self.resizeColumnsToContents()
            self.setColumnWidth(0, 50)
            if mails:
                self.selectRow(0)

    def _emit_selection(self):
        row = self.currentRow()
        if row < 0 or row >= len(self._mails):
            return
        self.mail_selected.emit(self._mails[row])

    def _on_double_click(self, index):
        row = index.row()
        if 0 <= row < len(self._mails):
            self.mail_double_clicked.emit(self._mails[row])

    def _on_scroll(self, value):
        if not self._loading and self._has_more and value > 0:
            max_val = self.verticalScrollBar().maximum()
            if max_val > 0 and value >= max_val - 5:
                self._loading = True
                self.need_more_mails.emit()

    @staticmethod
    def _fmt_size(size: int) -> str:
        for unit in ["B", "KB", "MB"]:
            if size < 1024:
                return f"{size:.0f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"


class MailPreview(QWidget):
    """Right panel: mail content preview with headers, body, attachments."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._current_mail: Optional[Dict] = None
        self._attachments: List[Dict] = []
        self._loader_thread: Optional[MailBodyLoaderThread] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Headers
        self.headers_frame = QFrame()
        self.headers_frame.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #e0e3e8;
                border-radius: 6px;
                padding: 12px;
            }
        """)
        headers_layout = QVBoxLayout(self.headers_frame)
        headers_layout.setContentsMargins(12, 8, 12, 8)
        headers_layout.setSpacing(4)

        self.lbl_from = QLabel("From: —")
        self.lbl_from.setStyleSheet("font-weight: 600; font-size: 13px;")
        headers_layout.addWidget(self.lbl_from)

        self.lbl_to = QLabel("To: —")
        self.lbl_to.setStyleSheet("color: #555; font-size: 12px;")
        headers_layout.addWidget(self.lbl_to)

        self.lbl_date = QLabel("Date: —")
        self.lbl_date.setStyleSheet("color: #888; font-size: 11px;")
        headers_layout.addWidget(self.lbl_date)

        self.lbl_subject = QLabel("Subject: —")
        self.lbl_subject.setStyleSheet("font-size: 16px; font-weight: 700; color: #1a1a2e; padding: 4px 0;")
        headers_layout.addWidget(self.lbl_subject)

        layout.addWidget(self.headers_frame)

        # Toolbar
        toolbar = QHBoxLayout()
        self.btn_raw = QPushButton("📄 Ham Kaynak (Raw)")
        self.btn_raw.setProperty("small", True)
        self.btn_raw.setProperty("outline", True)
        self.btn_raw.setCursor(Qt.PointingHandCursor)
        toolbar.addWidget(self.btn_raw)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Body
        self.body_view = QTextBrowser()
        self.body_view.setOpenExternalLinks(True)
        self.body_view.setStyleSheet("""
            QTextBrowser {
                background: #ffffff;
                border: 1px solid #e0e3e8;
                border-radius: 6px;
                padding: 16px;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        layout.addWidget(self.body_view, stretch=1)

        # Attachments
        self.attach_box = QGroupBox("Ek Dosyalar")
        attach_layout = QVBoxLayout(self.attach_box)
        self.attach_list = QListWidget()
        self.attach_list.setMaximumHeight(120)
        self.attach_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #e0e3e8;
                border-radius: 4px;
                font-size: 12px;
            }
            QListWidget::item { padding: 6px 10px; }
            QListWidget::item:hover { background: #e8ecf8; }
        """)
        attach_layout.addWidget(self.attach_list)
        self.attach_box.setVisible(False)
        layout.addWidget(self.attach_box)

        # Status
        self.label_status = QLabel("Önizleme için tablodan bir e-posta seçin")
        self.label_status.setProperty("status", True)
        self.label_status.setAlignment(Qt.AlignCenter)
        self.label_status.setStyleSheet("color: #999; padding: 40px; font-size: 14px;")
        layout.addWidget(self.label_status)

        self.btn_raw.clicked.connect(self._show_raw)

    def show_mail(self, mail_meta: Dict):
        """Display a mail from metadata asynchronously in background thread."""
        self._current_mail = mail_meta
        mail_id = mail_meta.get("id")

        # Headers
        self.lbl_from.setText(f"Gönderen:  {mail_meta.get('sender', '—')}")
        self.lbl_to.setText(f"Alıcı:     {mail_meta.get('recipients', '—')}")
        self.lbl_date.setText(f"Tarih:     {mail_meta.get('date', '—')}")
        self.lbl_subject.setText(mail_meta.get('subject', '(Konusuz Mail)'))

        self.body_view.setHtml("<div style='text-align:center;padding:40px;color:#2563eb;'><h3>⏳ E-posta içeriği yükleniyor...</h3></div>")

        if getattr(self, '_loader_thread', None) is not None and self._loader_thread.isRunning():
            try:
                self._loader_thread.finished_signal.disconnect()
            except Exception:
                pass
            self._loader_thread.quit()

        self._loader_thread = MailBodyLoaderThread(self.engine, mail_id, parent=self)
        self._loader_thread.finished_signal.connect(self._on_mail_loaded)
        self._loader_thread.finished_signal.connect(self._loader_thread.deleteLater)
        self._loader_thread.start()

    @Slot(object)
    def _on_mail_loaded(self, result):
        if isinstance(result, Exception):
            self.body_view.setHtml(
                f"<div style='text-align:center;padding:40px;color:#ef4444;'>"
                f"<p style='font-size:24px;'>⚠️</p>"
                f"<p>E-posta içeriği ayrıştırılamadı: {result}</p>"
                f"</div>"
            )
        elif isinstance(result, email.message.Message):
            self._render_message(result)
        else:
            self.body_view.setHtml(
                "<div style='text-align:center;padding:40px;color:#64748b;'>"
                "<p style='font-size:32px;'>📧</p>"
                "<h4 style='color:#1e293b;margin:8px 0;'>E-posta ham içeriği yerel veritabanında bulunamadı.</h4>"
                "<p style='font-size:12px;color:#64748b;'>Tam e-posta gövdesini ve eklerini indirmek için lütfen sol menüden Senkronizasyon çalıştırın.</p>"
                "</div>"
            )
            self.label_status.setVisible(False)

    def _render_message(self, msg: email.message.Message):
        """Parse and render an email message."""
        html_parts = []
        text_parts = []
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disp = str(part.get("Content-Disposition", ""))

                if "attachment" in content_disp or (part.get_filename() and content_type not in ("text/plain", "text/html")):
                    attachments.append(self._extract_attachment_info(part))
                    continue

                payload = self._decode_payload(part)
                if payload is None:
                    continue

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

        # Render body (prefer HTML)
        if html_parts:
            body_html = "<hr>".join(html_parts)
            self.body_view.setHtml(body_html)
        elif text_parts:
            text = "\n\n".join(text_parts)
            escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            self.body_view.setHtml(f"<pre style='font-family:inherit;white-space:pre-wrap;'>{escaped}</pre>")
        else:
            self.body_view.setHtml(
                "<div style='text-align:center;padding:40px;color:#999;'>"
                "<p>(No content)</p></div>"
            )

        self.label_status.setVisible(False)

        # Attachments
        if attachments:
            self._attachments = attachments
            self.attach_box.setVisible(True)
            self.attach_list.clear()
            for a in attachments:
                icon = "📎"
                size_str = self._fmt_size(a.get("size", 0))
                item_text = f"{icon}  {a.get('filename', 'unnamed')}  ({size_str})"
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, a)
                self.attach_list.addItem(item)
        else:
            self.attach_box.setVisible(False)

    def _show_raw(self):
        if not self._current_mail:
            return
        mail_id = self._current_mail.get("id")
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
            self.body_view.setPlainText(text[:50000])
            self.label_status.setVisible(False)

    # ------------------------------------------------------------------
    # Helpers
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
        for unit in ["B", "KB", "MB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.2f} GB"


# ---------------------------------------------------------------------------
# Mail Detail Dialog (Double-Click Window)
# ---------------------------------------------------------------------------

class MailDialog(QDialog):
    """Window showing complete email body, raw source, print, download, and attachments."""

    def __init__(self, mail_meta: Dict, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.mail_meta = mail_meta
        self.engine = engine
        self._attachments = []
        self.setWindowTitle(mail_meta.get("subject", "View Email"))
        self.resize(900, 650)
        self.setStyleSheet("QDialog { background-color: #f8fafc; }")
        self._setup_ui()
        self._load_mail()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        # Header card
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        h_layout = QVBoxLayout(header_frame)
        h_layout.setSpacing(4)

        self.lbl_from = QLabel("From: —")
        self.lbl_from.setStyleSheet("font-weight: 600; color: #1e293b;")
        self.lbl_to = QLabel("To: —")
        self.lbl_to.setStyleSheet("color: #475569;")
        self.lbl_date = QLabel("Date: —")
        self.lbl_date.setStyleSheet("color: #64748b; font-size: 11px;")
        self.lbl_subject = QLabel("Subject: —")
        self.lbl_subject.setStyleSheet("font-size: 15px; font-weight: bold; color: #0f172a;")

        h_layout.addWidget(self.lbl_from)
        h_layout.addWidget(self.lbl_to)
        h_layout.addWidget(self.lbl_date)
        h_layout.addWidget(self.lbl_subject)
        layout.addWidget(header_frame)

        # Toolbar Actions
        toolbar = QHBoxLayout()
        self.btn_print = QPushButton("🖨️ Print Email")
        self.btn_print.setStyleSheet(self._btn_style("#10b981", "#059669"))
        self.btn_print.setCursor(Qt.PointingHandCursor)
        self.btn_print.clicked.connect(self._print_mail)

        self.btn_download = QPushButton("💾 Save EML")
        self.btn_download.setStyleSheet(self._btn_style("#4361ee", "#3a56d4"))
        self.btn_download.setCursor(Qt.PointingHandCursor)
        self.btn_download.clicked.connect(self._save_mail)

        self.btn_raw = QPushButton("📄 Toggle Raw Source")
        self.btn_raw.setStyleSheet(self._btn_style("#64748b", "#475569"))
        self.btn_raw.setCursor(Qt.PointingHandCursor)
        self.btn_raw.setCheckable(True)
        self.btn_raw.toggled.connect(self._toggle_raw)

        toolbar.addWidget(self.btn_print)
        toolbar.addWidget(self.btn_download)
        toolbar.addWidget(self.btn_raw)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Document Browser
        self.body_view = QTextBrowser()
        self.body_view.setOpenExternalLinks(True)
        self.body_view.setStyleSheet("""
            QTextBrowser {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 12px;
                font-size: 13px;
                color: #0f172a;
            }
        """)
        layout.addWidget(self.body_view, stretch=1)

        # Attachments box
        self.attach_box = QGroupBox("Attachments")
        self.attach_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #4361ee;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                margin-top: 6px;
                padding: 8px;
            }
        """)
        attach_layout = QVBoxLayout(self.attach_box)
        self.attach_list = QListWidget()
        self.attach_list.setSelectionMode(QListWidget.SingleSelection)
        self.attach_list.setMaximumHeight(90)
        self.attach_list.setStyleSheet("""
            QListWidget { border: none; }
            QListWidget::item { padding: 4px; }
        """)
        attach_layout.addWidget(self.attach_list)

        # Attachment actions
        attach_btns = QHBoxLayout()
        self.btn_open_att = QPushButton("📂 Open File")
        self.btn_open_att.setStyleSheet(self._btn_style("#4b5563", "#374151", py=4, px=10, fs=11))
        self.btn_open_att.clicked.connect(self._open_selected_attachment)

        self.btn_save_att = QPushButton("📥 Download File")
        self.btn_save_att.setStyleSheet(self._btn_style("#10b981", "#059669", py=4, px=10, fs=11))
        self.btn_save_att.clicked.connect(self._save_selected_attachment)

        self.btn_print_att = QPushButton("🖨️ Print File")
        self.btn_print_att.setStyleSheet(self._btn_style("#f59e0b", "#d97706", py=4, px=10, fs=11))
        self.btn_print_att.clicked.connect(self._print_selected_attachment)

        attach_btns.addWidget(self.btn_open_att)
        attach_btns.addWidget(self.btn_save_att)
        attach_btns.addWidget(self.btn_print_att)
        attach_btns.addStretch()
        attach_layout.addLayout(attach_btns)

        self.attach_box.setVisible(False)
        layout.addWidget(self.attach_box)

        # Close button
        btn_close = QPushButton("Close")
        btn_close.setStyleSheet(self._btn_style("#475569", "#334155"))
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, 0, Qt.AlignRight)

    def _load_mail(self):
        mail_id = self.mail_meta.get("id")
        self.lbl_from.setText(f"From:    {self.mail_meta.get('sender', '—')}")
        self.lbl_to.setText(f"To:      {self.mail_meta.get('recipients', '—')}")
        self.lbl_date.setText(f"Date:    {self.mail_meta.get('date', '—')}")
        self.lbl_subject.setText(self.mail_meta.get('subject', '(No Subject)'))

        raw_data = None
        try:
            raw_data = self.engine.mails.get_raw(mail_id)
        except Exception:
            pass

        if raw_data:
            try:
                self._msg = email.message_from_bytes(raw_data)
                self._render_message(self._msg)
            except Exception as e:
                self.body_view.setPlainText(f"Could not parse raw email: {e}")
        else:
            self.body_view.setHtml(
                "<div style='text-align:center;padding:40px;color:#999;'>"
                "<p>Email raw content not found in local archive.</p></div>"
            )

    def _render_message(self, msg):
        html_parts = []
        text_parts = []
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disp = str(part.get("Content-Disposition", ""))
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

        if html_parts:
            self._body_html = "<hr>".join(html_parts)
            self.body_view.setHtml(self._body_html)
        elif text_parts:
            self._body_text = "\n\n".join(text_parts)
            escaped = self._body_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            self.body_view.setHtml(f"<pre style='font-family:inherit;white-space:pre-wrap;'>{escaped}</pre>")
        else:
            self.body_view.setHtml("<p>(No content)</p>")

        if attachments:
            self._attachments = attachments
            self.attach_box.setVisible(True)
            self.attach_list.clear()
            for a in attachments:
                size_str = self._fmt_size(a["size"])
                item = QListWidgetItem(f"📎  {a['filename']}  ({size_str})")
                item.setData(Qt.UserRole, a)
                self.attach_list.addItem(item)
            self.attach_list.setCurrentRow(0)

    @Slot()
    def _print_mail(self):
        try:
            from PySide6.QtPrintSupport import QPrinter, QPrintDialog
            printer = QPrinter()
            dialog = QPrintDialog(printer, self)
            if dialog.exec() == QPrintDialog.Accepted:
                self.body_view.print_(printer)
        except Exception as e:
            QMessageBox.critical(self, "Printing Failed", f"Could not print: {e}")

    @Slot()
    def _save_mail(self):
        try:
            raw_data = self.engine.mails.get_raw(self.mail_meta["id"])
            if not raw_data:
                QMessageBox.warning(self, "Warning", "Raw mail data not available.")
                return
            import re
            cleaned_subj = re.sub(r'[\\/*?:"<>|]', "", self.mail_meta.get("subject") or "mail")[:50]
            default_name = f"{self.mail_meta.get('uid')}_{cleaned_subj}.eml"
            path, _ = QFileDialog.getSaveFileName(self, "Save Email as EML", default_name, "EML Files (*.eml)")
            if path:
                Path(path).write_bytes(raw_data)
                QMessageBox.information(self, "Saved", "Email exported successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", str(e))

    @Slot(bool)
    def _toggle_raw(self, checked: bool):
        if checked:
            raw_data = self.engine.mails.get_raw(self.mail_meta["id"])
            if raw_data:
                try:
                    text = raw_data.decode("utf-8", errors="replace")
                except Exception:
                    text = str(raw_data)
                self.body_view.setPlainText(text[:80000])
        else:
            self._load_mail()

    @Slot()
    def _open_selected_attachment(self):
        item = self.attach_list.currentItem()
        if not item:
            return
        att = item.data(Qt.UserRole)
        try:
            import tempfile
            import os
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            temp_dir = Path(tempfile.gettempdir()) / "mail_archive_temp"
            temp_dir.mkdir(exist_ok=True)
            temp_file = temp_dir / att["filename"]
            temp_file.write_bytes(att["data"])
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(temp_file)))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open attachment: {e}")

    @Slot()
    def _save_selected_attachment(self):
        item = self.attach_list.currentItem()
        if not item:
            return
        att = item.data(Qt.UserRole)
        path, _ = QFileDialog.getSaveFileName(self, "Save Attachment", att["filename"], "*.*")
        if path:
            try:
                Path(path).write_bytes(att["data"])
                QMessageBox.information(self, "Saved", "Attachment saved successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    @Slot()
    def _print_selected_attachment(self):
        item = self.attach_list.currentItem()
        if not item:
            return
        att = item.data(Qt.UserRole)
        mime = att.get("mime_type", "")
        if mime.startswith("text/") or att["filename"].endswith(".txt"):
            try:
                from PySide6.QtPrintSupport import QPrinter, QPrintDialog
                printer = QPrinter()
                dialog = QPrintDialog(printer, self)
                if dialog.exec() == QPrintDialog.Accepted:
                    doc = QTextDocument()
                    doc.setPlainText(att["data"].decode("utf-8", errors="replace"))
                    doc.print_(printer)
            except Exception as e:
                QMessageBox.critical(self, "Printing Failed", str(e))
        else:
            QMessageBox.information(self, "Direct Print Unsupported", 
                                    "Direct printing is only supported for text files. Please save and open the file in its default program to print it.")

    @staticmethod
    def _btn_style(bg: str, hover: str, py=6, px=14, fs=12):
        return f"""
            QPushButton {{
                background-color: {bg};
                color: white;
                font-weight: 600;
                padding: {py}px {px}px;
                border-radius: 4px;
                font-size: {fs}px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
        """

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
        for unit in ["B", "KB", "MB"]:
            if size < 1024:
                return f"{size:.0f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"


# ---------------------------------------------------------------------------
# Main MailViewerPanel
# ---------------------------------------------------------------------------

class MailViewerPanel(QWidget):
    """Thunderbird-style 3-pane mail viewer with lazy pagination."""

    _log_signal = Signal(str)
    _on_page_loaded_signal = Signal(list, int)
    _on_page_load_error_signal = Signal(str)

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._current_account_id: Optional[int] = None
        self._current_folder: str = "INBOX"
        
        self._current_offset = 0
        self._page_size = 50

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)

        # Top toolbar
        toolbar = QHBoxLayout()

        self.combo_group = QComboBox()
        self.combo_group.setMinimumWidth(180)
        self.combo_group.setToolTip("Grup / Domain filtresine göre hesapları ve klasörleri süzün")
        toolbar.addWidget(QLabel("📁 Grup/Domain:"))
        toolbar.addWidget(self.combo_group)

        self.combo_account = QComboBox()
        self.combo_account.setMinimumWidth(220)
        toolbar.addWidget(QLabel("Account:"))
        toolbar.addWidget(self.combo_account)

        self.btn_sync = QPushButton("🔄 Sync Folder")
        self.btn_sync.setObjectName("btn_sync_folder")
        self.btn_sync.setStyleSheet("background:#2ecc71;color:white;font-weight:600;padding:8px 18px;border-radius:6px;font-size:12px;border:none;")
        toolbar.addWidget(self.btn_sync)

        self.btn_sync_all = QPushButton("🔁 Sync All")
        self.btn_sync_all.setObjectName("btn_sync_all")
        self.btn_sync_all.setStyleSheet("background:#4361ee;color:white;font-weight:600;padding:8px 18px;border-radius:6px;font-size:12px;border:none;")
        toolbar.addWidget(self.btn_sync_all)

        self.btn_log = QPushButton("📋 Log")
        self.btn_log.setObjectName("btn_log")
        self.btn_log.setCheckable(True)
        self.btn_log.setStyleSheet("background:transparent;color:#555;border:2px solid #aaa;font-weight:600;padding:8px 18px;border-radius:6px;font-size:12px;")
        toolbar.addWidget(self.btn_log)

        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setObjectName("btn_refresh")
        self.btn_refresh.setStyleSheet("background:#6c757d;color:white;font-weight:600;padding:8px 18px;border-radius:6px;font-size:12px;border:none;")
        toolbar.addWidget(self.btn_refresh)

        toolbar.addStretch()

        self.label_folder = QLabel("")
        self.label_folder.setStyleSheet("font-weight: 600; color: #4361ee;")
        toolbar.addWidget(self.label_folder)

        layout.addLayout(toolbar)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(6)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        # 3-pane splitter
        self.splitter = QSplitter(Qt.Horizontal)

        # Left: Folder tree
        self.folder_tree = FolderTree(self.engine)
        self.splitter.addWidget(self.folder_tree)

        # Center: Mail list
        self.mail_list = MailListTable()
        self.splitter.addWidget(self.mail_list)

        # Right: Mail preview
        self.mail_preview = MailPreview(self.engine)
        self.splitter.addWidget(self.mail_preview)

        self.splitter.setStretchFactor(0, 1)  # folder tree
        self.splitter.setStretchFactor(1, 2)  # mail list
        self.splitter.setStretchFactor(2, 3)  # preview
        self.splitter.setSizes([220, 450, 500])

        layout.addWidget(self.splitter, stretch=1)

        # Log area (collapsible)
        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(180)
        self.log_area.setVisible(False)
        self.log_area.setStyleSheet("""
            QPlainTextEdit {
                background: #1a1a2e;
                color: #a8d8ea;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                border: 1px solid #2d2d44;
                border-radius: 4px;
                padding: 6px;
            }
        """)
        layout.addWidget(self.log_area)

        # Status bar
        self.status_bar = QStatusBar()
        self.status_bar.setMaximumHeight(28)
        self.status_bar.setStyleSheet("""
            QStatusBar {
                background: #1a1a2e;
                color: #a8d8ea;
                font-size: 11px;
                border-radius: 4px;
                padding: 2px 8px;
            }
        """)
        layout.addWidget(self.status_bar)

    def _connect_signals(self):
        self.combo_group.currentIndexChanged.connect(self._on_group_changed)
        self.folder_tree.folder_selected.connect(self._on_folder_selected)
        self.mail_list.mail_selected.connect(self._on_mail_selected)
        self.mail_list.mail_double_clicked.connect(self._on_mail_double_clicked)
        self.mail_list.need_more_mails.connect(self._load_next_page)
        
        self.btn_sync.clicked.connect(self._sync_current_folder)
        self.btn_sync_all.clicked.connect(self._sync_all_folders)
        self.btn_log.toggled.connect(self._toggle_log)
        self.btn_refresh.clicked.connect(self.refresh)
        self.combo_account.currentIndexChanged.connect(self._on_account_changed)
        
        self._log_signal.connect(self._on_log_message)
        self._on_page_loaded_signal.connect(self._on_page_loaded)
        self._on_page_load_error_signal.connect(self._on_page_load_error)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @Slot(int, str)
    def _on_folder_selected(self, account_id: int, folder: str):
        self._current_account_id = account_id
        self._current_folder = folder
        self.label_folder.setText(f"📁 {folder}")
        self.status_bar.showMessage(f"Loading {folder}...")

        # Reset pagination offsets and table
        self._current_offset = 0
        self.mail_list.clear_mails()
        self._load_next_page()

    def _load_next_page(self):
        if not self._current_account_id:
            return
            
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_bar.showMessage("Loading messages in background...")

        def fetch_task(aid, fld, limit, offset):
            try:
                mails = self.engine.mails.get_for_account(aid, fld, limit=limit, offset=offset)
                self._on_page_loaded_signal.emit(mails, offset)
            except Exception as e:
                self._on_page_load_error_signal.emit(str(e))

        t = threading.Thread(
            target=fetch_task, 
            args=(self._current_account_id, self._current_folder, self._page_size, self._current_offset),
            daemon=True
        )
        t.start()

    @Slot(list, int)
    def _on_page_loaded(self, mails: list, offset: int):
        self.progress_bar.setVisible(False)
        self.mail_list._loading = False
        
        if not mails:
            self.mail_list._has_more = False
            self.status_bar.showMessage(f"{self._current_folder}: {len(self.mail_list._mails)} messages (End of list)", 5000)
            return

        self.mail_list.append_mails(mails)
        self._current_offset += len(mails)

        if len(mails) < self._page_size:
            self.mail_list._has_more = False

        self.status_bar.showMessage(f"{self._current_folder}: {len(self.mail_list._mails)} messages loaded", 5000)

    @Slot(str)
    def _on_page_load_error(self, err_msg: str):
        self.progress_bar.setVisible(False)
        self.mail_list._loading = False
        self.status_bar.showMessage(f"Error loading messages: {err_msg}")
        QMessageBox.critical(self, "Load Error", f"Failed to retrieve emails: {err_msg}")

    @Slot(dict)
    def _on_mail_selected(self, mail_meta: Dict):
        self.mail_preview.show_mail(mail_meta)

    @Slot(dict)
    def _on_mail_double_clicked(self, mail_meta: Dict):
        dialog = MailDialog(mail_meta, self.engine, self)
        dialog.exec()

    def _append_log(self, msg: str):
        self._log_signal.emit(msg)

    @Slot(str)
    def _on_log_message(self, msg: str):
        cursor = self.log_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(msg + "\n")
        self.log_area.setTextCursor(cursor)
        scrollbar = self.log_area.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def _log_callback(self, msg: str):
        self._append_log(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    @Slot(bool)
    def _toggle_log(self, checked: bool):
        self.log_area.setVisible(checked)

    @Slot()
    def _sync_current_folder(self):
        if not self._current_account_id:
            QMessageBox.warning(self, "No Folder", "Select a folder first.")
            return
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_bar.showMessage(f"Syncing {self._current_folder}...")
        self._append_log(f"=== Sync started: {self._current_folder} ===")

        def task():
            try:
                report = self.engine.sync_account(
                    self._current_account_id,
                    log_callback=self._log_callback,
                )
                self._append_log(
                    f"Sync done: {report.mails_fetched} fetched, "
                    f"{report.errors} errors"
                )
                self.progress_bar.setVisible(False)
                self.status_bar.showMessage(
                    f"Sync done: {report.mails_fetched} fetched, "
                    f"{report.errors} errors"
                )
                # Reload folder dynamically
                self._current_offset = 0
                self.mail_list.clear_mails()
                self._load_next_page()
            except Exception as exc:
                self._append_log(f"SYNC ERROR: {exc}")
                self.progress_bar.setVisible(False)
                self.status_bar.showMessage(f"Error: {exc}")

        threading.Thread(target=task, daemon=True).start()

    @Slot()
    def _sync_all_folders(self):
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_bar.showMessage("Syncing all accounts...")
        self._append_log("=== Sync All started ===")

        def task():
            try:
                reports = self.engine.sync_all(log_callback=self._log_callback)
                self.progress_bar.setVisible(False)
                total = sum(r.mails_fetched for r in reports)
                errors = sum(r.errors for r in reports)
                self._append_log(f"Sync All complete: {total} fetched, {errors} errors")
                self.status_bar.showMessage(f"Sync all: {total} fetched, {errors} errors")
                self.refresh()
            except Exception as exc:
                self._append_log(f"SYNC ALL ERROR: {exc}")
                self.progress_bar.setVisible(False)
                self.status_bar.showMessage(f"Error: {exc}")

        threading.Thread(target=task, daemon=True).start()

    @Slot(int)
    def _on_group_changed(self, idx: int):
        selected_group = self.combo_group.itemData(idx) if idx >= 0 else "__ALL__"
        self._populate_accounts_for_group(selected_group or "__ALL__")
        self.folder_tree.refresh(selected_group or "__ALL__")

    def _populate_accounts_for_group(self, selected_group: str):
        self.combo_account.blockSignals(True)
        self.combo_account.clear()
        try:
            all_accounts = self.engine.list_accounts()
            for acc in all_accounts:
                g_val = acc.get("account_group", "").strip()
                if not g_val and "@" in acc.get("email", ""):
                    g_val = acc["email"].split("@")[-1].strip()
                if selected_group == "__ALL__" or g_val == selected_group:
                    self.combo_account.addItem(f"{acc['label']} ({acc['email']})", acc)
        except Exception as exc:
            logger.error("Error populating accounts for group: %s", exc)
        finally:
            self.combo_account.blockSignals(False)

    @Slot()
    def _on_account_changed(self, idx: int):
        if idx >= 0:
            acc_data = self.combo_account.itemData(idx)
            if isinstance(acc_data, dict):
                self._current_account_id = acc_data.get("id")

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self):
        current_grp = self.combo_group.currentData() if hasattr(self, "combo_group") else "__ALL__"
        self.combo_group.blockSignals(True)
        self.combo_group.clear()
        self.combo_group.addItem("🌐 Tüm Gruplar / Domainler", "__ALL__")

        groups = set()
        try:
            all_accounts = self.engine.list_accounts()
            for acc in all_accounts:
                g_val = acc.get("account_group", "").strip()
                if not g_val and "@" in acc.get("email", ""):
                    g_val = acc["email"].split("@")[-1].strip()
                if g_val:
                    groups.add(g_val)
        except Exception:
            pass

        for g in sorted(groups):
            self.combo_group.addItem(f"📁 {g}", g)

        idx = self.combo_group.findData(current_grp)
        if idx >= 0:
            self.combo_group.setCurrentIndex(idx)
        else:
            self.combo_group.setCurrentIndex(0)
        self.combo_group.blockSignals(False)

        selected_group = self.combo_group.currentData() or "__ALL__"
        self._populate_accounts_for_group(selected_group)
        self.folder_tree.refresh(selected_group)
