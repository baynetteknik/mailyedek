"""
export_dialog.py — Dialog for exporting emails in ZIP, EML, JSON, MBOX, or pushing to an IMAP Server.
Includes saved export profile/definition management, dynamic scroll area, and screen-resolution bounding.
"""

import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, List

from PySide6.QtCore import Qt, Slot, Signal, QDate
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame, QScrollArea, QWidget,
    QComboBox, QListWidget, QListWidgetItem, QCheckBox, QDateEdit,
    QLineEdit, QPushButton, QFileDialog, QProgressBar, QTextEdit,
    QMessageBox, QDialogButtonBox, QLabel, QAbstractItemView, QGroupBox,
)

from core.mail_engine import MailEngine
from core.settings import AppSettings

logger = logging.getLogger(__name__)

class ExportDialog(QDialog):
    """Modal dialog for exporting archived emails with dynamic formats, profiles, and server push options."""

    progress_signal = Signal(int, int)  # current, total
    done_signal = Signal(object)        # report dict
    error_signal = Signal(str)         # error message

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.settings = AppSettings()
        self._is_loading = True
        
        self._setup_ui()
        self._load_accounts()
        self._load_profiles()
        
        self._is_loading = False
        self._on_account_changed()
        self._on_format_changed()
        
        self.progress_signal.connect(self._on_progress)
        self.done_signal.connect(self._on_done)
        self.error_signal.connect(self._on_error)

    def _setup_ui(self):
        self.setWindowTitle("Export Mails")
        self.setModal(True)
        
        # Determine sizes based on display resolution
        screen = QGuiApplication.primaryScreen()
        if screen:
            screen_geom = screen.availableGeometry()
            width = min(660, screen_geom.width() - 40)
            height = min(580, screen_geom.height() - 80)
            self.resize(width, height)
        else:
            self.resize(650, 560)
            
        self.setStyleSheet("""
            QDialog {
                background: #f8f9fa;
            }
            QLabel[heading="true"] {
                font-size: 18px;
                font-weight: 700;
                color: #1a1a2e;
                padding: 4px 0;
            }
            QFrame#form_frame {
                background: #ffffff;
                border: 1px solid #e0e3e8;
                border-radius: 8px;
                padding: 16px;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 12px;
            }
            QListWidget {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
            }
            QLineEdit, QComboBox, QDateEdit {
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QTextEdit {
                background: #1e293b;
                color: #e2e8f0;
                font-family: 'Consolas', monospace;
                font-size: 11px;
                border: 1px solid #334155;
                border-radius: 6px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        # Header
        header = QLabel("📤  Export Emails / Server Migration")
        header.setProperty("heading", "true")
        layout.addWidget(header)

        sub = QLabel("Select an account, save export profiles, export locally, or migrate to another server.")
        sub.setStyleSheet("color: #64748b; font-size: 11px; margin-bottom: 2px;")
        layout.addWidget(sub)

        # Profile/Definition Management Group (Fixed at the top)
        profile_group = QGroupBox("Export Definitions & Profiles")
        profile_layout = QHBoxLayout(profile_group)
        profile_layout.setContentsMargins(10, 8, 10, 8)
        self.combo_profile = QComboBox()
        self.combo_profile.setMinimumWidth(180)
        self.combo_profile.currentIndexChanged.connect(self._on_profile_selection_changed)
        
        self.input_profile_name = QLineEdit()
        self.input_profile_name.setPlaceholderText("New Profile Name...")
        
        self.btn_save_profile = QPushButton("💾 Save")
        self.btn_save_profile.setStyleSheet("background:#10b981; color:white; font-weight:bold; padding:4px 8px; border-radius:4px;")
        self.btn_save_profile.clicked.connect(self._save_current_profile)
        
        self.btn_delete_profile = QPushButton("🗑 Delete")
        self.btn_delete_profile.setStyleSheet("background:#ef4444; color:white; font-weight:bold; padding:4px 8px; border-radius:4px;")
        self.btn_delete_profile.clicked.connect(self._delete_selected_profile)
        
        profile_layout.addWidget(QLabel("Profile:"))
        profile_layout.addWidget(self.combo_profile)
        profile_layout.addWidget(self.input_profile_name)
        profile_layout.addWidget(self.btn_save_profile)
        profile_layout.addWidget(self.btn_delete_profile)
        layout.addWidget(profile_group)

        # Scroll Area for the form details (to prevent offscreen overflow)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        form_layout_main = QVBoxLayout(scroll_content)
        form_layout_main.setContentsMargins(0, 0, 0, 0)
        form_layout_main.setSpacing(8)

        # Form Container
        form_frame = QFrame()
        form_frame.setObjectName("form_frame")
        self.form_layout = QFormLayout(form_frame)
        self.form_layout.setSpacing(8)
        self.form_layout.setLabelAlignment(Qt.AlignRight)

        # 1. Account
        self.combo_account = QComboBox()
        self.form_layout.addRow("Select Account:", self.combo_account)

        # 2. Format
        self.combo_format = QComboBox()
        self.combo_format.addItem("ZIP Archive of EMLs (.zip)", "ZIP")
        self.combo_format.addItem("Directory of Raw EMLs (Thunderbird / Opera)", "DIRECTORY")
        self.combo_format.addItem("Single JSON Metadata file (.json)", "JSON")
        self.combo_format.addItem("Thunderbird MBOX Package (.mbox)", "MBOX")
        self.combo_format.addItem("Push to Mail Server (Outlook / IMAP)", "IMAP_SERVER")
        self.form_layout.addRow("Export Format / Target:", self.combo_format)

        # 3. Local Target Path Row
        self.path_label = QLabel("Target Path:")
        self.path_layout = QHBoxLayout()
        self.input_path = QLineEdit()
        self.input_path.setReadOnly(True)
        self.input_path.setPlaceholderText("Select target file or directory...")
        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.setStyleSheet("""
            QPushButton {
                background: #e2e8f0;
                color: #334155;
                border-radius: 4px;
                padding: 4px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #cbd5e1;
            }
        """)
        self.path_layout.addWidget(self.input_path)
        self.path_layout.addWidget(self.btn_browse)
        self.form_layout.addRow(self.path_label, self.path_layout)

        # 4. IMAP Server Connection Settings Group (Visible only if IMAP_SERVER is chosen)
        self.server_group = QGroupBox("Target IMAP Server Configuration")
        server_form = QFormLayout(self.server_group)
        server_form.setSpacing(6)
        
        self.input_host = QLineEdit()
        self.input_host.setPlaceholderText("e.g. imap.gmail.com")
        server_form.addRow("Host Server:", self.input_host)
        
        port_layout = QHBoxLayout()
        self.input_port = QLineEdit("993")
        self.input_port.setFixedWidth(60)
        self.chk_ssl = QCheckBox("Use SSL/TLS")
        self.chk_ssl.setChecked(True)
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
        
        self.form_layout.addRow("", self.server_group)

        # 5. Dates
        dates_layout = QHBoxLayout()
        self.chk_since = QCheckBox("Since:")
        self.chk_since.setStyleSheet("font-size: 11px;")
        self.date_since = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_since.setCalendarPopup(True)
        self.date_since.setEnabled(False)
        self.chk_since.toggled.connect(self.date_since.setEnabled)

        self.chk_before = QCheckBox("Before:")
        self.chk_before.setStyleSheet("font-size: 11px;")
        self.date_before = QDateEdit(QDate.currentDate())
        self.date_before.setCalendarPopup(True)
        self.date_before.setEnabled(False)
        self.chk_before.toggled.connect(self.date_before.setEnabled)

        dates_layout.addWidget(self.chk_since)
        dates_layout.addWidget(self.date_since)
        dates_layout.addWidget(self.chk_before)
        dates_layout.addWidget(self.date_before)
        self.form_layout.addRow("Date Range:", dates_layout)

        # 6. Folders List
        self.folder_list = QListWidget()
        self.folder_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.folder_list.setMinimumHeight(80)
        self.folder_list.setMaximumHeight(100)
        
        folder_ctrl = QHBoxLayout()
        btn_all = QPushButton("All")
        btn_all.setStyleSheet("padding: 2px 6px; font-size: 10px;")
        btn_all.clicked.connect(self._select_all_folders)
        btn_none = QPushButton("None")
        btn_none.setStyleSheet("padding: 2px 6px; font-size: 10px;")
        btn_none.clicked.connect(self._select_none_folders)
        folder_ctrl.addWidget(btn_all)
        folder_ctrl.addWidget(btn_none)
        folder_ctrl.addStretch()

        folder_vbox = QVBoxLayout()
        folder_vbox.addWidget(self.folder_list)
        folder_vbox.addLayout(folder_ctrl)
        self.form_layout.addRow("Select Folders:", folder_vbox)

        form_layout_main.addWidget(form_frame)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)

        # Bottom section fixed (keeps controls visible always)
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(6)

        # Progress Section
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        bottom_layout.addWidget(self.progress_bar)

        self.lbl_progress = QLabel("")
        self.lbl_progress.setStyleSheet("color: #475569; font-size: 11px; font-weight: 600;")
        self.lbl_progress.setVisible(False)
        bottom_layout.addWidget(self.lbl_progress)

        # Log output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(70)
        self.log_output.setPlaceholderText("Export logs will appear here...")
        bottom_layout.addWidget(self.log_output)

        # Dialog Buttons
        self.button_box = QDialogButtonBox()
        self.btn_export = QPushButton("📤 Start Export")
        self.btn_export.setStyleSheet("""
            QPushButton {
                background: #4361ee;
                color: white;
                font-weight: bold;
                padding: 6px 18px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background: #3a56d4;
            }
            QPushButton:disabled {
                background: #cbd5e1;
                color: #94a3b8;
            }
        """)
        self.btn_cancel = QPushButton("Close")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background: #64748b;
                color: white;
                font-weight: bold;
                padding: 6px 18px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background: #475569;
            }
        """)
        self.button_box.addButton(self.btn_export, QDialogButtonBox.AcceptRole)
        self.button_box.addButton(self.btn_cancel, QDialogButtonBox.RejectRole)
        self.button_box.accepted.connect(self._start_export)
        self.button_box.rejected.connect(self.reject)
        bottom_layout.addWidget(self.button_box)

        layout.addWidget(bottom_widget)

        # Connections
        self.combo_account.currentIndexChanged.connect(self._on_account_changed)
        self.combo_format.currentIndexChanged.connect(self._on_format_changed)
        self.btn_browse.clicked.connect(self._on_browse)

    def _load_accounts(self):
        self.combo_account.clear()
        try:
            accounts = self.engine.list_accounts()
            for acc in accounts:
                self.combo_account.addItem(f"{acc['label']} ({acc['email']})", acc["id"])
        except Exception as e:
            logger.exception("Failed to load accounts in export dialog")
            QMessageBox.critical(self, "Error", f"Failed to load accounts: {e}")

    def _load_profiles(self):
        self._is_loading = True
        self.combo_profile.clear()
        self.combo_profile.addItem("— Create New Definition —", None)
        
        profiles = self.settings.get("export_profiles", [])
        for prof in profiles:
            self.combo_profile.addItem(prof.get("name", "Unnamed Profile"), prof)
        self._is_loading = False

    def _select_all_folders(self):
        for i in range(self.folder_list.count()):
            self.folder_list.item(i).setCheckState(Qt.Checked)

    def _select_none_folders(self):
        for i in range(self.folder_list.count()):
            self.folder_list.item(i).setCheckState(Qt.Unchecked)

    @Slot()
    def _on_account_changed(self):
        if self._is_loading:
            return
        self.folder_list.clear()
        acc_id = self.combo_account.currentData()
        if acc_id is None:
            return
        
        try:
            with self.engine.db.get_conn() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT folder FROM mail_metadata WHERE account_id=? AND is_deleted=0 ORDER BY folder",
                    (acc_id,)
                ).fetchall()
                folders = [r["folder"] for r in rows]
                
            for f in folders:
                item = QListWidgetItem(f)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.folder_list.addItem(item)
        except Exception as e:
            logger.exception("Failed to load folders for export account")

    @Slot()
    def _on_format_changed(self):
        fmt = self.combo_format.currentData()
        
        is_server = (fmt == "IMAP_SERVER")
        self.server_group.setVisible(is_server)
        self.input_path.setVisible(not is_server)
        self.btn_browse.setVisible(not is_server)
        self.path_label.setVisible(not is_server)
        
        self.input_path.clear()

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

    @Slot()
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
            QMessageBox.warning(self, "Validation Error", "Please enter a name for the Export Definition profile.")
            return
            
        profiles = self.settings.get("export_profiles", [])
        
        existing_prof = None
        for p in profiles:
            if p.get("name") == name:
                existing_prof = p
                break
                
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
        
        QMessageBox.information(self, "Success", f"Export Definition '{name}' saved successfully.")
        self._load_profiles()
        
        for i in range(self.combo_profile.count()):
            item_data = self.combo_profile.itemData(i)
            if item_data and item_data.get("name") == name:
                self.combo_profile.setCurrentIndex(i)
                break

    @Slot()
    def _delete_selected_profile(self):
        idx = self.combo_profile.currentIndex()
        prof = self.combo_profile.itemData(idx)
        if prof is None:
            return
            
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete the export definition profile '{prof.get('name')}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            profiles = self.settings.get("export_profiles", [])
            profiles = [p for p in profiles if p.get("name") != prof.get("name")]
            self.settings.set("export_profiles", profiles)
            self.settings.save()
            
            QMessageBox.information(self, "Deleted", "Profile deleted successfully.")
            self._load_profiles()

    def _get_selected_folders(self) -> Optional[List[str]]:
        folders = []
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            if item.checkState() == Qt.Checked:
                folders.append(item.text())
        return folders if len(folders) < self.folder_list.count() else None

    @Slot()
    def _start_export(self):
        acc_id = self.combo_account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "Validation Error", "Please select an account.")
            return

        fmt = self.combo_format.currentData()
        
        target_path_str = self.input_path.text().strip()
        target_path = Path(target_path_str) if target_path_str else None
        
        imap_host = None
        imap_port = None
        imap_username = None
        imap_password = None
        imap_ssl = self.chk_ssl.isChecked()
        
        if fmt == "IMAP_SERVER":
            imap_host = self.input_host.text().strip()
            port_str = self.input_port.text().strip()
            imap_username = self.input_username.text().strip()
            imap_password = self.input_password.text()
            
            if not imap_host:
                QMessageBox.warning(self, "Validation Error", "Please enter target IMAP host.")
                return
            if not imap_username:
                QMessageBox.warning(self, "Validation Error", "Please enter target IMAP username.")
                return
            if not imap_password:
                QMessageBox.warning(self, "Validation Error", "Please enter target IMAP password.")
                return
                
            try:
                imap_port = int(port_str) if port_str else 993
            except ValueError:
                QMessageBox.warning(self, "Validation Error", "IMAP Port must be a number.")
                return
        else:
            if not target_path_str:
                QMessageBox.warning(self, "Validation Error", "Please specify a target path.")
                return

        folders = self._get_selected_folders()
        
        since_date = None
        if self.chk_since.isChecked():
            qdate = self.date_since.date()
            since_date = f"{qdate.year()}-{qdate.month():02d}-{qdate.day():02d} 00:00:00"
            
        before_date = None
        if self.chk_before.isChecked():
            qdate = self.date_before.date()
            before_date = f"{qdate.year()}-{qdate.month():02d}-{qdate.day():02d} 23:59:59"

        self.btn_export.setEnabled(False)
        self.combo_account.setEnabled(False)
        self.combo_format.setEnabled(False)
        self.combo_profile.setEnabled(False)
        self.btn_save_profile.setEnabled(False)
        self.btn_delete_profile.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.chk_since.setEnabled(False)
        self.chk_before.setEnabled(False)
        self.folder_list.setEnabled(False)
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.lbl_progress.setVisible(True)
        self.lbl_progress.setText("Quering database...")
        
        if fmt == "IMAP_SERVER":
            self.log_output.append(f"Starting migration to target server {imap_host}...")
        else:
            self.log_output.append(f"Starting export to {target_path_str} in format {fmt}...")

        def run():
            def cb(curr, tot):
                self.progress_signal.emit(curr, tot)
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
                self.done_signal.emit(report)
            except Exception as exc:
                self.error_signal.emit(str(exc))

        threading.Thread(target=run, daemon=True).start()

    @Slot(int, int)
    def _on_progress(self, current: int, total: int):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.lbl_progress.setText(f"Progress: {current} / {total} emails")

    @Slot(object)
    def _on_done(self, report: dict):
        total = report.get("total", 0)
        exp = report.get("exported", 0)
        errs = report.get("errors", 0)
        
        fmt = self.combo_format.currentData()
        action_name = "migrated" if fmt == "IMAP_SERVER" else "exported"
        
        self.log_output.append(f"Process Completed: {exp} {action_name}. {errs} errors.")
        QMessageBox.information(
            self, "Operation Complete",
            f"Successfully processed {exp} emails out of {total}.\nErrors: {errs}"
        )
        self._reset_ui()

    @Slot(str)
    def _on_error(self, err_msg: str):
        self.log_output.append(f"Operation failed: {err_msg}")
        QMessageBox.critical(self, "Operation Failed", f"An error occurred:\n{err_msg}")
        self._reset_ui()

    def _reset_ui(self):
        self.btn_export.setEnabled(True)
        self.combo_account.setEnabled(True)
        self.combo_format.setEnabled(True)
        self.combo_profile.setEnabled(True)
        self.btn_save_profile.setEnabled(True)
        self.btn_delete_profile.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.chk_since.setEnabled(True)
        self.chk_before.setEnabled(True)
        self.folder_list.setEnabled(True)
        
        self.progress_bar.setVisible(False)
        self.lbl_progress.setVisible(False)
