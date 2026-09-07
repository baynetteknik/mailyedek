"""
account_group_sidebar_widget.py — Modular Left Sidebar for Domain/Group Management & Filtering.
Includes collapsible accordion sections (initially collapsed by default),
domain search, count badges, bulk group operations, and Role-Based Access Control (RBAC).
"""

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QFrame,
    QScrollArea
)

logger = logging.getLogger(__name__)


class CollapsibleSection(QWidget):
    """
    Sleek accordion section with an interactive header button.
    Starts collapsed by default.
    """
    def __init__(self, title: str, parent=None, is_collapsed: bool = True):
        super().__init__(parent)
        self._is_collapsed = is_collapsed
        self.title_text = title

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header Toggle Button
        self.toggle_btn = QPushButton()
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self.toggle)
        main_layout.addWidget(self.toggle_btn)

        # Content Container Frame
        self.content_frame = QFrame(self)
        self.content_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-top: none;
                border-bottom-left-radius: 6px;
                border-bottom-right-radius: 6px;
            }
        """)
        self.content_layout = QVBoxLayout(self.content_frame)
        self.content_layout.setContentsMargins(8, 8, 8, 8)
        self.content_layout.setSpacing(6)

        main_layout.addWidget(self.content_frame)

        self._update_header()
        self.content_frame.setVisible(not self._is_collapsed)

    def toggle(self):
        self._is_collapsed = not self._is_collapsed
        self.content_frame.setVisible(not self._is_collapsed)
        self._update_header()

    def set_collapsed(self, collapsed: bool):
        self._is_collapsed = collapsed
        self.content_frame.setVisible(not self._is_collapsed)
        self._update_header()

    def is_collapsed(self) -> bool:
        return self._is_collapsed

    def _update_header(self):
        arrow = "▶ " if self._is_collapsed else "▼ "
        self.toggle_btn.setText(f"{arrow}{self.title_text}")
        if self._is_collapsed:
            self.toggle_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f8fafc;
                    color: #1e3a8a;
                    font-weight: 700;
                    font-size: 11px;
                    text-align: left;
                    padding: 8px 10px;
                    border: 1px solid #cbd5e1;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background-color: #e2e8f0;
                    color: #0f172a;
                    border-color: #94a3b8;
                }
            """)
        else:
            self.toggle_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1e3a8a;
                    color: #ffffff !important;
                    font-weight: 700;
                    font-size: 11px;
                    text-align: left;
                    padding: 8px 10px;
                    border: 1px solid #1e40af;
                    border-top-left-radius: 6px;
                    border-top-right-radius: 6px;
                    border-bottom-left-radius: 0px;
                    border-bottom-right-radius: 0px;
                }
                QPushButton:hover {
                    background-color: #1d4ed8;
                }
            """)


class AccountGroupSidebarWidget(QWidget):
    """
    Sol tarafta yer alan modüler ve açılır/kapanır menülü Grup / Domain Yönetim Paneli.
    Tüm menüler varsayılan olarak kapalı başlar.
    """

    group_selected = Signal(str)            # Emits group name or "__ALL__"
    bulk_optimize_requested = Signal(str)   # Emits selected group
    bulk_subfolder_requested = Signal(str)  # Emits selected group
    group_mgmt_requested = Signal()         # Request to open Group/Domain Dialog

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups_data: Dict[str, Dict] = {}  # group_name -> {"is_active": bool, "count": int}
        self._current_role = "admin"
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Outer Scroll Area for clean overflow handling
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
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(4, 0, 4, 10)
        c_layout.setSpacing(8)

        # -------------------------------------------------------------
        # Section 1: 🌐 DOMAİNLER (Accordion - open by default)
        # -------------------------------------------------------------
        self.sec_filter = CollapsibleSection("🌐 DOMAİNLER", parent=self, is_collapsed=False)

        # Top row inside filter section: count badge
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        lbl_info = QLabel("Kayıtlı Domainler:")
        lbl_info.setStyleSheet("font-weight: 600; color: #475569; font-size: 10.5px;")
        top_row.addWidget(lbl_info, stretch=1)

        self.lbl_count_badge = QLabel("0 Domain")
        self.lbl_count_badge.setStyleSheet("""
            QLabel {
                background-color: #e2e8f0;
                color: #1e3a8a;
                font-size: 10px;
                font-weight: bold;
                border-radius: 8px;
                padding: 2px 6px;
            }
        """)
        top_row.addWidget(self.lbl_count_badge)
        self.sec_filter.content_layout.addLayout(top_row)

        # Quick Search Box inside Domains
        self.txt_search_group = QLineEdit()
        self.txt_search_group.setPlaceholderText("🔍 Domain ara...")
        self.txt_search_group.setClearButtonEnabled(True)
        self.txt_search_group.setStyleSheet("""
            QLineEdit {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 4px 8px;
                background-color: #f8fafc;
                color: #0f172a;
                font-size: 11px;
            }
            QLineEdit:focus {
                border-color: #2563eb;
                background-color: #ffffff;
            }
        """)
        self.txt_search_group.textChanged.connect(self._filter_group_list_items)
        self.sec_filter.content_layout.addWidget(self.txt_search_group)

        # Domain List
        self.group_list = QListWidget()
        self.group_list.setMinimumHeight(150)
        self.group_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #e2e8f0;
                background: #f8fafc;
                border-radius: 6px;
                padding: 2px;
            }
            QListWidget::item {
                padding: 6px 8px;
                border-radius: 4px;
                color: #334155;
                font-size: 11px;
                margin-bottom: 2px;
            }
            QListWidget::item:hover {
                background: #e2e8f0;
                color: #0f172a;
            }
            QListWidget::item:selected {
                background: #2563eb;
                color: #ffffff !important;
                font-weight: bold;
            }
        """)
        self.group_list.currentItemChanged.connect(self._on_item_changed)
        self.sec_filter.content_layout.addWidget(self.group_list)

        c_layout.addWidget(self.sec_filter)

        # -------------------------------------------------------------
        # Section 2: ⚡ DOMAIN & HESAP İŞLEMLERİ (Accordion - initially collapsed)
        # -------------------------------------------------------------
        self.sec_bulk = CollapsibleSection("⚡ DOMAIN & HESAP İŞLEMLERİ", parent=self, is_collapsed=True)

        self.btn_open_group_mgmt = QPushButton("🏷️ Domain & Grup Yönetimi")
        self.btn_open_group_mgmt.setToolTip("Grup / Domain ekleme, silme, düzenleme ve domain eşitleme penceresini açar")
        self.btn_open_group_mgmt.setStyleSheet("""
            QPushButton {
                background-color: #1e3a8a;
                color: #ffffff !important;
                border: none;
                font-weight: bold;
                padding: 6px 10px;
                border-radius: 6px;
                font-size: 11px;
                min-height: 26px;
            }
            QPushButton:hover { background-color: #1e40af; }
            QPushButton:disabled { background-color: #cbd5e1; color: #94a3b8 !important; }
        """)
        self.btn_open_group_mgmt.clicked.connect(self.group_mgmt_requested.emit)
        self.sec_bulk.content_layout.addWidget(self.btn_open_group_mgmt)

        self.btn_bulk_optimize = QPushButton("⚙️ Domaini Optimize Et")
        self.btn_bulk_optimize.setToolTip("Seçili domaindeki tüm hesapların EML ve ek dosyalarını optimize eder")
        self.btn_bulk_optimize.setStyleSheet("""
            QPushButton {
                background-color: #f59e0b;
                color: #ffffff !important;
                border: none;
                border-radius: 6px;
                padding: 6px 8px;
                font-size: 11px;
                font-weight: bold;
                min-height: 24px;
            }
            QPushButton:hover { background-color: #d97706; }
            QPushButton:disabled { background-color: #cbd5e1; color: #94a3b8 !important; }
        """)
        self.btn_bulk_optimize.clicked.connect(self._on_bulk_optimize_clicked)
        self.sec_bulk.content_layout.addWidget(self.btn_bulk_optimize)

        self.btn_bulk_subfolder = QPushButton("📂 Alt Klasör Tanımla")
        self.btn_bulk_subfolder.setToolTip("Seçili domaindeki tüm hesaplar için ortak alt arşiv klasörü belirler")
        self.btn_bulk_subfolder.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff !important;
                border: none;
                border-radius: 6px;
                padding: 6px 8px;
                font-size: 11px;
                font-weight: bold;
                min-height: 24px;
            }
            QPushButton:hover { background-color: #2563eb; }
            QPushButton:disabled { background-color: #cbd5e1; color: #94a3b8 !important; }
        """)
        self.btn_bulk_subfolder.clicked.connect(self._on_bulk_subfolder_clicked)
        self.sec_bulk.content_layout.addWidget(self.btn_bulk_subfolder)

        c_layout.addWidget(self.sec_bulk)

        # Bottom stretch
        c_layout.addStretch()

        self.scroll_area.setWidget(container)
        layout.addWidget(self.scroll_area)

    def populate_groups(self, groups_data: Dict[str, Dict], total_accounts_count: int = 0, preserve_selection: Optional[str] = None):
        """
        Populates the domain/group list widget.
        groups_data: { "domain.com": {"is_active": True, "count": 12}, ... }
        """
        self._groups_data = groups_data
        self.group_list.blockSignals(True)

        current_selected = preserve_selection or self.get_selected_group()
        self.group_list.clear()

        # Update header badge
        self.lbl_count_badge.setText(f"{len(groups_data)} Domain")

        # 1. Tüm Domainler Item
        all_label = f"🌐 Tüm Domainler ({total_accounts_count})" if total_accounts_count > 0 else "🌐 Tüm Domainler"
        all_item = QListWidgetItem(all_label)
        all_item.setData(Qt.UserRole, "__ALL__")
        self.group_list.addItem(all_item)

        # 2. Individual Domains
        for g_name in sorted(groups_data.keys()):
            info = groups_data[g_name]
            is_active = info.get("is_active", True)
            count = info.get("count", 0)

            count_suffix = f" ({count})" if count > 0 else ""
            status_suffix = "" if is_active else " (Pasif)"
            label = f"🌐 {g_name}{count_suffix}{status_suffix}"

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, g_name)
            if not is_active:
                item.setForeground(QColor("#94a3b8"))
            self.group_list.addItem(item)

        # Restore selection or select 0
        found_item = None
        for i in range(self.group_list.count()):
            it = self.group_list.item(i)
            if it.data(Qt.UserRole) == current_selected:
                found_item = it
                break

        if found_item:
            self.group_list.setCurrentItem(found_item)
        else:
            self.group_list.setCurrentRow(0)

        self._filter_group_list_items(self.txt_search_group.text())
        self.group_list.blockSignals(False)

    def populate_domains(self, domains_data: Dict[str, Dict], total_accounts_count: int = 0, preserve_selection: Optional[str] = None):
        """Alias for populate_groups for domain clarity."""
        self.populate_groups(domains_data, total_accounts_count, preserve_selection)

    def get_selected_group(self) -> str:
        item = self.group_list.currentItem()
        if item:
            return item.data(Qt.UserRole) or "__ALL__"
        return "__ALL__"

    def get_selected_domain(self) -> str:
        return self.get_selected_group()

    def select_group(self, group_name: str):
        for i in range(self.group_list.count()):
            it = self.group_list.item(i)
            if it.data(Qt.UserRole) == group_name:
                self.group_list.setCurrentItem(it)
                break

    def _filter_group_list_items(self, text: str):
        query = text.strip().lower()
        for i in range(self.group_list.count()):
            it = self.group_list.item(i)
            role_data = str(it.data(Qt.UserRole) or "")
            item_text = it.text().lower()

            if not query or role_data == "__ALL__" or query in item_text or query in role_data.lower():
                it.setHidden(False)
            else:
                it.setHidden(True)

    @Slot(QListWidgetItem, QListWidgetItem)
    def _on_item_changed(self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]):
        if not current:
            return
        group = current.data(Qt.UserRole) or "__ALL__"
        self.group_selected.emit(group)

    @Slot()
    def _on_bulk_optimize_clicked(self):
        self.bulk_optimize_requested.emit(self.get_selected_group())

    @Slot()
    def _on_bulk_subfolder_clicked(self):
        self.bulk_subfolder_requested.emit(self.get_selected_group())

    def apply_permissions(self, role: str):
        """
        Role-Based Access Control (RBAC):
        'admin': Full access.
        'operator': Can filter and optimize, but cannot manage groups.
        'viewer': Read-only filtering, bulk actions disabled.
        """
        self._current_role = role.lower()
        is_admin = self._current_role == "admin"
        is_viewer = self._current_role == "viewer"

        self.btn_open_group_mgmt.setEnabled(is_admin)
        self.btn_bulk_optimize.setEnabled(not is_viewer)
        self.btn_bulk_subfolder.setEnabled(is_admin)

        if is_viewer:
            self.sec_bulk.setVisible(False)
        else:
            self.sec_bulk.setVisible(True)
