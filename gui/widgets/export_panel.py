"""
export_panel.py — Full-page email export / migration panel.

Features:
- "Selected Accounts" and "Run Export" buttons styled with thick borders.
- Dropdown per account row allowing user profile selection, plus a manual "⚙" configure popup button in the row itself.
- QCheckBox container in Column 3 (Checked) centered widget to ensure reliable clicks.
- Folder selection mode set to SingleSelection in configuration dialog to allow checkbox toggle clicking.
- Custom folder check state slot dynamically colors text to bold green.
"""

import os
import re
import imaplib
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional, List
from datetime import datetime

from PySide6.QtCore import Qt, Slot, Signal, QDate
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame, QScrollArea,
    QComboBox, QListWidget, QListWidgetItem, QCheckBox, QDateEdit,
    QLineEdit, QPushButton, QFileDialog, QProgressBar, QTextEdit,
    QMessageBox, QLabel, QAbstractItemView, QGroupBox, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QDialogButtonBox,
)

from core.mail_engine import MailEngine
from core.settings import AppSettings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Clickable Stat Card Widget
# ---------------------------------------------------------------------------

class StatCard(QFrame):
    def __init__(self, title: str, value: str = "0000", bg_color: str = "#3b82f6", callback=None, tooltip_text="", parent=None):
        super().__init__(parent)
        self.callback = callback
        if tooltip_text:
            self.setToolTip(tooltip_text)
            
        self.setStyleSheet(f"""
            StatCard {{
                background-color: {bg_color};
                border: 3px solid #ef4444;
                border-radius: 8px;
                padding: 6px;
            }}
            StatCard:hover {{
                background-color: {bg_color};
                border-color: #fca5a5;
            }}
        """)
        self.setMinimumHeight(75)
        self.setCursor(Qt.PointingHandCursor if callback else Qt.ArrowCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        
        self.title_label = QLabel(title.upper())
        self.title_label.setStyleSheet("font-size:10px; color:#ffffff; font-weight:bold; border:none; background:transparent;")
        self.title_label.setAlignment(Qt.AlignCenter)
        
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet("font-size:22px; font-weight:900; color:#ffffff; border:none; background:transparent;")
        self.value_label.setAlignment(Qt.AlignCenter)
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, val: str):
        if val.isdigit():
            val = f"{int(val):04d}"
        self.value_label.setText(val)


    def mousePressEvent(self, event):
        if self.callback:
            self.callback()
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Dynamic Config Dialog
# ---------------------------------------------------------------------------

class ExportConfigDialog(QDialog):
    """Popup configuration dialog to handle profiles, target formats, filters, and target IMAP credentials."""

    def __init__(self, engine: MailEngine, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings
        self._is_loading = True
        
        self.setWindowTitle("Configure Export Target & Filters")
        self.resize(740, 580)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
            }
            QGroupBox {
                color: #1e293b;
                font-weight: bold;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 18px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
                color: #4361ee;
            }
            QLabel {
                color: #475569;
                font-weight: bold;
                font-size: 11px;
                background: transparent;
            }
            QLineEdit, QComboBox, QDateEdit {
                background-color: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 5px;
                font-size: 11px;
            }
            QLineEdit:focus, QComboBox:focus, QDateEdit:focus {
                border: 1px solid #4361ee;
            }
            QPushButton {
                background-color: #f1f5f9;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #e2e8f0;
                border-color: #94a3b8;
            }
        """)
        
        self._setup_ui()
        self._load_profiles()
        self._load_folders_from_db()
        self._is_loading = False
        self._on_format_changed()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        form_layout = QVBoxLayout(scroll_content)
        form_layout.setSpacing(10)

        # Profile/Definition Management Group
        prof_group = QGroupBox("Saved Profiles / Definitions")
        prof_form = QFormLayout(prof_group)
        prof_form.setSpacing(6)
        
        self.combo_profile = QComboBox()
        self.combo_profile.currentIndexChanged.connect(self._on_profile_selection_changed)
        prof_form.addRow("Profile:", self.combo_profile)

        self.input_profile_name = QLineEdit()
        self.input_profile_name.setPlaceholderText("New Profile Name...")
        prof_form.addRow("Profile Name:", self.input_profile_name)

        prof_btns = QHBoxLayout()
        self.btn_save_profile = QPushButton("💾 Save")
        self.btn_save_profile.setStyleSheet("background:#10b981; color:white; font-weight:bold; padding:6px;")
        self.btn_save_profile.clicked.connect(self._save_current_profile)
        self.btn_delete_profile = QPushButton("🗑 Delete")
        self.btn_delete_profile.setStyleSheet("background:#ef4444; color:white; font-weight:bold; padding:6px;")
        self.btn_delete_profile.clicked.connect(self._delete_selected_profile)
        prof_btns.addWidget(self.btn_save_profile)
        prof_btns.addWidget(self.btn_delete_profile)
        prof_form.addRow("", prof_btns)
        form_layout.addWidget(prof_group)

        # Configuration Form
        config_group = QGroupBox("Target & Formatting Settings")
        opts_form = QFormLayout(config_group)
        opts_form.setSpacing(8)

        self.combo_format = QComboBox()
        self.combo_format.addItem("ZIP Archive of EMLs (.zip)", "ZIP")
        self.combo_format.addItem("Directory of Raw EMLs (Thunderbird / Opera)", "DIRECTORY")
        self.combo_format.addItem("Single JSON Metadata file (.json)", "JSON")
        self.combo_format.addItem("Thunderbird MBOX Package (.mbox)", "MBOX")
        self.combo_format.addItem("Push to Mail Server (Outlook / IMAP)", "IMAP_SERVER")
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)
        opts_form.addRow("Target Format:", self.combo_format)

        # Local Target Path Row
        self.path_label = QLabel("Target Path:")
        self.path_layout = QHBoxLayout()
        self.input_path = QLineEdit()
        self.input_path.setReadOnly(True)
        self.input_path.setPlaceholderText("Select target path...")
        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.setStyleSheet("background:#cbd5e1; padding:4px 8px; font-weight:bold;")
        self.btn_browse.clicked.connect(self._on_browse)
        self.path_layout.addWidget(self.input_path)
        self.path_layout.addWidget(self.btn_browse)
        opts_form.addRow(self.path_label, self.path_layout)

        # Server Settings Group
        self.server_group = QWidget()
        server_form = QFormLayout(self.server_group)
        server_form.setContentsMargins(0, 0, 0, 0)
        server_form.setSpacing(6)
        
        self.input_host = QLineEdit()
        self.input_host.setPlaceholderText("e.g. imap.mail.com")
        server_form.addRow("Host Server:", self.input_host)
        
        port_layout = QHBoxLayout()
        self.input_port = QLineEdit("993")
        self.input_port.setFixedWidth(60)
        self.chk_ssl = QCheckBox("SSL/TLS")
        self.chk_ssl.setChecked(True)
        self.chk_ssl.setStyleSheet("color:#1e293b; font-weight:bold;")
        port_layout.addWidget(self.input_port)
        port_layout.addWidget(self.chk_ssl)
        port_layout.addStretch()
        server_form.addRow("Port Config:", port_layout)
        
        self.input_username = QLineEdit()
        self.input_username.setPlaceholderText("Username or Email")
        server_form.addRow("Username:", self.input_username)
        
        self.input_password = QLineEdit()
        self.input_password.setPlaceholderText("Mailbox password")
        self.input_password.setEchoMode(QLineEdit.Password)
        server_form.addRow("Password:", self.input_password)

        self.btn_test_target = QPushButton("🔌 Test Target Connection")
        self.btn_test_target.setStyleSheet("background:#4361ee; color:white; font-weight:bold; padding:6px;")
        self.btn_test_target.clicked.connect(self._test_target_connection)
        server_form.addRow("", self.btn_test_target)

        self.lbl_target_test_status = QLabel("")
        self.lbl_target_test_status.setStyleSheet("font-size:11px; font-weight:bold;")
        server_form.addRow("", self.lbl_target_test_status)
        opts_form.addRow("", self.server_group)

        # Date Filters
        dates_layout = QHBoxLayout()
        self.chk_since = QCheckBox("Since:")
        self.chk_since.setStyleSheet("color:#1e293b; font-weight:bold;")
        self.date_since = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_since.setCalendarPopup(True)
        self.date_since.setEnabled(False)
        self.chk_since.toggled.connect(self.date_since.setEnabled)

        self.chk_before = QCheckBox("Before:")
        self.chk_before.setStyleSheet("color:#1e293b; font-weight:bold;")
        self.date_before = QDateEdit(QDate.currentDate())
        self.date_before.setCalendarPopup(True)
        self.date_before.setEnabled(False)
        self.chk_before.toggled.connect(self.date_before.setEnabled)

        dates_layout.addWidget(self.chk_since)
        dates_layout.addWidget(self.date_since)
        dates_layout.addWidget(self.chk_before)
        dates_layout.addWidget(self.date_before)
        opts_form.addRow("Date Range:", dates_layout)

        # Folders checklist selection mode changed to SingleSelection to allow checkbox click toggle
        self.folder_list = QListWidget()
        self.folder_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.folder_list.setMinimumHeight(110)
        self.folder_list.setMaximumHeight(150)
        self.folder_list.setStyleSheet("""
            QListWidget {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
            }
            QListWidget::item {
                color: #64748b;
                background-color: #ffffff;
                padding: 6px 8px;
                border-bottom: 1px solid #f1f5f9;
            }
            QListWidget::item:hover {
                background-color: #f8fafc;
            }
            QListWidget::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #4361ee;
                border-radius: 3px;
                background-color: #ffffff;
            }
            QListWidget::indicator:checked {
                background-color: #10b981;
                border-color: #10b981;
                image: url(data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>);
            }
            QListWidget::indicator:unchecked {
                background-color: #ffffff;
            }
        """)
        self.folder_list.itemChanged.connect(self._on_folder_item_changed)
        
        folder_ctrls = QHBoxLayout()
        btn_all = QPushButton("All")
        btn_all.setStyleSheet("padding:2px 8px; font-size:11px;")
        btn_all.clicked.connect(self._select_all_folders)
        btn_none = QPushButton("None")
        btn_none.setStyleSheet("padding:2px 8px; font-size:11px;")
        btn_none.clicked.connect(self._select_none_folders)
        folder_ctrls.addWidget(btn_all)
        folder_ctrls.addWidget(btn_none)
        folder_ctrls.addStretch()

        self.lbl_folder_summary = QLabel("Selected Folders: 0 / 0")
        self.lbl_folder_summary.setStyleSheet("color:#10b981; font-weight:bold; font-size:11px;")
        folder_ctrls.addWidget(self.lbl_folder_summary)

        f_layout = QVBoxLayout()
        f_layout.addWidget(self.folder_list)
        f_layout.addLayout(folder_ctrls)
        opts_form.addRow("Filter Folders:", f_layout)

        form_layout.addWidget(config_group)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.setStyleSheet("""
            QPushButton {
                min-width: 80px;
                padding: 6px 14px;
            }
        """)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _load_profiles(self):
        self._is_loading = True
        self.combo_profile.clear()
        self.combo_profile.addItem("— Create New Definition —", None)
        profiles = self.settings.get("export_profiles", [])
        for prof in profiles:
            self.combo_profile.addItem(prof.get("name", "Unnamed Profile"), prof)
        self._is_loading = False

    def _load_folders_from_db(self):
        self.folder_list.clear()
        try:
            with self.engine.db.get_conn() as conn:
                rows = conn.execute("SELECT DISTINCT folder FROM mail_metadata WHERE is_deleted=0 ORDER BY folder").fetchall()
            for r in rows:
                item = QListWidgetItem(r["folder"])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.folder_list.addItem(item)
        except Exception as exc:
            logger.error("Failed to load folder list: %s", exc)

    def _select_all_folders(self):
        self.folder_list.blockSignals(True)
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            item.setCheckState(Qt.Checked)
            item.setForeground(QColor("#10b981"))
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        self.folder_list.blockSignals(False)
        total = self.folder_list.count()
        self.lbl_folder_summary.setText(f"Selected Folders: {total} / {total}")

    def _select_none_folders(self):
        self.folder_list.blockSignals(True)
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            item.setCheckState(Qt.Unchecked)
            item.setForeground(QColor("#64748b"))
            f = item.font()
            f.setBold(False)
            item.setFont(f)
        self.folder_list.blockSignals(False)
        self.lbl_folder_summary.setText(f"Selected Folders: 0 / {self.folder_list.count()}")

    def _get_selected_folders(self) -> Optional[List[str]]:
        folders = []
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            if item.checkState() == Qt.Checked:
                folders.append(item.text())
        return folders if len(folders) < self.folder_list.count() else None

    @Slot(QListWidgetItem)
    def _on_folder_item_changed(self, item: QListWidgetItem):
        if item.checkState() == Qt.Checked:
            item.setForeground(QColor("#10b981"))
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        else:
            item.setForeground(QColor("#64748b"))
            f = item.font()
            f.setBold(False)
            item.setFont(f)

        total = self.folder_list.count()
        checked = sum(1 for i in range(total) if self.folder_list.item(i).checkState() == Qt.Checked)
        self.lbl_folder_summary.setText(f"Selected Folders: {checked} / {total}")

    @Slot()
    def _on_format_changed(self):
        fmt = self.combo_format.currentData()
        is_server = (fmt == "IMAP_SERVER")
        self.server_group.setVisible(is_server)
        self.input_path.setVisible(not is_server)
        self.btn_browse.setVisible(not is_server)
        self.path_label.setVisible(not is_server)

    @Slot()
    def _on_browse(self):
        fmt = self.combo_format.currentData()
        if fmt == "ZIP":
            path, _ = QFileDialog.getSaveFileName(self, "Select Export Target Zip", "", "Zip Archives (*.zip)")
        elif fmt == "JSON":
            path, _ = QFileDialog.getSaveFileName(self, "Select Export Target JSON", "", "JSON Files (*.json)")
        elif fmt == "MBOX":
            path, _ = QFileDialog.getSaveFileName(self, "Select Export Target MBOX", "", "MBOX Files (*.mbox)")
        else:
            path = QFileDialog.getExistingDirectory(self, "Select Export Target Directory")
        if path:
            self.input_path.setText(path)

    @Slot(int)
    def _on_profile_selection_changed(self, idx: int):
        if self._is_loading:
            return
        prof = self.combo_profile.itemData(idx)
        if prof is None:
            self.input_profile_name.clear()
            self.input_profile_name.setEnabled(True)
            self.combo_format.setCurrentIndex(0)
            self.input_path.clear()
            self.chk_since.setChecked(False)
            self.chk_before.setChecked(False)
            self.input_host.clear()
            self.input_port.setText("993")
            self.chk_ssl.setChecked(True)
            self.input_username.clear()
            self.input_password.clear()
            self._select_all_folders()
            return
            
        self.input_profile_name.setText(prof.get("name", ""))
        self.input_profile_name.setEnabled(False)
        
        fmt = prof.get("format", "ZIP")
        f_idx = self.combo_format.findData(fmt)
        if f_idx >= 0:
            self.combo_format.setCurrentIndex(f_idx)
            
        self.input_path.setText(prof.get("target_path", ""))
        self.chk_since.setChecked(prof.get("since_enabled", False))
        if prof.get("since_date"):
            self.date_since.setDate(QDate.fromString(prof.get("since_date"), Qt.ISODate))
            
        self.chk_before.setChecked(prof.get("before_enabled", False))
        if prof.get("before_date"):
            self.date_before.setDate(QDate.fromString(prof.get("before_date"), Qt.ISODate))
            
        self.input_host.setText(prof.get("imap_host", ""))
        self.input_port.setText(prof.get("imap_port", "993"))
        self.chk_ssl.setChecked(prof.get("imap_ssl", True))
        self.input_username.setText(prof.get("imap_username", ""))
        
        pwd_enc = prof.get("imap_password_enc", "")
        if pwd_enc:
            try:
                dec = self.engine.crypto.decrypt(pwd_enc)
                self.input_password.setText(dec)
            except Exception:
                self.input_password.clear()
        else:
            self.input_password.clear()
            
        p_folders = prof.get("folders")
        if p_folders is not None:
            self._select_none_folders()
            for i in range(self.folder_list.count()):
                item = self.folder_list.item(i)
                if item.text() in p_folders:
                    item.setCheckState(Qt.Checked)
        else:
            self._select_all_folders()

    @Slot()
    def _save_current_profile(self):
        name = self.input_profile_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Please enter a profile name.")
            return
            
        profiles = self.settings.get("export_profiles", [])
        existing_prof = next((p for p in profiles if p.get("name") == name), None)
        
        folders = self._get_selected_folders()
        pwd = self.input_password.text()
        pwd_enc = self.engine.crypto.encrypt(pwd) if pwd else ""
        
        prof_data = {
            "name": name,
            "format": self.combo_format.currentData(),
            "target_path": self.input_path.text(),
            "since_enabled": self.chk_since.isChecked(),
            "since_date": self.date_since.date().toString(Qt.ISODate) if self.chk_since.isChecked() else "",
            "before_enabled": self.chk_before.isChecked(),
            "before_date": self.date_before.date().toString(Qt.ISODate) if self.chk_before.isChecked() else "",
            "imap_host": self.input_host.text().strip(),
            "imap_port": self.input_port.text().strip(),
            "imap_ssl": self.chk_ssl.isChecked(),
            "imap_username": self.input_username.text().strip(),
            "imap_password_enc": pwd_enc,
            "folders": folders
        }
        
        if existing_prof:
            reply = QMessageBox.question(
                self, "Update Definition",
                f"An export definition named '{name}' already exists. Do you want to update it?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                profiles.remove(existing_prof)
                profiles.append(prof_data)
            else:
                return
        else:
            profiles.append(prof_data)
            
        self.settings.set("export_profiles", profiles)
        self.settings.save()
        
        QMessageBox.information(self, "Success", f"Export Definition '{name}' saved.")
        self._load_profiles()

    @Slot()
    def _delete_selected_profile(self):
        idx = self.combo_profile.currentIndex()
        prof = self.combo_profile.itemData(idx)
        if prof is None:
            return
            
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete the definition '{prof.get('name')}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            profiles = self.settings.get("export_profiles", [])
            profiles = [p for p in profiles if p.get("name") != prof.get("name")]
            self.settings.set("export_profiles", profiles)
            self.settings.save()
            
            QMessageBox.information(self, "Deleted", "Profile deleted.")
            self._load_profiles()

    @Slot()
    def _test_target_connection(self):
        host = self.input_host.text().strip()
        port_str = self.input_port.text().strip()
        ssl = self.chk_ssl.isChecked()
        user = self.input_username.text().strip()
        pwd = self.input_password.text()

        if not host or not user or not pwd:
            self.lbl_target_test_status.setText("⚠️ Enter Host, User, & Password")
            self.lbl_target_test_status.setStyleSheet("color: #e67e22;")
            return

        self.btn_test_target.setEnabled(False)
        self.lbl_target_test_status.setText("⏳ Testing connection...")
        self.lbl_target_test_status.setStyleSheet("color: #4361ee;")

        def test():
            try:
                port = int(port_str) if port_str else (993 if ssl else 143)
                if ssl:
                    client = imaplib.IMAP4_SSL(host, port, timeout=15)
                else:
                    client = imaplib.IMAP4(host, port, timeout=15)
                client.login(user, pwd)
                client.logout()
                self.lbl_target_test_status.setText("✅ Connection Successful")
                self.lbl_target_test_status.setStyleSheet("color: #2d6a4f;")
            except Exception as e:
                self.lbl_target_test_status.setText(f"❌ Failed: {e}")
                self.lbl_target_test_status.setStyleSheet("color: #e63946;")
            finally:
                self.btn_test_target.setEnabled(True)

        threading.Thread(target=test, daemon=True).start()


# ---------------------------------------------------------------------------
# Main ExportPanel
# ---------------------------------------------------------------------------

class ExportPanel(QWidget):
    """Full-page panel for configuring export Definitions, running migrations, and checking server inodes."""

    _log_signal = Signal(str)
    _progress_signal = Signal(int, str, int, int)
    _export_done_signal = Signal(int, object)
    _export_error_signal = Signal(int, str)

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.settings = AppSettings()
        
        self._active_exports = {}
        self._accounts_ui = {}
        self._all_selected_flag = False

        self._setup_ui()
        self.refresh()

        self._log_signal.connect(self._on_log_message)
        self._progress_signal.connect(self._on_export_progress)
        self._export_done_signal.connect(self._on_export_done)
        self._export_error_signal.connect(self._on_export_error)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(12)

        # Stats Cards Row
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(10)
        
        self.card_total_mails = StatCard(
            "Total Archived Mails", "0000", bg_color="#3b82f6",
            callback=self._show_archived_emails_info,
            tooltip_text="Click to view database size and summary metrics per account"
        )
        self.card_exported_count = StatCard(
            "Exported Counts", "0000", bg_color="#3b82f6",
            callback=self._show_exported_count_info,
            tooltip_text="Click to view total exported mail files counts"
        )
        self.card_error_count = StatCard(
            "Error Counts", "0000", bg_color="#ef4444",
            callback=self._show_errors_info,
            tooltip_text="Click to view error details"
        )
        self.card_status = StatCard(
            "Migration Status", "Idle", bg_color="#3b82f6",
            callback=self._show_migration_status_info,
            tooltip_text="Click to view current migration task state"
        )
        self.card_total_selected = StatCard(
            "Selected Account Details", "0000", bg_color="#475569",
            callback=self._show_selected_accounts_info,
            tooltip_text="Click to view details of selected accounts"
        )
        
        stats_layout.addWidget(self.card_total_mails)
        stats_layout.addWidget(self.card_exported_count)
        stats_layout.addWidget(self.card_error_count)
        stats_layout.addWidget(self.card_status)
        stats_layout.addWidget(self.card_total_selected)
        main_layout.addLayout(stats_layout)

        # Custom Stylesheets for Buttons
        btn_style_yellow = """
            QPushButton {
                background-color: #facc15;
                color: #ef4444;
                font-weight: 900;
                border: 3px solid #ef4444;
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 11px;
                min-height: 28px;
            }
            QPushButton:hover { background-color: #eab308; }
        """
        btn_style_green = """
            QPushButton {
                background-color: #22c55e;
                color: #000000;
                font-weight: 900;
                border: 3px solid #ef4444;
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 11px;
                min-height: 28px;
            }
            QPushButton:hover { background-color: #16a34a; }
        """
        btn_style_blue = """
            QPushButton {
                background-color: #3b82f6;
                color: #ffffff;
                font-weight: 900;
                border: 3px solid #ef4444;
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 11px;
                min-height: 28px;
            }
            QPushButton:hover { background-color: #2563eb; }
        """

        # Row 2 Actions: Single row containing all buttons styled exactly like the sketch
        action_bar = QHBoxLayout()
        action_bar.setSpacing(12)

        self.btn_export_selected = QPushButton("RUN EXPORT ON CHECKED ACCOUNTS")
        self.btn_export_selected.setStyleSheet(btn_style_yellow)
        self.btn_export_selected.setToolTip("Start archiving and export for checked items.")
        self.btn_export_selected.clicked.connect(self._run_export_on_checked)

        self.btn_check_inodes = QPushButton("CHECK INODE / MESSAGE COUNTS")
        self.btn_check_inodes.setStyleSheet(btn_style_green)
        self.btn_check_inodes.setToolTip("Compare local archived counts with target server folder message limits.")
        self.btn_check_inodes.clicked.connect(self._check_inodes_and_report)

        self.btn_toggle_select_all = QPushButton("SELECT ALL ACCOUNTS")
        self.btn_toggle_select_all.setStyleSheet(btn_style_blue)
        self.btn_toggle_select_all.setToolTip("Check/Uncheck all accounts in table.")
        self.btn_toggle_select_all.clicked.connect(self._toggle_select_all_accounts)

        self.btn_configure = QPushButton("CONFIGURE TARGET FILTERS")
        self.btn_configure.setStyleSheet(btn_style_blue)
        self.btn_configure.setToolTip("Edit profile definitions, credentials, formatting and folders filter.")
        self.btn_configure.clicked.connect(self._open_config_dialog)

        action_bar.addWidget(self.btn_export_selected, stretch=1)
        action_bar.addWidget(self.btn_check_inodes, stretch=1)
        action_bar.addWidget(self.btn_toggle_select_all, stretch=1)
        action_bar.addWidget(self.btn_configure, stretch=1)
        main_layout.addLayout(action_bar)

        # Splitter for Accounts List and Reports
        splitter = QSplitter(Qt.Vertical)

        # Accounts Selection Table (Columns layout: Details, Profile Dropdown, Progress, Checked, Actions)
        self.account_table = QTableWidget()
        self.account_table.setColumnCount(5)
        self.account_table.setHorizontalHeaderLabels([
            "Account Details", "Export Profile", "Operation Progress", "Checked", "Actions"
        ])
        self.account_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.account_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.account_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.account_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.account_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.account_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.account_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.account_table.verticalHeader().setVisible(False)
        self.account_table.verticalHeader().setDefaultSectionSize(50)
        
        self.account_table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                color: #0f172a;
                gridline-color: #e2e8f0;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
            }
            QTableWidget::item {
                background-color: #ffffff;
                color: #0f172a;
                border-bottom: 1px solid #f1f5f9;
            }
        """)
        splitter.addWidget(self.account_table)

        # Inode / Folder Details Reports Table
        self.report_table = QTableWidget()
        self.report_table.setColumnCount(4)
        self.report_table.setHorizontalHeaderLabels(["Folder Name", "Local Emails (Inodes)", "Target Server Emails (Inodes)", "Status"])
        self.report_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.report_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.report_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.report_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.report_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.report_table.verticalHeader().setVisible(False)
        self.report_table.verticalHeader().setDefaultSectionSize(35)
        self.report_table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                color: #0f172a;
                gridline-color: #e2e8f0;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
            }
            QTableWidget::item {
                background-color: #ffffff;
                color: #0f172a;
                border-bottom: 1px solid #f1f5f9;
            }
        """)
        splitter.addWidget(self.report_table)

        splitter.setSizes([220, 180])
        main_layout.addWidget(splitter, stretch=1)

        # Log Logger output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(90)
        self.log_output.setStyleSheet("""
            QTextEdit {
                background: #1a1a2e;
                color: #a8d8ea;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
        """)
        main_layout.addWidget(self.log_output)

        # General Progress bar
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        self.overall_progress.setVisible(False)
        self.overall_progress.setMaximumHeight(8)
        self.overall_progress.setTextVisible(False)
        main_layout.addWidget(self.overall_progress)

    @Slot()
    def _open_config_dialog(self):
        dialog = ExportConfigDialog(self.engine, self.settings, self)
        
        c = self._current_config
        f_idx = dialog.combo_format.findData(c["format"])
        if f_idx >= 0:
            dialog.combo_format.setCurrentIndex(f_idx)
        dialog.input_path.setText(c["target_path"])
        dialog.input_host.setText(c["imap_host"])
        dialog.input_port.setText(c["imap_port"])
        dialog.chk_ssl.setChecked(c["imap_ssl"])
        dialog.input_username.setText(c["imap_username"])
        dialog.input_password.setText(c["imap_password"])
        
        if dialog.exec() == QDialog.Accepted:
            fmt = dialog.combo_format.currentData()
            self._current_config = {
                "format": fmt,
                "target_path": dialog.input_path.text().strip(),
                "imap_host": dialog.input_host.text().strip(),
                "imap_port": dialog.input_port.text().strip(),
                "imap_ssl": dialog.chk_ssl.isChecked(),
                "imap_username": dialog.input_username.text().strip(),
                "imap_password": dialog.input_password.text(),
                "folders": dialog._get_selected_folders(),
                "since_date": f"{dialog.date_since.date().year()}-{dialog.date_since.date().month():02d}-{dialog.date_since.date().day():02d} 00:00:00" if dialog.chk_since.isChecked() else None,
                "before_date": f"{dialog.date_before.date().year()}-{dialog.date_before.date().month():02d}-{dialog.date_before.date().day():02d} 23:59:59" if dialog.chk_before.isChecked() else None,
            }
            self.refresh()
            self.log_output.append("Export settings updated successfully.")

    @Slot(QComboBox)
    def _open_config_dialog_for_combo(self, combo: QComboBox):
        """Open the popup config dialog manually preloaded with the selected profile name."""
        selected_name = combo.currentText()
        dialog = ExportConfigDialog(self.engine, self.settings, self)
        
        if selected_name != "Default (ZIP)":
            profiles = self.settings.get("export_profiles", [])
            prof = next((p for p in profiles if p.get("name") == selected_name), None)
            if prof:
                f_idx = dialog.combo_profile.findText(selected_name)
                if f_idx >= 0:
                    dialog.combo_profile.setCurrentIndex(f_idx)
                    
        if dialog.exec() == QDialog.Accepted:
            self.refresh()

    # ------------------------------------------------------------------
    # Clickable Stats Card Popups Detail Queries
    # ------------------------------------------------------------------

    def _show_info_dialog(self, title: str, text: str):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(550, 320)
        dialog.setStyleSheet("""
            QDialog { background-color: #f8fafc; }
            QLabel { color: #1e293b; font-weight: bold; }
        """)
        layout = QVBoxLayout(dialog)
        
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(text)
        txt.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-size: 12px;
                padding: 10px;
            }
        """)
        layout.addWidget(txt)
        
        btn = QPushButton("Close")
        btn.setStyleSheet("""
            QPushButton {
                background-color: #4361ee;
                color: white;
                font-weight: bold;
                padding: 6px 18px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #3a56d4; }
        """)
        btn.clicked.connect(dialog.accept)
        layout.addWidget(btn, 0, Qt.AlignCenter)
        dialog.exec()

    def _show_selected_accounts_info(self):
        checked_ids = self._get_checked_account_ids()
        if not checked_ids:
            msg = "No accounts are currently selected / checked in the list table.\n\nPlease tick at least one account checkbox to prepare for export."
        else:
            msg = f"Currently selected account count: {len(checked_ids)}\n\nListing accounts below:\n"
            try:
                with self.engine.db.get_conn() as conn:
                    placeholders = ",".join("?" for _ in checked_ids)
                    rows = conn.execute(f"SELECT id, label, email FROM accounts WHERE id IN ({placeholders})").fetchall()
                    for idx, r in enumerate(rows):
                        msg += f"  {idx+1}. Label: {r['label']} | Email: {r['email']} (ID: {r['id']})\n"
            except Exception as e:
                msg += f"Error loading accounts: {e}"
        self._show_info_dialog("Selected Accounts Detail", msg)

    def _show_archived_emails_info(self):
        checked_ids = self._get_checked_account_ids()
        if not checked_ids:
            msg = "Please check one or more accounts to estimate total archived items."
        else:
            msg = "Database statistics for selected accounts:\n\n"
            try:
                with self.engine.db.get_conn() as conn:
                    for aid in checked_ids:
                        acc_row = conn.execute("SELECT label, email FROM accounts WHERE id=?", (aid,)).fetchone()
                        cnt_row = conn.execute("SELECT COUNT(*) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (aid,)).fetchone()
                        fld_row = conn.execute("SELECT COUNT(DISTINCT folder) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (aid,)).fetchone()
                        
                        label = acc_row["label"] if acc_row else f"ID: {aid}"
                        email = acc_row["email"] if acc_row else "?"
                        msg += f"• Account: {label} ({email})\n"
                        msg += f"  - Total Mails: {cnt_row['cnt'] if cnt_row else 0}\n"
                        msg += f"  - Folders: {fld_row['cnt'] if fld_row else 0}\n\n"
            except Exception as e:
                msg += f"Error querying statistics: {e}"
        self._show_info_dialog("Database Archived Stats Details", msg)

    def _show_exported_count_info(self):
        msg = f"Export Statistics Report\n\nTotal emails successfully exported during the current run: {self.card_exported_count.value_label.text()}\n\nLogs and files will be updated in the Target folder configured."
        self._show_info_dialog("Export Summary Details", msg)

    def _show_errors_info(self):
        msg = f"Error Tracking Summary\n\nError Count state: {self.card_error_count.value_label.text()}\n\nPlease inspect the logs below inside the terminal panel or export logger text box for exact error track messages."
        self._show_info_dialog("Error log summary", msg)

    def _show_migration_status_info(self):
        msg = f"Current Migration Task status: {self.card_status.value_label.text()}\n\nStates explanation:\n- Idle: Ready for commands.\n- Running: Currently migrating messages sequentially.\n- Complete: Done archiving items."
        self._show_info_dialog("Migration Status Details", msg)

    # ------------------------------------------------------------------
    # Inodes check / report
    # ------------------------------------------------------------------

    @Slot()
    def _check_inodes_and_report(self):
        checked_ids = self._get_checked_account_ids()
        if not checked_ids:
            QMessageBox.warning(self, "No Accounts Selected", "Please check at least one account to verify counts.")
            return

        first_checked_id = checked_ids[0]
        row_idx = -1
        for i in range(self.account_table.rowCount()):
            widget = self.account_table.cellWidget(i, 3)
            if widget:
                chk = widget.findChild(QCheckBox)
                if chk and chk.property("account_id") == first_checked_id:
                    row_idx = i
                    break

        if row_idx == -1:
            return

        c = self._get_profile_for_row(row_idx)
        fmt = c.get("format", "ZIP")
        if fmt != "IMAP_SERVER":
            QMessageBox.warning(self, "Unsupported Target", "Inode checks are only supported for target IMAP mail servers. Assign an IMAP target profile to this account first.")
            return

        host = c.get("imap_host", "")
        port_str = str(c.get("imap_port", "993"))
        ssl = c.get("imap_ssl", True)
        user = c.get("imap_username", "")
        pwd_enc = c.get("imap_password_enc", "")
        pwd = ""
        if pwd_enc:
            try:
                pwd = self.engine.crypto.decrypt(pwd_enc)
            except Exception:
                pass

        if not host or not user or not pwd:
            QMessageBox.warning(self, "Configuration Required", "Selected profile is missing target IMAP server settings (host, username, password).")
            return

        self.btn_check_inodes.setEnabled(False)
        self.log_output.append("=== Starting Inode (Message) counts check on target IMAP server ===")
        self.report_table.setRowCount(0)

        def query():
            try:
                port = int(port_str) if port_str else (993 if ssl else 143)
                if ssl:
                    client = imaplib.IMAP4_SSL(host, port, timeout=15)
                else:
                    client = imaplib.IMAP4(host, port, timeout=15)
                client.login(user, pwd)

                folders = c.get("folders")
                if not folders:
                    with self.engine.db.get_conn() as conn:
                        placeholders = ",".join("?" for _ in checked_ids)
                        rows = conn.execute(f"SELECT DISTINCT folder FROM mail_metadata WHERE account_id IN ({placeholders}) AND is_deleted=0", checked_ids).fetchall()
                        folders = [r["folder"] for r in rows]

                self.log_output.append(f"Querying message counts for {len(folders)} folders...")
                
                local_counts = {}
                with self.engine.db.get_conn() as conn:
                    placeholders = ",".join("?" for _ in checked_ids)
                    count_rows = conn.execute(
                        f"SELECT folder, COUNT(*) as cnt FROM mail_metadata WHERE account_id IN ({placeholders}) AND is_deleted=0 GROUP BY folder",
                        checked_ids
                    ).fetchall()
                    for r in count_rows:
                        local_counts[r["folder"]] = r["cnt"]

                for i, folder in enumerate(folders):
                    local_cnt = local_counts.get(folder, 0)
                    target_cnt = 0
                    status = "Not Found on Server"
                    
                    try:
                        res, data = client.select(folder, readonly=True)
                        if res == 'OK':
                            target_cnt = int(data[0])
                            if target_cnt == local_cnt:
                                status = "In Sync"
                            elif target_cnt < local_cnt:
                                status = f"Target missing {local_cnt - target_cnt} messages"
                            else:
                                status = f"Target has {target_cnt - local_cnt} extra messages"
                    except Exception:
                        pass
                    
                    def update_ui(idx=i, fld=folder, l_cnt=local_cnt, t_cnt=target_cnt, st=status):
                        row = self.report_table.rowCount()
                        self.report_table.insertRow(row)
                        self.report_table.setItem(row, 0, QTableWidgetItem(fld))
                        self.report_table.setItem(row, 1, QTableWidgetItem(str(l_cnt)))
                        self.report_table.setItem(row, 2, QTableWidgetItem(str(t_cnt)))
                        
                        st_item = QTableWidgetItem(st)
                        if "Sync" in st:
                            st_item.setForeground(QColor("#10b981"))
                        elif "missing" in st:
                            st_item.setForeground(QColor("#f59e0b"))
                        self.report_table.setItem(row, 3, st_item)

                    update_ui()
                
                client.logout()
                self.log_output.append("=== Inode counts check complete ===")
            except Exception as e:
                self.log_output.append(f"❌ Inode check failed: {e}")
            finally:
                self.btn_check_inodes.setEnabled(True)

        threading.Thread(target=query, daemon=True).start()

    # ------------------------------------------------------------------
    # Running Exports
    # ------------------------------------------------------------------

    def _get_profile_for_row(self, row_idx: int) -> dict:
        widget = self.account_table.cellWidget(row_idx, 1)
        if not widget:
            return {"format": "ZIP"}
        combo = widget.findChild(QComboBox)
        if not combo:
            return {"format": "ZIP"}
        profile_name = combo.currentText()
        if profile_name.startswith("Default"):
            return {"format": "ZIP", "target_path": str(Path("data/exports"))}
            
        profiles = self.settings.get("export_profiles", [])
        prof = next((p for p in profiles if p.get("name") == profile_name), None)
        return prof or {"format": "ZIP", "target_path": str(Path("data/exports"))}

    @Slot()
    def _run_export_on_checked(self):
        checked_ids = self._get_checked_account_ids()
        if not checked_ids:
            QMessageBox.warning(self, "No Accounts Selected", "Please check at least one account in the table.")
            return

        self.btn_export_selected.setEnabled(False)
        self.btn_configure.setEnabled(False)
        self.card_status.set_value("Running")
        self.overall_progress.setVisible(True)
        self.overall_progress.setValue(0)

        self.log_output.append(f"=== Starting export run for {len(checked_ids)} accounts ===")

        def run_all():
            for idx, acc_id in enumerate(checked_ids):
                ui = self._accounts_ui.get(acc_id)
                if not ui:
                    continue
                
                row_idx = -1
                for r_i in range(self.account_table.rowCount()):
                    widget = self.account_table.cellWidget(r_i, 3)
                    if widget:
                        chk = widget.findChild(QCheckBox)
                        if chk and chk.property("account_id") == acc_id:
                            row_idx = r_i
                            break
                
                if row_idx == -1:
                    continue

                c = self._get_profile_for_row(row_idx)
                fmt = c.get("format", "ZIP")
                target_path = Path(c.get("target_path", "")) if c.get("target_path") else Path("data/exports")

                imap_host = None
                imap_port = None
                imap_ssl = c.get("imap_ssl", True)
                imap_username = None
                imap_password = None

                if fmt == "IMAP_SERVER":
                    imap_host = c.get("imap_host", "")
                    port_str = str(c.get("imap_port", "993"))
                    imap_username = c.get("imap_username", "")
                    pwd_enc = c.get("imap_password_enc", "")
                    if pwd_enc:
                        try:
                            imap_password = self.engine.crypto.decrypt(pwd_enc)
                        except Exception:
                            pass

                    if not imap_host or not imap_username or not imap_password:
                        self.log_output.append(f"⚠️ Skipping Account ID {acc_id}: Profile IMAP credentials missing.")
                        continue
                    try:
                        imap_port = int(port_str) if port_str else 993
                    except ValueError:
                        self.log_output.append(f"⚠️ Skipping Account ID {acc_id}: Port formatting value error.")
                        continue

                folders = c.get("folders")
                since_date = c.get("since_date")
                before_date = c.get("before_date")

                cancel_event = threading.Event()
                self._active_exports[acc_id] = {
                    "cancel_event": cancel_event,
                    "status": "Starting",
                }
                
                ui["btn_start"].setEnabled(False)
                ui["lbl_status"].setText("Running...")
                ui["progress_bar"].setRange(0, 0)

                def cb(curr, tot, aid=acc_id):
                    self._progress_signal.emit(aid, "Exporting", curr, tot)

                try:
                    report = self.engine.export_mails(
                        account_id=acc_id,
                        format_type=fmt,
                        output_path=target_path,
                        folders=folders,
                        since_date=since_date,
                        before_date=before_date,
                        progress_callback=cb,
                        imap_host=imap_host,
                        imap_port=imap_port,
                        imap_ssl=imap_ssl,
                        imap_username=imap_username,
                        imap_password=imap_password
                    )
                    self._export_done_signal.emit(acc_id, report)
                except Exception as exc:
                    self._export_error_signal.emit(acc_id, str(exc))

                self.overall_progress.setValue(int(((idx + 1) / len(checked_ids)) * 100))

                if cancel_event.is_set():
                    break

            self.btn_export_selected.setEnabled(True)
            self.btn_configure.setEnabled(True)
            self.card_status.set_value("Complete")
            self.overall_progress.setVisible(False)
            self.log_output.append("=== Finished export runs ===")

        threading.Thread(target=run_all, daemon=True).start()

    # ------------------------------------------------------------------
    # Signals/Slots for UI updates
    # ------------------------------------------------------------------

    @Slot(int, str, int, int)
    def _on_export_progress(self, account_id: int, status_text: str, current: int, total: int):
        ui = self._accounts_ui.get(account_id)
        if ui:
            ui["lbl_status"].setText(f"{status_text} ({current}/{total})")
            ui["progress_bar"].setRange(0, total)
            ui["progress_bar"].setValue(current)
        self.card_exported_count.set_value(str(current))

    @Slot(int, object)
    def _on_export_done(self, account_id: int, report: dict):
        ui = self._accounts_ui.get(account_id)
        if ui:
            ui["btn_start"].setEnabled(True)
            ui["lbl_status"].setText("Done")
            ui["progress_bar"].setRange(0, 100)
            ui["progress_bar"].setValue(100)
        self._active_exports.pop(account_id, None)
        self.log_output.append(f"Account ID {account_id} export complete: {report.get('exported', 0)} exported, {report.get('errors', 0)} errors.")

    @Slot(int, str)
    def _on_export_error(self, account_id: int, err_msg: str):
        ui = self._accounts_ui.get(account_id)
        if ui:
            ui["btn_start"].setEnabled(True)
            ui["lbl_status"].setText("Error")
            ui["progress_bar"].setRange(0, 100)
            ui["progress_bar"].setValue(0)
        self._active_exports.pop(account_id, None)
        self.log_output.append(f"❌ Account ID {account_id} export failed: {err_msg}")
        self.card_error_count.set_value("Error")

    @Slot(str)
    def _on_log_message(self, msg: str):
        self.log_output.append(msg)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_checked_account_ids(self) -> List[int]:
        ids = []
        for i in range(self.account_table.rowCount()):
            widget = self.account_table.cellWidget(i, 3)
            if widget:
                chk = widget.findChild(QCheckBox)
                if chk and chk.isChecked():
                    ids.append(chk.property("account_id"))
        return ids

    @Slot()
    def _toggle_select_all_accounts(self):
        self._all_selected_flag = not self._all_selected_flag
        for i in range(self.account_table.rowCount()):
            widget = self.account_table.cellWidget(i, 3)
            if widget:
                chk = widget.findChild(QCheckBox)
                if chk:
                    chk.blockSignals(True)
                    chk.setChecked(self._all_selected_flag)
                    chk.blockSignals(False)
        self.btn_toggle_select_all.setText("DESELECT ALL ACCOUNTS" if self._all_selected_flag else "SELECT ALL ACCOUNTS")
        self._update_stats_on_selection()

    @Slot()
    def _update_stats_on_selection(self):
        checked = self._get_checked_account_ids()
        self.card_total_selected.set_value(str(len(checked)))
        total_mails = 0
        if checked:
            try:
                with self.engine.db.get_conn() as conn:
                    placeholders = ",".join("?" for _ in checked)
                    row = conn.execute(f"SELECT COUNT(*) as cnt FROM mail_metadata WHERE account_id IN ({placeholders}) AND is_deleted=0", checked).fetchone()
                    total_mails = row["cnt"] if row else 0
            except Exception:
                pass
        self.card_total_mails.set_value(str(total_mails))

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self):
        self.account_table.blockSignals(True)
        self.account_table.setRowCount(0)
        self._accounts_ui.clear()
        
        try:
            accounts = self.engine.list_accounts()
            self.account_table.setRowCount(len(accounts))
            
            profiles = self.settings.get("export_profiles", [])
            profile_names = [p.get("name") for p in profiles if p.get("name")]
            
            for i, acc in enumerate(accounts):
                acc_id = acc["id"]
                
                # Fetch counts
                local_mails_cnt = 0
                folders_cnt = 0
                try:
                    with self.engine.db.get_conn() as conn:
                        row_mails = conn.execute("SELECT COUNT(*) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (acc_id,)).fetchone()
                        local_mails_cnt = row_mails["cnt"] if row_mails else 0
                        row_folders = conn.execute("SELECT COUNT(DISTINCT folder) as cnt FROM mail_metadata WHERE account_id=? AND is_deleted=0", (acc_id,)).fetchone()
                        folders_cnt = row_folders["cnt"] if row_folders else 0
                except Exception:
                    pass

                # Col 0: Account details
                info_widget = QWidget()
                info_widget.setStyleSheet("background: transparent;")
                info_layout = QVBoxLayout(info_widget)
                info_layout.setContentsMargins(6, 4, 6, 4)
                info_layout.setSpacing(2)
                
                lbl_label = QLabel(f"<b>{acc['label']}</b>")
                lbl_label.setStyleSheet("color: #1e293b; font-size: 13px; background: transparent; font-weight: bold;")
                lbl_email = QLabel(f"{acc['email']}  |  📁 {folders_cnt} folders  |  📧 {local_mails_cnt} archived")
                lbl_email.setStyleSheet("color: #475569; font-size: 11px; background: transparent; font-weight: 500;")
                info_layout.addWidget(lbl_label)
                info_layout.addWidget(lbl_email)
                self.account_table.setCellWidget(i, 0, info_widget)
                
                # Col 1: Export Profile dropdown + ⚙️ configure popup button
                prof_widget = QWidget()
                prof_widget.setStyleSheet("background: transparent;")
                prof_layout = QHBoxLayout(prof_widget)
                prof_layout.setContentsMargins(2, 2, 2, 2)
                prof_layout.setSpacing(4)
                
                combo = QComboBox()
                combo.setStyleSheet("""
                    QComboBox {
                        background-color: #ffffff;
                        color: #0f172a;
                        border: 1px solid #cbd5e1;
                        border-radius: 4px;
                        padding: 4px;
                        font-size: 11px;
                        min-width: 110px;
                    }
                """)
                combo.addItem("Default (ZIP)")
                for name in profile_names:
                    combo.addItem(name)
                
                btn_edit_prof = QPushButton("⚙")
                btn_edit_prof.setToolTip("Edit profile dynamically in manual popup config dialog")
                btn_edit_prof.setCursor(Qt.PointingHandCursor)
                btn_edit_prof.setStyleSheet("""
                    QPushButton {
                        background-color: #f1f5f9;
                        color: #0f172a;
                        border: 1px solid #cbd5e1;
                        border-radius: 4px;
                        font-weight: bold;
                        font-size: 12px;
                        padding: 4px;
                        min-width: 24px;
                        max-width: 24px;
                    }
                    QPushButton:hover {
                        background-color: #cbd5e1;
                    }
                """)
                btn_edit_prof.clicked.connect(lambda checked, c=combo: self._open_config_dialog_for_combo(c))
                
                prof_layout.addWidget(combo, stretch=1)
                prof_layout.addWidget(btn_edit_prof)
                self.account_table.setCellWidget(i, 1, prof_widget)
                
                # Col 2: Progress status
                prog_widget = QWidget()
                prog_widget.setStyleSheet("background: transparent;")
                prog_layout = QVBoxLayout(prog_widget)
                prog_layout.setContentsMargins(6, 4, 6, 4)
                prog_layout.setSpacing(2)
                
                lbl_status = QLabel("Idle")
                lbl_status.setStyleSheet("color: #475569; font-size: 11px; background: transparent;")
                progress_bar = QProgressBar()
                progress_bar.setRange(0, 100)
                progress_bar.setValue(0)
                progress_bar.setStyleSheet("""
                    QProgressBar {
                        background: #e2e8f0;
                        border: none;
                        border-radius: 4px;
                        height: 12px;
                        font-size: 9px;
                        text-align: center;
                        color: #1e293b;
                    }
                    QProgressBar::chunk {
                        background: #4361ee;
                        border-radius: 4px;
                    }
                """)
                prog_layout.addWidget(lbl_status)
                prog_layout.addWidget(progress_bar)
                self.account_table.setCellWidget(i, 2, prog_widget)

                # Col 3: Checked / Selection centered widget checkbox
                chk_widget = QWidget()
                chk_widget.setStyleSheet("background: transparent;")
                chk_layout = QHBoxLayout(chk_widget)
                chk_layout.setContentsMargins(0, 0, 0, 0)
                chk_layout.setSpacing(0)
                
                chk = QCheckBox()
                chk.setStyleSheet("""
                    QCheckBox::indicator {
                        width: 18px;
                        height: 18px;
                        border: 2px solid #4361ee;
                        border-radius: 4px;
                        background-color: #ffffff;
                    }
                    QCheckBox::indicator:checked {
                        background-color: #10b981;
                        border-color: #10b981;
                        image: url(data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>);
                    }
                    QCheckBox::indicator:unchecked {
                        background-color: #ffffff;
                        border: 2px solid #64748b;
                    }
                    QCheckBox::indicator:hover {
                        border-color: #4361ee;
                        background-color: #f1f5f9;
                    }
                """)
                chk.setProperty("account_id", acc_id)
                chk.setChecked(False)
                chk.toggled.connect(lambda checked: self._update_stats_on_selection())
                chk_layout.addWidget(chk, 0, Qt.AlignCenter)
                self.account_table.setCellWidget(i, 3, chk_widget)

                # Col 4: Actions
                actions_widget = QWidget()
                actions_widget.setStyleSheet("background: transparent;")
                actions_layout = QHBoxLayout(actions_widget)
                actions_layout.setContentsMargins(4, 2, 4, 2)
                actions_layout.setSpacing(4)
                
                btn_start = QPushButton("▶")
                btn_start.setToolTip("Start export for this account")
                btn_start.setStyleSheet("background:#10b981; color:white; font-size:11px; font-weight:bold; padding:4px 8px; border-radius:4px;")
                btn_start.clicked.connect(lambda checked, aid=acc_id: self._run_individual_export(aid))
                
                btn_pause = QPushButton("⏸")
                btn_pause.setToolTip("Pause/Resume export")
                btn_pause.setStyleSheet("background:#f59e0b; color:white; font-size:11px; font-weight:bold; padding:4px 8px; border-radius:4px;")
                btn_pause.setEnabled(False)
                
                btn_stop = QPushButton("⏹")
                btn_stop.setToolTip("Stop export")
                btn_stop.setStyleSheet("background:#ef4444; color:white; font-size:11px; font-weight:bold; padding:4px 8px; border-radius:4px;")
                btn_stop.setEnabled(False)
                
                actions_layout.addWidget(btn_start)
                actions_layout.addWidget(btn_pause)
                actions_layout.addWidget(btn_stop)
                self.account_table.setCellWidget(i, 4, actions_widget)

                self._accounts_ui[acc_id] = {
                    "chk": chk,
                    "lbl_status": lbl_status,
                    "progress_bar": progress_bar,
                    "btn_start": btn_start,
                }
        except Exception as e:
            logger.error("Failed to refresh list: %s", e)
        finally:
            self.account_table.blockSignals(False)

    def _run_individual_export(self, account_id: int):
        for i in range(self.account_table.rowCount()):
            widget = self.account_table.cellWidget(i, 3)
            if widget:
                chk = widget.findChild(QCheckBox)
                if chk:
                    chk.setChecked(chk.property("account_id") == account_id)
        self._update_stats_on_selection()
        self._run_export_on_checked()
