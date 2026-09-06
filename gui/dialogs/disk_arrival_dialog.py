"""
disk_arrival_dialog.py — Smart Disk / USB Insertion Analysis & Rapid Backup Dialog.
"""

import os
import subprocess
import logging
from typing import Dict, Any, List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QProgressBar, QMessageBox,
    QGroupBox,
)

from core.mail_engine import MailEngine
from core.settings import AppSettings
from infrastructure.disk_identifier import (
    inspect_drive_recognition,
    stamp_disk_signature,
    get_disk_signature,
)

logger = logging.getLogger(__name__)


class DiskBackupWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, engine: MailEngine, drive_path: str, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.drive_path = drive_path

    def run(self):
        try:
            # Look for jobs configured with auto_on_usb_connect or targeting this drive
            sql_jobs = self.engine.list_sql_jobs()
            vhdx_jobs = self.engine.list_vhdx_jobs()

            executed_count = 0
            errs = []

            # Match SQL jobs
            for j in sql_jobs:
                target = (j.get("target_directory") or "").upper()
                drive_p = self.drive_path.upper().rstrip("\\")
                if j.get("auto_on_usb_connect") or target.startswith(drive_p):
                    self.progress_signal.emit(f"SQL Yedekleme Başlatılıyor: {j.get('job_name')}...")
                    try:
                        res = self.engine.run_sql_backup(j["id"])
                        if res.get("status") == "COMPLETED":
                            executed_count += 1
                        else:
                            errs.append(f"{j.get('job_name')}: {res.get('error_message', 'Bilinmeyen hata')}")
                    except Exception as e:
                        errs.append(f"{j.get('job_name')}: {str(e)}")

            # Match VHDX jobs
            for j in vhdx_jobs:
                target = (j.get("target_directory") or "").upper()
                drive_p = self.drive_path.upper().rstrip("\\")
                if j.get("auto_on_usb_connect") or target.startswith(drive_p):
                    self.progress_signal.emit(f"VHDX Yedekleme Başlatılıyor: {j.get('job_name')}...")
                    try:
                        res = self.engine.run_vhdx_backup(j["id"])
                        if res.get("status") == "COMPLETED":
                            executed_count += 1
                        else:
                            errs.append(f"{j.get('job_name')}: {res.get('error_message', 'Bilinmeyen hata')}")
                    except Exception as e:
                        errs.append(f"{j.get('job_name')}: {str(e)}")

            if executed_count > 0 and not errs:
                self.finished_signal.emit(True, f"{executed_count} adet otomatik yedekleme başarıyla tamamlandı!")
            elif executed_count > 0 and errs:
                self.finished_signal.emit(True, f"{executed_count} yedek tamamlandı. Hatalar: {'; '.join(errs)}")
            elif errs:
                self.finished_signal.emit(False, f"Yedekleme hataları: {'; '.join(errs)}")
            else:
                self.finished_signal.emit(True, "Bu disk için tanımlı otomatik tetiklenen yedekleme görevi bulunamadı.")
        except Exception as exc:
            self.finished_signal.emit(False, f"İşlem sırasında hata: {exc}")


class DiskScanWorker(QThread):
    progress_signal = Signal(int, str)  # count, message
    item_found_signal = Signal(dict)   # backup item
    finished_signal = Signal(list, dict)  # all_items, summary_stats

    def __init__(self, engine: MailEngine, drive_path: str, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.drive_path = drive_path
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        found_items = []
        try:
            def on_progress(count, msg, item):
                if self._is_cancelled:
                    return
                self.progress_signal.emit(count, msg)
                if item:
                    found_items.append(item)
                    self.item_found_signal.emit(item)

            scan = self.engine.scan_drive_backups(self.drive_path, progress_callback=on_progress)
            all_backups = scan.get("all_backups", found_items)
            sql_cnt = len([i for i in all_backups if "SQL" in i.get("type", "")])
            vhdx_cnt = len([i for i in all_backups if "VHDX" in i.get("type", "") or "Hyper-V" in i.get("type", "")])
            mail_cnt = len([i for i in all_backups if "Mail" in i.get("type", "") or "E-Posta" in i.get("type", "")])
            stats = {
                "total": len(all_backups),
                "sql": sql_cnt,
                "vhdx": vhdx_cnt,
                "mail": mail_cnt,
            }
            self.finished_signal.emit(all_backups, stats)
        except Exception as e:
            logger.error("DiskScanWorker error: %s", e)
            self.finished_signal.emit(found_items, {"total": len(found_items), "sql": 0, "vhdx": 0, "mail": 0})


class DiskArrivalDialog(QDialog):
    """Smart notification dialog displayed automatically when a USB / External drive is attached."""

    def __init__(
        self,
        engine: MailEngine,
        drive_info: Dict[str, Any],
        parent=None,
        settings: Optional[AppSettings] = None,
    ):
        super().__init__(parent)
        self.engine = engine
        self.drive_info = drive_info
        self.settings = settings or getattr(parent, "settings", None) or AppSettings()
        self._worker: Optional[DiskBackupWorker] = None
        self._scan_worker: Optional[DiskScanWorker] = None

        self.setWindowTitle(f"💾 Yeni Disk Algılandı — {drive_info.get('path', '')}")
        self.resize(780, 560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._setup_ui()
        self._load_disk_data()

    def _setup_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            QFrame#banner {
                background-color: #1e3a8a;
                border: 1px solid #1e40af;
                border-radius: 8px;
                padding: 12px 16px;
            }
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                gridline-color: #e2e8f0;
                color: #0f172a;
            }
            QHeaderView::section {
                background-color: #2563eb;
                padding: 6px;
                font-weight: 700;
                color: #ffffff;
                border: 1px solid #1d4ed8;
            }
            QPushButton#primaryBtn {
                background-color: #059669;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 9px 18px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#primaryBtn:hover {
                background-color: #047857;
            }
            QPushButton#stampBtn {
                background-color: #2563eb;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#stampBtn:hover {
                background-color: #1d4ed8;
            }
            QPushButton#secondaryBtn {
                background-color: #ffffff;
                color: #334155;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton#secondaryBtn:hover {
                background-color: #f1f5f9;
                color: #0f172a;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # Header Banner
        banner = QFrame()
        banner.setObjectName("banner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(12, 8, 12, 8)

        icon_lbl = QLabel("🔌")
        icon_lbl.setStyleSheet("font-size: 32px; background: transparent;")
        banner_layout.addWidget(icon_lbl)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        title_lbl = QLabel("Yedekleme Sürücüsü Algılandı")
        title_lbl.setStyleSheet("color: #ffffff !important; font-size: 16px; font-weight: 700; background: transparent;")
        info_layout.addWidget(title_lbl)

        sub_lbl = QLabel("Sistem harici sürücüyü başarıyla tespit etti. Diskin kimlik durumu ve mevcut yedekleri aşağıda özetlenmiştir.")
        sub_lbl.setStyleSheet("color: #e2e8f0 !important; font-size: 11.5px; background: transparent;")
        info_layout.addWidget(sub_lbl)
        banner_layout.addLayout(info_layout)
        banner_layout.addStretch()

        layout.addWidget(banner)

        # Drive Recognition & Signature Status Box
        recog_box = QFrame()
        recog_box.setStyleSheet("background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px;")
        recog_layout = QHBoxLayout(recog_box)
        recog_layout.setContentsMargins(10, 6, 10, 6)

        self.lbl_recog_badge = QLabel("Tanımlama durumu yükleniyor...")
        self.lbl_recog_badge.setStyleSheet("font-size: 12px; font-weight: bold; color: #0f172a; background: transparent;")
        recog_layout.addWidget(self.lbl_recog_badge)
        recog_layout.addStretch()

        self.btn_stamp_disk = QPushButton("🏷️ Bu Diski Resmi Yedek Diski Olarak İmzala / Tanıt")
        self.btn_stamp_disk.setObjectName("stampBtn")
        self.btn_stamp_disk.setCursor(Qt.PointingHandCursor)
        self.btn_stamp_disk.clicked.connect(self._on_stamp_disk_clicked)
        recog_layout.addWidget(self.btn_stamp_disk)

        self.btn_set_primary = QPushButton("🔗 Ana Veri Deposu Olarak Bağla")
        self.btn_set_primary.setObjectName("stampBtn")
        self.btn_set_primary.setCursor(Qt.PointingHandCursor)
        self.btn_set_primary.setStyleSheet("background-color: #0d9488; color: white;")
        self.btn_set_primary.clicked.connect(self._on_set_primary_clicked)
        recog_layout.addWidget(self.btn_set_primary)

        layout.addWidget(recog_box)

        # Drive Stats Box
        stats_group = QGroupBox("Sürücü Özellikleri ve Kapasite Durumu")
        stats_group.setStyleSheet("QGroupBox { font-weight: 600; color: #1e293b; }")
        stats_layout = QVBoxLayout(stats_group)
        stats_layout.setSpacing(8)

        meta_layout = QHBoxLayout()
        path = self.drive_info.get("path", "")
        label = self.drive_info.get("label", "İsimsiz")
        drive_type = self.drive_info.get("type", "Bilinmeyen")
        total_gb = self.drive_info.get("total_gb", 0)
        free_gb = self.drive_info.get("free_gb", 0)
        used_gb = max(0.0, total_gb - free_gb)
        used_pct = int((used_gb / total_gb * 100)) if total_gb > 0 else 0

        lbl_drive_meta = QLabel(f"<b>Sürücü:</b> {path} ({label}) &nbsp;|&nbsp; <b>Tür:</b> {drive_type} &nbsp;|&nbsp; <b>Boş Alan:</b> {free_gb:.1f} GB / {total_gb:.1f} GB")
        lbl_drive_meta.setStyleSheet("font-size: 12px; color: #334155;")
        meta_layout.addWidget(lbl_drive_meta)
        meta_layout.addStretch()
        stats_layout.addLayout(meta_layout)

        # Progress bar for disk usage
        self.disk_bar = QProgressBar()
        self.disk_bar.setValue(used_pct)
        self.disk_bar.setFormat(f"Kullanım: %p% (Dolu: {used_gb:.1f} GB / Boş: {free_gb:.1f} GB)")
        self.disk_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                text-align: center;
                height: 18px;
                font-size: 11px;
                font-weight: 600;
                color: #0f172a;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #2563eb);
                border-radius: 3px;
            }
        """)
        stats_layout.addWidget(self.disk_bar)
        layout.addWidget(stats_group)

        # Backups Table
        table_group = QGroupBox("Diskte Bulunan Mevcut Yedek Dosyaları")
        table_group.setStyleSheet("QGroupBox { font-weight: 600; color: #1e293b; }")
        table_layout = QVBoxLayout(table_group)
        table_layout.setSpacing(6)

        self.table_backups = QTableWidget(0, 5)
        self.table_backups.setHorizontalHeaderLabels(["Tür", "Dosya Adı", "Boyut", "Değiştirilme Tarihi", "Konum"])
        self.table_backups.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_backups.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_backups.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_backups.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_backups.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_backups.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_backups.setEditTriggers(QTableWidget.NoEditTriggers)
        table_layout.addWidget(self.table_backups)

        self.lbl_scan_status = QLabel("Yedekler taranıyor...")
        self.lbl_scan_status.setStyleSheet("font-size: 11px; color: #64748b; font-style: italic;")
        table_layout.addWidget(self.lbl_scan_status)
        layout.addWidget(table_group)

        # Action Progress Status
        self.lbl_action_status = QLabel("")
        self.lbl_action_status.setStyleSheet("font-size: 12px; font-weight: 600; color: #2563eb;")
        self.lbl_action_status.setVisible(False)
        layout.addWidget(self.lbl_action_status)

        # Buttons
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        self.btn_open_explorer = QPushButton("📁 Klasörü Gezginde Aç")
        self.btn_open_explorer.setObjectName("secondaryBtn")
        self.btn_open_explorer.setCursor(Qt.PointingHandCursor)
        self.btn_open_explorer.clicked.connect(self._open_explorer)
        btn_bar.addWidget(self.btn_open_explorer)

        btn_bar.addStretch()

        self.btn_start_backup = QPushButton("🚀 Yedeklemeyi Bu Diske Başlat")
        self.btn_start_backup.setObjectName("primaryBtn")
        self.btn_start_backup.setCursor(Qt.PointingHandCursor)
        self.btn_start_backup.clicked.connect(self._start_backup_job)
        btn_bar.addWidget(self.btn_start_backup)

        self.btn_close = QPushButton("Kapat")
        self.btn_close.setObjectName("secondaryBtn")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.accept)
        btn_bar.addWidget(self.btn_close)

        layout.addLayout(btn_bar)

    def _load_disk_data(self):
        drive_path = self.drive_info.get("path", "")
        if not drive_path:
            return

        # 1. Inspect signature & recognition
        reg_sig = self.settings.data_disk_signature() if self.settings else None
        configured_path = str(self.settings.data_path()) if self.settings else None
        recog = inspect_drive_recognition(drive_path, reg_sig, configured_path)

        if recog.get("is_recognized"):
            lbl = recog.get("label", "Resmi Yedekleme Diski")
            self.lbl_recog_badge.setText(f"✅ <span style='color: #059669;'>Kayıtlı Resmi Yedek Diski: <b>{lbl}</b></span>")
            self.btn_stamp_disk.setVisible(False)
        else:
            self.lbl_recog_badge.setText("⚠️ <span style='color: #d97706;'>Tanımsız / İmzasız Harici Sürücü</span>")
            self.btn_stamp_disk.setVisible(True)

        # Check if already primary storage
        current_data_path = str(self.settings.data_path()).upper().rstrip("\\") if self.settings else ""
        if current_data_path == drive_path.upper().rstrip("\\"):
            self.btn_set_primary.setVisible(False)
        else:
            self.btn_set_primary.setVisible(True)

        # 2. Asynchronous scan of backups
        self.table_backups.setRowCount(0)
        self.lbl_scan_status.setText("⏳ Diskteki yedekler taranıyor... Lütfen bekleyin.")

        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.cancel()
            self._scan_worker.wait(500)

        self._scan_worker = DiskScanWorker(self.engine, drive_path, self)
        self._scan_worker.item_found_signal.connect(self._on_backup_item_found)
        self._scan_worker.progress_signal.connect(self._on_scan_progress)
        self._scan_worker.finished_signal.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_scan_progress(self, count: int, msg: str):
        self.lbl_scan_status.setText(f"⏳ {msg}")

    def _on_backup_item_found(self, item: Dict[str, Any]):
        row_idx = self.table_backups.rowCount()
        self.table_backups.insertRow(row_idx)

        b_type = item.get("type", "Bilinmeyen")
        name = item.get("name", "")
        size_mb = item.get("size_mb", 0)
        mtime = item.get("modified_at", "")
        folder = item.get("path", "")

        icon_map = {
            "SQL Veritabanı": "🗄️ SQL",
            "VHDX / Hyper-V Disk": "💿 VHDX",
            "E-Posta Arşivi": "📧 Mail",
            "Sıkıştırılmış Yedek": "📦 Sıkıştırılmış",
            "SQLite Veritabanı": "🗃️ SQLite",
        }
        type_text = icon_map.get(b_type, f"📦 {b_type}")
        size_text = f"{size_mb / 1024:.2f} GB" if size_mb >= 1024 else f"{size_mb:.1f} MB"

        item_type = QTableWidgetItem(type_text)
        item_name = QTableWidgetItem(name)
        item_size = QTableWidgetItem(size_text)
        item_mtime = QTableWidgetItem(mtime)
        item_folder = QTableWidgetItem(folder)

        self.table_backups.setItem(row_idx, 0, item_type)
        self.table_backups.setItem(row_idx, 1, item_name)
        self.table_backups.setItem(row_idx, 2, item_size)
        self.table_backups.setItem(row_idx, 3, item_mtime)
        self.table_backups.setItem(row_idx, 4, item_folder)

    def _on_scan_finished(self, all_backups: List[Dict[str, Any]], stats: Dict[str, Any]):
        total = stats.get("total", len(all_backups))
        sql = stats.get("sql", 0)
        vhdx = stats.get("vhdx", 0)
        mail = stats.get("mail", 0)
        self.lbl_scan_status.setText(
            f"✅ Tarama tamamlandı: Toplam {total} adet yedek bulundu ({sql} SQL, {vhdx} VHDX, {mail} Mail arşivi)."
        )

    def closeEvent(self, event):
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.cancel()
        super().closeEvent(event)

    def reject(self):
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.cancel()
        super().reject()

    def _on_stamp_disk_clicked(self):
        drive_path = self.drive_info.get("path", "")
        drive_label = self.drive_info.get("label", "Yedekleme Sürücüsü")
        reply = QMessageBox.question(
            self,
            "Diski Resmi Yedek Diski Olarak İmzala",
            f"Bu diski ({drive_path} - {drive_label}) sistemin otomatik tanıyacağı 'Resmi Yedekleme Diski' olarak imzalamak istiyor musunuz?\n\n"
            f"(Diske güvenli bir '.mail_yedek_disk_id' kimlik dosyası yazılacak ve sistem diski her takıldığında otomatik tanıyacaktır).",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                sig = stamp_disk_signature(Path(drive_path), label=f"Resmi Yedek Diski ({drive_label})")
                if self.settings:
                    self.settings.set_data_disk_signature(sig)
                QMessageBox.information(
                    self,
                    "Başarılı",
                    f"Disk başarıyla 'Resmi Yedekleme Diski' olarak imzalandı!\n\nKimlik ID: {sig['disk_id'][:8]}...",
                )
                self._load_disk_data()
            except Exception as exc:
                QMessageBox.critical(self, "Hata", f"Disk imzalanamadı: {exc}")

    def _on_set_primary_clicked(self):
        drive_path = self.drive_info.get("path", "")
        reply = QMessageBox.question(
            self,
            "Ana Veri Deposu Olarak Bağla",
            f"Bu sürücüyü ({drive_path}) aktif ana veri dizini (depolama alanı) olarak bağlamak istiyor musunuz?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                if self.settings:
                    self.settings.set_data_path(Path(drive_path))
                QMessageBox.information(
                    self,
                    "Bağlandı",
                    f"Ana veri dizini '{drive_path}' olarak güncellendi.",
                )
                self._load_disk_data()
            except Exception as exc:
                QMessageBox.critical(self, "Hata", f"Veri dizini güncellenemedi: {exc}")

        scan = self.engine.scan_drive_backups(drive_path)
        all_backups = scan.get("all_backups", [])

        self.table_backups.setRowCount(len(all_backups))
        for row_idx, item in enumerate(all_backups):
            b_type = item.get("type", "Bilinmeyen")
            name = item.get("name", "")
            size_mb = item.get("size_mb", 0)
            mtime = item.get("modified", "")
            folder = item.get("folder", "")

            icon_map = {
                "SQL Backup": "🗄️ SQL",
                "VHDX Disk": "💿 VHDX",
                "Mail Archive": "📧 Mail",
            }
            type_text = icon_map.get(b_type, f"📦 {b_type}")

            size_text = f"{size_mb / 1024:.2f} GB" if size_mb >= 1024 else f"{size_mb:.1f} MB"

            item_type = QTableWidgetItem(type_text)
            item_name = QTableWidgetItem(name)
            item_size = QTableWidgetItem(size_text)
            item_mtime = QTableWidgetItem(mtime)
            item_folder = QTableWidgetItem(folder)

            self.table_backups.setItem(row_idx, 0, item_type)
            self.table_backups.setItem(row_idx, 1, item_name)
            self.table_backups.setItem(row_idx, 2, item_size)
            self.table_backups.setItem(row_idx, 3, item_mtime)
            self.table_backups.setItem(row_idx, 4, item_folder)

        count_sql = len(scan.get("sql_backups", []))
        count_vhdx = len(scan.get("vhdx_backups", []))
        count_mail = len(scan.get("mail_backups", []))
        self.lbl_scan_status.setText(
            f"Toplam {len(all_backups)} adet yedek bulundu: {count_sql} SQL, {count_vhdx} VHDX, {count_mail} Mail arşivi."
        )

    def _open_explorer(self):
        path = self.drive_info.get("path", "")
        if path and os.path.exists(path):
            os.startfile(path)

    def _start_backup_job(self):
        drive_path = self.drive_info.get("path", "")
        self.btn_start_backup.setEnabled(False)
        self.lbl_action_status.setText("Yedekleme süreci başlatıldı, lütfen bekleyin...")
        self.lbl_action_status.setVisible(True)

        self._worker = DiskBackupWorker(self.engine, drive_path, self)
        self._worker.progress_signal.connect(self._on_worker_progress)
        self._worker.finished_signal.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_progress(self, msg: str):
        self.lbl_action_status.setText(msg)

    def _on_worker_finished(self, success: bool, message: str):
        self.btn_start_backup.setEnabled(True)
        if success:
            QMessageBox.information(self, "Yedekleme Tamamlandı", message)
            self._load_disk_data()
            self.lbl_action_status.setText("İşlem başarıyla tamamlandı.")
        else:
            QMessageBox.warning(self, "Yedekleme Hatası", message)
            self.lbl_action_status.setText("Hata oluştu.")
