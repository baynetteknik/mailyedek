"""
export_right_sidebar_widget.py — Modular Right Action Sidebar for Email Export & Server Migration,
View Profiles, Row Height Adjustments, Target Format Settings, and Flow Control.
Equipped with collapsible accordion sections (initially collapsed by default) and high-contrast UI.
"""

import logging
from typing import Optional, Dict, Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QInputDialog, QMessageBox,
    QComboBox, QSpinBox
)

from gui.widgets.view_profile_widget import ViewProfileWidget
from gui.widgets.account_group_sidebar_widget import CollapsibleSection

logger = logging.getLogger(__name__)


class ExportRightSidebarWidget(QWidget):
    """
    Sağ İşlem ve Ayar Çekmecesi (Action Drawer / Sidebar) - Dışa Aktarım ve Sunucu Göçü için.
    Tüm bölümler açılır/kapanır akordeon yapıdadır ve varsayılan olarak kapalı başlar.
    """

    # Signals for actions
    export_selected_requested = Signal()
    export_all_requested = Signal()
    pause_requested = Signal()
    cancel_requested = Signal()
    dry_run_requested = Signal()

    export_group_requested = Signal()
    select_all_requested = Signal()

    format_changed = Signal(str)
    config_dialog_requested = Signal()

    export_excel_requested = Signal()
    copy_emails_requested = Signal()

    reports_requested = Signal()
    toggle_log_requested = Signal()

    row_height_changed = Signal(int)

    # View profile signals forwarded
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
        # Section 1: ⚙️ GÖRÜNÜM & DÜZEN (Accordion - initially collapsed)
        # -------------------------------------------------------------
        self.sec_layout = CollapsibleSection("⚙️ GÖRÜNÜM & DÜZEN", parent=self, is_collapsed=True)

        self.view_profile_widget = ViewProfileWidget(
            profile_key="export_panel_grid",
            title="GÖRÜNÜM PROFİLLERİ",
            parent=self
        )
        self.view_profile_widget.profile_selected.connect(self.profile_selected.emit)
        self.view_profile_widget.save_requested.connect(self.save_profile_requested.emit)
        self.view_profile_widget.columns_requested.connect(self.columns_requested.emit)
        self.view_profile_widget.filter_row_toggled.connect(self.filter_row_toggled.emit)
        self.sec_layout.content_layout.addWidget(self.view_profile_widget)

        # Row Height Preset Bar inside Layout Section
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
        self.btn_h_compact.setToolTip("Kompakt satır yüksekliği")
        self.btn_h_compact.setStyleSheet(self._pill_btn_style())
        self.btn_h_compact.clicked.connect(lambda: self.row_height_changed.emit(40))
        h_btn_row.addWidget(self.btn_h_compact)

        self.btn_h_normal = QPushButton("60px")
        self.btn_h_normal.setToolTip("Normal satır yüksekliği")
        self.btn_h_normal.setStyleSheet(self._pill_btn_style())
        self.btn_h_normal.clicked.connect(lambda: self.row_height_changed.emit(60))
        h_btn_row.addWidget(self.btn_h_normal)

        self.btn_h_std = QPushButton("88px")
        self.btn_h_std.setToolTip("Standart rahat görünüm (Varsayılan)")
        self.btn_h_std.setStyleSheet(self._pill_btn_style())
        self.btn_h_std.clicked.connect(lambda: self.row_height_changed.emit(88))
        h_btn_row.addWidget(self.btn_h_std)

        self.btn_h_large = QPushButton("110px")
        self.btn_h_large.setToolTip("Geniş görünüm")
        self.btn_h_large.setStyleSheet(self._pill_btn_style())
        self.btn_h_large.clicked.connect(lambda: self.row_height_changed.emit(110))
        h_btn_row.addWidget(self.btn_h_large)

        lyt_height.addLayout(h_btn_row)
        self.sec_layout.content_layout.addWidget(grp_height)

        self.btn_col_manager = QPushButton("👁️ Sütun Görünürlüğü (Kolon Aç/Kapa)...")
        self.btn_col_manager.setToolTip("Sütunları göster / gizle ve yönet")
        self.btn_col_manager.setStyleSheet(self._action_btn_style(bg="#475569", hover="#334155"))
        self.btn_col_manager.clicked.connect(self.columns_requested.emit)
        self.sec_layout.content_layout.addWidget(self.btn_col_manager)

        lyt.addWidget(self.sec_layout)

        # -------------------------------------------------------------
        # Section 2: 🚀 DIŞA AKTARIM İŞLEMLERİ (Accordion - initially collapsed)
        # -------------------------------------------------------------
        self.sec_export = CollapsibleSection("🚀 DIŞA AKTARIM İŞLEMLERİ", parent=self, is_collapsed=True)

        self.btn_export = QPushButton("⚡ Seçilenleri Dışa Aktar")
        self.btn_export.setToolTip("İşaretli hesapların dışa aktarımını / sunucu göçünü başlatır")
        self.btn_export.setStyleSheet(self._action_btn_style(bg="#2563eb", hover="#1d4ed8", bold=True))
        self.btn_export.setMinimumHeight(32)
        self.btn_export.clicked.connect(self.export_selected_requested.emit)
        self.sec_export.content_layout.addWidget(self.btn_export)

        self.btn_export_all = QPushButton("🌐 Tüm Hesapları Aktar")
        self.btn_export_all.setToolTip("Tablodaki tüm hesapları aktarır")
        self.btn_export_all.setStyleSheet(self._action_btn_style(bg="#059669", hover="#047857", bold=True))
        self.btn_export_all.setMinimumHeight(32)
        self.btn_export_all.clicked.connect(self.export_all_requested.emit)
        self.sec_export.content_layout.addWidget(self.btn_export_all)

        self.btn_pause = QPushButton("⏸️ Tümünü Duraklat")
        self.btn_pause.setToolTip("Aktif aktarım işlemlerini duraklatır")
        self.btn_pause.setStyleSheet(self._action_btn_style(bg="#f59e0b", hover="#d97706"))
        self.btn_pause.setEnabled(False)
        self.btn_pause.setMinimumHeight(30)
        self.btn_pause.clicked.connect(self.pause_requested.emit)
        self.sec_export.content_layout.addWidget(self.btn_pause)

        self.btn_cancel = QPushButton("⏹️ Tümünü İptal Et")
        self.btn_cancel.setToolTip("Aktif aktarım işlemlerini iptal eder")
        self.btn_cancel.setStyleSheet(self._action_btn_style(bg="#dc2626", hover="#b91c1c"))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setMinimumHeight(30)
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)
        self.sec_export.content_layout.addWidget(self.btn_cancel)

        self.btn_dry_run = QPushButton("🔍 Kuru Çalıştırma (Önizleme)")
        self.btn_dry_run.setToolTip("Seçili hesaplar için aktarılacak mail sayılarını ve hedefi hesaplar")
        self.btn_dry_run.setStyleSheet(self._action_btn_style(bg="#475569", hover="#334155"))
        self.btn_dry_run.setMinimumHeight(30)
        self.btn_dry_run.clicked.connect(self.dry_run_requested.emit)
        self.sec_export.content_layout.addWidget(self.btn_dry_run)

        lyt.addWidget(self.sec_export)

        # -------------------------------------------------------------
        # Section 3: 📁 GRUP & SEÇİM İŞLEMLERİ (Accordion - initially collapsed)
        # -------------------------------------------------------------
        self.sec_group = CollapsibleSection("📁 GRUP & SEÇİM İŞLEMLERİ", parent=self, is_collapsed=True)

        self.btn_export_group = QPushButton("🚀 Seçili Grubu Aktar")
        self.btn_export_group.setToolTip("Filtrelenmiş olan grubun tüm hesaplarını aktarır")
        self.btn_export_group.setStyleSheet(self._action_btn_style(bg="#0284c7", hover="#0369a1"))
        self.btn_export_group.setMinimumHeight(30)
        self.btn_export_group.clicked.connect(self.export_group_requested.emit)
        self.sec_group.content_layout.addWidget(self.btn_export_group)

        self.btn_select_all = QPushButton("☑️ Tümünü / Grubu Seç")
        self.btn_select_all.setToolTip("Tablodaki görünür hesapların seçim kutularını işaretler/kaldırır")
        self.btn_select_all.setStyleSheet(self._action_btn_style(bg="#ffffff", hover="#f1f5f9", text_color="#334155", border="#cbd5e1"))
        self.btn_select_all.setMinimumHeight(30)
        self.btn_select_all.clicked.connect(self.select_all_requested.emit)
        self.sec_group.content_layout.addWidget(self.btn_select_all)

        lyt.addWidget(self.sec_group)

        # -------------------------------------------------------------
        # Section 4: 🛠️ HEDEF BİÇİM & SUNUCU AYARLARI (Accordion - initially collapsed)
        # -------------------------------------------------------------
        self.sec_format = CollapsibleSection("🛠️ HEDEF BİÇİM & AYARLAR", parent=self, is_collapsed=True)

        lbl_fmt = QLabel("Aktarım Biçimi / Hedefi:")
        lbl_fmt.setStyleSheet("font-size: 10.5px; font-weight: 600; color: #64748b;")
        self.sec_format.content_layout.addWidget(lbl_fmt)

        self.combo_format = QComboBox()
        self.combo_format.addItem("📦 ZIP Arşivi (.zip)", "ZIP")
        self.combo_format.addItem("✉️ Ham EML Dosyaları (.eml)", "EML")
        self.combo_format.addItem("📁 Standart MBOX (.mbox)", "MBOX")
        self.combo_format.addItem("🗃️ Outlook PST (.pst)", "PST")
        self.combo_format.addItem("🌐 IMAP Sunucu Göçü (Doğrudan Aktarım)", "IMAP")
        self.combo_format.setStyleSheet("""
            QComboBox {
                padding: 5px 8px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background-color: #ffffff;
                font-size: 11px;
                font-weight: 600;
                color: #1e293b;
            }
        """)
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)
        self.sec_format.content_layout.addWidget(self.combo_format)

        self.btn_open_config = QPushButton("⚙️ Dışa Aktarım Ayarları & Sunucu Eşleme...")
        self.btn_open_config.setToolTip("Hedef dizin, IMAP sunucu bilgileri ve tarih filtrelerini yapılandırır")
        self.btn_open_config.setStyleSheet(self._action_btn_style(bg="#0284c7", hover="#0369a1"))
        self.btn_open_config.setMinimumHeight(30)
        self.btn_open_config.clicked.connect(self.config_dialog_requested.emit)
        self.sec_format.content_layout.addWidget(self.btn_open_config)

        lyt.addWidget(self.sec_format)

        # -------------------------------------------------------------
        # Section 5: 📊 EXCEL & DÜZENLEME (Accordion - initially collapsed)
        # -------------------------------------------------------------
        self.sec_excel = CollapsibleSection("📊 EXCEL & DÜZENLEME", parent=self, is_collapsed=True)

        self.btn_export_excel = QPushButton("📥 Excel / CSV'ye Aktar")
        self.btn_export_excel.setToolTip("Mevcut görünür hesap tablosunu Excel / CSV dosyası olarak kaydeder")
        self.btn_export_excel.setStyleSheet(self._action_btn_style(bg="#059669", hover="#047857"))
        self.btn_export_excel.setMinimumHeight(30)
        self.btn_export_excel.clicked.connect(self.export_excel_requested.emit)
        self.sec_excel.content_layout.addWidget(self.btn_export_excel)

        self.btn_copy_all_emails = QPushButton("📋 E-Postaları Kopyala")
        self.btn_copy_all_emails.setToolTip("Tablodaki tüm e-posta adreslerini panoya kopyalar")
        self.btn_copy_all_emails.setStyleSheet(self._action_btn_style(bg="#ffffff", hover="#f1f5f9", text_color="#334155", border="#cbd5e1"))
        self.btn_copy_all_emails.setMinimumHeight(30)
        self.btn_copy_all_emails.clicked.connect(self.copy_emails_requested.emit)
        self.sec_excel.content_layout.addWidget(self.btn_copy_all_emails)

        lyt.addWidget(self.sec_excel)

        # -------------------------------------------------------------
        # Section 6: 📈 RAPOR & DİAGNOSTİK (Accordion - initially collapsed)
        # -------------------------------------------------------------
        self.sec_report = CollapsibleSection("📈 RAPOR & DİAGNOSTİK", parent=self, is_collapsed=True)

        self.btn_reports = QPushButton("📊 Oturum Raporları")
        self.btn_reports.setToolTip("Dışa aktarım sonuç raporlarını görüntüler")
        self.btn_reports.setStyleSheet(self._action_btn_style(bg="#7c3aed", hover="#6d28d9"))
        self.btn_reports.setMinimumHeight(30)
        self.btn_reports.clicked.connect(self.reports_requested.emit)
        self.sec_report.content_layout.addWidget(self.btn_reports)

        self.btn_toggle_log = QPushButton("📋 Aktarım Log Kutusunu Aç/Kapat")
        self.btn_toggle_log.setToolTip("Canlı aktarım log tablosunu göster/gizle")
        self.btn_toggle_log.setStyleSheet(self._action_btn_style(bg="#334155", hover="#1e293b"))
        self.btn_toggle_log.setMinimumHeight(30)
        self.btn_toggle_log.clicked.connect(self.toggle_log_requested.emit)
        self.sec_report.content_layout.addWidget(self.btn_toggle_log)

        lyt.addWidget(self.sec_report)

        lyt.addStretch()
        self.scroll_area.setWidget(container)
        main_layout.addWidget(self.scroll_area)

    @Slot(int)
    def _on_format_changed(self, idx: int):
        val = self.combo_format.itemData(idx)
        if val:
            self.format_changed.emit(val)

    @staticmethod
    def _action_btn_style(bg: str = "#2563eb", hover: str = "#1d4ed8", text_color: str = "#ffffff", border: str = "none", bold: bool = False) -> str:
        border_css = f"border: 1px solid {border};" if border != "none" else "border: none;"
        font_weight = "700" if bold else "600"
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {text_color};
                font-weight: {font_weight};
                font-size: 11px;
                padding: 6px 10px;
                border-radius: 6px;
                text-align: left;
                {border_css}
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QPushButton:disabled {{
                background-color: #cbd5e1;
                color: #94a3b8;
                border: none;
            }}
        """

    @staticmethod
    def _pill_btn_style() -> str:
        return """
            QPushButton {
                background-color: #ffffff;
                color: #1e3a8a;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10.5px;
                padding: 4px 6px;
                min-height: 22px;
            }
            QPushButton:hover {
                background-color: #2563eb;
                color: #ffffff;
                border-color: #1d4ed8;
            }
        """
