"""
account_dialog.py — Add/Edit/Copy email account dialog with provider presets & Thunderbird autoconfig.
"""

import logging
import threading
from typing import Any, Dict, Optional
from pathlib import Path

from PySide6.QtCore import Qt, Slot, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLineEdit, QSpinBox, QCheckBox, QPushButton, QLabel,
    QMessageBox, QProgressBar, QDialogButtonBox, QFrame,
    QComboBox, QFileDialog, QInputDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox,
)

from core.mail_engine import MailEngine
from core.settings import AppSettings
from core.provider_presets import lookup_autoconfig, BUILTIN_PRESETS

logger = logging.getLogger(__name__)


class AutodiscoverWorker(QThread):
    """Background worker for looking up Thunderbird ISPDB / Autodiscover / Preset configuration."""
    finished = Signal(dict)

    def __init__(self, email_or_domain: str, custom_presets=None, parent=None):
        super().__init__(parent)
        self.email_or_domain = email_or_domain
        self.custom_presets = custom_presets or []

    def run(self):
        try:
            res = lookup_autoconfig(self.email_or_domain, self.custom_presets)
            self.finished.emit(res or {})
        except Exception as e:
            logger.debug("Autodiscover lookup exception: %s", e)
            self.finished.emit({})


class AccountDialog(QDialog):
    """Modal dialog for adding, editing, or duplicating an email account."""

    def __init__(self, engine: MailEngine, parent=None,
                 account: Optional[Dict[str, Any]] = None,
                 settings: AppSettings = None,
                 is_copy: bool = False):
        super().__init__(parent)
        self.engine = engine
        self.account = account  # None = add mode, dict = edit or copy mode
        self.settings = settings or AppSettings()
        self._is_copy = is_copy
        self._is_edit = (account is not None) and not is_copy
        self._is_loading = True
        self._autodiscover_worker = None

        # Debounce timer for auto-detect while typing
        self._autodiscover_timer = QTimer(self)
        self._autodiscover_timer.setSingleShot(True)
        self._autodiscover_timer.setInterval(600)
        self._autodiscover_timer.timeout.connect(self._trigger_autodiscover)

        self._setup_ui()
        self._load_data()
        self._is_loading = False

    def showEvent(self, event):
        super().showEvent(event)
        # Open dialog maximized as requested by user
        self.showMaximized()

    def _stop_autodiscover_worker(self):
        if self._autodiscover_worker is not None:
            try:
                try:
                    self._autodiscover_worker.finished.disconnect()
                except Exception:
                    pass
                if self._autodiscover_worker.isRunning():
                    self._autodiscover_worker.quit()
                    self._autodiscover_worker.wait(500)
            except Exception as e:
                logger.debug("Error stopping autodiscover worker: %s", e)
            finally:
                self._autodiscover_worker = None

    def closeEvent(self, event):
        self._stop_autodiscover_worker()
        super().closeEvent(event)

    def reject(self):
        self._stop_autodiscover_worker()
        super().reject()

    def _show_styled_msg(self, title: str, text: str, icon=QMessageBox.Information, buttons=QMessageBox.Ok):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setIcon(icon)
        msg_box.setText(text)
        msg_box.setStandardButtons(buttons)
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #ffffff;
            }
            QLabel {
                color: #0f172a !important;
                font-size: 13px !important;
                font-weight: 600 !important;
                background-color: transparent !important;
            }
            QPushButton {
                background-color: #2563eb !important;
                color: #ffffff !important;
                font-weight: 700 !important;
                font-size: 13px !important;
                border: none !important;
                border-radius: 6px !important;
                padding: 8px 24px !important;
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
        ok_btn = msg_box.button(QMessageBox.Ok)
        if ok_btn:
            ok_btn.setText("Tamam")
            ok_btn.setCursor(Qt.PointingHandCursor)
        return msg_box.exec()

    def _setup_ui(self):
        if self._is_copy:
            title = "Hesap Kopyala (Duplicate Account)"
        elif self._is_edit:
            title = "Edit Account"
        else:
            title = "Add New Account"

        self.setWindowTitle(title)
        self.resize(1100, 680)
        self.setMinimumWidth(900)
        self.setMinimumHeight(600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog {
                background: #f8fafc;
            }
            QLabel[heading="true"] {
                font-size: 20px;
                font-weight: 700;
                color: #0f172a;
                padding: 4px 0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Header
        header = QLabel("📧  " + title)
        header.setProperty("heading", True)
        layout.addWidget(header)

        sub = QLabel("IMAP e-posta hesabı yapılandırması. "
                     "Parolalar saklanmadan önce AES-256 ile şifrelenir. E-posta adresi yazıldığında sunucu ayarları otomatik algılanır.")
        sub.setStyleSheet("color: #64748b; font-size: 13px; margin-bottom: 8px;")
        layout.addWidget(sub)

        # Form
        form_frame = QFrame()
        form_frame.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        form = QGridLayout(form_frame)
        form.setSpacing(12)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(4, 1)
        form.setColumnMinimumWidth(2, 30)

        # Left Column: Basic Account Info
        self.input_label = QLineEdit()
        self.input_label.setPlaceholderText("e.g. Work Gmail, Personal Outlook")
        form.addWidget(QLabel("Label:"), 0, 0, Qt.AlignRight | Qt.AlignVCenter)
        form.addWidget(self.input_label, 0, 1)

        email_layout = QHBoxLayout()
        email_layout.setSpacing(6)

        self.input_email = QLineEdit()
        self.input_email.setPlaceholderText("user@example.com")
        self.input_email.editingFinished.connect(self._trigger_autodiscover)
        self.input_email.textChanged.connect(self._on_email_text_changed)

        self.btn_detect_email = QPushButton("🔍 Algıla")
        self.btn_detect_email.setToolTip("E-posta sunucusu IMAP, Port ve SSL ayarlarını otomatik ara ve doldur")
        self.btn_detect_email.setCursor(Qt.PointingHandCursor)
        self.btn_detect_email.setStyleSheet("""
            QPushButton {
                background-color: #2563eb !important;
                color: #ffffff !important;
                font-weight: bold;
                font-size: 11px;
                border-radius: 4px;
                padding: 6px 12px;
                min-height: 26px;
            }
            QPushButton:hover {
                background-color: #1d4ed8 !important;
            }
        """)
        self.btn_detect_email.clicked.connect(self._trigger_autodiscover)

        email_layout.addWidget(self.input_email, stretch=1)
        email_layout.addWidget(self.btn_detect_email)

        form.addWidget(QLabel("Email:"), 1, 0, Qt.AlignRight | Qt.AlignVCenter)
        form.addLayout(email_layout, 1, 1)

        # Autoconfig status label below email input
        self.lbl_autoconfig_status = QLabel("")
        self.lbl_autoconfig_status.setStyleSheet("color: #2563eb; font-size: 11px; font-weight: bold;")
        form.addWidget(self.lbl_autoconfig_status, 2, 1)

        self.input_username = QLineEdit()
        self.input_username.setPlaceholderText("Same as email, or app-specific password")
        form.addWidget(QLabel("Username:"), 3, 0, Qt.AlignRight | Qt.AlignVCenter)
        form.addWidget(self.input_username, 3, 1)

        self.input_password = QLineEdit()
        self.input_password.setPlaceholderText("App password or mailbox password")
        self.input_password.setEchoMode(QLineEdit.Password)
        form.addWidget(QLabel("Password:"), 4, 0, Qt.AlignRight | Qt.AlignVCenter)
        form.addWidget(self.input_password, 4, 1)

        # Right Column: Server & Storage Info
        # Provider Presets dropdown
        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(4)

        self.combo_preset = QComboBox()
        self.combo_preset.setToolTip("Yandex, Gmail, Outlook vb. hazır sunucu şablonu seçin")
        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)

        self.btn_save_preset = QPushButton("💾")
        self.btn_save_preset.setToolTip("Mevcut IMAP sunucu ayarlarını özel şablon olarak kaydet")
        self.btn_save_preset.setCursor(Qt.PointingHandCursor)
        self.btn_save_preset.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
                padding: 4px;
                min-width: 28px;
                max-width: 28px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #cbd5e1;
            }
        """)
        self.btn_save_preset.clicked.connect(self._on_save_custom_preset)

        preset_layout.addWidget(self.combo_preset, stretch=1)
        preset_layout.addWidget(self.btn_save_preset)

        form.addWidget(QLabel("Sunucu Şablonu:"), 0, 3, Qt.AlignRight | Qt.AlignVCenter)
        form.addLayout(preset_layout, 0, 4)

        self.input_host = QLineEdit()
        self.input_host.setPlaceholderText("imap.gmail.com")
        form.addWidget(QLabel("IMAP Host:"), 1, 3, Qt.AlignRight | Qt.AlignVCenter)
        form.addWidget(self.input_host, 1, 4)

        port_row = QHBoxLayout()
        self.input_port = QSpinBox()
        self.input_port.setRange(1, 65535)
        self.input_port.setValue(993)
        self.input_port.setFixedWidth(80)
        port_row.addWidget(self.input_port)
        self.input_ssl = QCheckBox("Use SSL/TLS")
        self.input_ssl.setChecked(True)
        port_row.addWidget(self.input_ssl)
        port_row.addStretch()
        form.addWidget(QLabel("Port:"), 2, 3, Qt.AlignRight | Qt.AlignVCenter)
        form.addLayout(port_row, 2, 4)

        storage_layout = QHBoxLayout()
        storage_layout.setSpacing(4)

        self.combo_storage = QComboBox()
        self.combo_storage.currentIndexChanged.connect(self._on_storage_changed)

        self.btn_edit_storage = QPushButton("⚙")
        self.btn_edit_storage.setToolTip("Depolama konumlarını tanımla ve yönet")
        self.btn_edit_storage.setCursor(Qt.PointingHandCursor)
        self.btn_edit_storage.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
                padding: 4px;
                min-width: 28px;
                max-width: 28px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #cbd5e1;
            }
        """)
        self.btn_edit_storage.clicked.connect(self._open_storage_settings_dialog)

        storage_layout.addWidget(self.combo_storage, stretch=1)
        storage_layout.addWidget(self.btn_edit_storage)

        self._refresh_storage_combo()

        subfolder_layout = QHBoxLayout()
        self.input_export_subfolder = QLineEdit()
        self.input_export_subfolder.setPlaceholderText("e.g. User1 (veya klasör seçin)")
        self.btn_browse_subfolder = QPushButton("📂 Klasör Seç/Oluştur")
        self.btn_browse_subfolder.setProperty("outline", True)
        self.btn_browse_subfolder.clicked.connect(self._on_browse_subfolder)
        subfolder_layout.addWidget(self.input_export_subfolder, stretch=1)
        subfolder_layout.addWidget(self.btn_browse_subfolder)
        form.addWidget(QLabel("Alt Klasör (Subfolder):"), 3, 3, Qt.AlignRight | Qt.AlignVCenter)
        form.addLayout(subfolder_layout, 3, 4)

        group_layout = QHBoxLayout()
        group_layout.setSpacing(4)

        self.input_group = QComboBox()
        self.input_group.setEditable(True)
        self.input_group.setInsertPolicy(QComboBox.NoInsert)
        self.input_group.lineEdit().setPlaceholderText("e.g. seges.com.tr or Baynet (Boş bırakılırsa domain alınır)")

        self.btn_edit_group = QPushButton("⚙")
        self.btn_edit_group.setToolTip("Grup / Domain tanımla ve yönet")
        self.btn_edit_group.setCursor(Qt.PointingHandCursor)
        self.btn_edit_group.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
                padding: 4px;
                min-width: 28px;
                max-width: 28px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #cbd5e1;
            }
        """)
        self.btn_edit_group.clicked.connect(self._open_group_dialog)

        group_layout.addWidget(self.input_group, stretch=1)
        group_layout.addWidget(self.btn_edit_group)

        self._refresh_group_combo()

        form.addWidget(QLabel("Grup / Domain:"), 4, 3, Qt.AlignRight | Qt.AlignVCenter)
        form.addLayout(group_layout, 4, 4)

        layout.addWidget(form_frame)

        # Multi-Server Endpoints Group Box (Visible in Edit mode or if profiles exist)
        if self._is_edit and self.account:
            profiles_group = QGroupBox("Çoklu Sunucu Profilleri (Multi-Server Endpoints)")
            profiles_group.setStyleSheet("""
                QGroupBox {
                    font-weight: bold;
                    color: #1e293b;
                    border: 1px solid #cbd5e1;
                    border-radius: 8px;
                    margin-top: 6px;
                    padding-top: 14px;
                    background: #ffffff;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 4px;
                    color: #2563eb;
                }
            """)
            p_layout = QVBoxLayout(profiles_group)
            p_layout.setContentsMargins(10, 10, 10, 10)

            self.table_profiles = QTableWidget()
            self.table_profiles.setColumnCount(5)
            self.table_profiles.setHorizontalHeaderLabels(["Aktif", "Profil Adı", "IMAP Host", "Port/SSL", "Kullanıcı Adı"])
            self.table_profiles.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.table_profiles.setSelectionBehavior(QTableWidget.SelectRows)
            self.table_profiles.setSelectionMode(QTableWidget.SingleSelection)
            self.table_profiles.setMinimumHeight(120)
            self.table_profiles.setMaximumHeight(160)
            self.table_profiles.setStyleSheet("QTableWidget { background: #ffffff; font-size: 11px; border: 1px solid #e2e8f0; }")
            p_layout.addWidget(self.table_profiles)

            p_btns = QHBoxLayout()
            self.btn_add_profile = QPushButton("➕ Yeni Sunucu Profili Ekle (Örn: Yandex / Eski Sunucu)")
            self.btn_add_profile.setStyleSheet("background-color: #10b981 !important; color: white !important; font-weight: bold; padding: 5px 10px;")
            self.btn_add_profile.clicked.connect(self._add_new_server_profile)

            self.btn_set_default_profile = QPushButton("⭐ Varsayılan (Aktif) Yap")
            self.btn_set_default_profile.setStyleSheet("background-color: #2563eb !important; color: white !important; font-weight: bold; padding: 5px 10px;")
            self.btn_set_default_profile.clicked.connect(self._set_selected_profile_as_default)

            self.btn_del_profile = QPushButton("🗑️ Profili Sil")
            self.btn_del_profile.setStyleSheet("background-color: #ef4444 !important; color: white !important; font-weight: bold; padding: 5px 10px;")
            self.btn_del_profile.clicked.connect(self._delete_selected_server_profile)

            p_btns.addWidget(self.btn_add_profile)
            p_btns.addWidget(self.btn_set_default_profile)
            p_btns.addWidget(self.btn_del_profile)
            p_btns.addStretch()
            p_layout.addLayout(p_btns)

            layout.addWidget(profiles_group)

        # Fill provider presets combo box
        self._refresh_preset_combo()

        # Connection test button + progress
        test_row = QHBoxLayout()
        self.btn_test = QPushButton("🔌  Test Connection")
        self.btn_test.setProperty("outline", True)
        self.btn_test.setCursor(Qt.PointingHandCursor)
        self.btn_test.setMinimumHeight(36)
        test_row.addWidget(self.btn_test)

        self.test_status = QLabel("")
        self.test_status.setStyleSheet("font-size: 12px; padding-left: 8px;")
        test_row.addWidget(self.test_status)
        test_row.addStretch()
        layout.addLayout(test_row)

        self.test_progress = QProgressBar()
        self.test_progress.setVisible(False)
        self.test_progress.setMaximumHeight(4)
        self.test_progress.setTextVisible(False)
        layout.addWidget(self.test_progress)

        # Buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setMinimumWidth(120)
        self.btn_cancel.setMinimumHeight(42)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #64748b !important;
                color: #ffffff !important;
                font-size: 13px;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
            }
            QPushButton:hover {
                background-color: #475569 !important;
            }
        """)
        btn_box.addWidget(self.btn_cancel)

        save_btn_text = "💾 Save Account"
        if self._is_copy:
            save_btn_text = "📋 Kopyala ve Kaydet"
        elif self._is_edit:
            save_btn_text = "💾 Update Account"

        self.btn_save = QPushButton(save_btn_text)
        self.btn_save.setMinimumWidth(180)
        self.btn_save.setMinimumHeight(42)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #2563eb !important;
                color: #ffffff !important;
                font-size: 13px;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
            }
            QPushButton:hover {
                background-color: #1d4ed8 !important;
            }
            QPushButton:pressed {
                background-color: #1e40af !important;
            }
        """)
        btn_box.addWidget(self.btn_save)

        layout.addLayout(btn_box)

        # Connections
        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_test.clicked.connect(self._test_connection)

        if self._is_edit:
            self.combo_storage.setEnabled(False)
            self.btn_edit_storage.setEnabled(False)

    # ------------------------------------------------------------------
    # Presets & Autodiscover Slots
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_email_text_changed(self, text: str):
        if "@" in text and "." in text.split("@")[-1]:
            self._autodiscover_timer.start()

    def _refresh_preset_combo(self):
        """Populate preset dropdown with built-in presets and user custom presets."""
        self.combo_preset.blockSignals(True)
        self.combo_preset.clear()

        self.combo_preset.addItem("🔍 Otomatik Algıla / Elle Gir", None)

        # Built-in presets
        for p in BUILTIN_PRESETS:
            self.combo_preset.addItem(f"⭐ {p['name']} ({p['host']})", p)

        # Custom presets from settings
        customs = self.settings.custom_presets()
        if customs:
            for cp in customs:
                self.combo_preset.addItem(f"👤 {cp['name']} ({cp['host']})", cp)

        self.combo_preset.blockSignals(False)

    @Slot(int)
    def _on_preset_changed(self, index: int):
        if self._is_loading or index < 0:
            return

        preset = self.combo_preset.itemData(index)
        if isinstance(preset, dict):
            self.input_host.setText(preset.get("host", ""))
            self.input_port.setValue(preset.get("port", 993))
            self.input_ssl.setChecked(bool(preset.get("use_ssl", True)))
            self.lbl_autoconfig_status.setText(f"📋 Şablon uygulandı: {preset.get('name')}")
            self.lbl_autoconfig_status.setStyleSheet("color: #10b981; font-size: 11px; font-weight: bold;")

    @Slot()
    def _on_save_custom_preset(self):
        host = self.input_host.text().strip()
        port = self.input_port.value()
        use_ssl = self.input_ssl.isChecked()

        if not host:
            QMessageBox.warning(self, "Uyarı", "Lütfen önce geçerli bir IMAP Host adresi girin.")
            return

        name, ok = QInputDialog.getText(
            self, "Şablon Olarak Kaydet",
            f"Bu IMAP yapılandırması ({host}:{port}) için bir şablon ismi girin:"
        )
        if ok and name.strip():
            name = name.strip()
            # Extract domain if email present
            email = self.input_email.text().strip()
            domains = [email.split("@")[-1]] if "@" in email else []
            self.settings.add_custom_preset(name, host, port, use_ssl, domains)
            self._refresh_preset_combo()

            # Select newly added custom preset
            idx = self.combo_preset.findText(f"👤 {name} ({host})")
            if idx >= 0:
                self.combo_preset.setCurrentIndex(idx)

            QMessageBox.information(self, "Başarılı", f"'{name}' şablonu başarıyla kaydedildi.")

    @Slot()
    def _trigger_autodiscover(self):
        """Automatically lookup IMAP configuration when user finishes typing email address."""
        if self._is_loading or self._is_edit:
            return

        email = self.input_email.text().strip()
        if not email or "@" not in email:
            return

        domain = email.split("@")[-1].strip()
        if not domain or "." not in domain:
            return

        # If username is empty, set username to email address by default
        if not self.input_username.text().strip():
            self.input_username.setText(email)

        # If group is empty, set default group to domain
        if not self.input_group.currentText().strip():
            self.input_group.setCurrentText(domain)

        self.lbl_autoconfig_status.setText("⏳ Otomatik sunucu yapılandırması aranıyor...")
        self.lbl_autoconfig_status.setStyleSheet("color: #6366f1; font-size: 11px; font-weight: bold;")

        self._stop_autodiscover_worker()

        customs = self.settings.custom_presets()
        worker = AutodiscoverWorker(email, customs, parent=self)
        worker.finished.connect(self._on_autodiscover_finished)
        worker.finished.connect(worker.deleteLater)
        self._autodiscover_worker = worker
        worker.start()

    @Slot(dict)
    def _on_autodiscover_finished(self, result: dict):
        if not result or not result.get("host"):
            self.lbl_autoconfig_status.setText("")
            return

        host = result["host"]
        port = result.get("port", 993)
        use_ssl = result.get("use_ssl", True)
        name = result.get("name", host)
        source = result.get("source", "autoconfig")

        # Fill form fields
        self.input_host.setText(host)
        self.input_port.setValue(port)
        self.input_ssl.setChecked(use_ssl)

        # Set default label if empty
        if not self.input_label.text().strip():
            self.input_label.setText(f"{name} ({self.input_email.text().strip()})")

        # Highlight matching preset in combo box if exists
        idx = -1
        for i in range(self.combo_preset.count()):
            p_data = self.combo_preset.itemData(i)
            if isinstance(p_data, dict) and p_data.get("host") == host:
                idx = i
                break
        if idx >= 0:
            self.combo_preset.blockSignals(True)
            self.combo_preset.setCurrentIndex(idx)
            self.combo_preset.blockSignals(False)

        source_tr = {
            "preset": "Hazır Şablon",
            "autoconfig_xml": "Thunderbird / Autodiscover",
            "socket_probe": "Otomatik Sunucu Bağlantısı Tespiti"
        }.get(source, "Otomatik Bulundu")

        self.lbl_autoconfig_status.setText(f"⚡ {source_tr}: {host}:{port} ({'SSL' if use_ssl else 'Non-SSL'})")
        self.lbl_autoconfig_status.setStyleSheet("color: #10b981; font-size: 11px; font-weight: bold;")

    # ------------------------------------------------------------------
    # Storage / Group helpers
    # ------------------------------------------------------------------

    def _is_path_outside_default(self, folder_path: str) -> bool:
        try:
            data_path = self.settings.data_path().resolve()
            target_path = Path(folder_path).resolve()
            return not str(target_path).startswith(str(data_path))
        except Exception:
            return False

    def _on_storage_changed(self, idx: int):
        if hasattr(self, '_is_loading') and self._is_loading:
            return

        selected_loc_name = self.combo_storage.itemData(idx)

        if selected_loc_name == "__BROWSE__":
            folder = QFileDialog.getExistingDirectory(
                self, "Select Storage Folder", str(Path.cwd()),
                QFileDialog.ShowDirsOnly
            )
            if folder:
                if self._is_path_outside_default(folder):
                    QMessageBox.warning(
                        self, "Uyarı: Harici Dizin",
                        f"Uyarı: Seçilen yedekleme/depolama klasörü varsayılan veri dizininin dışındadır.\n\n"
                        f"Senkronizasyon (aktif veritabanı ve önbellek) yalnızca varsayılan veri dizini ({self.settings.data_path()}) içinde çalışacaktır. "
                        f"Bu konum sadece harici yedeklemeler/aktarımlar için kullanılacaktır."
                    )
                name, ok = QInputDialog.getText(
                    self, "Storage Name",
                    "Give this storage location a name:"
                )
                if ok and name.strip():
                    name = name.strip()
                    self.settings.add_storage_location(name, folder)
                    self.combo_storage.insertItem(
                        self.combo_storage.count() - 1, name, name
                    )
                    self.combo_storage.setCurrentIndex(
                        self.combo_storage.findText(name)
                    )
                    return
            # User cancelled → revert to Default
            self.combo_storage.setCurrentIndex(0)
        elif selected_loc_name:
            path_found = None
            for loc in self.settings.storage_locations():
                if loc.name == selected_loc_name:
                    path_found = loc.path
                    break
            if path_found and self._is_path_outside_default(path_found):
                QMessageBox.warning(
                    self, "Uyarı: Harici Dizin",
                    f"Uyarı: Seçilen yedekleme/depolama klasörü varsayılan veri dizininin dışındadır.\n\n"
                    f"Senkronizasyon (aktif veritabanı ve önbellek) yalnızca varsayılan veri dizini ({self.settings.data_path()}) içinde çalışacaktır. "
                    f"Bu konum sadece harici yedeklemeler/aktarımlar için kullanılacaktır."
                )

    @Slot()
    def _on_browse_subfolder(self):
        idx = self.combo_storage.currentIndex()
        storage_name = self.combo_storage.itemData(idx)

        if storage_name == "__BROWSE__":
            QMessageBox.warning(self, "Uyarı", "Lütfen önce geçerli bir ana depolama alanı seçin.")
            return

        if storage_name is None:
            base_path = self.settings.data_path().resolve()
        else:
            locs = self.settings.storage_locations()
            matched = next((l for l in locs if l.name == storage_name), None)
            if matched:
                base_path = Path(matched.path).resolve()
            else:
                base_path = self.settings.data_path().resolve()

        base_path.mkdir(parents=True, exist_ok=True)

        selected_dir = QFileDialog.getExistingDirectory(
            self, "Alt Klasör Seçin veya Yeni Klasör Oluşturun", str(base_path)
        )
        if not selected_dir:
            return

        selected_path = Path(selected_dir).resolve()

        relative_path = None
        try:
            relative_path = selected_path.relative_to(base_path)
        except ValueError:
            if base_path.parent and base_path.parent != base_path.root:
                try:
                    relative_path = selected_path.relative_to(base_path.parent)
                except ValueError:
                    pass

        if relative_path is not None:
            self.input_export_subfolder.setText(str(relative_path).replace("\\", "/"))
        else:
            QMessageBox.warning(
                self, "Geçersiz Konum",
                f"Seçtiğiniz klasör ana depolama alanı altında değil!\n\n"
                f"Ana depolama alanı: {base_path}\n"
                f"Seçilen konum: {selected_path}\n\n"
                f"Lütfen ana depolama alanı içinde bir klasör seçin veya oluşturun."
            )

    def _load_data(self):
        if self.account:
            if self._is_copy:
                self.input_label.setText(f"{self.account.get('label', '')} (Kopya)")
                self.input_email.setText("")
            else:
                self.input_label.setText(self.account.get("label", ""))
                self.input_email.setText(self.account.get("email", ""))

            self.input_host.setText(self.account.get("imap_host", ""))
            self.input_port.setValue(self.account.get("imap_port", 993))
            self.input_ssl.setChecked(bool(self.account.get("use_ssl", True)))

            # Username & Password decryption
            try:
                username_enc = self.account.get("username_enc", "")
                if username_enc:
                    username = self.engine.crypto.decrypt(username_enc)
                    self.input_username.setText(username)
                else:
                    self.input_username.setText(self.account.get("email", ""))
            except Exception:
                self.input_username.setText(self.account.get("email", ""))

            try:
                password_enc = self.account.get("password_enc", "")
                if password_enc:
                    password = self.engine.crypto.decrypt(password_enc)
                    self.input_password.setText(password)
            except Exception:
                if self._is_edit:
                    self.input_password.setPlaceholderText("(unchanged — leave blank to keep)")

            # Select matching preset if available
            host = self.account.get("imap_host", "")
            if host:
                for i in range(self.combo_preset.count()):
                    p_data = self.combo_preset.itemData(i)
                    if isinstance(p_data, dict) and p_data.get("host") == host:
                        self.combo_preset.setCurrentIndex(i)
                        break

            # Restore storage location
            stor_name = self.settings.account_storage(self.account["id"])
            if stor_name:
                idx = self.combo_storage.findText(stor_name)
                if idx >= 0:
                    self.combo_storage.setCurrentIndex(idx)

            # Restore export subfolder
            self.input_export_subfolder.setText(self.account.get("export_subfolder", ""))

            # Restore account group
            grp = self.account.get("account_group", "")
            if grp:
                idx = -1
                for i in range(self.input_group.count()):
                    if self.input_group.itemData(i) == grp:
                        idx = i
                        break
                if idx >= 0:
                    self.input_group.setCurrentIndex(idx)
                else:
                    self.input_group.setCurrentText(grp)

            self._refresh_server_profiles_table()

    def _refresh_server_profiles_table(self):
        if not hasattr(self, "table_profiles") or not self.account:
            return
        self.table_profiles.setRowCount(0)
        profiles = self.engine.list_server_profiles(self.account["id"])
        self.table_profiles.setRowCount(len(profiles))

        for row, prof in enumerate(profiles):
            is_def = bool(prof.get("is_default"))
            item_active = QTableWidgetItem("★ Aktif" if is_def else "")
            if is_def:
                item_active.setForeground(QColor("#10b981"))
                f = item_active.font()
                f.setBold(True)
                item_active.setFont(f)

            item_name = QTableWidgetItem(prof.get("profile_name", ""))
            item_name.setData(Qt.UserRole, prof["id"])
            item_host = QTableWidgetItem(prof.get("imap_host", ""))
            ssl_str = "SSL" if prof.get("use_ssl") else "Plain"
            item_port = QTableWidgetItem(f"{prof.get('imap_port')}/{ssl_str}")
            item_user = QTableWidgetItem(prof.get("username", ""))

            self.table_profiles.setItem(row, 0, item_active)
            self.table_profiles.setItem(row, 1, item_name)
            self.table_profiles.setItem(row, 2, item_host)
            self.table_profiles.setItem(row, 3, item_port)
            self.table_profiles.setItem(row, 4, item_user)

    @Slot()
    def _add_new_server_profile(self):
        if not self.account:
            return

        name, ok = QInputDialog.getText(self, "Yeni Sunucu Profili", "Profil Adı (Örn: Yandex Mail, Eski cPanel):")
        if not ok or not name.strip():
            return
        name = name.strip()

        host, ok2 = QInputDialog.getText(self, "IMAP Sunucu Adresi", "IMAP Host Adresi (Örn: imap.yandex.com):")
        if not ok2 or not host.strip():
            return
        host = host.strip()

        pwd, ok3 = QInputDialog.getText(self, "Şifre", "Posta Kutusu Şifresi:", QLineEdit.Password)
        if not ok3:
            pwd = ""

        try:
            prof_id = self.engine.add_server_profile(
                account_id=self.account["id"],
                profile_name=name,
                imap_host=host,
                imap_port=993,
                use_ssl=True,
                username=self.account.get("email", ""),
                password=pwd,
                make_default=False,
            )
            self._show_styled_msg("Başarılı", f"'{name}' sunucu profili başarıyla eklendi.", icon=QMessageBox.Information)
            self._refresh_server_profiles_table()
        except Exception as e:
            self._show_styled_msg("Hata", f"Profil eklenirken hata oluştu: {e}", icon=QMessageBox.Critical)

    @Slot()
    def _set_selected_profile_as_default(self):
        if not hasattr(self, "table_profiles") or not self.account:
            return
        curr_row = self.table_profiles.currentRow()
        if curr_row < 0:
            self._show_styled_msg("Seçim Yapılmadı", "Lütfen aktif yapmak istediğiniz sunucu profilini seçin.", icon=QMessageBox.Warning)
            return

        item = self.table_profiles.item(curr_row, 1)
        prof_id = item.data(Qt.UserRole) if item else None
        if prof_id is None:
            return

        try:
            self.engine.set_default_server_profile(self.account["id"], prof_id)
            self._show_styled_msg("Varsayılan Sunucu Değişti", "Seçilen sunucu profili varsayılan (aktif) yapıldı.", icon=QMessageBox.Information)
            self._refresh_server_profiles_table()
            # Update Host UI input
            profs = self.engine.list_server_profiles(self.account["id"])
            active = next((p for p in profs if p["id"] == prof_id), None)
            if active:
                self.input_host.setText(active.get("imap_host", ""))
                self.input_port.setValue(active.get("imap_port", 993))
                self.input_ssl.setChecked(bool(active.get("use_ssl", True)))
        except Exception as e:
            self._show_styled_msg("Hata", f"Aktif profil değiştirilemedi: {e}", icon=QMessageBox.Critical)

    @Slot()
    def _delete_selected_server_profile(self):
        if not hasattr(self, "table_profiles") or not self.account:
            return
        curr_row = self.table_profiles.currentRow()
        if curr_row < 0:
            self._show_styled_msg("Seçim Yapılmadı", "Lütfen silmek istediğiniz sunucu profilini seçin.", icon=QMessageBox.Warning)
            return

        item = self.table_profiles.item(curr_row, 1)
        prof_id = item.data(Qt.UserRole) if item else None
        if prof_id is None:
            return

        reply = QMessageBox.question(self, "Profili Sil", "Seçilen sunucu profilini silmek istediğinizden emin misiniz?")
        if reply == QMessageBox.Yes:
            try:
                self.engine.delete_server_profile(self.account["id"], prof_id)
                self._refresh_server_profiles_table()
            except Exception as e:
                self._show_styled_msg("Hata", f"Profil silinemedi: {e}", icon=QMessageBox.Critical)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save(self):
        label = self.input_label.text().strip()
        email_addr = self.input_email.text().strip()
        host = self.input_host.text().strip()
        port = self.input_port.value()
        use_ssl = self.input_ssl.isChecked()
        username = self.input_username.text().strip() or email_addr
        password = self.input_password.text()
        export_subfolder = self.input_export_subfolder.text().strip()
        idx = self.input_group.currentIndex()
        if idx >= 0 and self.input_group.itemText(idx) == self.input_group.currentText():
            account_group = self.input_group.itemData(idx) or self.input_group.currentText().strip()
        else:
            account_group = self.input_group.currentText().strip()
        if account_group.endswith(" (Pasif)"):
            account_group = account_group[:-8].strip()

        if not account_group and "@" in email_addr:
            account_group = email_addr.split("@")[-1]

        # Validation
        errors = []
        if not label:
            errors.append("Label is required")
        if not email_addr or "@" not in email_addr:
            errors.append("Valid email address is required")
        if not host:
            errors.append("IMAP host is required")
        if not self._is_edit and not password:
            errors.append("Password is required")

        if export_subfolder:
            if ".." in export_subfolder or export_subfolder.startswith("/") or export_subfolder.startswith("\\") or ":" in export_subfolder:
                errors.append("Alt klasör ismi geçersiz karakter veya üst dizin referansı (..) içeremez!")

        if errors:
            self._show_styled_msg("Validation Error",
                                  "Please fix the following:\n• " + "\n• ".join(errors),
                                  icon=QMessageBox.Warning)
            return

        try:
            if self._is_edit:
                # Update existing
                acc_id = self.account["id"]
                old_host = self.account.get("imap_host", "")
                host_changed = host and old_host and host != old_host

                if host_changed:
                    reply = QMessageBox.question(
                        self,
                        "Sunucu Değişikliği Tespit Edildi (Server Migration)",
                        f"Hesabın IMAP sunucu adresi '{old_host}' -> '{host}' olarak değiştiriliyor.\n\n"
                        "• Arşivdeki eski e-postalarınız korunacaktır.\n"
                        "• Yeni sunucudaki e-postalar indirilerek var olan maillere eklenecektir (Append/Merge).\n"
                        "• Çakışan aynı e-postalar otomatik elenecektir (Deduplikasyon).\n"
                        "• İşlem Denetim İzi (Audit Log) kaydına işlenecektir.\n\n"
                        "Devam etmek istiyor musunuz?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes
                    )
                    if reply != QMessageBox.Yes:
                        return

                update_data = {
                    "label": label,
                    "email": email_addr,
                    "imap_host": host,
                    "imap_port": port,
                    "use_ssl": int(use_ssl),
                    "export_subfolder": export_subfolder,
                    "account_group": account_group,
                }
                if username:
                    update_data["username"] = username
                if password:
                    update_data["password"] = password

                self.engine.update_account(acc_id, **update_data)
                self._show_styled_msg("Başarılı", "Hesap bilgileri ve sunucu yapılandırması güncellendi.", icon=QMessageBox.Information)
            else:
                # Add new (or save copied account as new)
                acc_id = self.engine.add_account(
                    label=label, email=email_addr,
                    imap_host=host, imap_port=port,
                    use_ssl=use_ssl, username=username, password=password,
                    export_subfolder=export_subfolder,
                    account_group=account_group,
                )
                msg = f"Account added with ID: {acc_id}" if not self._is_copy else f"Account duplicated successfully with ID: {acc_id}"
                self._show_styled_msg("Success", msg, icon=QMessageBox.Information)

            # Save storage location assignment
            stor_name = self.combo_storage.currentData()
            if stor_name:
                self.settings.set_account_storage(acc_id, stor_name)
            else:
                self.settings.set_account_storage(acc_id, None)

            # Create subfolder directory immediately
            if export_subfolder:
                base = self.settings.data_path()
                if stor_name:
                    for loc in self.settings.storage_locations():
                        if loc.name == stor_name:
                            base = Path(loc.path)
                            break
                sub_clean = export_subfolder.replace("\\", "/").strip("/")
                email_clean = email_addr.replace("@", "_")
                target = base / sub_clean / email_clean
                target.mkdir(parents=True, exist_ok=True)

            self.accept()

        except Exception as exc:
            self._show_styled_msg("Error", f"Failed to save account:\n{exc}", icon=QMessageBox.Critical)

    # ------------------------------------------------------------------
    # Connection Test
    # ------------------------------------------------------------------

    @Slot()
    def _test_connection(self):
        host = self.input_host.text().strip()
        port = self.input_port.value()
        use_ssl = self.input_ssl.isChecked()
        username = self.input_username.text().strip() or self.input_email.text().strip()
        password = self.input_password.text()

        if not host:
            self.test_status.setText("⚠️ Enter host first")
            self.test_status.setStyleSheet("color: #e67e22; font-size: 12px;")
            return
        if not password and not self._is_edit:
            self.test_status.setText("⚠️ Enter password first")
            self.test_status.setStyleSheet("color: #e67e22; font-size: 12px;")
            return

        # For edit mode with no password change, decrypt existing
        if not password and self._is_edit:
            try:
                password = self.engine.crypto.decrypt(self.account.get("password_enc", ""))
            except Exception:
                self.test_status.setText("⚠️ Enter password to test")
                self.test_status.setStyleSheet("color: #e67e22; font-size: 12px;")
                return

        self.btn_test.setEnabled(False)
        self.test_progress.setVisible(True)
        self.test_progress.setRange(0, 0)
        self.test_status.setText("⏳ Testing connection...")
        self.test_status.setStyleSheet("color: #4361ee; font-size: 12px;")

        def test():
            from infrastructure.imap_client import ImapClient
            client = ImapClient()
            ok = client.connect(host, port, use_ssl, username, password)
            if ok:
                client.disconnect()
            self.btn_test.setEnabled(True)
            self.test_progress.setVisible(False)
            if ok:
                self.test_status.setText("✅ Connection successful")
                self.test_status.setStyleSheet("color: #2d6a4f; font-size: 12px; font-weight: 600;")
            else:
                self.test_status.setText("❌ Connection failed — check settings")
                self.test_status.setStyleSheet("color: #e63946; font-size: 12px; font-weight: 600;")

        threading.Thread(target=test, daemon=True).start()

    # ------------------------------------------------------------------
    # Group / Domain Management slots
    # ------------------------------------------------------------------

    def _refresh_group_combo(self):
        current_text = self.input_group.currentText()
        if current_text.endswith(" (Pasif)"):
            current_text = current_text[:-8].strip()

        self.input_group.clear()
        groups_dict = {}

        # 1. From settings
        raw_settings_groups = self.settings.get("group_domains", [])
        for g in raw_settings_groups:
            if isinstance(g, str):
                groups_dict[g.strip()] = True
            elif isinstance(g, dict):
                name = g.get("name", "").strip()
                if name:
                    groups_dict[name] = g.get("is_active", True)

        # 2. From database
        try:
            with self.engine.db.get_conn() as conn:
                rows = conn.execute("SELECT DISTINCT account_group FROM accounts WHERE account_group IS NOT NULL AND account_group != ''").fetchall()
                for r in rows:
                    name = r["account_group"].strip()
                    if name not in groups_dict:
                        groups_dict[name] = True
        except Exception as e:
            logger.error("Failed to query database for groups: %s", e)

        for name in sorted(groups_dict.keys()):
            is_active = groups_dict[name]
            label = name if is_active else f"{name} (Pasif)"
            self.input_group.addItem(label, name)

        if current_text:
            idx = -1
            for i in range(self.input_group.count()):
                if self.input_group.itemData(i) == current_text:
                    idx = i
                    break
            if idx >= 0:
                self.input_group.setCurrentIndex(idx)
            else:
                self.input_group.setCurrentText(current_text)

    # ------------------------------------------------------------------
    # Storage Location slots
    # ------------------------------------------------------------------

    def _refresh_storage_combo(self):
        current_data = self.combo_storage.currentData()
        self.combo_storage.clear()
        self.combo_storage.addItem("Default (data/ directory)", None)
        for loc in self.settings.storage_locations():
            self.combo_storage.addItem(loc.name, loc.name)
        self.combo_storage.addItem("📂  Browse for folder...", "__BROWSE__")

        if current_data:
            idx = self.combo_storage.findData(current_data)
            if idx >= 0:
                self.combo_storage.setCurrentIndex(idx)

    @Slot()
    def _open_storage_settings_dialog(self):
        from gui.main_window import StorageSettingsDialog
        dialog = StorageSettingsDialog(self.settings, self)
        dialog.exec()
        self._refresh_storage_combo()

    @Slot()
    def _open_group_dialog(self):
        from gui.dialogs.group_domain_dialog import GroupDomainDialog
        dialog = GroupDomainDialog(self.engine, self.settings, self)

        curr = self.input_group.currentText().strip()
        if curr:
            if curr.endswith(" (Pasif)"):
                curr = curr[:-8].strip()
            for row in range(dialog.tbl_groups.rowCount()):
                item = dialog.tbl_groups.item(row, 0)
                if item and item.data(Qt.UserRole) == curr:
                    dialog.tbl_groups.setCurrentCell(row, 0)
                    break

        if dialog.exec() == QDialog.Accepted:
            self._refresh_group_combo()
            if dialog.selected_group:
                idx = -1
                for i in range(self.input_group.count()):
                    if self.input_group.itemData(i) == dialog.selected_group:
                        idx = i
                        break
                if idx >= 0:
                    self.input_group.setCurrentIndex(idx)
                else:
                    self.input_group.setCurrentText(dialog.selected_group)
