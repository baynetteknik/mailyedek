"""
vhdx_job_dialog.py — Add / Edit Hyper-V & VHDX Backup Job Dialog with Standard Blue Banner.
High-contrast light theme, VM discovery, and Numeric Retention Stepper.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any

from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtGui import QColor, QPalette, QFont
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QGroupBox, QFileDialog,
    QMessageBox, QFormLayout, QFrame, QSpinBox
)

from core.mail_engine import MailEngine
from gui.widgets.numeric_stepper import NumericStepperWidget


class VhdxJobDialog(QDialog):
    """Modern modal dialog for configuring Hyper-V and VHDX virtual disk backup jobs."""

    job_saved = Signal(dict)

    def __init__(
        self,
        engine: MailEngine,
        job_data: Optional[Dict[str, Any]] = None,
        parent=None
    ):
        super().__init__(parent)
        self.engine = engine
        self.job_data = job_data or {}
        self.is_edit = bool(job_data and job_data.get("id"))

        self.setWindowTitle("Hyper-V & VHDX Yedekleme Görevi Yapılandırması")
        self.setMinimumWidth(580)
        self.resize(600, 540)
        self._setup_theme()
        self._setup_ui()
        self._load_initial_data()

    def _setup_theme(self):
        # Explicit Light Palette to protect against OS Dark Theme inheritance
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor("#f8fafc"))
        pal.setColor(QPalette.WindowText, QColor("#0f172a"))
        pal.setColor(QPalette.Base, QColor("#ffffff"))
        pal.setColor(QPalette.AlternateBase, QColor("#f1f5f9"))
        pal.setColor(QPalette.Text, QColor("#0f172a"))
        pal.setColor(QPalette.Button, QColor("#ffffff"))
        pal.setColor(QPalette.ButtonText, QColor("#0f172a"))
        self.setPalette(pal)
        self.setAutoFillBackground(True)

        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
                color: #0f172a;
            }
            QWidget {
                color: #0f172a;
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }
            QLabel {
                color: #0f172a;
                font-size: 12px;
                font-weight: 500;
                background: transparent;
            }
            QLineEdit, QComboBox, QSpinBox {
                background-color: #ffffff !important;
                color: #0f172a !important;
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                min-height: 22px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border-color: #2563eb !important;
                background-color: #ffffff !important;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #0f172a;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
                border: 1px solid #cbd5e1;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 12px;
                color: #1e40af;
                background-color: #ffffff;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 10px;
                padding: 16px 12px 12px 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                color: #1e40af;
                background-color: #ffffff;
            }
            QCheckBox {
                color: #0f172a;
                font-weight: 500;
                font-size: 12px;
                background: transparent;
            }
        """)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(12)

        # -------------------------------------------------------------
        # 1. Standard Royal Blue Header Banner with White Text
        # -------------------------------------------------------------
        header_banner = QFrame()
        header_banner.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1e40af, stop:1 #2563eb);
                border-radius: 8px;
                border: none;
            }
        """)
        h_layout = QHBoxLayout(header_banner)
        h_layout.setContentsMargins(14, 12, 14, 12)
        h_layout.setSpacing(12)

        lbl_icon = QLabel("💾")
        lbl_icon.setStyleSheet("font-size: 28px; background: transparent; color: #ffffff;")
        h_layout.addWidget(lbl_icon)

        v_text = QVBoxLayout()
        v_text.setSpacing(3)
        lbl_title = QLabel("Hyper-V & VHDX Sanal Disk Görevi")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff; background: transparent;")
        lbl_sub = QLabel("Canlı sanal makineler (VSS) veya bağımsız .vhdx/.vhd disk dosyası yedekleme")
        lbl_sub.setStyleSheet("font-size: 11.5px; color: #dbeafe; background: transparent;")
        v_text.addWidget(lbl_title)
        v_text.addWidget(lbl_sub)
        h_layout.addLayout(v_text, stretch=1)
        main_layout.addWidget(header_banner)

        # -------------------------------------------------------------
        # 2. Form Groups
        # -------------------------------------------------------------
        # Source Box
        source_box = QGroupBox("Kaynak Sanal Disk & Mod")
        form_src = QFormLayout(source_box)
        form_src.setSpacing(8)
        form_src.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("Örn: HyperV_DC_Sunucu_Yedek")
        form_src.addRow("Görev Tanımı *:", self.txt_name)

        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Doğrudan VHD / VHDX Disk Dosyası", "Canlı Hyper-V Sanal Makine (Live VM)"])
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        form_src.addRow("Yedekleme Modu:", self.combo_mode)

        # File source row
        self.file_container = QWidget()
        self.file_container.setStyleSheet("background: transparent; border: none;")
        file_layout = QHBoxLayout(self.file_container)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(4)
        self.txt_source = QLineEdit()
        self.txt_source.setPlaceholderText("C:\\Hyper-V\\Virtual Hard Disks\\Disk.vhdx")
        btn_browse_src = QPushButton("📁 Gözat")
        btn_browse_src.setStyleSheet("background-color: #f1f5f9; color: #0f172a; font-size: 11px; padding: 6px 12px; border: 1px solid #cbd5e1; border-radius: 4px;")
        btn_browse_src.clicked.connect(self._browse_source_file)
        file_layout.addWidget(self.txt_source, 1)
        file_layout.addWidget(btn_browse_src, 0)
        form_src.addRow("Kaynak Disk Dosyası *:", self.file_container)

        # VM selector container
        self.vm_container = QWidget()
        self.vm_container.setStyleSheet("background: transparent; border: none;")
        vm_layout = QHBoxLayout(self.vm_container)
        vm_layout.setContentsMargins(0, 0, 0, 0)
        vm_layout.setSpacing(4)
        self.combo_vm = QComboBox()
        self.combo_vm.setEditable(True)
        self.combo_vm.lineEdit().setPlaceholderText("Sanal Makine Adı")
        btn_scan_vm = QPushButton("🔍 VM Tara")
        btn_scan_vm.setStyleSheet("background-color: #0284c7; color: white; font-weight: 600; font-size: 11px; padding: 6px 12px; border-radius: 4px;")
        btn_scan_vm.clicked.connect(self._scan_vms)
        vm_layout.addWidget(self.combo_vm, 1)
        vm_layout.addWidget(btn_scan_vm, 0)
        form_src.addRow("Hyper-V VM Seçimi:", self.vm_container)
        self.vm_container.setVisible(False)

        self.combo_compress = QComboBox()
        self.combo_compress.addItems(["Ham İmaj (Raw 1:1 Boyut)", "Sıkıştırılmış (.gz Arşivi)", "Dinamik Boyut (Sparse)"])
        form_src.addRow("Sıkıştırma Modu:", self.combo_compress)

        main_layout.addWidget(source_box)

        # Target Box
        dest_box = QGroupBox("Hedef Konum & Saklama Politikası")
        form_dest = QFormLayout(dest_box)
        form_dest.setSpacing(8)
        form_dest.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        dest_row = QHBoxLayout()
        dest_row.setSpacing(4)
        self.txt_dest = QLineEdit("data/backups/vhdx")
        btn_browse_dest = QPushButton("📁 Gözat")
        btn_browse_dest.setStyleSheet("background-color: #f1f5f9; color: #0f172a; font-size: 11px; padding: 4px 10px; border: 1px solid #cbd5e1; border-radius: 4px;")
        btn_browse_dest.clicked.connect(self._browse_destination)
        dest_row.addWidget(self.txt_dest, 1)
        dest_row.addWidget(btn_browse_dest, 0)
        form_dest.addRow("Hedef Klasör *:", dest_row)

        # Retention Stepper [-] [ 10 ] [+] adet
        ret_row = QHBoxLayout()
        ret_row.setSpacing(6)
        self.stepper_retention = NumericStepperWidget(value=10, minimum=1, maximum=999, suffix="adet", parent=self)
        ret_row.addWidget(self.stepper_retention)
        ret_row.addStretch()
        form_dest.addRow("Saklama Politikası:", ret_row)

        opt_row = QHBoxLayout()
        opt_row.setSpacing(12)
        self.chk_vss = QCheckBox("Canlı VSS Gölgesi (Shadow Copy)")
        self.chk_vss.setChecked(True)
        self.chk_hash = QCheckBox("SHA-256 Sağlama")
        self.chk_hash.setChecked(True)
        opt_row.addWidget(self.chk_vss)
        opt_row.addWidget(self.chk_hash)
        opt_row.addStretch()
        form_dest.addRow("Seçenekler:", opt_row)

        main_layout.addWidget(dest_box)

        # Status
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("font-size: 11px; font-weight: 600; color: #2563eb;")
        main_layout.addWidget(self.lbl_status)

        # -------------------------------------------------------------
        # 3. Bottom Action Buttons
        # -------------------------------------------------------------
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        btn_cancel = QPushButton("İptal")
        btn_cancel.setStyleSheet("background-color: #ffffff; color: #334155; font-size: 12px; font-weight: 600; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 16px; min-width: 80px;")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        self.btn_save = QPushButton("💾 Görevi Kaydet")
        self.btn_save.setStyleSheet("background-color: #2563eb; color: #ffffff; font-size: 12px; font-weight: bold; border: none; border-radius: 6px; padding: 6px 20px; min-width: 110px;")
        self.btn_save.clicked.connect(self._save_job)
        btn_box.addWidget(self.btn_save)

        main_layout.addLayout(btn_box)

    def _load_initial_data(self):
        if not self.job_data:
            return
        self.txt_name.setText(self.job_data.get("name", ""))
        self.txt_source.setText(self.job_data.get("source_path", ""))
        self.txt_dest.setText(self.job_data.get("dest_dir", "data/backups/vhdx"))
        self.chk_vss.setChecked(self.job_data.get("use_vss", True))
        self.chk_hash.setChecked(self.job_data.get("verify_hash", True))
        self.stepper_retention.setValue(self.job_data.get("retention_value", 10))

    def _on_mode_changed(self, idx: int):
        is_vm = (idx == 1)
        self.vm_container.setVisible(is_vm)
        self.file_container.setVisible(not is_vm)

    def _browse_source_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Kaynak VHD / VHDX Dosyasını Seç",
            "",
            "VHD Dosyaları (*.vhdx *.vhd *.vhds);;Tüm Dosyalar (*.*)"
        )
        if path:
            self.txt_source.setText(path)

    def _browse_destination(self):
        folder = QFileDialog.getExistingDirectory(self, "Yedekleme Hedef Klasörünü Seç", self.txt_dest.text())
        if folder:
            self.txt_dest.setText(folder)

    @Slot()
    def _scan_vms(self):
        self.lbl_status.setText("🔍 Hyper-V Sanal Makineleri taranıyor...")
        self.lbl_status.setStyleSheet("color: #0284c7; font-weight: bold;")
        try:
            if hasattr(self.engine, "vhdx_backup_usecase"):
                vms = self.engine.vhdx_backup_usecase.list_hyperv_vms()
                self.combo_vm.clear()
                for v in vms:
                    self.combo_vm.addItem(v.get("name", ""), v)
                self.lbl_status.setText(f"✅ {len(vms)} adet Sanal Makine tespit edildi.")
                self.lbl_status.setStyleSheet("color: #16a34a; font-weight: bold;")
            else:
                self.lbl_status.setText("ℹ️ Hyper-V servis modülü hazır.")
        except Exception as e:
            self.lbl_status.setText(f"❌ VM tarama hatası: {e}")
            self.lbl_status.setStyleSheet("color: #dc2626; font-weight: bold;")

    @Slot()
    def _save_job(self):
        name = self.txt_name.text().strip()
        if not name:
            name = "VHDX_Backup"

        mode = "vm" if self.combo_mode.currentIndex() == 1 else "file"
        src_path = self.combo_vm.currentText().strip() if mode == "vm" else self.txt_source.text().strip()

        data = dict(self.job_data)
        data.update({
            "name": name,
            "mode": mode,
            "source_path": src_path,
            "compress_mode": "raw" if self.combo_compress.currentIndex() == 0 else "gzip",
            "dest_dir": self.txt_dest.text().strip() or "data/backups/vhdx",
            "use_vss": self.chk_vss.isChecked(),
            "verify_hash": self.chk_hash.isChecked(),
            "retention_mode": "count",
            "retention_value": self.stepper_retention.value()
        })

        try:
            if hasattr(self.engine, "vhdx_backup_usecase"):
                self.engine.vhdx_backup_usecase.save_job(data)
            self.job_saved.emit(data)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"VHDX görevi kaydedilemedi: {e}")
