"""
portable_import_dialog.py — Interactive Portable Drive / Backup Folder Import Dialog.
"""

import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any

from PySide6.QtCore import Qt, Slot, Signal, QThread
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame,
    QLineEdit, QPushButton, QFileDialog, QProgressBar, QMessageBox,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QWidget,
    QGroupBox, QTextEdit
)

from core.mail_engine import MailEngine

logger = logging.getLogger(__name__)


class PortableImportWorker(QThread):
    progress_signal = Signal(int, int, str)
    finished_signal = Signal(object)

    def __init__(self, engine: MailEngine, backup_dir: Path, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.backup_dir = backup_dir

    def run(self):
        try:
            def cb(current, total, status_text):
                self.progress_signal.emit(current, total, status_text)
            
            res = self.engine.import_portable_backup(self.backup_dir, progress_callback=cb)
            self.finished_signal.emit(res)
        except Exception as exc:
            self.finished_signal.emit(exc)


class PortableImportDialog(QDialog):
    """Dialog for scanning, inspecting, and importing a portable drive mail backup folder."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.inspection_result: Optional[Dict[str, Any]] = None
        self._worker: Optional[PortableImportWorker] = None

        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Taşınabilir Disk / Klasör Yedeği İçe Aktar")
        self.resize(780, 600)
        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
            }
            QGroupBox {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                font-weight: bold;
                font-size: 12px;
                margin-top: 6px;
            }
            QLineEdit {
                background-color: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 11px;
            }
            QPushButton {
                font-weight: bold;
                font-size: 11px;
                padding: 6px 14px;
                border-radius: 4px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header Frame
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1e3a8a, stop:1 #2563eb);
                border-radius: 8px;
                padding: 12px;
            }
        """)
        h_layout = QVBoxLayout(header_frame)
        lbl_title = QLabel("📦 Taşınabilir Disk & Dış Klasör Yedeği İçe Aktar")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: 800; color: #ffffff;")
        lbl_sub = QLabel("Başka bir bilgisayarda veya harici diskte yedeklenmiş mail arşivini (veritabanı, hesaplar, ekler ve dışa aktarım profilleri) mevcut sisteme aktarır.")
        lbl_sub.setStyleSheet("font-size: 11px; color: #dbeafe;")
        lbl_sub.setWordWrap(True)
        h_layout.addWidget(lbl_title)
        h_layout.addWidget(lbl_sub)
        layout.addWidget(header_frame)

        # Step 1: Directory Selection Box
        dir_box = QGroupBox("1. Harici / Taşınabilir Yedek Klasörünü Seçin")
        dir_layout = QHBoxLayout(dir_box)

        self.txt_path = QLineEdit()
        self.txt_path.setPlaceholderText("Örn: D:\\mailyedek veya E:\\Yedekler\\MailArchive")
        dir_layout.addWidget(self.txt_path, stretch=1)

        self.btn_browse = QPushButton("📁 Klasör Seç...")
        self.btn_browse.setStyleSheet("background-color: #e2e8f0; color: #0f172a;")
        self.btn_browse.clicked.connect(self._on_browse)
        dir_layout.addWidget(self.btn_browse)

        self.btn_inspect = QPushButton("🔍 İncele ve Taramayı Başlat")
        self.btn_inspect.setStyleSheet("background-color: #2563eb; color: #ffffff;")
        self.btn_inspect.clicked.connect(self._on_inspect)
        dir_layout.addWidget(self.btn_inspect)

        layout.addWidget(dir_box)

        # Step 2: Warning Banner (Hidden by default)
        self.warning_banner = QFrame()
        self.warning_banner.setStyleSheet("""
            QFrame {
                background-color: #fef2f2;
                border: 1.5px solid #ef4444;
                border-radius: 6px;
                padding: 8px 12px;
            }
        """)
        wb_layout = QHBoxLayout(self.warning_banner)
        self.lbl_warning = QLabel("⚠️ ÇAKIŞAN HESAP UYARISI: İçe aktarılacak bazı hesaplar mevcut sisteminizde zaten yüklü! Varolan hesapların mailleri mükerrer olmadan mevcut arşiv birleştirilecektir.")
        self.lbl_warning.setStyleSheet("color: #991b1b; font-weight: bold; font-size: 11px;")
        self.lbl_warning.setWordWrap(True)
        wb_layout.addWidget(self.lbl_warning)
        self.warning_banner.setVisible(False)
        layout.addWidget(self.warning_banner)

        # Step 3: Account Preview & Inspection Details Table
        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(5)
        self.preview_table.setHorizontalHeaderLabels(["Hesap Adı", "E-Posta", "IMAP Sunucusu", "Grup / Domain", "Sistem Durumu"])
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.preview_table.setStyleSheet("background: #ffffff; gridline-color: #f1f5f9; font-size: 11px;")
        layout.addWidget(self.preview_table, stretch=1)

        # Step 4: Statistics Summary Bar
        self.lbl_stats = QLabel("Lütfen yedek alınan klasörü seçip 'İncele' butonuna basınız.")
        self.lbl_stats.setStyleSheet("font-weight: bold; color: #475569; font-size: 11px;")
        layout.addWidget(self.lbl_stats)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Log box
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(80)
        self.txt_log.setStyleSheet("background: #1e293b; color: #a8d8ea; font-family: monospace; font-size: 10px;")
        self.txt_log.setVisible(False)
        layout.addWidget(self.txt_log)

        # Dialog Action Buttons
        btn_box = QHBoxLayout()
        self.btn_cancel = QPushButton("İptal")
        self.btn_cancel.setStyleSheet("background-color: #cbd5e1; color: #0f172a;")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_import = QPushButton("📥 Verileri İçe Aktar ve Birleştir")
        self.btn_import.setStyleSheet("background-color: #10b981; color: #ffffff; font-size: 12px; padding: 8px 18px;")
        self.btn_import.setEnabled(False)
        self.btn_import.clicked.connect(self._on_start_import)

        btn_box.addStretch()
        btn_box.addWidget(self.btn_cancel)
        btn_box.addWidget(self.btn_import)
        layout.addLayout(btn_box)

    @Slot()
    def _on_browse(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Yedek Alınmış Mail Klasörünü Seçin", self.txt_path.text() or "D:\\")
        if dir_path:
            self.txt_path.setText(dir_path)
            self._on_inspect()

    @Slot()
    def _on_inspect(self):
        raw_path = self.txt_path.text().strip()
        if not raw_path:
            QMessageBox.warning(self, "Klasör Seçilmedi", "Lütfen bir dış yedek klasör yolu seçiniz.")
            return

        p = Path(raw_path)
        if not p.exists() or not p.is_dir():
            QMessageBox.warning(self, "Geçersiz Klasör", "Seçilen dizin mevcut değil veya bir klasör değil.")
            return

        res = self.engine.inspect_portable_backup(p)
        if not res.get("is_valid"):
            QMessageBox.critical(self, "Yedek İnceleme Hatası", res.get("error", "Geçersiz yedek klasörü."))
            self.btn_import.setEnabled(False)
            self.warning_banner.setVisible(False)
            return

        self.inspection_result = res
        accs = res.get("accounts", [])
        conflicts = res.get("conflicting_accounts", [])

        # Fill table
        self.preview_table.setRowCount(0)
        for idx, acc in enumerate(accs):
            self.preview_table.insertRow(idx)
            self.preview_table.setItem(idx, 0, QTableWidgetItem(acc.get("label") or "—"))
            self.preview_table.setItem(idx, 1, QTableWidgetItem(acc.get("email") or "—"))
            self.preview_table.setItem(idx, 2, QTableWidgetItem(acc.get("imap_host") or "—"))
            self.preview_table.setItem(idx, 3, QTableWidgetItem(acc.get("account_group") or "—"))

            is_conflict = any(c.get("email", "").lower() == acc.get("email", "").lower() for c in conflicts)
            st_item = QTableWidgetItem("Mevcut Hesap (Birleştirilecek)" if is_conflict else "Yeni Hesap (Eklenecek)")
            st_item.setForeground(QColor("#ef4444") if is_conflict else QColor("#10b981"))
            st_item.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.preview_table.setItem(idx, 4, st_item)

        if conflicts:
            self.lbl_warning.setText(
                f"⚠️ ÇAKIŞAN HESAP UYARISI: İçe aktarılacak {len(conflicts)} adet hesap mevcut sisteminizde zaten tanımlı! "
                "İçe aktarma işleminde hesap ayarlarınız korunacak, bu hesaplara ait yeni e-postalar mükerrer oluşmadan arşive eklenecektir."
            )
            self.warning_banner.setVisible(True)
        else:
            self.warning_banner.setVisible(False)

        total_mails = res.get("total_mails", 0)
        total_att = res.get("total_attachments", 0)
        profiles_cnt = len(res.get("export_profiles", []))

        self.lbl_stats.setText(
            f"✅ İnceleme Tamamlandı: {len(accs)} Hesap, {total_mails:,} E-posta, {total_att:,} Ek Dosya, {profiles_cnt} Dışa Aktarım Profili bulundu."
        )
        self.btn_import.setEnabled(True)

    @Slot()
    def _on_start_import(self):
        if not self.inspection_result or not self.inspection_result.get("is_valid"):
            return

        conflicts = self.inspection_result.get("conflicting_accounts", [])
        if conflicts:
            conf_names = "\n".join([f"• {c.get('email')}" for c in conflicts[:5]])
            if len(conflicts) > 5:
                conf_names += f"\n... ve {len(conflicts)-5} hesap daha"

            msg = (
                f"Aşağıdaki hesaplar mevcut sisteminizde zaten yüklü:\n\n{conf_names}\n\n"
                "İçeri aktarma işlemi başlatıldığında varolan mailler korunarak eksik veriler otomatik birleştirilecektir.\n\n"
                "Devam etmek istiyor musunuz?"
            )
            if QMessageBox.question(self, "İçe Aktarmayı Onayla", msg, QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return

        self.btn_import.setEnabled(False)
        self.btn_inspect.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.txt_path.setEnabled(False)

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.txt_log.setVisible(True)
        self.txt_log.append("=== Taşınabilir Disk Aktarımı Başlatıldı ===")

        backup_dir = Path(self.inspection_result["backup_dir"])
        self._worker = PortableImportWorker(self.engine, backup_dir, self)
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.start()

    @Slot(int, int, str)
    def _on_progress(self, current: int, total: int, status_text: str):
        if total > 0:
            pct = int(current * 100 / total)
            self.progress_bar.setValue(pct)
        self.txt_log.append(status_text)
        self.txt_log.verticalScrollBar().setValue(self.txt_log.verticalScrollBar().maximum())

    @Slot(object)
    def _on_finished(self, result):
        self.progress_bar.setValue(100)
        if isinstance(result, Exception):
            QMessageBox.critical(self, "Aktarım Hatası", f"İçe aktarma sırasında bir hata oluştu: {result}")
            self.txt_log.append(f"❌ HATA: {result}")
        else:
            acc_cnt = result.get("imported_accounts", 0)
            mail_cnt = result.get("imported_mails", 0)
            att_cnt = result.get("imported_attachments", 0)
            prof_cnt = result.get("imported_profiles", 0)

            msg = (
                f"🎉 Taşınabilir Disk Aktarımı Başarıyla Tamamlandı!\n\n"
                f"• Eklenen Yeni Hesap: {acc_cnt}\n"
                f"• Aktarılan E-posta: {mail_cnt:,}\n"
                f"• Aktarılan Ek Dosya: {att_cnt:,}\n"
                f"• Aktarılan Profiller: {prof_cnt}\n"
            )
            QMessageBox.information(self, "Aktarım Başarılı", msg)
            self.accept()
