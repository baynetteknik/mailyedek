"""
sync_right_sidebar_widget.py — Modular Right Action Sidebar for Synchronization Operations,
View Profiles, Row Height Adjustments, and Flow Control.
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


class SyncRightSidebarWidget(QWidget):
    """
    Sağ İşlem ve Ayar Çekmecesi (Action Drawer / Sidebar) - Senkronizasyon Paneli için.
    Tüm bölümler açılır/kapanır akordeon yapıdadır ve varsayılan olarak kapalı başlar.
    """

    # Signals for actions
    sync_selected_requested = Signal()
    sync_all_requested = Signal()
    pause_requested = Signal()
    cancel_requested = Signal()
    dry_run_requested = Signal()

    sync_group_requested = Signal()
    select_all_requested = Signal()

    export_excel_requested = Signal()
    copy_emails_requested = Signal()

    filters_requested = Signal()
    folder_lang_changed = Signal(str)

    reports_requested = Signal()
    detailed_report_requested = Signal()
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
            profile_key="sync_panel_grid",
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
        self.btn_h_std.setToolTip("Standart rahat görünüm")
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
        self.btn_col_manager.setToolTip("Sütunları göster / gizle ve ara")
        self.btn_col_manager.setStyleSheet(self._action_btn_style(bg="#475569", hover="#334155"))
        self.btn_col_manager.clicked.connect(self.columns_requested.emit)
        self.sec_layout.content_layout.addWidget(self.btn_col_manager)

        lyt.addWidget(self.sec_layout)

        # -------------------------------------------------------------
        # Section 2: ⚡ SENKRONİZASYON İŞLEMLERİ (Accordion - initially collapsed)
        # -------------------------------------------------------------
        self.sec_sync = CollapsibleSection("⚡ SENKRONİZASYON İŞLEMLERİ", parent=self, is_collapsed=True)

        self.btn_sync = QPushButton("⚡ Seçilenleri Başlat")
        self.btn_sync.setToolTip("Seçili kutucuğu işaretli tüm hesapların senkronizasyonunu başlatır")
        self.btn_sync.setStyleSheet(self._action_btn_style(bg="#2563eb", hover="#1d4ed8", bold=True))
        self.btn_sync.setMinimumHeight(32)
        self.btn_sync.clicked.connect(self.sync_selected_requested.emit)
        self.sec_sync.content_layout.addWidget(self.btn_sync)

        self.btn_sync_all = QPushButton("🚀 Tüm Hesapları Başlat")
        self.btn_sync_all.setToolTip("Sistemdeki tüm hesapları senkronize eder")
        self.btn_sync_all.setStyleSheet(self._action_btn_style(bg="#059669", hover="#047857", bold=True))
        self.btn_sync_all.setMinimumHeight(32)
        self.btn_sync_all.clicked.connect(self.sync_all_requested.emit)
        self.sec_sync.content_layout.addWidget(self.btn_sync_all)

        self.btn_pause = QPushButton("⏸️ Tümünü Duraklat")
        self.btn_pause.setToolTip("Aktif arşiv işlemlerini duraklatır")
        self.btn_pause.setStyleSheet(self._action_btn_style(bg="#f59e0b", hover="#d97706"))
        self.btn_pause.setEnabled(False)
        self.btn_pause.setMinimumHeight(30)
        self.btn_pause.clicked.connect(self.pause_requested.emit)
        self.sec_sync.content_layout.addWidget(self.btn_pause)

        self.btn_cancel = QPushButton("⏹️ Tümünü İptal Et")
        self.btn_cancel.setToolTip("Aktif arşiv işlemlerini iptal eder")
        self.btn_cancel.setStyleSheet(self._action_btn_style(bg="#dc2626", hover="#b91c1c"))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setMinimumHeight(30)
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)
        self.sec_sync.content_layout.addWidget(self.btn_cancel)

        self.btn_dry_run = QPushButton("🔍 Kuru Çalıştırma (Dry Run)")
        self.btn_dry_run.setToolTip("Sunucuya bağlanıp taranacak tahmini mail sayısını hesaplar")
        self.btn_dry_run.setStyleSheet(self._action_btn_style(bg="#475569", hover="#334155"))
        self.btn_dry_run.setMinimumHeight(30)
        self.btn_dry_run.clicked.connect(self.dry_run_requested.emit)
        self.sec_sync.content_layout.addWidget(self.btn_dry_run)

        lyt.addWidget(self.sec_sync)

        # -------------------------------------------------------------
        # Section 3: 📁 GRUP & SEÇİM İŞLEMLERİ (Accordion - initially collapsed)
        # -------------------------------------------------------------
        self.sec_group = CollapsibleSection("📁 GRUP & SEÇİM İŞLEMLERİ", parent=self, is_collapsed=True)

        self.btn_sync_group = QPushButton("🚀 Seçili Grubu Senkronize Et")
        self.btn_sync_group.setToolTip("Filtrelenmiş olan grubun/domain'in tüm hesaplarını senkronize eder")
        self.btn_sync_group.setStyleSheet(self._action_btn_style(bg="#0284c7", hover="#0369a1"))
        self.btn_sync_group.setMinimumHeight(30)
        self.btn_sync_group.clicked.connect(self.sync_group_requested.emit)
        self.sec_group.content_layout.addWidget(self.btn_sync_group)

        self.btn_select_all = QPushButton("☑️ Tümünü / Grubu Seç")
        self.btn_select_all.setToolTip("Tablodaki görünür hesapların seçim kutularını işaretler/kaldırır")
        self.btn_select_all.setStyleSheet(self._action_btn_style(bg="#ffffff", hover="#f1f5f9", text_color="#334155", border="#cbd5e1"))
        self.btn_select_all.setMinimumHeight(30)
        self.btn_select_all.clicked.connect(self.select_all_requested.emit)
        self.sec_group.content_layout.addWidget(self.btn_select_all)

        lyt.addWidget(self.sec_group)

        # -------------------------------------------------------------
        # Section 4: 📊 EXCEL & DÜZENLEME (Accordion - initially collapsed)
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
        # Section 5: 🌐 FİLTRE & ÇEVİRİ (Accordion - initially collapsed)
        # -------------------------------------------------------------
        self.sec_filter = CollapsibleSection("🌐 FİLTRE & ÇEVİRİ", parent=self, is_collapsed=True)

        self.btn_filters = QPushButton("⚙️ Klasör Filtreleri...")
        self.btn_filters.setToolTip("Hesap için arşivlenecek klasörleri ve filtreleri ayarlar")
        self.btn_filters.setStyleSheet(self._action_btn_style(bg="#0284c7", hover="#0369a1"))
        self.btn_filters.setMinimumHeight(30)
        self.btn_filters.clicked.connect(self.filters_requested.emit)
        self.sec_filter.content_layout.addWidget(self.btn_filters)

        lbl_folder_lang = QLabel("Klasör İsim Dili:")
        lbl_folder_lang.setStyleSheet("font-size: 10.5px; font-weight: 600; color: #64748b;")
        self.sec_filter.content_layout.addWidget(lbl_folder_lang)

        self.combo_folder_lang = QComboBox()
        self.combo_folder_lang.addItem("Orijinal Dilinde Bırak", "original")
        self.combo_folder_lang.addItem("Türkçeleştir (TR)", "tr")
        self.combo_folder_lang.addItem("İngilizceye Çevir (EN)", "en")
        self.combo_folder_lang.setStyleSheet("""
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
        self.combo_folder_lang.currentIndexChanged.connect(self._on_lang_changed)
        self.sec_filter.content_layout.addWidget(self.combo_folder_lang)

        lyt.addWidget(self.sec_filter)

        # -------------------------------------------------------------
        # Section 6: 📈 RAPOR & DİAGNOSTİK (Accordion - initially collapsed)
        # -------------------------------------------------------------
        self.sec_report = CollapsibleSection("📈 RAPOR & DİAGNOSTİK", parent=self, is_collapsed=True)

        self.btn_reports = QPushButton("📊 Oturum Raporları")
        self.btn_reports.setToolTip("Oturum raporlarını görüntüler")
        self.btn_reports.setStyleSheet(self._action_btn_style(bg="#7c3aed", hover="#6d28d9"))
        self.btn_reports.setMinimumHeight(30)
        self.btn_reports.clicked.connect(self.reports_requested.emit)
        self.sec_report.content_layout.addWidget(self.btn_reports)

        self.btn_detailed_report = QPushButton("🔬 Diagnostik Raporu")
        self.btn_detailed_report.setToolTip("Detaylı diagnostik raporunu gösterir")
        self.btn_detailed_report.setStyleSheet(self._action_btn_style(bg="#475569", hover="#334155"))
        self.btn_detailed_report.setMinimumHeight(30)
        self.btn_detailed_report.clicked.connect(self.detailed_report_requested.emit)
        self.sec_report.content_layout.addWidget(self.btn_detailed_report)

        self.btn_toggle_log = QPushButton("📋 Sync Log Kutusunu Aç/Kapat")
        self.btn_toggle_log.setToolTip("Sync log tablosunu göster/gizle")
        self.btn_toggle_log.setStyleSheet(self._action_btn_style(bg="#334155", hover="#1e293b"))
        self.btn_toggle_log.setMinimumHeight(30)
        self.btn_toggle_log.clicked.connect(self.toggle_log_requested.emit)
        self.sec_report.content_layout.addWidget(self.btn_toggle_log)

        lyt.addWidget(self.sec_report)

        lyt.addStretch()
        self.scroll_area.setWidget(container)
        main_layout.addWidget(self.scroll_area)

    @Slot(int)
    def _on_lang_changed(self, idx: int):
        val = self.combo_folder_lang.itemData(idx)
        if val:
            self.folder_lang_changed.emit(val)

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
