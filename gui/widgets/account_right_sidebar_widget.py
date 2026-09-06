"""
account_right_sidebar_widget.py — Modular Right Action Sidebar for Account Operations,
View Profiles, Row Height Adjustments, and Excel Inline Editing Mode.
Equipped with collapsible accordion sections (initially collapsed by default) and RBAC.
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


class AccountRightSidebarWidget(QWidget):
    """
    Yedeklenecek Mail Hesapları için Sağ İşlem ve Ayar Çekmecesi (Action Drawer / Sidebar).
    Tüm bölümler açılır/kapanır akordeon yapıdadır ve varsayılan olarak kapalı başlar.
    """

    # Signal definitions for all actions
    add_requested = Signal()
    edit_requested = Signal()
    copy_requested = Signal()
    delete_requested = Signal()
    toggle_active_requested = Signal()
    test_requested = Signal()
    bulk_import_requested = Signal()
    scan_disk_requested = Signal()
    import_eml_requested = Signal()
    clean_start_requested = Signal()

    excel_mode_toggled = Signal(bool)
    row_height_changed = Signal(int)

    # View profile signals forwarded
    profile_selected = Signal(str, dict)
    save_profile_requested = Signal(str)
    columns_requested = Signal()
    filter_row_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_role = "admin"
        self._excel_editing_enabled = False
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
            profile_key="account_panel_grid",
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

        self.btn_h_compact = QPushButton("28px")
        self.btn_h_compact.setToolTip("Kompakt satır yüksekliği")
        self.btn_h_compact.setStyleSheet(self._pill_btn_style())
        self.btn_h_compact.clicked.connect(lambda: self.row_height_changed.emit(28))
        h_btn_row.addWidget(self.btn_h_compact)

        self.btn_h_normal = QPushButton("36px")
        self.btn_h_normal.setToolTip("Normal satır yüksekliği")
        self.btn_h_normal.setStyleSheet(self._pill_btn_style())
        self.btn_h_normal.clicked.connect(lambda: self.row_height_changed.emit(36))
        h_btn_row.addWidget(self.btn_h_normal)

        self.btn_h_std = QPushButton("44px")
        self.btn_h_std.setToolTip("Standart rahat görünüm")
        self.btn_h_std.setStyleSheet(self._pill_btn_style())
        self.btn_h_std.clicked.connect(lambda: self.row_height_changed.emit(44))
        h_btn_row.addWidget(self.btn_h_std)

        self.btn_h_large = QPushButton("54px")
        self.btn_h_large.setToolTip("Geniş dokunmatik görünüm")
        self.btn_h_large.setStyleSheet(self._pill_btn_style())
        self.btn_h_large.clicked.connect(lambda: self.row_height_changed.emit(54))
        h_btn_row.addWidget(self.btn_h_large)

        lyt_height.addLayout(h_btn_row)
        self.sec_layout.content_layout.addWidget(grp_height)

        lyt.addWidget(self.sec_layout)

        # -------------------------------------------------------------
        # Section 2: ⚡ E-POSTA İŞLEMLERİ (Accordion - initially collapsed)
        # -------------------------------------------------------------
        self.sec_email = CollapsibleSection("⚡ E-POSTA İŞLEMLERİ", parent=self, is_collapsed=True)

        # Primary Add Account Button
        self.btn_add = QPushButton("➕ Yeni E-Posta Hesabı Ekle")
        self.btn_add.setToolTip("Sisteme yeni bir IMAP e-posta hesabı ekler")
        self.btn_add.setStyleSheet(self._action_btn_style(bg="#16a34a", hover="#15803d", bold=True))
        self.btn_add.setMinimumHeight(32)
        self.btn_add.clicked.connect(self.add_requested.emit)
        self.sec_email.content_layout.addWidget(self.btn_add)

        # Selection Based Action Buttons
        self.btn_edit = QPushButton("✏️ Seçili Hesabı Düzenle")
        self.btn_edit.setToolTip("Seçili hesabın sunucu ve kimlik bilgilerini düzenler")
        self.btn_edit.setStyleSheet(self._action_btn_style(bg="#2563eb", hover="#1d4ed8"))
        self.btn_edit.setEnabled(False)
        self.btn_edit.clicked.connect(self.edit_requested.emit)
        self.sec_email.content_layout.addWidget(self.btn_edit)

        self.btn_copy = QPushButton("📋 Seçili Hesabı Çoğalt (Kopyala)")
        self.btn_copy.setToolTip("Seçili hesabı şablon alarak yeni hesap oluşturur")
        self.btn_copy.setStyleSheet(self._action_btn_style(bg="#0891b2", hover="#0e7490"))
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self.copy_requested.emit)
        self.sec_email.content_layout.addWidget(self.btn_copy)

        self.btn_toggle_active = QPushButton("⏸️ Durumu Değiştir (Pasif Yap)")
        self.btn_toggle_active.setToolTip("Hesabın yedekleme durumunu aktif/pasif yapar")
        self.btn_toggle_active.setStyleSheet(self._action_btn_style(bg="#475569", hover="#334155"))
        self.btn_toggle_active.setEnabled(False)
        self.btn_toggle_active.clicked.connect(self.toggle_active_requested.emit)
        self.sec_email.content_layout.addWidget(self.btn_toggle_active)

        self.btn_test = QPushButton("🔌 Bağlantıyı Test Et")
        self.btn_test.setToolTip("Seçili hesabın IMAP sunucu ve şifre doğrulamasını test eder")
        self.btn_test.setStyleSheet(self._action_btn_style(bg="#7c3aed", hover="#6d28d9"))
        self.btn_test.setEnabled(False)
        self.btn_test.clicked.connect(self.test_requested.emit)
        self.sec_email.content_layout.addWidget(self.btn_test)

        self.btn_delete = QPushButton("🗑️ Seçili Hesabı Sil")
        self.btn_delete.setToolTip("Seçili hesabı ve arşivi kalıcı olarak siler")
        self.btn_delete.setStyleSheet(self._action_btn_style(bg="#dc2626", hover="#b91c1c", bold=True))
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self.delete_requested.emit)
        self.sec_email.content_layout.addWidget(self.btn_delete)

        # Separator line
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("border: none; border-top: 1px solid #e2e8f0; margin: 4px 0px;")
        self.sec_email.content_layout.addWidget(sep1)

        self.btn_bulk_import = QPushButton("📥 Toplu Hesap Ekle (CSV/TXT)")
        self.btn_bulk_import.setToolTip("Excel veya CSV listesinden toplu e-posta hesabı içe aktarır")
        self.btn_bulk_import.setStyleSheet(self._sec_btn_style())
        self.btn_bulk_import.clicked.connect(self.bulk_import_requested.emit)
        self.sec_email.content_layout.addWidget(self.btn_bulk_import)

        self.btn_scan_disk = QPushButton("🔍 Depolamayı Tara (Otomatik Bul)")
        self.btn_scan_disk.setToolTip("Yedek diskindeki e-posta klasörlerini tarayıp veri tabanına otomatik ekler")
        self.btn_scan_disk.setStyleSheet(self._sec_btn_style())
        self.btn_scan_disk.clicked.connect(self.scan_disk_requested.emit)
        self.sec_email.content_layout.addWidget(self.btn_scan_disk)

        self.btn_import_eml = QPushButton("📂 EML Tarama / Arşive Eşle")
        self.btn_import_eml.setToolTip("Seçili hesap için mevcut EML dosyalarını tarayıp dizine kaydeder")
        self.btn_import_eml.setStyleSheet(self._sec_btn_style())
        self.btn_import_eml.clicked.connect(self.import_eml_requested.emit)
        self.sec_email.content_layout.addWidget(self.btn_import_eml)

        self.btn_clean_start = QPushButton("⚠️ Temiz Başlangıç (Arşivi Sıfırla)")
        self.btn_clean_start.setToolTip("Hesapları koruyarak arşivlenmiş tüm e-postaları sıfırlar")
        self.btn_clean_start.setStyleSheet("""
            QPushButton {
                background-color: #fee2e2;
                color: #b91c1c !important;
                border: 1px solid #fca5a5;
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 11px;
                font-weight: 600;
                min-height: 24px;
            }
            QPushButton:hover { background-color: #fecaca; }
            QPushButton:disabled { background-color: #f8fafc; color: #cbd5e1 !important; border-color: #e2e8f0; }
        """)
        self.btn_clean_start.clicked.connect(self.clean_start_requested.emit)
        self.sec_email.content_layout.addWidget(self.btn_clean_start)

        lyt.addWidget(self.sec_email)

        # -------------------------------------------------------------
        # Section 3: ⚡ CANLI DÜZENLEME (Accordion - initially collapsed)
        # -------------------------------------------------------------
        self.sec_excel = CollapsibleSection("⚡ EXCEL CANLI DÜZENLEME", parent=self, is_collapsed=True)

        lbl_excel_desc = QLabel("Hücreye çift tıklayarak tablo üzerinde doğrudan düzenleme yapın.")
        lbl_excel_desc.setWordWrap(True)
        lbl_excel_desc.setStyleSheet("color: #475569; font-size: 10.5px; border: none; background: transparent; margin-bottom: 4px;")
        self.sec_excel.content_layout.addWidget(lbl_excel_desc)

        self.btn_excel_mode = QPushButton("⚡ Canlı Düzenleme: KAPALI")
        self.btn_excel_mode.setToolTip("Tablo hücrelerinde doğrudan Excel gibi yazma modunu açar/kapatır")
        self.btn_excel_mode.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #334155 !important;
                border: 1.5px solid #cbd5e1;
                font-weight: bold;
                padding: 8px 10px;
                border-radius: 6px;
                font-size: 11px;
                min-height: 28px;
            }
            QPushButton:hover { background-color: #e2e8f0; }
        """)
        self.btn_excel_mode.clicked.connect(self._toggle_excel_mode)
        self.sec_excel.content_layout.addWidget(self.btn_excel_mode)

        lyt.addWidget(self.sec_excel)

        # Bottom spacer
        lyt.addStretch()

        self.scroll_area.setWidget(container)
        main_layout.addWidget(self.scroll_area)

    # -------------------------------------------------------------
    # State Management & Helpers
    # -------------------------------------------------------------

    def update_selection_state(self, has_selection: bool, is_active: bool = True):
        """Updates enablement and status labels for selected account buttons."""
        is_admin = self._current_role == "admin"
        is_operator = self._current_role in ("admin", "operator")

        self.btn_edit.setEnabled(has_selection and is_operator)
        self.btn_copy.setEnabled(has_selection and is_operator)
        self.btn_test.setEnabled(has_selection)
        self.btn_toggle_active.setEnabled(has_selection and is_operator)
        self.btn_delete.setEnabled(has_selection and is_admin)

        if has_selection:
            self.btn_toggle_active.setText("⏸️ Durumu Değiştir (Pasif Yap)" if is_active else "▶️ Durumu Değiştir (Aktif Yap)")
        else:
            self.btn_toggle_active.setText("⏸️ Durumu Değiştir")

    @Slot()
    def _toggle_excel_mode(self):
        self._excel_editing_enabled = not self._excel_editing_enabled
        if self._excel_editing_enabled:
            self.btn_excel_mode.setText("⚡ Canlı Düzenleme: AÇIK")
            self.btn_excel_mode.setStyleSheet("""
                QPushButton {
                    background-color: #10b981;
                    color: #ffffff !important;
                    border: none;
                    font-weight: bold;
                    padding: 8px 10px;
                    border-radius: 6px;
                    font-size: 11px;
                    min-height: 28px;
                }
                QPushButton:hover { background-color: #059669; }
            """)
        else:
            self.btn_excel_mode.setText("⚡ Canlı Düzenleme: KAPALI")
            self.btn_excel_mode.setStyleSheet("""
                QPushButton {
                    background-color: #f1f5f9;
                    color: #334155 !important;
                    border: 1.5px solid #cbd5e1;
                    font-weight: bold;
                    padding: 8px 10px;
                    border-radius: 6px;
                    font-size: 11px;
                    min-height: 28px;
                }
                QPushButton:hover { background-color: #e2e8f0; }
            """)
        self.excel_mode_toggled.emit(self._excel_editing_enabled)

    def set_excel_mode(self, enabled: bool):
        if self._excel_editing_enabled != enabled:
            self._toggle_excel_mode()

    def is_excel_mode_enabled(self) -> bool:
        return self._excel_editing_enabled

    def apply_permissions(self, role: str):
        """
        Role-Based Access Control (RBAC):
        'admin': Full access to all operations.
        'operator': Can Add, Edit, Copy, Test, Scan, EML, Excel Mode; cannot Delete or Clean Start.
        'viewer': Read-only access.
        """
        self._current_role = role.lower()
        is_admin = self._current_role == "admin"
        is_operator = self._current_role in ("admin", "operator")
        is_viewer = self._current_role == "viewer"

        self.btn_add.setEnabled(is_operator)
        self.btn_bulk_import.setEnabled(is_operator)
        self.btn_scan_disk.setEnabled(is_operator)
        self.btn_import_eml.setEnabled(is_operator)
        self.btn_clean_start.setEnabled(is_admin)
        self.btn_clean_start.setVisible(is_admin)

        self.sec_excel.setEnabled(not is_viewer)
        if is_viewer:
            self.set_excel_mode(False)

    # -------------------------------------------------------------
    # CSS Stylesheets
    # -------------------------------------------------------------

    def _action_btn_style(self, bg="#2563eb", hover="#1d4ed8", bold=False) -> str:
        return f"""
            QPushButton {{
                background-color: {bg};
                color: #ffffff !important;
                border: none;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 11.5px;
                font-weight: {'bold' if bold else '600'};
                min-height: 26px;
            }}
            QPushButton:hover {{ background-color: {hover}; }}
            QPushButton:disabled {{ background-color: #cbd5e1; color: #94a3b8 !important; }}
        """

    def _sec_btn_style(self) -> str:
        return """
            QPushButton {
                background-color: #ffffff;
                color: #334155 !important;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: 600;
                min-height: 24px;
            }
            QPushButton:hover { background-color: #f1f5f9; border-color: #94a3b8; }
            QPushButton:disabled { background-color: #f8fafc; color: #cbd5e1 !important; border-color: #e2e8f0; }
        """

    def _pill_btn_style(self) -> str:
        return """
            QPushButton {
                background-color: #ffffff;
                color: #1e3a8a !important;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 3px 6px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #e2e8f0; border-color: #2563eb; }
        """
