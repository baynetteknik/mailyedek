"""
account_panel.py — Account management panel with 3-column ergonomic layout:
- Left Modular Domain/Group Filter & Bulk Action Sidebar (AccountGroupSidebarWidget)
- Middle Edge Small Arrow Toggle Buttons for Left & Right sidebars
- Center Grid with Toya ERP right-click layout management (column widths, row heights, column visibility)
- Right Action Drawer for Operations, Profiles, and Excel Inline Editing (AccountRightSidebarWidget)
- Full Role-Based Access Control (RBAC) support & High Contrast Typography
"""

import logging
import threading
from typing import Optional, Dict, List, Any
from pathlib import Path

from PySide6.QtCore import Qt, Slot, QPoint, QThread, Signal, QSize
from PySide6.QtGui import QAction, QColor, QFont, QCursor, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QMessageBox, QGroupBox,
    QFrame, QProgressBar, QDialog, QFileDialog, QLineEdit,
    QInputDialog, QMenu, QApplication
)

from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.dialogs.account_dialog import AccountDialog
from gui.dialogs.bulk_import_dialog import BulkImportDialog
from gui.widgets.account_group_sidebar_widget import AccountGroupSidebarWidget
from gui.widgets.account_right_sidebar_widget import AccountRightSidebarWidget
from gui.widgets.view_profile_widget import SaveLayoutProfileDialog, ColumnManagerDialog

logger = logging.getLogger(__name__)


class EmlImportWorker(QThread):
    progress = Signal(int, str)  # percentage, message
    finished = Signal(int, int)  # imported_count, skipped_count

    def __init__(self, engine, account_id, folder_path):
        super().__init__()
        self.engine = engine
        self.account_id = account_id
        self.folder_path = Path(folder_path)

    def run(self):
        import os
        import email
        import hashlib
        import re
        from email.parser import BytesParser
        from email import policy

        eml_files = []
        try:
            for root, dirs, files in os.walk(self.folder_path):
                for file in files:
                    if file.lower().endswith(".eml"):
                        eml_files.append(Path(root) / file)
        except Exception as e:
            logger.error("Failed to walk folder path: %s", e)
            self.finished.emit(0, 0)
            return

        total = len(eml_files)
        if total == 0:
            self.finished.emit(0, 0)
            return

        imported_count = 0
        skipped_count = 0
        folder_max_uids = {}  # folder_name -> max_uid

        for i, file_path in enumerate(eml_files):
            if i % 10 == 0 or i == total - 1:
                self.progress.emit(
                    int((i + 1) * 100 / total),
                    f"Taranıyor: {i+1} / {total} - {file_path.name[:30]}"
                )

            folder_name = file_path.parent.name
            if not folder_name or folder_name.lower() in ("mails", "data"):
                folder_name = "INBOX"

            filename = file_path.name
            uid = None
            match = re.match(r'^\d{8}_\d{6}_(\d+)_', filename)
            if match:
                uid = int(match.group(1))
            else:
                parts = filename.split('_')
                for part in parts:
                    if part.isdigit():
                        uid = int(part)
                        break

            if uid is None:
                skipped_count += 1
                continue

            try:
                existing = self.engine.db.get_mail_by_uid(self.account_id, folder_name, uid)
                if existing:
                    skipped_count += 1
                    if folder_name not in folder_max_uids or uid > folder_max_uids[folder_name]:
                        folder_max_uids[folder_name] = uid
                    continue

                with open(file_path, "rb") as f:
                    raw_bytes = f.read()

                sha256 = hashlib.sha256(raw_bytes).hexdigest()
                is_dup = self.engine.db.is_duplicate_hash(sha256)

                msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
                subject = msg.get("subject", "")
                sender = msg.get("from", "")
                recipients = msg.get("to", "")
                cc = msg.get("cc", "") or ""
                bcc = msg.get("bcc", "") or ""
                message_id = msg.get("message-id", "")
                date_header = msg.get("date", "")

                mail_id = self.engine.db.upsert_mail_metadata(
                    account_id=self.account_id,
                    folder=folder_name,
                    uid=uid,
                    subject=subject,
                    sender=sender,
                    recipients=recipients,
                    cc=cc,
                    bcc=bcc,
                    message_id=message_id,
                    date=date_header,
                    size_bytes=len(raw_bytes),
                    sha256_hash=sha256,
                    is_duplicate=1 if is_dup else 0
                )

                self.engine.db.register_hash(sha256, self.account_id, mail_id)

                if folder_name not in folder_max_uids or uid > folder_max_uids[folder_name]:
                    folder_max_uids[folder_name] = uid

                imported_count += 1
            except Exception as e:
                logger.error("Failed to import EML %s: %s", file_path, e)
                skipped_count += 1

        for folder_name, max_uid in folder_max_uids.items():
            try:
                existing_state = self.engine.db.get_sync_state(self.account_id, folder_name)
                uid_val = existing_state.get("uid_validity", 0) if existing_state else 0
                mail_cnt = existing_state.get("mail_count", 0) if existing_state else 0
                current_last_uid = existing_state.get("last_uid", 0) if existing_state else 0
                if max_uid > current_last_uid:
                    self.engine.db.update_sync_state(
                        self.account_id, folder_name, max_uid, uid_val, mail_cnt + imported_count
                    )
            except Exception as e:
                logger.error("Failed to update sync state for folder %s: %s", folder_name, e)

        try:
            self.engine.db.rebuild_fts_index()
        except Exception as e:
            logger.error("Failed to rebuild FTS: %s", e)

        self.finished.emit(imported_count, skipped_count)


class AccountPanel(QWidget):
    """
    Account management with 3-column layout:
    - Left Sidebar: AccountGroupSidebarWidget
    - Middle Small Arrow Toggle Buttons
    - Center Table: Toya ERP Context Menu DBGrid
    - Right Sidebar: AccountRightSidebarWidget
    """

    def __init__(self, engine: MailEngine, parent=None, settings: AppSettings = None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings or AppSettings()
        self._active_optimizer = None
        self._excel_editing_enabled = False
        self._is_refreshing = False
        self._current_row_height = 36
        self._current_role = "admin"
        self._cached_accounts = []

        self._setup_ui()
        self._connect_signals()
        self.refresh()

    def _setup_ui(self):
        main_vbox = QVBoxLayout(self)
        main_vbox.setContentsMargins(10, 8, 10, 8)
        main_vbox.setSpacing(6)

        # -------------------------------------------------------------
        # TOP TOOLBAR: Minimalist & Ergonomic
        # -------------------------------------------------------------
        self.top_bar = QFrame()
        self.top_bar.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 4px;
            }
        """)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(8, 4, 8, 4)
        top_layout.setSpacing(8)

        # Left Sidebar Toggle
        self.btn_toggle_left = QPushButton("◀ Grupları Gizle")
        self.btn_toggle_left.setToolTip("Sol Grup/Domain filtre panelini gizler/gösterir")
        self.btn_toggle_left.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_left.setStyleSheet(self._toggle_btn_style())
        self.btn_toggle_left.clicked.connect(self._toggle_left_sidebar)
        top_layout.addWidget(self.btn_toggle_left)

        # Instant Search Box
        self.txt_search_accounts = QLineEdit()
        self.txt_search_accounts.setPlaceholderText("🔍 Hesap Adı, E-Posta, IMAP Sunucu veya Grup Ara...")
        self.txt_search_accounts.setClearButtonEnabled(True)
        self.txt_search_accounts.setStyleSheet("""
            QLineEdit {
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 5px 10px;
                background-color: #f8fafc;
                color: #0f172a;
                font-size: 11.5px;
            }
            QLineEdit:focus {
                border-color: #2563eb;
                background-color: #ffffff;
            }
        """)
        self.txt_search_accounts.textChanged.connect(self._filter_table_rows)
        top_layout.addWidget(self.txt_search_accounts, stretch=1)

        # Statistics Badges
        self.lbl_stat_total = QLabel("📊 0 Hesap")
        self.lbl_stat_total.setStyleSheet(self._badge_style(bg="#e0e7ff", fg="#1e3a8a"))
        top_layout.addWidget(self.lbl_stat_total)

        self.lbl_stat_active = QLabel("🟢 0 Aktif")
        self.lbl_stat_active.setStyleSheet(self._badge_style(bg="#dcfce7", fg="#15803d"))
        top_layout.addWidget(self.lbl_stat_active)

        # Optimizer status button (dynamic)
        self.btn_active_opt_status = QPushButton("🔄 Optimizasyon Çalışıyor")
        self.btn_active_opt_status.setVisible(False)
        self.btn_active_opt_status.setStyleSheet("background-color: #f59e0b; color: #ffffff; font-weight: bold; border-radius: 6px; padding: 4px 10px; font-size: 11px;")
        self.btn_active_opt_status.clicked.connect(self._restore_active_optimizer)
        top_layout.addWidget(self.btn_active_opt_status)

        # Refresh button
        self.btn_refresh = QPushButton("🔄 Yenile")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #1e3a8a;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 11.5px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #f1f5f9; border-color: #2563eb; }
        """)
        self.btn_refresh.clicked.connect(self.refresh)
        top_layout.addWidget(self.btn_refresh)

        # Right Sidebar Toggle
        self.btn_toggle_right = QPushButton("⚙️ İşlemler ▶")
        self.btn_toggle_right.setToolTip("Sağ işlem ve ayar çekmecesini gizler/gösterir")
        self.btn_toggle_right.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_right.setStyleSheet(self._toggle_btn_style())
        self.btn_toggle_right.clicked.connect(self._toggle_right_sidebar)
        top_layout.addWidget(self.btn_toggle_right)

        main_vbox.addWidget(self.top_bar)

        # Testing Progress & Status
        self.test_progress = QProgressBar()
        self.test_progress.setVisible(False)
        self.test_progress.setMaximumHeight(3)
        self.test_progress.setTextVisible(False)
        main_vbox.addWidget(self.test_progress)

        self.test_status = QLabel("")
        self.test_status.setVisible(False)
        self.test_status.setStyleSheet("font-size: 11px; font-weight: 600; padding: 2px 4px; color: #1e293b;")
        main_vbox.addWidget(self.test_status)

        # -------------------------------------------------------------
        # 3-COLUMN SPLIT LAYOUT + MIDDLE ARROW BUTTONS
        # -------------------------------------------------------------
        split_layout = QHBoxLayout()
        split_layout.setSpacing(2)
        split_layout.setContentsMargins(0, 0, 0, 0)

        # 1. Left Sidebar: Group / Domain Widget
        self.left_sidebar = AccountGroupSidebarWidget(self)
        self.left_sidebar.setFixedWidth(230)
        split_layout.addWidget(self.left_sidebar)

        # Middle Arrow Toggle Button for Left Sidebar
        self.btn_middle_toggle_left = QPushButton("◀")
        self.btn_middle_toggle_left.setToolTip("Sol Filtre Panelini Gizle / Göster")
        self.btn_middle_toggle_left.setFixedWidth(16)
        self.btn_middle_toggle_left.setCursor(Qt.PointingHandCursor)
        self.btn_middle_toggle_left.setStyleSheet("""
            QPushButton {
                background-color: #e2e8f0;
                color: #334155;
                border: 1px solid #cbd5e1;
                border-left: none;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                font-weight: bold;
                font-size: 10px;
                padding: 0px;
                min-height: 50px;
                max-height: 50px;
            }
            QPushButton:hover {
                background-color: #2563eb;
                color: #ffffff;
                border-color: #1d4ed8;
            }
        """)
        self.btn_middle_toggle_left.clicked.connect(self._toggle_left_sidebar)
        split_layout.addWidget(self.btn_middle_toggle_left)

        # 2. Center: Table Grid
        table_container = QGroupBox("📮 Kayıtlı E-Posta (Mail) Hesapları Listesi")
        table_container.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #1e3a8a;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 14px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 3px 10px;
                background-color: #1e3a8a;
                color: #ffffff !important;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        center_layout = QVBoxLayout(table_container)
        center_layout.setContentsMargins(6, 8, 6, 6)

        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels([
            "ID", "Hesap Adı (Label)", "E-Posta Adresi", "IMAP Sunucu", "Port", "SSL", "Durum", "Depolama", "Alt Klasör", "Domain Grubu", "Son Güncelleme", "Hızlı İşlemler"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)

        # High Contrast Professional DBGrid Header & Cells
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #f8fafc;
                gridline-color: #e2e8f0;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                color: #0f172a;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
                font-size: 11.5px;
            }
            QTableWidget::item {
                padding: 4px 8px;
                border-bottom: 1px solid #f1f5f9;
                color: #0f172a;
            }
            QTableWidget::item:selected {
                background-color: #2563eb;
                color: #ffffff !important;
            }
            QHeaderView::section {
                background-color: #1e3a8a;
                color: #ffffff !important;
                font-weight: 700;
                font-size: 11.5px;
                border: 1px solid #1e40af;
                padding: 6px 8px;
                min-height: 32px;
                height: 32px;
            }
            QHeaderView::section:hover {
                background-color: #2563eb;
            }
        """)

        # Connect Context Menus (Toya ERP Right Click Menus)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_toya_grid_context_menu)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self._show_toya_grid_context_menu)
        self.table.horizontalHeader().sectionResized.connect(self._auto_save_current_layout)
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(self._on_table_double_clicked)

        center_layout.addWidget(self.table)
        split_layout.addWidget(table_container, stretch=1)

        # Middle Arrow Toggle Button for Right Sidebar
        self.btn_middle_toggle_right = QPushButton("▶")
        self.btn_middle_toggle_right.setToolTip("Sağ İşlem Çekmecesini Gizle / Göster")
        self.btn_middle_toggle_right.setFixedWidth(16)
        self.btn_middle_toggle_right.setCursor(Qt.PointingHandCursor)
        self.btn_middle_toggle_right.setStyleSheet("""
            QPushButton {
                background-color: #e2e8f0;
                color: #334155;
                border: 1px solid #cbd5e1;
                border-right: none;
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                font-weight: bold;
                font-size: 10px;
                padding: 0px;
                min-height: 50px;
                max-height: 50px;
            }
            QPushButton:hover {
                background-color: #2563eb;
                color: #ffffff;
                border-color: #1d4ed8;
            }
        """)
        self.btn_middle_toggle_right.clicked.connect(self._toggle_right_sidebar)
        split_layout.addWidget(self.btn_middle_toggle_right)

        # 3. Right Sidebar: Action Drawer & Profile Manager
        self.right_sidebar = AccountRightSidebarWidget(self)
        self.right_sidebar.setFixedWidth(260)
        split_layout.addWidget(self.right_sidebar)

        main_vbox.addLayout(split_layout, stretch=1)

    def _connect_signals(self):
        # Left sidebar signals
        self.left_sidebar.group_selected.connect(self._on_group_filter_changed)
        self.left_sidebar.bulk_optimize_requested.connect(self._on_bulk_optimize)
        self.left_sidebar.bulk_subfolder_requested.connect(self._on_bulk_subfolder)
        self.left_sidebar.group_mgmt_requested.connect(self._open_group_management)

        # Right sidebar signals
        self.right_sidebar.add_requested.connect(self._add_account)
        self.right_sidebar.edit_requested.connect(self._edit_account)
        self.right_sidebar.copy_requested.connect(self._copy_account)
        self.right_sidebar.delete_requested.connect(self._delete_account)
        self.right_sidebar.toggle_active_requested.connect(self._toggle_active)
        self.right_sidebar.test_requested.connect(self._test_selected)
        self.right_sidebar.bulk_import_requested.connect(self._bulk_import)
        self.right_sidebar.scan_disk_requested.connect(self._on_scan_storage_disk)
        self.right_sidebar.import_eml_requested.connect(self._on_import_eml)
        self.right_sidebar.clean_start_requested.connect(self._clean_start)
        self.right_sidebar.excel_mode_toggled.connect(self._on_excel_mode_toggled)
        self.right_sidebar.row_height_changed.connect(lambda h: self.set_row_height(h, auto_save=True))

        # Right sidebar view profile signals
        self.right_sidebar.profile_selected.connect(self._on_grid_profile_selected)
        self.right_sidebar.save_profile_requested.connect(self._save_grid_profile)
        self.right_sidebar.columns_requested.connect(self._open_column_manager_dialog)

    # -------------------------------------------------------------
    # Sidebar Toggles & Middle Arrow Synchronizers
    # -------------------------------------------------------------

    def _toggle_left_sidebar(self):
        is_hidden = self.left_sidebar.isHidden()
        self.left_sidebar.setHidden(not is_hidden)
        
        logo_path = Path("gui/resources/toya_logo.png")
        if not logo_path.exists():
            logo_path = Path("C:/xampp/htdocs/toya/assets/smarty/images/manifest/icon_192x192.png")

        if not is_hidden:
            # Now became collapsed (hidden)
            if logo_path.exists():
                self.btn_toggle_left.setIcon(QIcon(str(logo_path)))
                self.btn_toggle_left.setIconSize(QSize(18, 18))
                self.btn_toggle_left.setText(" TOYA ERP | Grupları Aç")
                self.btn_middle_toggle_left.setIcon(QIcon(str(logo_path)))
                self.btn_middle_toggle_left.setIconSize(QSize(14, 14))
                self.btn_middle_toggle_left.setText("")
                self.btn_middle_toggle_left.setFixedWidth(24)
            else:
                self.btn_toggle_left.setIcon(QIcon())
                self.btn_toggle_left.setText("▶ Grupları Aç")
                self.btn_middle_toggle_left.setIcon(QIcon())
                self.btn_middle_toggle_left.setText("▶")
                self.btn_middle_toggle_left.setFixedWidth(16)
            self.btn_middle_toggle_left.setToolTip("TOYA ERP - Sol Filtre Panelini Aç")
            self.btn_toggle_left.setStyleSheet(self._toggle_btn_style(active=True))
        else:
            # Now became expanded (visible)
            self.btn_toggle_left.setIcon(QIcon())
            self.btn_toggle_left.setText("◀ Grupları Gizle")
            self.btn_middle_toggle_left.setIcon(QIcon())
            self.btn_middle_toggle_left.setText("◀")
            self.btn_middle_toggle_left.setFixedWidth(16)
            self.btn_middle_toggle_left.setToolTip("Sol Filtre Panelini Gizle")
            self.btn_toggle_left.setStyleSheet(self._toggle_btn_style(active=False))

    def _toggle_right_sidebar(self):
        is_hidden = self.right_sidebar.isHidden()
        self.right_sidebar.setHidden(not is_hidden)
        self.btn_toggle_right.setText("⚙️ İşlemleri Aç ▶" if not is_hidden else "⚙️ İşlemleri Gizle ◀")
        self.btn_middle_toggle_right.setText("▶" if not is_hidden else "◀")

    # -------------------------------------------------------------
    # TOYA ERP Grid Layout & Context Menu (Navy #1e3a8a Standard)
    # -------------------------------------------------------------

    @Slot(QPoint)
    def _show_toya_grid_context_menu(self, pos: QPoint):
        """
        TOYA ERP Professional DBGrid Context Menu.
        """
        sender = self.sender()
        is_header = (sender == self.table.horizontalHeader())

        global_pos = sender.mapToGlobal(pos) if sender else QCursor.pos()
        row = self.table.rowAt(pos.y()) if not is_header else -1

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e3a8a;
                color: #ffffff;
                border: 1.5px solid #1e40af;
                border-radius: 8px;
                padding: 6px;
                font-weight: 600;
                font-size: 11.5px;
            }
            QMenu::item {
                padding: 6px 22px 6px 12px;
                border-radius: 4px;
                color: #ffffff;
            }
            QMenu::item:selected {
                background-color: #2563eb;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background-color: #3b82f6;
                margin: 4px 6px;
            }
        """)

        # 1. Row Specific Actions (if clicked on a row)
        server_actions = {}
        acc_id_str = ""
        if row >= 0 and not is_header:
            id_item = self.table.item(row, 0)
            if id_item:
                acc_id_str = id_item.text()
                act_edt = menu.addAction("✏️ Hesabı Düzenle")
                act_edt.triggered.connect(self._edit_account)

                act_cpy = menu.addAction("📋 Hesabı Çoğalt (Kopyala)")
                act_cpy.triggered.connect(self._copy_account)

                act_tst = menu.addAction("🔌 Bağlantıyı Test Et")
                act_tst.triggered.connect(self._test_selected)

                if acc_id_str.isdigit():
                    acc_id = int(acc_id_str)
                    profiles = self.engine.list_server_profiles(acc_id)
                    if profiles and len(profiles) > 1:
                        menu_servers = menu.addMenu("🔌 Aktif Sunucuyu Seç")
                        menu_servers.setStyleSheet(menu.styleSheet())
                        for p in profiles:
                            prefix = "★ " if p.get("is_default") else "  "
                            act_p = menu_servers.addAction(f"{prefix}{p.get('profile_name')} ({p.get('imap_host')})")
                            server_actions[act_p] = p["id"]

                menu.addSeparator()
                act_cp_email = menu.addAction("📋 E-Posta Adresini Kopyala")
                act_cp_email.triggered.connect(lambda: self._copy_email_to_clipboard(row))

                act_del = menu.addAction("🗑️ Hesabı Sil")
                act_del.triggered.connect(self._delete_account)

                menu.addSeparator()

        # 2. TOYA ERP Layout Management Section
        title_layout = menu.addAction("⚙️ TOYA ERP GRID & GÖRÜNÜM DÜZENİ")
        title_layout.setEnabled(False)

        act_save_layout = menu.addAction("💾 Görünüm Düzenini Kaydet")
        act_save_layout.triggered.connect(self._save_current_layout_dialog)

        # Registered Layouts Submenu
        menu_profiles = menu.addMenu("📂 Kayıtlı Görünüm Düzenleri")
        menu_profiles.setStyleSheet(menu.styleSheet())
        profile_names = self.right_sidebar.view_profile_widget.manager.get_profile_names()
        active_prof = self.right_sidebar.view_profile_widget.get_current_profile_name()

        for p_name in profile_names:
            p_prefix = "✔ " if p_name == active_prof else "  "
            act_p = menu_profiles.addAction(f"{p_prefix}{p_name}")
            act_p.triggered.connect(lambda chk=False, name=p_name: self._apply_named_profile(name))

        # Row Height Menu (Satır Yüksekliği Ayarla)
        menu_row_h = menu.addMenu("📏 Satır Yüksekliği Ayarla")
        menu_row_h.setStyleSheet(menu.styleSheet())

        h_presets = [
            ("Kompakt (28 px)", 28),
            ("Normal (36 px)", 36),
            ("Standart (44 px)", 44),
            ("Geniş (54 px)", 54),
        ]
        for h_label, h_val in h_presets:
            h_prefix = "✔ " if self._current_row_height == h_val else "  "
            act_h = menu_row_h.addAction(f"{h_prefix}{h_label}")
            act_h.triggered.connect(lambda chk=False, val=h_val: self.set_row_height(val, auto_save=True))

        act_custom_h = menu_row_h.addAction("✏️ Özel Yükseklik Gir (px)...")
        act_custom_h.triggered.connect(self._prompt_custom_row_height)

        # Column Visibility Submenu
        menu_cols = menu.addMenu("👁️ Sütun Görünürlüğü (Kolon Aç/Kapa)")
        menu_cols.setStyleSheet(menu.styleSheet())

        for col in range(self.table.columnCount()):
            header_item = self.table.horizontalHeaderItem(col)
            label = header_item.text() if header_item else f"Kolon {col+1}"
            act_col = QAction(label, menu_cols)
            act_col.setCheckable(True)
            act_col.setChecked(not self.table.isColumnHidden(col))
            act_col.triggered.connect(lambda checked, c=col: self._toggle_column_visibility(c, checked))
            menu_cols.addAction(act_col)

        menu.addSeparator()
        act_reset = menu.addAction("🔄 Varsayılan Düzene Sıfırla")
        act_reset.triggered.connect(self._reset_grid_layout_to_default)

        # Exec menu
        chosen = menu.exec(global_pos)
        if chosen in server_actions and acc_id_str.isdigit():
            prof_id = server_actions[chosen]
            self.engine.set_default_server_profile(int(acc_id_str), prof_id)
            self.refresh()

    def _copy_email_to_clipboard(self, row: int):
        item = self.table.item(row, 2)
        if item:
            QApplication.clipboard().setText(item.text().strip())
            self.test_status.setVisible(True)
            self.test_status.setText(f"📋 '{item.text().strip()}' panoya kopyalandı.")

    def set_row_height(self, height: int, auto_save: bool = True):
        """Sets the height for all rows in the grid and persists in settings."""
        self._current_row_height = max(20, min(120, height))
        self.table.verticalHeader().setDefaultSectionSize(self._current_row_height)
        for r in range(self.table.rowCount()):
            self.table.setRowHeight(r, self._current_row_height)

        if auto_save:
            self._auto_save_current_layout()

    def _prompt_custom_row_height(self):
        val, ok = QInputDialog.getInt(
            self, "Satır Yüksekliği Ayarla",
            "Lütfen satır yüksekliğini piksel (px) cinsinden girin (20 - 120):",
            self._current_row_height, 20, 120, 1
        )
        if ok:
            self.set_row_height(val, auto_save=True)

    def _toggle_column_visibility(self, col: int, visible: bool):
        self.table.setColumnHidden(col, not visible)
        self._auto_save_current_layout()

    def _open_column_manager_dialog(self):
        """Dialog to toggle column visibilities with search and checkboxes."""
        columns = [self.table.horizontalHeaderItem(col).text() for col in range(self.table.columnCount())]
        hidden = [col for col in range(self.table.columnCount()) if self.table.isColumnHidden(col)]
        dlg = ColumnManagerDialog(columns, hidden, parent=self)
        if dlg.exec() == QDialog.Accepted:
            new_hidden = set(dlg.get_hidden_columns())
            for col in range(self.table.columnCount()):
                self.table.setColumnHidden(col, col in new_hidden)
            self._auto_save_current_layout()

    # -------------------------------------------------------------
    # Profile Persistence
    # -------------------------------------------------------------

    def _get_current_layout_state(self) -> Dict[str, Any]:
        return {
            "hidden_columns": [c for c in range(self.table.columnCount()) if self.table.isColumnHidden(c)],
            "column_widths": [self.table.columnWidth(c) for c in range(self.table.columnCount())],
            "row_height": self._current_row_height,
        }

    def _auto_save_current_layout(self, *args):
        if self._is_refreshing:
            return
        active_profile = self.right_sidebar.view_profile_widget.get_current_profile_name()
        state = self._get_current_layout_state()
        self.right_sidebar.view_profile_widget.manager.save_profile(active_profile, state, set_active=True)

    def _save_grid_profile(self, profile_name: str):
        state = self._get_current_layout_state()
        self.right_sidebar.view_profile_widget.manager.save_profile(profile_name, state, set_active=True)
        self.right_sidebar.view_profile_widget.reload_profiles()
        self.test_status.setVisible(True)
        self.test_status.setText(f"💾 '{profile_name}' görünüm düzeni başarıyla kaydedildi.")

    def _save_current_layout_dialog(self):
        current_name = self.right_sidebar.view_profile_widget.get_current_profile_name()
        existing_names = self.right_sidebar.view_profile_widget.manager.get_profile_names()
        dialog = SaveLayoutProfileDialog(
            existing_profiles=existing_names,
            current_profile=current_name,
            parent=self
        )
        if dialog.exec() == QDialog.Accepted and dialog.selected_profile_name:
            chosen_name = dialog.selected_profile_name
            self._save_grid_profile(chosen_name)
            self.right_sidebar.view_profile_widget.reload_profiles()
            idx = self.right_sidebar.view_profile_widget.combo_profiles.findText(chosen_name)
            if idx >= 0:
                self.right_sidebar.view_profile_widget.combo_profiles.setCurrentIndex(idx)

    def _apply_named_profile(self, name: str):
        state = self.right_sidebar.view_profile_widget.manager.get_profile(name)
        if state:
            self._apply_grid_profile_state(name, state)

    @Slot(str, dict)
    def _on_grid_profile_selected(self, name: str, state: dict):
        self._apply_grid_profile_state(name, state)

    def _apply_grid_profile_state(self, name: str, state: dict):
        if not state:
            return
        self.table.horizontalHeader().blockSignals(True)

        hidden = state.get("hidden_columns", [])
        widths = state.get("column_widths", [])
        row_h = state.get("row_height", 36)

        for col in range(self.table.columnCount()):
            if col < len(widths) and widths[col] > 10:
                self.table.setColumnWidth(col, widths[col])
            self.table.setColumnHidden(col, col in hidden)

        self.table.horizontalHeader().blockSignals(False)
        self.set_row_height(row_h, auto_save=False)

    def _reset_grid_layout_to_default(self):
        for col in range(self.table.columnCount()):
            self.table.setColumnHidden(col, False)
        self.table.resizeColumnsToContents()
        self.set_row_height(36, auto_save=True)
        self.right_sidebar.view_profile_widget.reload_profiles()
        self.test_status.setVisible(True)
        self.test_status.setText("🔄 Tablo görünüm düzeni varsayılana sıfırlandı.")

    # -------------------------------------------------------------
    # Table Population & Filtering
    # -------------------------------------------------------------

    def refresh(self):
        self._is_refreshing = True
        try:
            # 1. Retrieve accounts from database
            all_accounts = self.engine.list_accounts()
            self._cached_accounts = all_accounts

            # 2. Extract and organize domain groups with count
            groups_data = {}
            for acc in all_accounts:
                g_val = acc.get("account_group", "").strip()
                if not g_val and "@" in acc.get("email", ""):
                    g_val = acc["email"].split("@")[-1].strip()
                if not g_val:
                    g_val = "Diğer"

                if g_val not in groups_data:
                    groups_data[g_val] = {"is_active": True, "count": 0}
                groups_data[g_val]["count"] += 1

            # Populate Left Sidebar
            self.left_sidebar.populate_groups(groups_data, total_accounts_count=len(all_accounts))

            # Update Header Statistics Badges
            active_cnt = sum(1 for a in all_accounts if bool(a.get("is_active", True)))
            self.lbl_stat_total.setText(f"📊 {len(all_accounts)} Hesap")
            self.lbl_stat_active.setText(f"🟢 {active_cnt} Aktif")

            # 3. Filter accounts based on Left Sidebar selection
            selected_group = self.left_sidebar.get_selected_group()
            filtered_accounts = []
            for acc in all_accounts:
                g_val = acc.get("account_group", "").strip()
                if not g_val and "@" in acc.get("email", ""):
                    g_val = acc["email"].split("@")[-1].strip()
                if not g_val:
                    g_val = "Diğer"

                if selected_group == "__ALL__" or g_val == selected_group:
                    filtered_accounts.append(acc)

            # 4. Fill Table
            self.table.setRowCount(len(filtered_accounts))
            for i, acc in enumerate(filtered_accounts):
                self.table.setItem(i, 0, QTableWidgetItem(str(acc["id"])))
                self.table.setItem(i, 1, QTableWidgetItem(acc.get("label", "")))
                self.table.setItem(i, 2, QTableWidgetItem(acc.get("email", "")))
                self.table.setItem(i, 3, QTableWidgetItem(acc.get("imap_host", "")))
                self.table.setItem(i, 4, QTableWidgetItem(str(acc.get("imap_port", ""))))
                self.table.setItem(i, 5, QTableWidgetItem("Yes" if acc.get("use_ssl") else "No"))

                is_active = bool(acc.get("is_active", True))
                status_text = "✅ Aktif" if is_active else "⏸ Pasif"
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(QColor("#16a34a") if is_active else QColor("#94a3b8"))
                self.table.setItem(i, 6, status_item)

                # Storage location
                stor_name = self.settings.account_storage(acc["id"]) or "Default"
                self.table.setItem(i, 7, QTableWidgetItem(stor_name))

                # Export Subfolder
                self.table.setItem(i, 8, QTableWidgetItem(acc.get("export_subfolder", "")))

                # Group / Domain
                self.table.setItem(i, 9, QTableWidgetItem(acc.get("account_group", "")))

                updated = (acc.get("updated_at") or "")[:19]
                self.table.setItem(i, 10, QTableWidgetItem(updated))

                # Fast Action Row Buttons (Column 11)
                action_widget = QWidget()
                action_layout = QHBoxLayout(action_widget)
                action_layout.setContentsMargins(2, 2, 2, 2)
                action_layout.setSpacing(4)

                btn_opt = QPushButton("⚙️ Optimize")
                btn_opt.setStyleSheet("background-color: #f59e0b; color: #ffffff !important; border: none; border-radius: 4px; font-size: 10.5px; font-weight: bold; min-height: 22px; padding: 2px 6px;")
                btn_opt.clicked.connect(lambda checked=False, aid=acc["id"]: self._optimize_single_account(aid))
                action_layout.addWidget(btn_opt)

                btn_sub = QPushButton("📂 Klasör")
                btn_sub.setStyleSheet("background-color: #3b82f6; color: #ffffff !important; border: none; border-radius: 4px; font-size: 10.5px; font-weight: bold; min-height: 22px; padding: 2px 6px;")
                btn_sub.clicked.connect(lambda checked=False, aid=acc["id"]: self._edit_single_subfolder(aid))
                action_layout.addWidget(btn_sub)

                btn_cpy = QPushButton("📋 Kopyala")
                btn_cpy.setStyleSheet("background-color: #10b981; color: #ffffff !important; border: none; border-radius: 4px; font-size: 10.5px; font-weight: bold; min-height: 22px; padding: 2px 6px;")
                btn_cpy.clicked.connect(lambda checked=False, aid=acc["id"]: self._copy_account(aid))
                action_layout.addWidget(btn_cpy)

                action_layout.addStretch()
                self.table.setCellWidget(i, 11, action_widget)

                # Set cell editability based on Excel mode
                editable_cols = [1, 2, 3, 4, 5, 6, 8, 9]
                for c_idx in editable_cols:
                    it = self.table.item(i, c_idx)
                    if it:
                        if self._excel_editing_enabled:
                            it.setFlags(it.flags() | Qt.ItemIsEditable)
                        else:
                            it.setFlags(it.flags() & ~Qt.ItemIsEditable)

            # Apply layout profile & row heights
            self.set_row_height(self._current_row_height, auto_save=False)
            active_profile = self.right_sidebar.view_profile_widget.get_current_profile_name()
            state = self.right_sidebar.view_profile_widget.manager.get_profile(active_profile)
            if state:
                self._apply_grid_profile_state(active_profile, state)
            else:
                self.table.resizeColumnsToContents()

            self._filter_table_rows(self.txt_search_accounts.text())
        except Exception as exc:
            logger.exception("AccountPanel refresh error: %s", exc)
        finally:
            self._is_refreshing = False

    @Slot(str)
    def _on_group_filter_changed(self, group_name: str):
        self.refresh()

    def _filter_table_rows(self, query_text: str):
        query = query_text.strip().lower()
        for r in range(self.table.rowCount()):
            if not query:
                self.table.setRowHidden(r, False)
                continue

            row_match = False
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if item and query in item.text().lower():
                    row_match = True
                    break

            self.table.setRowHidden(r, not row_match)

    # -------------------------------------------------------------
    # Selection & Excel Inline Editing
    # -------------------------------------------------------------

    @Slot()
    def _on_selection_changed(self):
        row = self.table.currentRow()
        has_sel = row >= 0
        is_active = True

        if has_sel:
            id_item = self.table.item(row, 0)
            if id_item and id_item.text().isdigit():
                acc = self.engine.accounts.get(int(id_item.text()))
                if acc:
                    is_active = bool(acc.get("is_active", True))

        self.right_sidebar.update_selection_state(has_sel, is_active=is_active)

    def _on_table_double_clicked(self):
        if not self._excel_editing_enabled:
            self._edit_account()

    @Slot(bool)
    def _on_excel_mode_toggled(self, enabled: bool):
        self._excel_editing_enabled = enabled
        if enabled:
            self.table.setEditTriggers(
                QTableWidget.DoubleClicked | QTableWidget.AnyKeyPressed | QTableWidget.EditKeyPressed | QTableWidget.SelectedClicked
            )
            self.test_status.setVisible(True)
            self.test_status.setText("⚡ Excel Tipi Canlı Düzenleme AÇIK — Hücreye çift tıklayıp yazarak Enter'a basın, anında güncellenir.")
        else:
            self.table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.test_status.setVisible(True)
            self.test_status.setText("⚡ Excel Tipi Canlı Düzenleme Kapalı.")
        self.refresh()

    @Slot(QTableWidgetItem)
    def _on_table_item_changed(self, item: QTableWidgetItem):
        if not getattr(self, "_excel_editing_enabled", False) or getattr(self, "_is_refreshing", False):
            return

        row = item.row()
        col = item.column()
        id_item = self.table.item(row, 0)
        if not id_item or not id_item.text().isdigit():
            return

        acc_id = int(id_item.text())
        acc = self.engine.accounts.get(acc_id)
        if not acc:
            return

        val = item.text().strip()
        update_field = ""

        try:
            if col == 1:  # Label
                self.engine.accounts.update(acc_id, label=val)
                update_field = f"Hesap Adı: '{val}'"
            elif col == 2:  # Email
                self.engine.accounts.update(acc_id, email=val)
                update_field = f"E-Posta: '{val}'"
            elif col == 3:  # IMAP Host
                self.engine.accounts.update(acc_id, imap_host=val)
                update_field = f"IMAP Sunucu: '{val}'"
            elif col == 4:  # IMAP Port
                try:
                    port = int(val)
                    self.engine.accounts.update(acc_id, imap_port=port)
                    update_field = f"IMAP Port: '{port}'"
                except ValueError:
                    QMessageBox.warning(self, "Hatalı Değer", "Port numarası sayısal bir değer olmalıdır.")
                    self.refresh()
                    return
            elif col == 5:  # SSL
                use_ssl = 1 if val.lower() in ("yes", "evet", "1", "true") else 0
                self.engine.accounts.update(acc_id, use_ssl=use_ssl)
                update_field = f"SSL Kullanımı: {'Evet' if use_ssl else 'Hayır'}"
            elif col == 6:  # Status
                is_active = 1 if "active" in val.lower() or "aktif" in val.lower() or val.lower() in ("1", "true") else 0
                self.engine.accounts.update(acc_id, is_active=is_active)
                update_field = f"Hesap Durumu: {'Aktif' if is_active else 'Pasif'}"
            elif col == 8:  # Subfolder
                self.engine.accounts.update(acc_id, export_subfolder=val)
                update_field = f"Alt Klasör: '{val}'"
            elif col == 9:  # Group / Domain
                self.engine.accounts.update(acc_id, account_group=val)
                update_field = f"Domain Grubu: '{val}'"

            if update_field:
                self.engine.audit.append("account.updated_inline", account_id=acc_id, details={"col": col, "val": val})
                self.test_status.setVisible(True)
                self.test_status.setText(f"🟢 Hesap ID #{acc_id} başarıyla güncellendi ({update_field})")
        except Exception as exc:
            logger.exception("Error in inline account cell edit: %s", exc)
            self.test_status.setVisible(True)
            self.test_status.setText(f"🔴 Güncelleme Hatası: {exc}")
            QMessageBox.critical(self, "Güncelleme Hatası", f"Hesap bilgisi veritabanına kaydedilemedi:\n{exc}")
            self.refresh()

    # -------------------------------------------------------------
    # Account Operations (Add, Edit, Copy, Delete, Toggle, Test)
    # -------------------------------------------------------------

    @Slot()
    def _open_group_management(self):
        from gui.dialogs.group_domain_dialog import GroupDomainDialog
        dialog = GroupDomainDialog(self.engine, self.settings, self)
        dialog.exec()
        self.refresh()

    @Slot()
    def _add_account(self):
        dialog = AccountDialog(self.engine, self, settings=self.settings)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    @Slot()
    def _bulk_import(self):
        dialog = BulkImportDialog(self.engine, self, settings=self.settings)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    @Slot()
    def _edit_account(self):
        row = self.table.currentRow()
        if row < 0:
            return
        id_item = self.table.item(row, 0)
        if not id_item or not id_item.text().isdigit():
            return
        acc_id = int(id_item.text())
        acc = self.engine.accounts.get(acc_id)
        if not acc:
            QMessageBox.warning(self, "Error", "Account not found.")
            return

        dialog = AccountDialog(self.engine, self, account=acc, settings=self.settings)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    @Slot()
    def _copy_account(self, account_id: Optional[int] = None):
        if account_id is None:
            row = self.table.currentRow()
            if row < 0:
                return
            id_item = self.table.item(row, 0)
            if not id_item or not id_item.text().isdigit():
                return
            account_id = int(id_item.text())

        acc = self.engine.accounts.get(account_id)
        if not acc:
            QMessageBox.warning(self, "Error", "Account not found.")
            return

        dialog = AccountDialog(self.engine, self, account=acc, settings=self.settings, is_copy=True)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    @Slot()
    def _toggle_active(self):
        row = self.table.currentRow()
        if row < 0:
            return
        id_item = self.table.item(row, 0)
        if not id_item or not id_item.text().isdigit():
            return
        acc_id = int(id_item.text())
        acc = self.engine.accounts.get(acc_id)
        if not acc:
            return

        is_active = bool(acc.get("is_active", True))
        new_status = 0 if is_active else 1
        label = acc.get("label", "")
        action_tr = "pasif" if is_active else "aktif"

        reply = self._show_styled_message_box(
            f"Hesabı {action_tr.title()} Yap",
            f"'{label}' hesabını {action_tr} duruma getirmek istediğinizden emin misiniz?",
            QMessageBox.Question,
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.engine.accounts.update(acc_id, is_active=new_status)
                self.engine.audit.append(
                    f"account.{'deactivated' if is_active else 'activated'}",
                    account_id=acc_id
                )
                self.refresh()
            except Exception as exc:
                self._show_styled_message_box("Error", str(exc), QMessageBox.Critical)

    @Slot()
    def _test_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        id_item = self.table.item(row, 0)
        if not id_item or not id_item.text().isdigit():
            return
        acc_id = int(id_item.text())
        acc = self.engine.accounts.get(acc_id)
        if not acc:
            return

        self.test_progress.setVisible(True)
        self.test_progress.setRange(0, 0)
        self.test_status.setVisible(True)
        self.test_status.setText(f"⏳ Bağlantı test ediliyor: {acc.get('label', '')}...")
        self.test_status.setStyleSheet("color: #2563eb; font-size: 11.5px;")

        def test():
            from infrastructure.imap_client import ImapClient
            try:
                username = self.engine.crypto.decrypt(acc.get("username_enc", ""))
                password = self.engine.crypto.decrypt(acc.get("password_enc", ""))
                client = ImapClient()
                ok = client.connect(
                    acc["imap_host"], acc["imap_port"],
                    bool(acc["use_ssl"]), username, password
                )
                if ok:
                    client.disconnect()
                self.test_progress.setVisible(False)
                if ok:
                    self.test_status.setText(f"✅ {acc.get('label', '')}: Bağlantı Başarılı (OK)")
                    self.test_status.setStyleSheet("color: #15803d; font-size: 11.5px; font-weight: bold;")
                else:
                    self.test_status.setText(f"❌ {acc.get('label', '')}: Bağlantı Başarısız")
                    self.test_status.setStyleSheet("color: #b91c1c; font-size: 11.5px; font-weight: bold;")
            except Exception as exc:
                self.test_progress.setVisible(False)
                self.test_status.setText(f"❌ Hata: {exc}")
                self.test_status.setStyleSheet("color: #b91c1c; font-size: 11.5px;")

        threading.Thread(target=test, daemon=True).start()

    @Slot()
    def _delete_account(self):
        row = self.table.currentRow()
        if row < 0:
            return
        id_item = self.table.item(row, 0)
        if not id_item or not id_item.text().isdigit():
            return
        acc_id = int(id_item.text())
        acc = self.engine.accounts.get(acc_id)
        if not acc:
            return

        if bool(acc.get("is_active", True)):
            self._show_styled_message_box(
                "Silinemez",
                f"'{acc.get('label', '')}' hesabı şu anda aktiftir.\n"
                "Silmeden önce lütfen hesabı pasif duruma getirin.",
                QMessageBox.Warning
            )
            return

        label = acc.get("label", "")
        reply = self._show_styled_message_box(
            "Silme Onayı",
            f"'{label}' (ID: {acc_id}) hesabını kalıcı olarak silmek istiyor musunuz?\n\n"
            "Bu hesaba ait tüm veriler ve eşitleme geçmişi silinecektir.\n"
            "Bu işlem geri alınamaz.",
            QMessageBox.Question,
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.engine.remove_account(acc_id)
                self.refresh()
            except Exception as exc:
                self._show_styled_message_box("Hata", f"Silme işlemi başarısız:\n{exc}", QMessageBox.Critical)

    @Slot()
    def _clean_start(self):
        reply = self._show_styled_message_box(
            "Temiz Başlangıç (Clean Start)",
            "Tüm arşivlenmiş e-postalar, ek dosyalar ve senkronizasyon geçmişi kalıcı olarak silinecektir.\n"
            "Yapılandırılmış e-posta hesapları korunacaktır.\n"
            "Bu işlem geri alınamaz. Devam etmek istiyor musunuz?",
            QMessageBox.Question,
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.engine.clear_archive_data()
                self._show_styled_message_box(
                    "Başarılı",
                    "Canlı eşitleme arşivi başarıyla sıfırlandı. Temiz başlangıç hazır.",
                    QMessageBox.Information
                )
                self.refresh()
            except Exception as exc:
                self._show_styled_message_box("Hata", f"Sıfırlama başarısız oldu:\n{exc}", QMessageBox.Critical)

    @Slot()
    def _on_batch_change_group(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Seçim Yapılmadı", "Lütfen önce grubunu değiştirmek istediğiniz bir hesap seçin.")
            return

        acc_id = int(self.table.item(row, 0).text())
        acc = self.engine.accounts.get(acc_id)
        current_group = acc.get("account_group", "") if acc else ""

        new_group, ok = QInputDialog.getText(
            self, "Toplu / Hızlı Grup Değiştir",
            f"'{acc.get('label', '')}' hesabı için yeni Domain Grubunu girin:",
            QLineEdit.Normal, current_group
        )
        if ok and new_group is not None:
            self.engine.accounts.update(acc_id, account_group=new_group.strip())
            self.test_status.setVisible(True)
            self.test_status.setText(f"🟢 Hesap grubu '{new_group.strip()}' olarak güncellendi.")
            self.refresh()

    @Slot()
    def _on_batch_change_password(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Seçim Yapılmadı", "Lütfen önce şifresini değiştirmek istediğiniz bir hesap seçin.")
            return

        acc_id = int(self.table.item(row, 0).text())
        acc = self.engine.accounts.get(acc_id)

        new_pwd, ok = QInputDialog.getText(
            self, "Hızlı Şifre Güncelleme",
            f"'{acc.get('label', '')}' hesabı için yeni şifreyi girin:",
            QLineEdit.Password
        )
        if ok and new_pwd:
            pwd_enc = self.engine.crypto.encrypt(new_pwd)
            self.engine.accounts.update(acc_id, password_enc=pwd_enc)
            self.test_status.setVisible(True)
            self.test_status.setText(f"🟢 Hesap şifresi şifrelenerek başarıyla güncellendi.")
            self.refresh()

    # -------------------------------------------------------------
    # Single / Bulk Optimize & EML Import
    # -------------------------------------------------------------

    def _optimize_single_account(self, account_id):
        if hasattr(self, "_active_optimizer") and self._active_optimizer and self._active_optimizer.worker and self._active_optimizer.worker.isRunning():
            self._restore_active_optimizer()
            return

        from gui.dialogs.archive_optimizer_dialog import ArchiveOptimizerDialog
        dialog = ArchiveOptimizerDialog(self.engine, self.settings, self, account_ids=[account_id])
        self._active_optimizer = dialog
        dialog.show()

    def _edit_single_subfolder(self, account_id):
        acc = self.engine.accounts.get(account_id)
        if not acc:
            return
        current_sub = acc.get("export_subfolder") or ""
        new_sub, ok = QInputDialog.getText(
            self, "Alt Klasör Değiştir",
            f"'{acc.get('email')}' hesabı için arşiv alt klasör adını girin:\n\n"
            f"(Bu klasör, ana yedekleme dizini altında oluşturulacaktır)",
            QLineEdit.Normal, current_sub
        )
        if ok:
            import re
            new_sub_clean = re.sub(r'[\/:*?"<>|]', '_', new_sub).strip()
            try:
                with self.engine.db.transaction() as conn:
                    conn.execute("UPDATE accounts SET export_subfolder = ? WHERE id = ?", (new_sub_clean, account_id))
                self.engine.audit.append("account.update_subfolder", account_id=account_id)
                QMessageBox.information(self, "Başarılı", f"Alt klasör adı '{new_sub_clean}' olarak güncellendi.")
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Hata", f"Alt klasör adı güncellenemedi: {e}")

    @Slot(str)
    def _on_bulk_optimize(self, selected_group: str):
        if hasattr(self, "_active_optimizer") and self._active_optimizer and self._active_optimizer.worker and self._active_optimizer.worker.isRunning():
            self._restore_active_optimizer()
            return

        all_accounts = self.engine.list_accounts()
        matching_ids = []
        for acc in all_accounts:
            g_val = acc.get("account_group", "").strip()
            if not g_val and "@" in acc.get("email", ""):
                g_val = acc["email"].split("@")[-1].strip()
            if selected_group == "__ALL__" or g_val == selected_group:
                matching_ids.append(acc["id"])

        if not matching_ids:
            QMessageBox.information(self, "Bilgi", "İşlenecek etkin hesap bulunamadı.")
            return

        from gui.dialogs.archive_optimizer_dialog import ArchiveOptimizerDialog
        dialog = ArchiveOptimizerDialog(self.engine, self.settings, self, account_ids=matching_ids)
        self._active_optimizer = dialog
        dialog.show()

    @Slot(str)
    def _on_bulk_subfolder(self, selected_group: str):
        group_label = f"'{selected_group}' grubu" if selected_group != "__ALL__" else "Tüm hesaplar"
        new_sub, ok = QInputDialog.getText(
            self, "Toplu Alt Klasör Tanımla",
            f"{group_label} için ortak arşiv alt klasör adını girin:\n\n"
            f"(Bu klasör, ana yedekleme dizini altında oluşturulacaktır)",
            QLineEdit.Normal, ""
        )
        if not ok:
            return

        import re
        new_sub_clean = re.sub(r'[\/:*?"<>|]', '_', new_sub).strip()
        all_accounts = self.engine.list_accounts()
        matching_ids = []
        for acc in all_accounts:
            g_val = acc.get("account_group", "").strip()
            if not g_val and "@" in acc.get("email", ""):
                g_val = acc["email"].split("@")[-1].strip()
            if selected_group == "__ALL__" or g_val == selected_group:
                matching_ids.append(acc["id"])

        if not matching_ids:
            QMessageBox.information(self, "Bilgi", "Güncellenecek hesap bulunamadı.")
            return

        reply = QMessageBox.question(
            self, "Onayla",
            f"Seçilen {len(matching_ids)} adet hesabın alt klasör adını '{new_sub_clean}' olarak güncellemek istiyor musunuz?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        try:
            with self.engine.db.transaction() as conn:
                for aid in matching_ids:
                    conn.execute("UPDATE accounts SET export_subfolder = ? WHERE id = ?", (new_sub_clean, aid))
            QMessageBox.information(self, "Başarılı", f"{len(matching_ids)} adet hesabın alt klasör adı başarıyla güncellendi.")
            self.refresh()
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Toplu güncelleme başarısız oldu: {e}")

    @Slot()
    def _on_import_eml(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Uyarı", "Lütfen önce EML dosyalarını eşleştirmek istediğiniz e-posta hesabını listeden seçin.")
            return

        acc_id = int(self.table.item(row, 0).text())
        email_addr = self.table.item(row, 2).text()

        reply = QMessageBox.question(
            self,
            "EML İçe Aktarma",
            f"'{email_addr}' hesabı için diskteki EML dosyalarını tarayıp veri tabanına işlemek istiyor musunuz?\n\n"
            "Bu işlem indirilen e-postaları algılayıp tekrar indirmeyi engelleyecektir.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        folder = QFileDialog.getExistingDirectory(self, "EML Dosyalarının Bulunduğu Klasörü Seçin")
        if not folder:
            return

        from PySide6.QtWidgets import QProgressDialog
        progress_dialog = QProgressDialog("Klasör taranıyor...", "İptal", 0, 100, self)
        progress_dialog.setWindowTitle("EML Tarama ve İçe Aktarma")
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setValue(0)

        self.worker = EmlImportWorker(self.engine, acc_id, folder)

        def on_progress(val, text):
            progress_dialog.setValue(val)
            progress_dialog.setLabelText(text)
            if progress_dialog.wasCanceled():
                self.worker.terminate()

        def on_finished(imported, skipped):
            progress_dialog.close()
            QMessageBox.information(
                self,
                "Başarılı",
                f"Tarama tamamlandı!\n\n"
                f"✅ İçe Aktarılan: {imported} e-posta\n"
                f"ℹ️ Atlanan/Var olan: {skipped} e-posta\n\n"
                f"E-postalar veri tabanına işlendi. Tekrar indirilmeyeceklerdir.",
                QMessageBox.Ok
            )
            self.refresh()

        self.worker.progress.connect(on_progress)
        self.worker.finished.connect(on_finished)
        self.worker.start()

    @Slot()
    def _on_scan_storage_disk(self):
        base_path = self.engine.db._db_path.parent
        storage_dirs = [base_path]
        for loc in self.settings.storage_locations():
            storage_dirs.append(Path(loc.path))

        discovered_map = {}
        import os
        for s_dir in storage_dirs:
            s_dir_path = Path(s_dir).resolve()
            if not s_dir_path.exists():
                continue

            try:
                for root, dirs, files in os.walk(str(s_dir_path)):
                    rel_depth = len(Path(root).relative_to(s_dir_path).parts)
                    if rel_depth > 5:
                        dirs.clear()

                    has_emls = any(f.lower().endswith(".eml") for f in files)
                    if has_emls:
                        res = self._parse_mail_path(root, s_dir_path)
                        if res:
                            email = res["email"]
                            if email not in discovered_map:
                                discovered_map[email] = res
            except Exception as e:
                logger.error("Error scanning storage directory %s: %s", s_dir_path, e)

        discovered = list(discovered_map.values())
        if not discovered:
            self._show_styled_message_box(
                "Bilgi",
                "Disk üzerinde yedeklenmiş e-posta klasörü bulunamadı veya tümü zaten veri tabanında kayıtlı."
            )
            return

        existing_accounts = self.engine.list_accounts()
        existing_emails = {acc["email"].lower() for acc in existing_accounts}
        to_add = [d for d in discovered if d["email"].lower() not in existing_emails]

        if not to_add:
            self._show_styled_message_box(
                "Bilgi",
                f"Taranan klasörlerden {len(discovered)} adet hesap algılandı, ancak hepsi zaten veri tabanında mevcut."
            )
            return

        confirm_text = "Disk üzerinde veri tabanında bulunmayan aşağıdaki hesaplar tespit edildi:\n\n"
        for idx, item in enumerate(to_add):
            confirm_text += f"{idx+1}. {item['email']} (Grup: {item['group']}, Alt Klasör: {item['subfolder']})\n"
        confirm_text += "\nBu hesapları veri tabanına otomatik eklemek istiyor musunuz?"

        reply = self._show_styled_message_box(
            "Hesapları İçe Aktar",
            confirm_text,
            QMessageBox.Question,
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            added_count = 0
            for item in to_add:
                try:
                    acc_id = self.engine.add_account(
                        label=item["email"],
                        email=item["email"],
                        imap_host="imap." + item["group"],
                        imap_port=993,
                        use_ssl=1,
                        username=item["email"],
                        password="placeholder_password"
                    )
                    with self.engine.db.transaction() as conn:
                        conn.execute(
                            "UPDATE accounts SET account_group = ?, export_subfolder = ? WHERE id = ?",
                            (item["group"], item["subfolder"], acc_id)
                        )
                    for loc in self.settings.storage_locations():
                        if Path(loc.path).resolve() == Path(item["storage_dir"]).resolve():
                            self.settings.set_account_storage(acc_id, loc.name)
                            break
                    added_count += 1
                except Exception as ex:
                    logger.error("Failed to auto-register account %s: %s", item["email"], ex)

            self.refresh()
            self._show_styled_message_box(
                "Başarılı",
                f"{added_count} adet hesap başarıyla veri tabanına geri kazandırıldı ve listeye eklendi."
            )

    def _parse_mail_path(self, full_path, storage_dir):
        try:
            rel = Path(full_path).relative_to(Path(storage_dir))
        except ValueError:
            return None

        parts = list(rel.parts)
        if len(parts) < 4:
            return None

        mailbox = parts[-1]
        username = parts[-2]
        group_name = parts[-3]

        if group_name.lower() in ("mails", "attachments", "inbox", "sent", "drafts", "trash", "junk", "spam", "archive"):
            return None

        standard_mailboxes = ("inbox", "sent", "drafts", "trash", "junk", "spam", "archive", "gelen", "giden", "cop", "arsiv", "kargom kolay")
        if mailbox.lower() not in standard_mailboxes:
            return None

        idx = parts.index(group_name)
        prefix_parts = parts[:idx]
        if prefix_parts and prefix_parts[-1].lower() == "mails":
            prefix_parts = prefix_parts[:-1]

        subfolder = "/".join(prefix_parts)
        if "@" in username:
            email = username
        else:
            email = f"{username}@{group_name}"

        return {
            "email": email.lower(),
            "group": group_name,
            "subfolder": subfolder,
            "storage_dir": str(storage_dir)
        }

    # -------------------------------------------------------------
    # Optimizer Status Handlers
    # -------------------------------------------------------------

    def update_optimizer_status(self, percentage):
        if hasattr(self, "btn_active_opt_status"):
            self.btn_active_opt_status.setVisible(True)
            self.btn_active_opt_status.setText(f"🔄 Optimizasyon %{percentage} (Geri Yükle)")

    def _restore_active_optimizer(self):
        if hasattr(self, "_active_optimizer") and self._active_optimizer:
            self._active_optimizer.show()
            self._active_optimizer.raise_()
            self._active_optimizer.activateWindow()

    def clear_optimizer_status(self):
        if hasattr(self, "btn_active_opt_status"):
            self.btn_active_opt_status.setVisible(False)

    # -------------------------------------------------------------
    # Role-Based Permissions (RBAC)
    # -------------------------------------------------------------

    def apply_permissions(self, role: str):
        """
        Cascades RBAC permissions down to left sidebar, right sidebar, and table editing.
        """
        self._current_role = role.lower()
        self.left_sidebar.apply_permissions(self._current_role)
        self.right_sidebar.apply_permissions(self._current_role)

    # -------------------------------------------------------------
    # Helpers & Styles
    # -------------------------------------------------------------

    def _show_styled_message_box(self, title, text, icon=QMessageBox.Information, buttons=QMessageBox.Ok):
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setIcon(icon)
        msg.setStandardButtons(buttons)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #ffffff;
            }
            QLabel {
                color: #1e293b;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton {
                background-color: #2563eb !important;
                color: #ffffff !important;
                border: none !important;
                border-radius: 6px !important;
                padding: 6px 16px !important;
                font-weight: 700 !important;
                font-size: 11.5px !important;
                min-width: 80px !important;
                min-height: 26px !important;
            }
            QPushButton:hover { background-color: #1d4ed8 !important; }
        """)
        return msg.exec()

    def _toggle_btn_style(self, active: bool = False) -> str:
        bg = "#e0e7ff" if active else "#f1f5f9"
        border = "#6366f1" if active else "#cbd5e1"
        fg = "#1e1b4b" if active else "#1e3a8a"
        return f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {border};
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
                padding: 5px 10px;
                min-height: 22px;
            }}
            QPushButton:hover {{
                background-color: #e2e8f0;
                border-color: #94a3b8;
                color: #0f172a;
            }}
        """

    def _badge_style(self, bg: str, fg: str) -> str:
        return f"""
            QLabel {{
                background-color: {bg};
                color: {fg} !important;
                font-weight: bold;
                font-size: 11px;
                padding: 4px 10px;
                border-radius: 6px;
                border: none;
            }}
        """
