"""
restore_right_sidebar_widget.py — Action Drawer / Sidebar for Restore Center.
Equipped with View Profiles, 88px Row Height Controls, IMAP Push & Translation Options,
Multi-Cloud Account Triggers, and Live Console Controls.
"""

import logging
from typing import Optional, Dict, Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QInputDialog, QMessageBox,
    QComboBox, QCheckBox
)

from gui.widgets.view_profile_widget import ViewProfileWidget
from gui.widgets.account_group_sidebar_widget import CollapsibleSection

logger = logging.getLogger(__name__)


class RestoreRightSidebarWidget(QWidget):
    """Right Action Sidebar for Restore Center."""

    # Signals
    restore_selected_requested = Signal()
    dry_run_requested = Signal()
    cancel_requested = Signal()

    add_s3_account_requested = Signal()
    add_gdrive_account_requested = Signal()
    scan_cloud_requested = Signal()
    pick_local_file_requested = Signal()

    folder_lang_changed = Signal(str)
    target_imap_changed = Signal(bool)

    export_excel_requested = Signal()
    toggle_log_requested = Signal()

    row_height_changed = Signal(int)

    # View profiles
    profile_selected = Signal(str, dict)
    save_profile_requested = Signal(str)
    columns_requested = Signal()
    filter_row_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scroll area for responsive fit
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: #f1f5f9;
                width: 6px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #cbd5e1;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #94a3b8;
            }
        """)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        lyt = QVBoxLayout(container)
        lyt.setContentsMargins(4, 0, 4, 10)
        lyt.setSpacing(8)

        # -------------------------------------------------------------
        # Section 1: ⚙️ GÖRÜNÜM & DÜZEN (Accordion)
        # -------------------------------------------------------------
        self.sec_layout = CollapsibleSection("⚙️ GÖRÜNÜM & DÜZEN", parent=self, is_collapsed=True)

        self.view_profile_widget = ViewProfileWidget(
            profile_key="restore_panel_grid",
            title="GÖRÜNÜM PROFİLLERİ",
            parent=self
        )
        self.view_profile_widget.profile_selected.connect(self.profile_selected.emit)
        self.view_profile_widget.save_requested.connect(self.save_profile_requested.emit)
        self.view_profile_widget.columns_requested.connect(self.columns_requested.emit)
        self.view_profile_widget.filter_row_toggled.connect(self.filter_row_toggled.emit)
        self.sec_layout.content_layout.addWidget(self.view_profile_widget)

        # Row Height Presets
        grp_height = QFrame()
        grp_height.setStyleSheet("QFrame { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 4px; }")
        lyt_height = QVBoxLayout(grp_height)
        lyt_height.setContentsMargins(6, 4, 6, 4)
        lyt_height.setSpacing(4)

        lbl_h = QLabel("📏 Satır Yüksekliği (Grid Boyutu):")
        lbl_h.setStyleSheet("color: #334155; font-weight: 600; font-size: 10.5px;")
        lyt_height.addWidget(lbl_h)

        h_btn_row = QHBoxLayout()
        h_btn_row.setSpacing(4)

        self.btn_h_compact = QPushButton("40px")
        self.btn_h_compact.setStyleSheet(self._pill_btn_style())
        self.btn_h_compact.clicked.connect(lambda: self.row_height_changed.emit(40))
        h_btn_row.addWidget(self.btn_h_compact)

        self.btn_h_normal = QPushButton("60px")
        self.btn_h_normal.setStyleSheet(self._pill_btn_style())
        self.btn_h_normal.clicked.connect(lambda: self.row_height_changed.emit(60))
        h_btn_row.addWidget(self.btn_h_normal)

        self.btn_h_std = QPushButton("88px")
        self.btn_h_std.setToolTip("Standart rahat görünüm (Varsayılan)")
        self.btn_h_std.setStyleSheet(self._pill_btn_style(active=True))
        self.btn_h_std.clicked.connect(lambda: self.row_height_changed.emit(88))
        h_btn_row.addWidget(self.btn_h_std)

        self.btn_h_large = QPushButton("110px")
        self.btn_h_large.setStyleSheet(self._pill_btn_style())
        self.btn_h_large.clicked.connect(lambda: self.row_height_changed.emit(110))
        h_btn_row.addWidget(self.btn_h_large)

        self.btn_h_custom = QPushButton("Özel...")
        self.btn_h_custom.setStyleSheet(self._pill_btn_style())
        self.btn_h_custom.clicked.connect(self._prompt_custom_row_height)
        h_btn_row.addWidget(self.btn_h_custom)

        lyt_height.addLayout(h_btn_row)
        self.sec_layout.content_layout.addWidget(grp_height)
        lyt.addWidget(self.sec_layout)

        # -------------------------------------------------------------
        # Section 2: 📥 GERİ YÜKLEME İŞLEMLERİ (Accordion)
        # -------------------------------------------------------------
        self.sec_actions = CollapsibleSection("📥 GERİ YÜKLEME İŞLEMLERİ", parent=self, is_collapsed=False)

        self.btn_restore_sel = QPushButton("📥 Seçilenleri Geri Yükle")
        self.btn_restore_sel.setCursor(Qt.PointingHandCursor)
        self.btn_restore_sel.setStyleSheet(self._action_btn_style("#16a34a"))
        self.btn_restore_sel.clicked.connect(self.restore_selected_requested.emit)
        self.sec_actions.content_layout.addWidget(self.btn_restore_sel)

        self.btn_dry_run = QPushButton("🔍 Önizleme (Dry Run)")
        self.btn_dry_run.setCursor(Qt.PointingHandCursor)
        self.btn_dry_run.setStyleSheet(self._action_btn_style("#0284c7"))
        self.btn_dry_run.clicked.connect(self.dry_run_requested.emit)
        self.sec_actions.content_layout.addWidget(self.btn_dry_run)

        self.btn_cancel = QPushButton("⏹️ İptal Et")
        self.btn_cancel.setStyleSheet(self._action_btn_style("#dc2626", height=28, font_size=11))
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)
        self.sec_actions.content_layout.addWidget(self.btn_cancel)

        lyt.addWidget(self.sec_actions)

        # -------------------------------------------------------------
        # Section 3: ⚙️ GERİ YÜKLEME SEÇENEKLERİ
        # -------------------------------------------------------------
        self.sec_options = CollapsibleSection("⚙️ GERİ YÜKLEME SEÇENEKLERİ", parent=self, is_collapsed=False)

        opt_box = QFrame()
        opt_box.setStyleSheet("QFrame { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 6px; }")
        opt_layout = QVBoxLayout(opt_box)
        opt_layout.setContentsMargins(6, 6, 6, 6)
        opt_layout.setSpacing(6)

        self.chk_target_imap = QCheckBox("E-Postaları IMAP Sunucusuna Geri Aktar")
        self.chk_target_imap.setStyleSheet("font-weight: 600; font-size: 11px; color: #0f172a;")
        self.chk_target_imap.setChecked(False)
        self.chk_target_imap.toggled.connect(self.target_imap_changed.emit)
        opt_layout.addWidget(self.chk_target_imap)

        lbl_lang = QLabel("Klasör Adı Dönüşümü:")
        lbl_lang.setStyleSheet("color: #334155; font-weight: 600; font-size: 11px;")
        opt_layout.addWidget(lbl_lang)

        self.combo_folder_lang = QComboBox()
        self.combo_folder_lang.addItem("Orijinal Dilinde Bırak", "original")
        self.combo_folder_lang.addItem("Türkçeleştir (TR)", "tr")
        self.combo_folder_lang.addItem("İngilizceye Çevir (EN)", "en")
        self.combo_folder_lang.setStyleSheet("""
            QComboBox {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 4px 8px;
                font-size: 11px;
                color: #0f172a;
            }
        """)
        self.combo_folder_lang.currentIndexChanged.connect(
            lambda: self.folder_lang_changed.emit(self.combo_folder_lang.currentData() or "original")
        )
        opt_layout.addWidget(self.combo_folder_lang)

        self.sec_options.content_layout.addWidget(opt_box)
        lyt.addWidget(self.sec_options)

        # -------------------------------------------------------------
        # Section 4: ☁️ BULUT & YEREL KAYNAK YÖNETİMİ
        # -------------------------------------------------------------
        self.sec_sources = CollapsibleSection("☁️ BULUT & YEREL KAYNAKLAR", parent=self, is_collapsed=False)

        self.btn_add_s3 = QPushButton("☁️ Amazon S3 Hesabı Ekle")
        self.btn_add_s3.setStyleSheet(self._action_btn_style("#0284c7", height=28, font_size=11))
        self.btn_add_s3.clicked.connect(self.add_s3_account_requested.emit)
        self.sec_sources.content_layout.addWidget(self.btn_add_s3)

        self.btn_add_gd = QPushButton("📁 Google Drive Hesabı Ekle")
        self.btn_add_gd.setStyleSheet(self._action_btn_style("#059669", height=28, font_size=11))
        self.btn_add_gd.clicked.connect(self.add_gdrive_account_requested.emit)
        self.sec_sources.content_layout.addWidget(self.btn_add_gd)

        self.btn_pick_local = QPushButton("📂 Yerel Yedek Dosyası Seç (.tar.gz / .bak / .vhdx)")
        self.btn_pick_local.setStyleSheet(self._action_btn_style("#475569", height=28, font_size=11))
        self.btn_pick_local.clicked.connect(self.pick_local_file_requested.emit)
        self.sec_sources.content_layout.addWidget(self.btn_pick_local)

        self.btn_scan_cloud = QPushButton("🔄 Bulut Yedeklerini Yeniden Tara")
        self.btn_scan_cloud.setStyleSheet(self._action_btn_style("#4f46e5", height=28, font_size=11))
        self.btn_scan_cloud.clicked.connect(self.scan_cloud_requested.emit)
        self.sec_sources.content_layout.addWidget(self.btn_scan_cloud)

        lyt.addWidget(self.sec_sources)

        # -------------------------------------------------------------
        # Section 5: 📊 RAPORLAR & KONSOL
        # -------------------------------------------------------------
        self.sec_reports = CollapsibleSection("📊 RAPORLAR & KONSOL", parent=self, is_collapsed=True)

        self.btn_excel = QPushButton("📊 Excel Raporu İndir")
        self.btn_excel.setStyleSheet(self._action_btn_style("#0d9488", height=30, font_size=11))
        self.btn_excel.clicked.connect(self.export_excel_requested.emit)
        self.sec_reports.content_layout.addWidget(self.btn_excel)

        self.btn_log = QPushButton("👁️ Canlı Günlüğü Aç / Kapat")
        self.btn_log.setStyleSheet(self._action_btn_style("#334155", height=30, font_size=11))
        self.btn_log.clicked.connect(self.toggle_log_requested.emit)
        self.sec_reports.content_layout.addWidget(self.btn_log)

        lyt.addWidget(self.sec_reports)

        lyt.addStretch()
        self.scroll_area.setWidget(container)
        main_layout.addWidget(self.scroll_area)

    # ------------------------------------------------------------------
    # Handlers & Styles
    # ------------------------------------------------------------------

    def _prompt_custom_row_height(self):
        val, ok = QInputDialog.getInt(
            self, "Özel Satır Yüksekliği",
            "Piksel cinsinden satır yüksekliği girin (30 - 200 px):",
            value=88, min=30, max=200, step=2
        )
        if ok:
            self.row_height_changed.emit(val)

    def _pill_btn_style(self, active: bool = False) -> str:
        bg = "#2563eb" if active else "#ffffff"
        color = "#ffffff" if active else "#334155"
        border = "#1d4ed8" if active else "#cbd5e1"
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {color};
                font-weight: 600;
                font-size: 10px;
                border: 1px solid {border};
                border-radius: 4px;
                padding: 3px 6px;
                min-height: 20px;
            }}
            QPushButton:hover {{
                background-color: {"#1d4ed8" if active else "#f1f5f9"};
                border-color: #94a3b8;
            }}
        """

    def _action_btn_style(self, bg_color: str, height: int = 34, font_size: int = 12) -> str:
        return f"""
            QPushButton {{
                background-color: {bg_color};
                color: #ffffff;
                font-weight: bold;
                font-size: {font_size}px;
                border: none;
                border-radius: 6px;
                padding: 4px 10px;
                min-height: {height}px;
            }}
            QPushButton:hover {{
                opacity: 0.9;
                background-color: {bg_color};
            }}
            QPushButton:pressed {{
                opacity: 0.8;
            }}
            QPushButton:disabled {{
                background-color: #cbd5e1;
                color: #94a3b8;
            }}
        """
