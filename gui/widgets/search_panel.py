"""
search_panel.py — Redesigned search panel with advanced filters and Thunderbid-style email preview.
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

from PySide6.QtCore import Qt, Slot, QDate, QUrl
from PySide6.QtGui import QFont, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QGroupBox, QTextBrowser, QMessageBox, QComboBox, QDateEdit,
    QCheckBox, QSplitter, QFrame, QListWidget, QListWidgetItem,
)

from core.mail_engine import MailEngine

logger = logging.getLogger(__name__)

# BTN styling helpers
BTN_STYLE_BLUE = """
    QPushButton {
        background-color: #4361ee;
        color: white;
        font-weight: 600;
        padding: 5px 12px;
        border-radius: 6px;
        font-size: 12px;
        border: none;
    }
    QPushButton:hover {
        background-color: #3a56d4;
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


class SearchPanel(QWidget):
    """Full-text search panel with advanced metadata filters and rich preview."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._results: List[Dict[str, Any]] = []
        self._current_attachments: List[Dict[str, Any]] = []
        self._raw_mode = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Header
        header = QLabel("Full-Text Search & Discovery")
        header.setProperty("heading", True)
        header.setStyleSheet("font-size: 22px; font-weight: bold; color: #1a1a2e;")
        layout.addWidget(header)

        sub = QLabel("Search archived messages across all folders, dates, and contents using SQLite FTS5 index.")
        sub.setProperty("subheading", True)
        sub.setStyleSheet("font-size: 13px; color: #64748b; margin-bottom: 4px;")
        layout.addWidget(sub)

        # Splitter for Filters+Table (Left) vs Email Viewer (Right)
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setStyleSheet("QSplitter::handle { background-color: #e2e8f0; width: 2px; }")

        # Left Widget containing search inputs, advanced filters, and results list
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(10)

        # Search bar
        search_box = QFrame()
        search_box.setStyleSheet("QFrame { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; }")
        search_bar_layout = QHBoxLayout(search_box)
        search_bar_layout.setContentsMargins(10, 8, 10, 8)
        search_bar_layout.setSpacing(8)

        self.input_query = QLineEdit()
        self.input_query.setPlaceholderText("Metin ara... (Örn: fatura, acil, rapor, 'proje x')")
        self.input_query.setMinimumHeight(34)
        self.input_query.setStyleSheet("font-size: 13px; border: 1px solid #cbd5e1; border-radius: 4px; padding: 4px 8px;")
        search_bar_layout.addWidget(self.input_query, stretch=1)

        self.btn_search = QPushButton("🔍 Ara")
        self.btn_search.setStyleSheet(BTN_STYLE_BLUE)
        self.btn_search.setMinimumHeight(34)
        search_bar_layout.addWidget(self.btn_search)

        self.btn_rebuild = QPushButton("Dizini Yeniden Kur")
        self.btn_rebuild.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_rebuild.setMinimumHeight(34)
        search_bar_layout.addWidget(self.btn_rebuild)

        left_layout.addWidget(search_box)

        # Advanced Filters Group
        filters_box = QGroupBox("Gelişmiş Arama Filtreleri")
        filters_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 11px;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 14px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                color: #4361ee;
            }
        """)
        filters_grid = QVBoxLayout(filters_box)
        filters_grid.setContentsMargins(10, 10, 10, 10)
        filters_grid.setSpacing(8)

        # Row 1 of Filters: Account, Folder, Attachment
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        
        row1.addWidget(QLabel("Hesap:"))
        self.combo_account = QComboBox()
        self.combo_account.setMinimumWidth(180)
        row1.addWidget(self.combo_account)

        row1.addWidget(QLabel("Klasör:"))
        self.input_folder = QLineEdit()
        self.input_folder.setPlaceholderText("Örn: INBOX, Sent")
        self.input_folder.setMinimumWidth(100)
        row1.addWidget(self.input_folder)

        row1.addWidget(QLabel("Ek Dosya:"))
        self.combo_attachments = QComboBox()
        self.combo_attachments.addItems(["Tümü", "Ekli Olanlar", "Eksiz Olanlar"])
        row1.addWidget(self.combo_attachments)

        filters_grid.addLayout(row1)

        # Row 2 of Filters: Date constraints & Read status
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        self.chk_since = QCheckBox("Şu tarihten yeni:")
        row2.addWidget(self.chk_since)
        self.date_since = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_since.setCalendarPopup(True)
        self.date_since.setEnabled(False)
        self.chk_since.toggled.connect(self.date_since.setEnabled)
        row2.addWidget(self.date_since)

        self.chk_before = QCheckBox("Şu tarihten eski:")
        row2.addWidget(self.chk_before)
        self.date_before = QDateEdit(QDate.currentDate())
        self.date_before.setCalendarPopup(True)
        self.date_before.setEnabled(False)
        self.chk_before.toggled.connect(self.date_before.setEnabled)
        row2.addWidget(self.date_before)

        row2.addWidget(QLabel("Okuma Durumu:"))
        self.combo_read = QComboBox()
        self.combo_read.addItems(["Tümü", "Yalnızca Okunmamış", "Yalnızca Okunmuş"])
        row2.addWidget(self.combo_read)

        filters_grid.addLayout(row2)
        left_layout.addWidget(filters_box)

        # Results Table
        self.label_count = QLabel("0 sonuç bulundu")
        self.label_count.setStyleSheet("font-size: 12px; color: #64748b; font-weight: 500;")
        left_layout.addWidget(self.label_count)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Tarih", "Hesap", "Kimden", "Konu", "Klasör", "Ek"
        ])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                background-color: #ffffff;
                color: #0f172a;
            }
            QTableWidget::item { padding: 6px 8px; }
            QTableWidget::item:selected { background-color: #cbd5e1; color: #000000; }
        """)
        left_layout.addWidget(self.table, stretch=1)

        main_splitter.addWidget(left_widget)

        # Right Widget: Thunderbird-style Email Viewer Pane
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)

        # Preview Headers Group
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
        header_grid.setContentsMargins(12, 12, 12, 12)
        header_grid.setSpacing(4)

        self.lbl_subject = QLabel("(Konu Yok)")
        self.lbl_subject.setStyleSheet("font-size: 14px; font-weight: bold; color: #1e3a8a;")
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

        # Toolbar inside preview pane
        preview_toolbar = QHBoxLayout()
        preview_toolbar.setSpacing(6)

        self.btn_save_eml = QPushButton("📥 .EML Dışa Aktar")
        self.btn_save_eml.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_save_eml.setEnabled(False)
        preview_toolbar.addWidget(self.btn_save_eml)

        self.btn_print = QPushButton("🖨️ Yazdır")
        self.btn_print.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_print.setEnabled(False)
        preview_toolbar.addWidget(self.btn_print)

        self.btn_toggle_raw = QPushButton("📄 Ham Kaynak")
        self.btn_toggle_raw.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_toggle_raw.setEnabled(False)
        self.btn_toggle_raw.setCheckable(True)
        preview_toolbar.addWidget(self.btn_toggle_raw)

        preview_toolbar.addStretch()
        header_grid.addLayout(preview_toolbar)

        right_layout.addWidget(self.preview_header_frame)

        # Body Preview Browser
        self.preview_browser = QTextBrowser()
        self.preview_browser.setOpenLinks(False)
        self.preview_browser.setStyleSheet("""
            QTextBrowser {
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                background-color: #ffffff;
                padding: 12px;
            }
        """)
        right_layout.addWidget(self.preview_browser, stretch=1)

        # Attachments pane
        self.attach_box = QGroupBox("Ekli Dosyalar")
        self.attach_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1.5px solid #ef4444;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                color: #ef4444;
            }
        """)
        attach_layout = QVBoxLayout(self.attach_box)
        attach_layout.setContentsMargins(8, 8, 8, 8)

        self.attach_list = QListWidget()
        self.attach_list.setMaximumHeight(80)
        self.attach_list.setStyleSheet("border: 1px solid #cbd5e1; border-radius: 4px;")
        attach_layout.addWidget(self.attach_list)

        attach_btns = QHBoxLayout()
        self.btn_open_attach = QPushButton("📂 Aç")
        self.btn_open_attach.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_save_attach = QPushButton("📥 Kaydet")
        self.btn_save_attach.setStyleSheet(BTN_STYLE_BLUE)
        attach_btns.addWidget(self.btn_open_attach)
        attach_btns.addWidget(self.btn_save_attach)
        attach_btns.addStretch()
        attach_layout.addLayout(attach_btns)

        self.attach_box.setVisible(False)
        right_layout.addWidget(self.attach_box)

        main_splitter.addWidget(right_widget)
        main_splitter.setSizes([850, 550])
        layout.addWidget(main_splitter)

        # Connections
        self.btn_search.clicked.connect(self._search)
        self.btn_rebuild.clicked.connect(self._rebuild_index)
        self.input_query.returnPressed.connect(self._search)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        
        self.btn_save_eml.clicked.connect(self._save_eml)
        self.btn_print.clicked.connect(self._print_mail)
        self.btn_toggle_raw.toggled.connect(self._toggle_raw_mode)

        self.btn_open_attach.clicked.connect(self._open_selected_attachment)
        self.btn_save_attach.clicked.connect(self._save_selected_attachment)

    # ------------------------------------------------------------------
    # Data loading / Refresh account filters
    # ------------------------------------------------------------------

    def refresh(self):
        self.combo_account.clear()
        self.combo_account.addItem("Tüm Hesaplar", None)
        try:
            accounts = self.engine.list_accounts()
            for acc in accounts:
                self.combo_account.addItem(acc["label"], acc["id"])
        except Exception as exc:
            logger.error("Failed to load accounts in search: %s", exc)

    # ------------------------------------------------------------------
    # Search implementation
    # ------------------------------------------------------------------

    @Slot()
    def _search(self):
        query = self.input_query.text().strip()
        
        # Resolve filter params
        account_id = self.combo_account.currentData()
        folder = self.input_folder.text().strip() or None
        
        since_date = None
        if self.chk_since.isChecked():
            since_date = self.date_since.date().toString("yyyy-MM-dd 00:00:00")
            
        before_date = None
        if self.chk_before.isChecked():
            before_date = self.date_before.date().toString("yyyy-MM-dd 23:59:59")

        att_idx = self.combo_attachments.currentIndex()
        has_attachments = None
        if att_idx == 1:
            has_attachments = True
        elif att_idx == 2:
            has_attachments = False

        read_idx = self.combo_read.currentIndex()
        unread_only = None
        if read_idx == 1:
            unread_only = True
        elif read_idx == 2:
            unread_only = False

        try:
            results = self.engine.search(
                query=query,
                limit=300,
                account_id=account_id,
                folder=folder,
                since_date=since_date,
                before_date=before_date,
                has_attachments=has_attachments,
                unread_only=unread_only
            )
            self.label_count.setText(f"{len(results)} sonuç bulundu")
            self._results = results
            
            self.table.setRowCount(0)
            self.table.setRowCount(len(results))

            for i, r in enumerate(results):
                # Format Date
                date_val = (r.get("date") or "")[:10]
                self.table.setItem(i, 0, QTableWidgetItem(date_val))

                # Account
                acc_id = r.get("account_id")
                acc_label = f"#{acc_id}"
                acc = self.engine.accounts.get(acc_id)
                if acc:
                    acc_label = acc.get("label", acc_label)
                self.table.setItem(i, 1, QTableWidgetItem(acc_label))

                # From
                self.table.setItem(i, 2, QTableWidgetItem((r.get("sender") or "")[:35]))
                
                # Subject
                self.table.setItem(i, 3, QTableWidgetItem((r.get("subject") or "")[:60]))
                
                # Folder
                self.table.setItem(i, 4, QTableWidgetItem(r.get("folder", "")))

                # Attachment
                has_att = r.get("has_attachments", 0)
                self.table.setItem(i, 5, QTableWidgetItem("📎" if has_att else ""))

                # Bind metadata inside UserRole
                for col in range(6):
                    self.table.item(i, col).setData(Qt.UserRole, r)

            self.table.resizeColumnsToContents()
            self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            
            if results:
                self.table.selectRow(0)
            else:
                self._clear_preview()

        except Exception as exc:
            QMessageBox.critical(self, "Arama Hatası", f"İşlem başarısız oldu:\n{exc}")

    @Slot()
    def _rebuild_index(self):
        try:
            self.engine.db.rebuild_fts_index()
            QMessageBox.information(self, "Başarılı", "FTS5 Arama İndeksi başarıyla yeniden oluşturuldu.")
        except Exception as exc:
            QMessageBox.critical(self, "Hata", str(exc))

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
        if row < 0 or row >= len(self._results):
            self._clear_preview()
            return

        r = self.table.item(row, 0).data(Qt.UserRole)
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
                "<div style='text-align:center;padding:40px;color:#999;'>"
                "<p>E-posta ham içeriği yerel veritabanında bulunamadı.</p></div>"
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
            self.preview_browser.setPlainText("Ham veri bulunamadı.")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @Slot()
    def _save_eml(self):
        row = self.table.currentRow()
        if row < 0:
            return
        r = self.table.item(row, 0).data(Qt.UserRole)
        if not r:
            return

        try:
            raw_data = self.engine.mails.get_raw(r["id"])
            if not raw_data:
                QMessageBox.warning(self, "Hata", "E-postanın ham verisi veritabanında yok.")
                return
                
            cleaned_subj = re.sub(r'[\\/*?:"<>|]', "", r.get("subject") or "mail")[:50]
            default_name = f"{r.get('uid')}_{cleaned_subj}.eml"
            
            path, _ = QFileDialog.getSaveFileName(self, "E-postayı EML olarak kaydet", default_name, "EML Dosyaları (*.eml)")
            if path:
                Path(path).write_bytes(raw_data)
                QMessageBox.information(self, "Başarılı", "E-posta başarıyla kaydedildi.")
        except Exception as e:
            QMessageBox.critical(self, "Kaydetme Başarısız", str(e))

    @Slot()
    def _print_mail(self):
        try:
            from PySide6.QtPrintSupport import QPrinter, QPrintDialog
            printer = QPrinter()
            dialog = QPrintDialog(printer, self)
            if dialog.exec() == QPrintDialog.Accepted:
                self.preview_browser.print_(printer)
        except Exception as e:
            QMessageBox.critical(self, "Yazdırma Hatası", f"Yazdırılamadı: {e}")

    @Slot(bool)
    def _toggle_raw_mode(self, checked: bool):
        self._raw_mode = checked
        row = self.table.currentRow()
        if row >= 0:
            r = self.table.item(row, 0).data(Qt.UserRole)
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
            QMessageBox.critical(self, "Hata", f"Dosya açılamadı: {e}")

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
                QMessageBox.information(self, "Başarılı", "Ek başarıyla kaydedildi.")
            except Exception as e:
                QMessageBox.critical(self, "Hata", str(e))

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
        for unit in ["B", "KB", "MB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.2f} GB"
