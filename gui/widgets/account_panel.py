"""
account_panel.py — Account management panel with dialog-based add/edit.
"""

import logging
import threading
from typing import Optional

import csv
from pathlib import Path

from PySide6.QtCore import Qt, Slot, QPoint
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QMessageBox, QGroupBox,
    QFrame, QProgressBar, QDialog, QFileDialog, QListWidget, QListWidgetItem,
    QComboBox, QInputDialog, QLineEdit,
)

from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.dialogs.account_dialog import AccountDialog
from gui.dialogs.bulk_import_dialog import BulkImportDialog

logger = logging.getLogger(__name__)



from PySide6.QtCore import QThread, Signal

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

        # Cache highest UIDs per folder to update sync_state
        folder_max_uids = {}  # folder_name -> max_uid

        for i, file_path in enumerate(eml_files):
            if i % 10 == 0 or i == total - 1:
                self.progress.emit(
                    int((i + 1) * 100 / total),
                    f"Taranıyor: {i+1} / {total} - {file_path.name[:30]}"
                )

            # immediate parent directory name represents folder name
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

        # Update sync states with max UIDs
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

        # Rebuild full text index
        try:
            self.engine.db.rebuild_fts_index()
        except Exception as e:
            logger.error("Failed to rebuild FTS: %s", e)

        self.finished.emit(imported_count, skipped_count)


class AccountPanel(QWidget):
    """Account management with add/edit/deactivate/delete and connection test."""

    def __init__(self, engine: MailEngine, parent=None, settings: AppSettings = None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings or AppSettings()
        self._active_optimizer = None
        self._excel_editing_enabled = False
        self._is_refreshing = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        sub = QLabel("Manage your IMAP email accounts. "
                     "Passwords are encrypted with AES-256 before storage.")
        sub.setProperty("subheading", True)
        layout.addWidget(sub)

        # Toolbar
        toolbar = QFrame()
        toolbar.setStyleSheet("""
            QFrame { background: #ffffff; border-radius: 8px; padding: 8px; }
        """)
        tool_layout = QHBoxLayout(toolbar)
        tool_layout.setContentsMargins(12, 8, 12, 8)

        # Dropdown actions menu to save horizontal space
        self.btn_actions = QPushButton("⚙️  Account Actions  ▼")
        self.btn_actions.setProperty("outline", True)
        self.btn_actions.setStyleSheet("QPushButton { font-weight: bold; padding: 6px 14px; min-height: 24px; }")
        
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction
        self.actions_menu = QMenu(self)
        self.actions_menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                color: #1e293b;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px 0px;
            }
            QMenu::item {
                padding: 8px 24px 8px 30px;
                background-color: transparent;
                color: #1e293b;
            }
            QMenu::item:selected {
                background-color: #f1f5f9;
                color: #0f172a;
            }
            QMenu::item:disabled {
                color: #94a3b8;
            }
        """)
        
        self.act_add = self.actions_menu.addAction("➕  Add Account")
        self.act_edit = self.actions_menu.addAction("✏️  Edit Selected")
        self.act_edit.setEnabled(False)
        self.act_copy = self.actions_menu.addAction("📋  Duplicate Selected (Kopyala)")
        self.act_copy.setEnabled(False)
        self.act_delete = self.actions_menu.addAction("🗑  Delete Selected")
        self.act_delete.setEnabled(False)
        
        self.actions_menu.addSeparator()
        
        self.act_bulk_import = self.actions_menu.addAction("📥  Bulk Import")
        self.act_scan_disk = self.actions_menu.addAction("🔍  Scan Storage")
        self.act_import_eml = self.actions_menu.addAction("📂  EML Tarama / Aktar")
        
        self.actions_menu.addSeparator()
        self.act_toggle_active = self.actions_menu.addAction("⏸  Deactivate Selected")
        self.act_toggle_active.setEnabled(False)
        self.act_test = self.actions_menu.addAction("🔌  Test Connection")
        self.act_test.setEnabled(False)
        self.act_clean_start = self.actions_menu.addAction("🗑  Clean Start")

        self.actions_menu.addSeparator()
        self.act_group_mgmt = self.actions_menu.addAction("🏷️  Grup / Domain Yönetimi")
        self.act_group_mgmt.triggered.connect(self._open_group_management)
        self.act_batch_group = self.actions_menu.addAction("🏷️  Toplu Grup Değiştir")
        self.act_batch_group.triggered.connect(self._on_batch_change_group)
        self.act_batch_password = self.actions_menu.addAction("🔑  Toplu Şifre Güncelle")
        self.act_batch_password.triggered.connect(self._on_batch_change_password)

        self.btn_actions.setMenu(self.actions_menu)
        tool_layout.addWidget(self.btn_actions)

        # Direct Group Management Button in Toolbar
        self.btn_group_mgmt = QPushButton("🏷️  Grup Yönetimi")
        self.btn_group_mgmt.setToolTip("Grup / Domain ekleme, silme, düzenleme ve domain eşitleme penceresini açar")
        self.btn_group_mgmt.setStyleSheet("""
            QPushButton {
                background-color: #2563eb !important;
                color: #ffffff !important;
                border: none !important;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 6px;
                font-size: 11px;
                min-height: 24px;
            }
            QPushButton:hover { background-color: #1d4ed8 !important; }
        """)
        self.btn_group_mgmt.clicked.connect(self._open_group_management)
        tool_layout.addWidget(self.btn_group_mgmt)

        # Excel-Style Inline Editing Toggle Button
        self.btn_excel_mode = QPushButton("⚡ Excel Tipi Canlı Düzenleme: Kapalı")
        self.btn_excel_mode.setToolTip("Tablo üzerinde hücreye çift tıklayıp doğrudan Excel gibi değer değiştirebilmenizi sağlar")
        self.btn_excel_mode.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #475569;
                border: 1px solid #cbd5e1;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 6px;
                font-size: 11px;
                min-height: 24px;
            }
            QPushButton:hover { background-color: #e2e8f0; }
        """)
        self.btn_excel_mode.clicked.connect(self._toggle_excel_editing_mode)
        tool_layout.addWidget(self.btn_excel_mode)

        # Background Optimizer restore status button
        self.btn_active_opt_status = QPushButton("🔄 Optimizasyon Çalışıyor (Geri Yükle)")
        self.btn_active_opt_status.setVisible(False)
        self.btn_active_opt_status.setStyleSheet("background-color: #f59e0b; color: white; font-weight: bold; border-radius: 4px; padding: 4px 10px; font-size: 11px; min-height: 24px;")
        self.btn_active_opt_status.clicked.connect(self._restore_active_optimizer)
        tool_layout.addWidget(self.btn_active_opt_status)

        # Grid layout profile controls in toolbar
        lbl_grid = QLabel("Grid Layout:")
        lbl_grid.setStyleSheet("color: #4b5563; font-weight: bold; margin-left: 10px; font-size: 11px;")
        tool_layout.addWidget(lbl_grid)
        
        self.combo_grid_profiles = QComboBox()
        self.combo_grid_profiles.setFixedWidth(110)
        self.combo_grid_profiles.setStyleSheet("""
            QComboBox {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 3px 6px;
                color: #374151;
                font-size: 11px;
                min-height: 24px;
            }
        """)
        self.combo_grid_profiles.currentIndexChanged.connect(self._on_grid_profile_changed)
        tool_layout.addWidget(self.combo_grid_profiles)

        self.btn_save_profile = QPushButton("💾 Save")
        self.btn_save_profile.setProperty("outline", True)
        self.btn_save_profile.setToolTip("Mevcut grid genişlik ve sütun düzenini yeni isimle profil olarak kaydeder")
        self.btn_save_profile.clicked.connect(self._on_save_new_profile)
        self.btn_save_profile.setStyleSheet("QPushButton { font-size: 11px; padding: 4px 8px; }")
        tool_layout.addWidget(self.btn_save_profile)

        self.btn_delete_profile = QPushButton("🗑 Delete")
        self.btn_delete_profile.setProperty("outline", True)
        self.btn_delete_profile.clicked.connect(self._on_delete_profile)
        self.btn_delete_profile.setStyleSheet("QPushButton { font-size: 11px; padding: 4px 8px; }")
        tool_layout.addWidget(self.btn_delete_profile)

        tool_layout.addStretch()

        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setProperty("outline", True)
        tool_layout.addWidget(self.btn_refresh)

        layout.addWidget(toolbar)

        # Test progress
        self.test_progress = QProgressBar()
        self.test_progress.setVisible(False)
        self.test_progress.setMaximumHeight(4)
        self.test_progress.setTextVisible(False)
        layout.addWidget(self.test_progress)

        self.test_status = QLabel("")
        self.test_status.setProperty("status", True)
        layout.addWidget(self.test_status)

        # Main Split Layout
        main_split_layout = QHBoxLayout()
        main_split_layout.setSpacing(12)

        # Left Sidebar for Group / Domain Filter
        self.sidebar_widget = QFrame()
        self.sidebar_widget.setFrameShape(QFrame.StyledPanel)
        self.sidebar_widget.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #e0e3e8;
                border-radius: 8px;
            }
            QListWidget {
                border: none;
                background: transparent;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-radius: 4px;
                color: #374151;
            }
            QListWidget::item:hover {
                background: #f1f5f9;
            }
            QListWidget::item:selected {
                background: #e2e8f0;
                color: #0f172a;
                font-weight: bold;
            }
        """)
        self.sidebar_widget.setFixedWidth(210)
        sidebar_layout = QVBoxLayout(self.sidebar_widget)
        sidebar_layout.setContentsMargins(10, 12, 10, 12)

        lbl_side = QLabel("📁 Grup / Domain Filtresi")
        lbl_side.setStyleSheet("font-weight: bold; color: #1e293b; font-size: 12px; margin-bottom: 6px; border: none; background: transparent;")
        sidebar_layout.addWidget(lbl_side)

        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        self.group_filter_list = QListWidget()
        self.group_filter_list.currentItemChanged.connect(self._on_group_filter_changed)
        sidebar_layout.addWidget(self.group_filter_list)

        # Bulk actions container at bottom of sidebar
        bulk_group = QFrame()
        bulk_group.setStyleSheet("QFrame { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 6px; }")
        bulk_layout = QVBoxLayout(bulk_group)
        bulk_layout.setContentsMargins(6, 8, 6, 8)
        bulk_layout.setSpacing(8)

        lbl_bulk = QLabel("⚡ Toplu Grup İşlemleri")
        lbl_bulk.setStyleSheet("font-weight: bold; color: #475569; font-size: 11px; border: none; background: transparent;")
        bulk_layout.addWidget(lbl_bulk)

        self.btn_bulk_optimize = QPushButton("⚙️ Grubu Optimize Et")
        self.btn_bulk_optimize.setStyleSheet("""
            QPushButton {
                background-color: #f59e0b;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #d97706; }
        """)
        self.btn_bulk_optimize.clicked.connect(self._on_bulk_optimize)
        bulk_layout.addWidget(self.btn_bulk_optimize)

        self.btn_bulk_subfolder = QPushButton("📂 Alt Klasör Tanımla")
        self.btn_bulk_subfolder.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 8px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #2563eb; }
        """)
        self.btn_bulk_subfolder.clicked.connect(self._on_bulk_subfolder)
        bulk_layout.addWidget(self.btn_bulk_subfolder)

        sidebar_layout.addWidget(bulk_group)
        main_split_layout.addWidget(self.sidebar_widget)

        # Sidebar toggle button
        self.btn_toggle_sidebar = QPushButton("◀")
        self.btn_toggle_sidebar.setFixedWidth(20)
        self.btn_toggle_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_sidebar.setStyleSheet("""
            QPushButton {
                background-color: #e2e8f0;
                color: #475569;
                border: 1px solid #cbd5e1;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                font-weight: bold;
                font-size: 11px;
                padding: 0px;
                min-height: 40px;
            }
            QPushButton:hover {
                background-color: #cbd5e1;
            }
        """)
        self.btn_toggle_sidebar.clicked.connect(self._toggle_sidebar)
        main_split_layout.addWidget(self.btn_toggle_sidebar)

        # Account table
        table_box = QGroupBox("Configured Accounts")
        table_layout = QVBoxLayout(table_box)

        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels([
            "ID", "Label", "Email", "IMAP Host", "Port", "SSL", "Status", "Storage", "Subfolder", "Group / Domain", "Last Updated", "Actions"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setSortingEnabled(True)
        table_layout.addWidget(self.table)

        # Context Menu policy for table rows and column management
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self._on_header_context_menu)
        self.table.horizontalHeader().sectionResized.connect(self._auto_save_current_layout)
        self.table.itemChanged.connect(self._on_table_item_changed)

        main_split_layout.addWidget(table_box, stretch=1)
        layout.addLayout(main_split_layout, stretch=1)

        # Connections
        self.act_add.triggered.connect(self._add_account)
        self.act_bulk_import.triggered.connect(self._bulk_import)
        self.act_scan_disk.triggered.connect(self._on_scan_storage_disk)
        self.act_import_eml.triggered.connect(self._on_import_eml)
        self.act_edit.triggered.connect(self._edit_account)
        self.act_copy.triggered.connect(self._copy_account)
        self.act_toggle_active.triggered.connect(self._toggle_active)
        self.act_test.triggered.connect(self._test_selected)
        self.act_delete.triggered.connect(self._delete_account)
        self.act_clean_start.triggered.connect(self._clean_start)
        self.btn_refresh.clicked.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.doubleClicked.connect(self._edit_account)

        # Load grid profiles
        self._populate_grid_profiles()
        self._apply_grid_profile(self.settings.get("grid_active_profile", "Default"))

    def _on_table_context_menu(self, pos: QPoint):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return

        from PySide6.QtWidgets import QMenu, QApplication
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 8px 20px; font-size: 12px; color: #1e293b; border-radius: 4px; }
            QMenu::item:selected { background-color: #2563eb; color: #ffffff; }
        """)

        act_edt = menu.addAction("✏️ Hesabı Düzenle (Edit)")
        act_mig = menu.addAction("🔄 Sunucu Değiştir / Yönet (Multi-Server)")
        act_cpy = menu.addAction("📋 Hesabı Kopyala (Duplicate)")
        act_tst = menu.addAction("🔌 Bağlantı Testi Yap")
        act_flt = menu.addAction("⚙️ Klasör & Filtre Ayarları")

        # Dynamic Server Switcher Sub-menu
        acc_id_str = self.table.item(row, 0).text() if self.table.item(row, 0) else ""
        server_actions = {}
        if acc_id_str.isdigit():
            acc_id = int(acc_id_str)
            profiles = self.engine.list_server_profiles(acc_id)
            if profiles and len(profiles) > 1:
                menu_servers = menu.addMenu("🔌 Aktif Sunucuyu Seç")
                menu_servers.setStyleSheet("""
                    QMenu { background-color: #ffffff; border: 1px solid #cbd5e1; padding: 4px; }
                    QMenu::item { padding: 6px 16px; font-size: 11px; }
                    QMenu::item:selected { background-color: #2563eb; color: #ffffff; }
                """)
                for p in profiles:
                    icon_prefix = "★ " if p.get("is_default") else "  "
                    label_text = f"{icon_prefix}{p.get('profile_name')} ({p.get('imap_host')})"
                    act_p = menu_servers.addAction(label_text)
                    server_actions[act_p] = p["id"]

        menu.addSeparator()
        act_cp_email = menu.addAction("📋 E-Posta Adresini Kopyala")
        menu.addSeparator()
        act_del = menu.addAction("🗑️ Hesabı Sil")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action in server_actions:
            prof_id = server_actions[action]
            acc_id = int(acc_id_str)
            self.engine.set_default_server_profile(acc_id, prof_id)
            self.refresh()
        elif action == act_edt or action == act_mig:
            self._edit_account()
        elif action == act_cpy:
            self._copy_account()
        elif action == act_tst:
            self._test_selected()
        elif action == act_flt:
            acc_id = int(self.table.item(row, 0).text())
            from gui.dialogs.account_dialog import AccountDialog
            acc = self.engine.accounts.get(acc_id)
            if acc:
                dialog = AccountDialog(self.engine, self, account=acc, settings=self.settings)
                dialog.exec()
        elif action == act_cp_email:
            email_val = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
            QApplication.clipboard().setText(email_val)
        elif action == act_del:
            self._delete_account()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @Slot()
    def _open_group_management(self):
        from gui.dialogs.group_domain_dialog import GroupDomainDialog
        dialog = GroupDomainDialog(self.engine, self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()
        else:
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
        acc_id = int(self.table.item(row, 0).text())
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
            account_id = int(self.table.item(row, 0).text())

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
        acc_id = int(self.table.item(row, 0).text())
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
        acc_id = int(self.table.item(row, 0).text())
        acc = self.engine.accounts.get(acc_id)
        if not acc:
            return

        self.test_progress.setVisible(True)
        self.test_progress.setRange(0, 0)
        self.test_status.setText(f"⏳ Testing {acc.get('label', '')}...")
        self.test_status.setStyleSheet("color: #4361ee; font-size: 12px;")
        self.act_test.setEnabled(False)

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
                self.act_test.setEnabled(True)
                self.test_progress.setVisible(False)
                if ok:
                    self.test_status.setText(f"✅ {acc.get('label', '')}: Connection OK")
                    self.test_status.setStyleSheet("color: #2d6a4f; font-size: 12px; font-weight: 600;")
                else:
                    self.test_status.setText(f"❌ {acc.get('label', '')}: Connection failed")
                    self.test_status.setStyleSheet("color: #e63946; font-size: 12px; font-weight: 600;")
            except Exception as exc:
                self.act_test.setEnabled(True)
                self.test_progress.setVisible(False)
                self.test_status.setText(f"❌ Error: {exc}")
                self.test_status.setStyleSheet("color: #e63946; font-size: 12px;")

        threading.Thread(target=test, daemon=True).start()

    @Slot()
    def _delete_account(self):
        row = self.table.currentRow()
        if row < 0:
            return
        acc_id = int(self.table.item(row, 0).text())
        acc = self.engine.accounts.get(acc_id)
        if not acc:
            return

        if bool(acc.get("is_active", True)):
            self._show_styled_message_box(
                "Cannot Delete",
                f"Account '{acc.get('label', '')}' is active.\n"
                "Deactivate it first, then delete.",
                QMessageBox.Warning
            )
            return

        label = acc.get("label", "")
        reply = self._show_styled_message_box(
            "Confirm Delete",
            f"Permanently delete '{label}' (ID: {acc_id})?\n\n"
            "All associated emails, attachments, and sync state will be removed.\n"
            "This cannot be undone.",
            QMessageBox.Question,
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.engine.remove_account(acc_id)
                self.refresh()
            except Exception as exc:
                self._show_styled_message_box("Error", f"Failed to delete:\n{exc}", QMessageBox.Critical)

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
                    "Success",
                    "Canlı eşitleme arşivi başarıyla sıfırlandı. Temiz başlangıç hazır.",
                    QMessageBox.Information
                )
                self.refresh()
            except Exception as exc:
                self._show_styled_message_box("Error", f"Sıfırlama başarısız oldu:\n{exc}", QMessageBox.Critical)

    @Slot()
    def _on_selection_changed(self):
        has_selection = self.table.currentRow() >= 0
        self.act_edit.setEnabled(has_selection)
        self.act_copy.setEnabled(has_selection)
        self.act_delete.setEnabled(has_selection)
        self.act_test.setEnabled(has_selection)
        
        # Dynamically switch deactivate/activate text based on selection
        if has_selection:
            try:
                row = self.table.currentRow()
                acc_id = int(self.table.item(row, 0).text())
                acc = self.engine.accounts.get(acc_id)
                if acc:
                    is_active = bool(acc.get("is_active", True))
                    self.act_toggle_active.setText("⏸  Deactivate Selected" if is_active else "▶  Activate Selected")
            except Exception:
                pass
        self.act_toggle_active.setEnabled(has_selection)

    # ------------------------------------------------------------------
    # Excel-Style Inline Editing Slots & Batch Actions
    # ------------------------------------------------------------------

    @Slot()
    def _toggle_excel_editing_mode(self):
        self._excel_editing_enabled = not self._excel_editing_enabled
        if self._excel_editing_enabled:
            self.btn_excel_mode.setText("⚡ Excel Tipi Canlı Düzenleme: AÇIK")
            self.btn_excel_mode.setStyleSheet("""
                QPushButton {
                    background-color: #10b981;
                    color: white;
                    border: none;
                    font-weight: bold;
                    padding: 6px 12px;
                    border-radius: 6px;
                    font-size: 11px;
                    min-height: 24px;
                }
                QPushButton:hover { background-color: #059669; }
            """)
            self.table.setEditTriggers(
                QTableWidget.DoubleClicked | QTableWidget.AnyKeyPressed | QTableWidget.EditKeyPressed | QTableWidget.SelectedClicked
            )
            self.test_status.setText("⚡ Excel Tipi Canlı Düzenleme AÇIK — Hücreye çift tıklayıp yazarak Enter'a basın, anında güncellenir.")
        else:
            self.btn_excel_mode.setText("⚡ Excel Tipi Canlı Düzenleme: Kapalı")
            self.btn_excel_mode.setStyleSheet("""
                QPushButton {
                    background-color: #f1f5f9;
                    color: #475569;
                    border: 1px solid #cbd5e1;
                    font-weight: bold;
                    padding: 6px 12px;
                    border-radius: 6px;
                    font-size: 11px;
                    min-height: 24px;
                }
                QPushButton:hover { background-color: #e2e8f0; }
            """)
            self.table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.test_status.setText("⚡ Excel Tipi Canlı Düzenleme Kapalı.")

        self.refresh()

    @Slot(QTableWidgetItem)
    def _on_table_item_changed(self, item: QTableWidgetItem):
        if not getattr(self, "_excel_editing_enabled", False) or getattr(self, "_is_refreshing", False):
            return

        row = item.row()
        col = item.column()

        id_item = self.table.item(row, 0)
        if not id_item:
            return

        try:
            acc_id = int(id_item.text())
        except ValueError:
            return

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
                self.test_status.setText(f"🟢 Hesap ID #{acc_id} başarıyla güncellendi ({update_field})")
                logger.info("Account #%d inline updated via Excel mode: col %d -> %s", acc_id, col, val)
        except Exception as exc:
            logger.exception("Error in inline account cell edit: %s", exc)
            self.test_status.setText(f"🔴 Güncelleme Hatası: {exc}")
            QMessageBox.critical(self, "Güncelleme Hatası", f"Hesap bilgisi veritabanına kaydedilemedi:\n{exc}")
            self.refresh()

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
            self.test_status.setText(f"🟢 Hesap şifresi şifrelenerek başarıyla güncellendi.")
            self.refresh()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self):
        self._is_refreshing = True
        try:
            # Check if settings contain custom storage configurations
            has_custom_storage = (
                len(self.settings.storage_locations()) > 0 or 
                len(self.settings.get("account_storage_map", {})) > 0
            )
            if has_custom_storage:
                self.settings.set("storage_locations", [])
                self.settings.set("account_storage_map", {})
                self.settings.save()
                self._show_styled_message_box(
                    "Depolama Bildirimi",
                    "Default Storage, sistemin varsayılan depolama alanına ayarlanacaktır."
                )

            # 1. Update groups sidebar list
            self._refresh_groups_sidebar()

            # 2. Get active group filter
            selected_item = self.group_filter_list.currentItem()
            selected_group = selected_item.data(Qt.UserRole) if selected_item else "__ALL__"

            # 3. Retrieve and filter accounts
            all_accounts = self.engine.list_accounts()
            accounts = []
            for acc in all_accounts:
                g_val = acc.get("account_group", "").strip()
                if not g_val and "@" in acc.get("email", ""):
                    g_val = acc["email"].split("@")[-1].strip()
                if selected_group == "__ALL__" or g_val == selected_group:
                    accounts.append(acc)

            self.table.setRowCount(len(accounts))
            for i, acc in enumerate(accounts):
                self.table.setItem(i, 0, QTableWidgetItem(str(acc["id"])))
                self.table.setItem(i, 1, QTableWidgetItem(acc.get("label", "")))
                self.table.setItem(i, 2, QTableWidgetItem(acc.get("email", "")))
                self.table.setItem(i, 3, QTableWidgetItem(acc.get("imap_host", "")))
                self.table.setItem(i, 4, QTableWidgetItem(str(acc.get("imap_port", ""))))
                self.table.setItem(i, 5, QTableWidgetItem("Yes" if acc.get("use_ssl") else "No"))

                is_active = bool(acc.get("is_active", True))
                status_text = "✅ Active" if is_active else "⏸ Inactive"
                status_item = QTableWidgetItem(status_text)
                status_item.setForeground(Qt.darkGreen if is_active else Qt.darkGray)
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

                # 4. Action Row Buttons Column (Column 11)
                action_widget = QWidget()
                action_layout = QHBoxLayout(action_widget)
                action_layout.setContentsMargins(4, 2, 4, 2)
                action_layout.setSpacing(6)
                
                # Button 1: Optimize EML & attachments
                btn_opt = QPushButton("⚙️ Optimize")
                btn_opt.setStyleSheet("background-color: #f59e0b; color: #ffffff; border: 1px solid #d97706; border-radius: 4px; font-size: 11px; font-weight: bold; min-height: 24px; padding: 3px 8px;")
                btn_opt.clicked.connect(lambda checked=False, aid=acc["id"]: self._optimize_single_account(aid))
                action_layout.addWidget(btn_opt)
                
                # Button 2: Edit export_subfolder
                btn_sub = QPushButton("📂 Folder")
                btn_sub.setStyleSheet("background-color: #3b82f6; color: #ffffff; border: 1px solid #2563eb; border-radius: 4px; font-size: 11px; font-weight: bold; min-height: 24px; padding: 3px 8px;")
                btn_sub.clicked.connect(lambda checked=False, aid=acc["id"]: self._edit_single_subfolder(aid))
                action_layout.addWidget(btn_sub)
                
                # Button 3: Duplicate account
                btn_cpy = QPushButton("📋 Copy")
                btn_cpy.setStyleSheet("background-color: #10b981; color: #ffffff; border: 1px solid #059669; border-radius: 4px; font-size: 11px; font-weight: bold; min-height: 24px; padding: 3px 8px;")
                btn_cpy.clicked.connect(lambda checked=False, aid=acc["id"]: self._copy_account(aid))
                action_layout.addWidget(btn_cpy)

                action_layout.addStretch()
                self.table.setCellWidget(i, 11, action_widget)

                # Set cell editability flags based on _excel_editing_enabled
                editable_cols = [1, 2, 3, 4, 5, 6, 8, 9]
                for c_idx in editable_cols:
                    it = self.table.item(i, c_idx)
                    if it:
                        if self._excel_editing_enabled:
                            it.setFlags(it.flags() | Qt.ItemIsEditable)
                        else:
                            it.setFlags(it.flags() & ~Qt.ItemIsEditable)

            self.table.resizeColumnsToContents()
            self.table.setColumnWidth(6, 100)
            self.table.setColumnWidth(7, 90)
            self.table.setColumnWidth(8, 90)
            self.table.setColumnWidth(9, 110)
            self.table.setColumnWidth(11, 220)
        except Exception as exc:
            logger.error("Refresh error: %s", exc)
        finally:
            self._is_refreshing = False
            self.table.setColumnWidth(9, 110)
            self.table.setColumnWidth(11, 160)

            # Apply active grid layout profile override
            active_profile = self.settings.get("grid_active_profile", "Default")
            self._apply_grid_profile(active_profile)

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

        # Select folder to scan
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
    def _on_group_filter_changed(self):
        self.refresh()

    def _refresh_groups_sidebar(self):
        self.group_filter_list.blockSignals(True)
        current_item = self.group_filter_list.currentItem()
        current_group = current_item.data(Qt.UserRole) if current_item else "__ALL__"
        self.group_filter_list.clear()

        groups_status = {}

        # 1. From settings
        settings_groups = self.settings.get("group_domains", [])
        for g in settings_groups:
            if isinstance(g, str):
                name = g.strip()
                is_active = True
            elif isinstance(g, dict):
                name = g.get("name", "").strip()
                is_active = g.get("is_active", True)
            else:
                continue
            if name:
                groups_status[name] = is_active

        # 2. From database
        try:
            with self.engine.db.get_conn() as conn:
                rows = conn.execute("SELECT DISTINCT account_group FROM accounts").fetchall()
                for r in rows:
                    if r["account_group"] and r["account_group"].strip():
                        name = r["account_group"].strip()
                        if name not in groups_status:
                            groups_status[name] = True
                # Fallback email domains
                rows_email = conn.execute("SELECT DISTINCT email FROM accounts").fetchall()
                for r in rows_email:
                    if r["email"] and "@" in r["email"]:
                        domain = r["email"].split("@")[-1].strip()
                        if domain and domain not in groups_status:
                            groups_status[domain] = True
        except Exception as e:
            logger.error("Failed to query database groups in account_panel: %s", e)

        # Add All groups item
        all_item = QListWidgetItem("📁 Tüm Gruplar")
        all_item.setData(Qt.UserRole, "__ALL__")
        self.group_filter_list.addItem(all_item)

        # Sort and add other groups
        for g in sorted(groups_status.keys()):
            is_active = groups_status[g]
            label = f"📁 {g}" if is_active else f"📁 {g} (Pasif)"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, g)
            if not is_active:
                item.setForeground(Qt.gray)
            self.group_filter_list.addItem(item)

        # Restore selection
        found_item = None
        for i in range(self.group_filter_list.count()):
            item = self.group_filter_list.item(i)
            if item.data(Qt.UserRole) == current_group:
                found_item = item
                break
        if found_item:
            self.group_filter_list.setCurrentItem(found_item)
        else:
            self.group_filter_list.setCurrentRow(0)

        self.group_filter_list.blockSignals(False)

    def _optimize_single_account(self, account_id):
        # If there is already a background running optimizer, restore it instead of opening a new one
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
            f"'{acc.get('email')}' hesabı için arşiv alt klasör (subfolder) adını girin:\n\n"
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

    @Slot()
    def _on_bulk_optimize(self):
        # If there is already a background running optimizer, restore it instead of opening a new one
        if hasattr(self, "_active_optimizer") and self._active_optimizer and self._active_optimizer.worker and self._active_optimizer.worker.isRunning():
            self._restore_active_optimizer()
            return

        selected_item = self.group_filter_list.currentItem()
        selected_group = selected_item.data(Qt.UserRole) if selected_item else "__ALL__"
        
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

    @Slot()
    def _on_bulk_subfolder(self):
        selected_item = self.group_filter_list.currentItem()
        selected_group = selected_item.data(Qt.UserRole) if selected_item else "__ALL__"
        
        group_label = f"'{selected_group}' grubu" if selected_group != "__ALL__" else "Tüm hesaplar"
        new_sub, ok = QInputDialog.getText(
            self, "Toplu Alt Klasör Tanımla",
            f"{group_label} için ortak arşiv alt klasör (subfolder) adını girin:\n\n"
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
    def _toggle_sidebar(self):
        is_visible = self.sidebar_widget.isVisible()
        self.sidebar_widget.setVisible(not is_visible)
        if not is_visible:
            self.btn_toggle_sidebar.setText("◀")
        else:
            self.btn_toggle_sidebar.setText("▶")

    @Slot(QPoint)
    def _on_header_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction
        
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                color: #1e293b;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px 0px;
            }
            QMenu::item {
                padding: 6px 20px 6px 30px;
                background-color: transparent;
                color: #1e293b;
            }
            QMenu::item:selected {
                background-color: #f1f5f9;
                color: #0f172a;
            }
        """)
        headers = [self.table.horizontalHeaderItem(i).text() for i in range(12)]
        
        for idx, name in enumerate(headers):
            action = QAction(name, menu, checkable=True)
            action.setChecked(not self.table.isColumnHidden(idx))
            action.triggered.connect(lambda checked, col=idx: self._toggle_column_visibility(col, checked))
            menu.addAction(action)
            
        menu.exec(self.table.horizontalHeader().mapToGlobal(pos))

    def _toggle_column_visibility(self, col, checked):
        self.table.setColumnHidden(col, not checked)
        self._auto_save_current_layout()

    def _auto_save_current_layout(self, *args):
        active_profile = self.settings.get("grid_active_profile", "Default")
        profiles = self.settings.get("grid_profiles", {})
        if active_profile not in profiles:
            profiles[active_profile] = {}

        # Collect visible columns
        visible = []
        for col in range(12):
            if not self.table.isColumnHidden(col):
                visible.append(col)

        # Collect widths
        widths = {}
        for col in range(12):
            widths[str(col)] = self.table.columnWidth(col)

        profiles[active_profile] = {
            "visible": visible,
            "widths": widths
        }
        self.settings.set("grid_profiles", profiles)
        self.settings.save()

    def _apply_grid_profile(self, profile_name):
        profiles = self.settings.get("grid_profiles", {})
        if profile_name not in profiles:
            if profile_name == "Default":
                profiles["Default"] = {
                    "visible": list(range(12)),
                    "widths": {}
                }
                self.settings.set("grid_profiles", profiles)
                self.settings.save()
            else:
                return

        layout_data = profiles[profile_name]
        visible_cols = layout_data.get("visible", list(range(12)))
        widths = layout_data.get("widths", {})

        # Block header signals to prevent auto-saving during layout restoration
        self.table.horizontalHeader().blockSignals(True)
        
        # Apply visibility
        for col in range(12):
            self.table.setColumnHidden(col, col not in visible_cols)

        # Apply widths
        for col_str, w in widths.items():
            try:
                self.table.setColumnWidth(int(col_str), w)
            except Exception:
                pass
                
        self.table.horizontalHeader().blockSignals(False)
        
        # Save active profile in settings
        self.settings.set("grid_active_profile", profile_name)
        self.settings.save()

    def _populate_grid_profiles(self):
        self.combo_grid_profiles.blockSignals(True)
        self.combo_grid_profiles.clear()
        
        profiles = self.settings.get("grid_profiles", {})
        if "Default" not in profiles:
            profiles["Default"] = {
                "visible": list(range(12)),
                "widths": {}
            }
            self.settings.set("grid_profiles", profiles)
            self.settings.save()
            
        for name in sorted(profiles.keys()):
            self.combo_grid_profiles.addItem(name)
            
        active = self.settings.get("grid_active_profile", "Default")
        idx = self.combo_grid_profiles.findText(active)
        if idx >= 0:
            self.combo_grid_profiles.setCurrentIndex(idx)
        else:
            self.combo_grid_profiles.setCurrentIndex(0)
            
        self.combo_grid_profiles.blockSignals(False)

    @Slot(int)
    def _on_grid_profile_changed(self, index):
        if index < 0:
            return
        profile_name = self.combo_grid_profiles.itemText(index)
        self._apply_grid_profile(profile_name)

    @Slot()
    def _on_save_new_profile(self):
        name, ok = QInputDialog.getText(
            self, "Save Grid Layout Profile",
            "Mevcut kolon düzeni ve boyutları için profil ismi girin:"
        )
        if ok and name.strip():
            profile_name = name.strip()
            if profile_name == "Default":
                QMessageBox.warning(self, "Hata", "Varsayılan (Default) profil adı değiştirilemez.")
                return
                
            profiles = self.settings.get("grid_profiles", {})
            # Initialize layout metadata
            visible = []
            for col in range(12):
                if not self.table.isColumnHidden(col):
                    visible.append(col)
            widths = {}
            for col in range(12):
                widths[str(col)] = self.table.columnWidth(col)
                
            profiles[profile_name] = {
                "visible": visible,
                "widths": widths
            }
            self.settings.set("grid_profiles", profiles)
            self.settings.set("grid_active_profile", profile_name)
            self.settings.save()
            
            self._populate_grid_profiles()
            QMessageBox.information(self, "Başarılı", f"'{profile_name}' düzen profili kaydedildi.")

    @Slot()
    def _on_delete_profile(self):
        active = self.settings.get("grid_active_profile", "Default")
        if active == "Default":
            QMessageBox.warning(self, "Hata", "Varsayılan (Default) profil silinemez.")
            return
            
        reply = QMessageBox.question(
            self, "Profili Sil",
            f"'{active}' profilini silmek istediğinize emin misiniz?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            profiles = self.settings.get("grid_profiles", {})
            profiles.pop(active, None)
            self.settings.set("grid_profiles", profiles)
            self.settings.set("grid_active_profile", "Default")
            self.settings.save()
            
            self._populate_grid_profiles()
            self._apply_grid_profile("Default")

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
        
        # Filter out standard system folders
        if group_name.lower() in ("mails", "attachments", "inbox", "sent", "drafts", "trash", "junk", "spam", "archive"):
            return None
            
        # We require the mailbox directory name to look like a standard mailbox folder to filter out garbage files/dirs
        standard_mailboxes = ("inbox", "sent", "drafts", "trash", "junk", "spam", "archive", "gelen", "giden", "cop", "arsiv", "kargom kolay")
        if mailbox.lower() not in standard_mailboxes:
            return None
            
        idx = parts.index(group_name)
        prefix_parts = parts[:idx]
        
        # If the last element of prefix is "mails", remove it
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
                padding: 8px 20px !important;
                font-weight: 700 !important;
                font-size: 12px !important;
                min-width: 95px !important;
                min-height: 28px !important;
            }
            QPushButton:hover {
                background-color: #1d4ed8 !important;
                color: #ffffff !important;
            }
            QPushButton:pressed {
                background-color: #1e40af !important;
                color: #ffffff !important;
            }
        """)
        return msg.exec()

    @Slot()
    def _on_scan_storage_disk(self):
        # 1. Resolve base path
        base_path = self.engine.db._db_path.parent
        # Scan settings named locations just in case
        storage_dirs = [base_path]
        for loc in self.settings.storage_locations():
            storage_dirs.append(Path(loc.path))

        discovered_map = {}  # email.lower() -> dict

        import os
        for s_dir in storage_dirs:
            s_dir_path = Path(s_dir).resolve()
            if not s_dir_path.exists():
                continue

            try:
                for root, dirs, files in os.walk(str(s_dir_path)):
                    rel_depth = len(Path(root).relative_to(s_dir_path).parts)
                    if rel_depth > 5:
                        # Clear dirs to prevent descending further
                        dirs.clear()

                    # Check if there are EML files in this folder
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

        # Filter out already existing accounts in database
        existing_accounts = self.engine.list_accounts()
        existing_emails = {acc["email"].lower() for acc in existing_accounts}

        to_add = [d for d in discovered if d["email"].lower() not in existing_emails]

        if not to_add:
            self._show_styled_message_box(
                "Bilgi",
                f"Taranan klasörlerden {len(discovered)} adet hesap algılandı, ancak hepsi zaten veri tabanında mevcut."
            )
            return

        # Show confirmation
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
                    # Register virtual IMAP configuration in database
                    # Use a placeholder IMAP server since we only need the local metadata
                    acc_id = self.engine.add_account(
                        label=item["email"],
                        email=item["email"],
                        imap_host="imap." + item["group"],
                        imap_port=993,
                        use_ssl=1,
                        username=item["email"],
                        password="placeholder_password"
                    )
                    # Update group and subfolder in database
                    with self.engine.db.transaction() as conn:
                        conn.execute(
                            "UPDATE accounts SET account_group = ?, export_subfolder = ? WHERE id = ?",
                            (item["group"], item["subfolder"], acc_id)
                        )
                    # Also associate custom storage location if it was on a custom drive
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
                f"{added_count} adet hesap başarıyla veri tabanına geri kazandırıldı ve listeye eklendi.\n"
                "Artık bu hesaplar için 'Optimize' işlemlerini çalıştırabilirsiniz."
            )

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
