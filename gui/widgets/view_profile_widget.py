"""
view_profile_widget.py — TOYA ERP Standartlarında Görünüm Profilleri & Grid Ayar Widget'ı.

Özellikler:
- Grid görünüm profillerini (Varsayılan, Kompakt, Geniş, Özel) yönetir.
- Sütun genişlikleri, sütun sıraları, gizli sütunlar ve satır yüksekliklerini saklar.
- Yeni profil kaydetme, profili güncelleme (üzerine yazma uyarısı ile), profil silme ve varsayılana sıfırlama.
- Yüksek kontrastlı, net ve şık SaveLayoutProfileDialog penceresi.
- Her ekranda (Sync, Account, Backup, Export) yeniden kullanılabilir (DRY).
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from PySide6.QtCore import Qt, Signal, QObject, QSize
from PySide6.QtGui import QFont, QAction, QCursor, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QMessageBox, QLineEdit,
    QDialog, QTableWidget, QHeaderView, QFrame,
    QListWidget, QListWidgetItem
)
from gui.dialogs.delete_confirm_dialog import DeleteConfirmDialog

logger = logging.getLogger(__name__)


class SaveLayoutProfileDialog(QDialog):
    """
    TOYA ERP Standartlarında Görünüm Düzenini Kaydetme / Güncelleme Penceresi.
    - Açık / net beyaz tema (siyah zemin sorunu yok).
    - Mevcut profiller listesi (QListWidget) üzerinden tek tıklamayla seçim yapabilme.
    - Yeni profil adı yazabilme (QLineEdit).
    - Var olan bir profil seçildiğinde '⚠️ Var olan profil güncellenecektir / değiştirilecektir!' uyarısı ve onayı.
    """
    def __init__(self, existing_profiles: List[str], current_profile: str = "Varsayılan", parent=None):
        super().__init__(parent)
        self.existing_profiles = existing_profiles
        self.selected_profile_name = ""
        self.setWindowTitle("💾 Görünüm Düzenini Kaydet / Güncelle")
        self.setFixedWidth(460)
        self.setStyleSheet("""
            QDialog {
                background-color: #ffffff;
                color: #0f172a;
            }
            QLabel {
                color: #1e293b;
                font-size: 12px;
            }
            QLineEdit, QComboBox {
                background-color: #ffffff;
                color: #0f172a;
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 7px 10px;
                font-size: 12px;
                font-weight: 600;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #2563eb;
            }
        """)
        self._init_ui(current_profile)

    def _init_ui(self, current_profile: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        # Header Title
        title = QLabel("💾 Tablo Görünüm Düzenini Kaydet")
        title.setStyleSheet("font-size: 14.5px; font-weight: bold; color: #1e3a8a;")
        layout.addWidget(title)

        desc = QLabel("Mevcut sütun genişliklerini, satır yüksekliğini ve gizli/açık sütun düzenini kaydetmek için bir profil seçin veya yeni bir isim girin:")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #475569; font-size: 11.5px; line-height: 1.4;")
        layout.addWidget(desc)

        # Profile Name Input
        lbl_input = QLabel("✏️ Profil Adı:")
        lbl_input.setStyleSheet("font-weight: bold; font-size: 12px; color: #1e3a8a; margin-top: 4px;")
        layout.addWidget(lbl_input)

        self.txt_profile_name = QLineEdit(self)
        self.txt_profile_name.setPlaceholderText("Profil adı girin veya aşağıdaki listeden seçin...")
        self.txt_profile_name.setClearButtonEnabled(True)
        self.txt_profile_name.setText(current_profile)
        self.txt_profile_name.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.txt_profile_name)

        # Hidden or synced combo for full backward compatibility
        self.combo_profile = QComboBox(self)
        self.combo_profile.setEditable(True)
        self.combo_profile.addItems(self.existing_profiles)
        self.combo_profile.setEditText(current_profile)
        self.combo_profile.setVisible(False)
        layout.addWidget(self.combo_profile)

        # Existing Profiles List Section
        lbl_list = QLabel("📋 Kayıtlı Görünüm Düzenleri (Seçmek için tıklayın):")
        lbl_list.setStyleSheet("font-weight: bold; font-size: 12px; color: #1e3a8a; margin-top: 6px;")
        layout.addWidget(lbl_list)

        self.list_profiles = QListWidget(self)
        self.list_profiles.setFixedHeight(130)
        self.list_profiles.setStyleSheet("""
            QListWidget {
                background-color: #f8fafc;
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px;
                font-size: 12px;
                color: #0f172a;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-radius: 4px;
                margin-bottom: 2px;
                font-weight: 500;
            }
            QListWidget::item:hover {
                background-color: #e0e7ff;
                color: #1e3a8a;
            }
            QListWidget::item:selected {
                background-color: #2563eb;
                color: #ffffff !important;
                font-weight: bold;
            }
        """)

        for p_name in self.existing_profiles:
            item = QListWidgetItem(f"📂  {p_name}")
            item.setData(Qt.UserRole, p_name)
            self.list_profiles.addItem(item)
            if p_name == current_profile:
                item.setSelected(True)

        self.list_profiles.itemClicked.connect(self._on_list_item_clicked)
        self.list_profiles.itemDoubleClicked.connect(self._on_list_item_double_clicked)
        layout.addWidget(self.list_profiles)

        # Warning / Info banner
        self.lbl_warning = QLabel("")
        self.lbl_warning.setWordWrap(True)
        self.lbl_warning.setStyleSheet("""
            QLabel {
                background-color: #fef3c7;
                color: #92400e;
                border: 1px solid #fde68a;
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 11.5px;
                font-weight: 600;
            }
        """)
        self.lbl_warning.setVisible(False)
        layout.addWidget(self.lbl_warning)

        # Buttons Row
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)
        btn_box.addStretch()

        self.btn_cancel = QPushButton("İptal")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #475569;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 7px 18px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #e2e8f0; }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("💾 Kaydet / Güncelle")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff !important;
                border: none;
                border-radius: 6px;
                padding: 7px 20px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        self.btn_save.clicked.connect(self._on_save_clicked)
        btn_box.addWidget(self.btn_save)

        layout.addLayout(btn_box)

        # Trigger initial validation
        self._on_text_changed(self.txt_profile_name.text())

    def _on_list_item_clicked(self, item: QListWidgetItem):
        name = item.data(Qt.UserRole) or item.text().replace("📂  ", "").strip()
        self.txt_profile_name.setText(name)
        self.combo_profile.setEditText(name)

    def _on_list_item_double_clicked(self, item: QListWidgetItem):
        name = item.data(Qt.UserRole) or item.text().replace("📂  ", "").strip()
        self.txt_profile_name.setText(name)
        self.combo_profile.setEditText(name)
        self._on_save_clicked()

    def _on_text_changed(self, text: str):
        name = text.strip()
        self.combo_profile.setEditText(name)
        
        # Sync selection in list
        for i in range(self.list_profiles.count()):
            it = self.list_profiles.item(i)
            p_name = it.data(Qt.UserRole) or it.text().replace("📂  ", "").strip()
            it.setSelected(p_name == name)

        if not name:
            self.lbl_warning.setVisible(False)
            self.btn_save.setEnabled(False)
            self.btn_save.setText("💾 Kaydet")
            return

        self.btn_save.setEnabled(True)
        if name in self.existing_profiles:
            self.lbl_warning.setText(f"⚠️ Dikkat: '{name}' profili zaten mevcut. Kaydedilirse var olan düzen değiştirilecektir!")
            self.lbl_warning.setVisible(True)
            self.btn_save.setText("💾 Üzerine Yaz / Güncelle")
            self.btn_save.setStyleSheet("""
                QPushButton {
                    background-color: #d97706;
                    color: #ffffff !important;
                    border: none;
                    border-radius: 6px;
                    padding: 7px 20px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #b45309; }
            """)
        else:
            self.lbl_warning.setVisible(False)
            self.btn_save.setText("💾 Yeni Profil Olarak Kaydet")
            self.btn_save.setStyleSheet("""
                QPushButton {
                    background-color: #2563eb;
                    color: #ffffff !important;
                    border: none;
                    border-radius: 6px;
                    padding: 7px 20px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #1d4ed8; }
            """)

    def _on_save_clicked(self):
        name = self.txt_profile_name.text().strip() or self.combo_profile.currentText().strip()
        if not name:
            QMessageBox.warning(self, "Uyarı", "Lütfen bir profil ismi girin.")
            return

        if name in self.existing_profiles:
            reply = QMessageBox.question(
                self,
                "Var Olan Profili Güncelle",
                f"'{name}' profili zaten kayıtlı.\n\nVar olan düzen değiştirilecektir! Güncellemek istediğinizden emin misiniz?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        self.selected_profile_name = name
        self.accept()


class ColumnManagerDialog(QDialog):
    """
    TOYA ERP Sütun Görünürlük Yönetimi Penceresi.
    - Sütun arama alanı (QLineEdit - '🔍 Sütun Ara...')
    - Hızlı seçim butonları: '☑️ Tümünü Seç', '⬜ Tümünü Kaldır', '🔄 Tersine Çevir'
    - Onay kutucuklu (Checkbox) sütun listesi (QListWidget)
    - Arama yapılırken anlık filtreleme ve işaret durumlarının korunması
    - Yüksek kontrastlı, açık ve şık tema
    """
    def __init__(self, columns: List[str], hidden_columns: List[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("👁️ Sütun Görünürlük Yönetimi")
        self.setFixedWidth(380)
        self.setFixedHeight(480)
        self.setStyleSheet("""
            QDialog {
                background-color: #ffffff;
                color: #0f172a;
            }
            QLabel {
                color: #1e293b;
                font-size: 12px;
            }
            QLineEdit {
                background-color: #f8fafc;
                color: #0f172a;
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #2563eb;
                background-color: #ffffff;
            }
        """)
        self._columns = columns
        self._hidden_columns = set(hidden_columns)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        # Title
        lbl_title = QLabel("👁️ Sütun Görünürlük Yönetimi")
        lbl_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1e3a8a;")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel("Tabloda görüntülemek istediğiniz sütunların kutucuklarını işaretleyin:")
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #475569; font-size: 11.5px;")
        layout.addWidget(lbl_desc)

        # Search Bar
        self.txt_search = QLineEdit(self)
        self.txt_search.setPlaceholderText("🔍 Sütun Adı Ara...")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self.txt_search)

        # Quick Actions Row
        quick_layout = QHBoxLayout()
        quick_layout.setSpacing(6)

        btn_all = QPushButton("☑️ Tümünü Seç", self)
        btn_all.setCursor(Qt.PointingHandCursor)
        btn_all.setStyleSheet(self._btn_quick_style())
        btn_all.clicked.connect(self._select_all)
        quick_layout.addWidget(btn_all)

        btn_none = QPushButton("⬜ Kaldır", self)
        btn_none.setCursor(Qt.PointingHandCursor)
        btn_none.setStyleSheet(self._btn_quick_style())
        btn_none.clicked.connect(self._deselect_all)
        quick_layout.addWidget(btn_none)

        btn_invert = QPushButton("🔄 Tersine", self)
        btn_invert.setCursor(Qt.PointingHandCursor)
        btn_invert.setStyleSheet(self._btn_quick_style())
        btn_invert.clicked.connect(self._invert_selection)
        quick_layout.addWidget(btn_invert)

        layout.addLayout(quick_layout)

        # Column List with Checkboxes
        self.list_columns = QListWidget(self)
        self.list_columns.setStyleSheet("""
            QListWidget {
                background-color: #f8fafc;
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px;
                font-size: 12px;
                color: #0f172a;
            }
            QListWidget::item {
                padding: 6px 8px;
                border-radius: 4px;
                margin-bottom: 2px;
                color: #0f172a;
            }
            QListWidget::item:hover {
                background-color: #e2e8f0;
            }
            QListWidget::item:selected {
                background-color: #2563eb;
                color: #ffffff;
            }
        """)

        for col_idx, col_name in enumerate(self._columns):
            item = QListWidgetItem(col_name)
            item.setData(Qt.UserRole, col_idx)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            is_checked = col_idx not in self._hidden_columns
            item.setCheckState(Qt.Checked if is_checked else Qt.Unchecked)
            self.list_columns.addItem(item)

        layout.addWidget(self.list_columns, stretch=1)

        # Bottom Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)
        btn_box.addStretch()

        btn_cancel = QPushButton("İptal", self)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #475569;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 7px 18px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #e2e8f0; }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_apply = QPushButton("💾 Uygula", self)
        btn_apply.setCursor(Qt.PointingHandCursor)
        btn_apply.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff !important;
                border: none;
                border-radius: 6px;
                padding: 7px 20px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        btn_apply.clicked.connect(self.accept)
        btn_box.addWidget(btn_apply)

        layout.addLayout(btn_box)

    def _btn_quick_style(self) -> str:
        return """
            QPushButton {
                background-color: #f1f5f9;
                color: #1e3a8a;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #e2e8f0;
                border-color: #94a3b8;
            }
        """

    def _on_search_text_changed(self, text: str):
        query = text.strip().lower()
        for i in range(self.list_columns.count()):
            item = self.list_columns.item(i)
            match = query in item.text().lower()
            item.setHidden(not match)

    def _select_all(self):
        for i in range(self.list_columns.count()):
            item = self.list_columns.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.Checked)

    def _deselect_all(self):
        for i in range(self.list_columns.count()):
            item = self.list_columns.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.Unchecked)

    def _invert_selection(self):
        for i in range(self.list_columns.count()):
            item = self.list_columns.item(i)
            if not item.isHidden():
                new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
                item.setCheckState(new_state)

    def get_hidden_columns(self) -> List[int]:
        hidden = []
        for i in range(self.list_columns.count()):
            item = self.list_columns.item(i)
            col_idx = item.data(Qt.UserRole)
            if item.checkState() == Qt.Unchecked:
                hidden.append(col_idx)
        return hidden


class GridProfileManager:
    """Manages named grid view profiles stored persistently in JSON."""

    def __init__(self, profile_key: str = "default_grid", storage_file: Optional[Path] = None):
        self.profile_key = profile_key
        self.storage_file = storage_file or Path("data/grid_profiles.json")
        self._ensure_storage()

    def _ensure_storage(self):
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_file.exists():
            try:
                with open(self.storage_file, "w", encoding="utf-8") as f:
                    json.dump({}, f)
            except Exception as e:
                logger.error("Failed to init grid profiles file: %s", e)

    def _read_all(self) -> Dict[str, Any]:
        try:
            if self.storage_file.exists():
                with open(self.storage_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error("Failed to read grid profiles: %s", e)
        return {}

    def _write_all(self, data: Dict[str, Any]):
        try:
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Failed to save grid profiles: %s", e)

    def get_profiles(self) -> Dict[str, Dict[str, Any]]:
        all_data = self._read_all()
        return all_data.get(self.profile_key, {
            "profiles": {
                "Varsayılan": {"hidden_columns": [], "column_widths": [], "row_height": 36, "column_order": []}
            },
            "active_profile": "Varsayılan"
        })

    def get_profile_names(self) -> List[str]:
        data = self.get_profiles()
        return list(data.get("profiles", {}).keys())

    def get_profile(self, name: str) -> Optional[Dict[str, Any]]:
        data = self.get_profiles()
        return data.get("profiles", {}).get(name)

    def get_active_profile_name(self) -> str:
        data = self.get_profiles()
        return data.get("active_profile", "Varsayılan")

    def save_profile(self, name: str, state: Dict[str, Any], set_active: bool = True):
        all_data = self._read_all()
        grid_data = all_data.get(self.profile_key, {"profiles": {}, "active_profile": "Varsayılan"})
        if "profiles" not in grid_data:
            grid_data["profiles"] = {}
        grid_data["profiles"][name] = state
        if set_active:
            grid_data["active_profile"] = name
        all_data[self.profile_key] = grid_data
        self._write_all(all_data)

    def set_active_profile(self, name: str):
        all_data = self._read_all()
        grid_data = all_data.get(self.profile_key, {"profiles": {}, "active_profile": "Varsayılan"})
        if name in grid_data.get("profiles", {}):
            grid_data["active_profile"] = name
            all_data[self.profile_key] = grid_data
            self._write_all(all_data)

    def delete_profile(self, name: str) -> bool:
        if name == "Varsayılan":
            return False
        all_data = self._read_all()
        grid_data = all_data.get(self.profile_key, {"profiles": {}, "active_profile": "Varsayılan"})
        if name in grid_data.get("profiles", {}):
            del grid_data["profiles"][name]
            if grid_data.get("active_profile") == name:
                grid_data["active_profile"] = "Varsayılan"
            all_data[self.profile_key] = grid_data
            self._write_all(all_data)
            return True
        return False


class ViewProfileWidget(QWidget):
    """
    Modular widget placed in the right action drawer / toolbar for managing
    grid view profiles, row heights, and column configurations.
    """

    profile_selected = Signal(str, dict)  # profile_name, profile_state
    save_requested = Signal(str)           # profile_name
    columns_requested = Signal()
    filter_row_toggled = Signal(bool)

    def __init__(self, profile_key: str = "default_grid", title: str = "GÖRÜNÜM PROFİLLERİ", parent=None):
        super().__init__(parent)
        self.profile_key = profile_key
        self.title = title
        self.manager = GridProfileManager(profile_key=self.profile_key)
        self._is_filter_row_active = True

        self._init_ui()
        self.reload_profiles()

    def _init_ui(self):
        main_lyt = QVBoxLayout(self)
        main_lyt.setContentsMargins(0, 0, 0, 0)
        main_lyt.setSpacing(6)

        self.grp_box = QGroupBox(f"⚙️ {self.title}")
        self.grp_box.setStyleSheet("""
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
                left: 10px;
                padding: 3px 8px;
                background-color: #1e3a8a;
                color: #ffffff !important;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
        """)
        grp_lyt = QVBoxLayout(self.grp_box)
        grp_lyt.setSpacing(6)
        grp_lyt.setContentsMargins(8, 8, 8, 8)

        lbl_prof = QLabel("Aktif Görünüm Profili:")
        lbl_prof.setStyleSheet("font-weight: 600; color: #475569; font-size: 10.5px;")
        grp_lyt.addWidget(lbl_prof)

        self.combo_profiles = QComboBox()
        self.combo_profiles.setStyleSheet("""
            QComboBox {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 5px 8px;
                background-color: #ffffff;
                color: #0f172a;
                font-size: 11px;
                font-weight: 600;
            }
            QComboBox:hover { border-color: #2563eb; }
        """)
        self.combo_profiles.currentTextChanged.connect(self._on_profile_changed)
        grp_lyt.addWidget(self.combo_profiles)

        # Profile Actions Buttons Row 1 (Save, New, Delete)
        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(4)

        btn_style_primary = """
            QPushButton {
                background-color: #2563eb;
                color: #ffffff !important;
                border: none;
                border-radius: 4px;
                padding: 5px 6px;
                font-size: 10.5px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """
        btn_style_sec = """
            QPushButton {
                background-color: #ffffff;
                color: #334155 !important;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 5px 6px;
                font-size: 10.5px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #f1f5f9; border-color: #94a3b8; }
        """

        self.btn_save = QPushButton("💾 Kaydet")
        self.btn_save.setToolTip("Mevcut sütun genişliklerini ve düzeni aktif profile kaydeder / günceller")
        self.btn_save.setStyleSheet(btn_style_primary)
        self.btn_save.clicked.connect(self._on_save_clicked)
        btn_row1.addWidget(self.btn_save)

        self.btn_new = QPushButton("➕ Yeni")
        self.btn_new.setToolTip("Yeni bir görünüm profili oluşturur veya var olanın üzerine yazar")
        self.btn_new.setStyleSheet(btn_style_sec)
        self.btn_new.clicked.connect(self._on_new_profile_clicked)
        btn_row1.addWidget(self.btn_new)

        self.btn_del = QPushButton("🗑️")
        self.btn_del.setToolTip("Seçili profili siler")
        self.btn_del.setFixedWidth(28)
        self.btn_del.setStyleSheet("""
            QPushButton {
                background-color: #fee2e2;
                color: #dc2626 !important;
                border: 1px solid #fca5a5;
                border-radius: 4px;
                padding: 5px 0px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #fecaca; }
        """)
        self.btn_del.clicked.connect(self._on_delete_profile_clicked)
        btn_row1.addWidget(self.btn_del)

        grp_lyt.addLayout(btn_row1)

        # Quick Grid Tools Row (Filter Row Toggle, Column Manager)
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(4)

        self.btn_toggle_filters = QPushButton("🔍 Kolon Filtreleri: Açık")
        self.btn_toggle_filters.setToolTip("Her sütun başlığının altındaki hızlı arama kutularını gizler/gösterir")
        self.btn_toggle_filters.setStyleSheet("""
            QPushButton {
                background-color: #ecfdf5;
                color: #065f46 !important;
                border: 1px solid #10b981;
                border-radius: 4px;
                padding: 5px 6px;
                font-size: 10.5px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #d1fae5; }
        """)
        self.btn_toggle_filters.clicked.connect(self._toggle_filter_row)
        btn_row2.addWidget(self.btn_toggle_filters)

        self.btn_columns = QPushButton("👁️ Sütunlar")
        self.btn_columns.setToolTip("Sütun görünürlük ve gizleme menüsü")
        self.btn_columns.setStyleSheet(btn_style_sec)
        self.btn_columns.clicked.connect(self.columns_requested.emit)
        btn_row2.addWidget(self.btn_columns)

        grp_lyt.addLayout(btn_row2)
        main_lyt.addWidget(self.grp_box)

    def reload_profiles(self):
        self.combo_profiles.blockSignals(True)
        self.combo_profiles.clear()
        data = self.manager.get_profiles()
        profiles = data.get("profiles", {})
        active = data.get("active_profile", "Varsayılan")

        for name in sorted(profiles.keys()):
            self.combo_profiles.addItem(name)

        idx = self.combo_profiles.findText(active)
        if idx >= 0:
            self.combo_profiles.setCurrentIndex(idx)
        else:
            self.combo_profiles.setCurrentIndex(0)
        self.combo_profiles.blockSignals(False)

    def _on_profile_changed(self, name: str):
        if not name:
            return
        self.manager.set_active_profile(name)
        data = self.manager.get_profiles()
        state = data.get("profiles", {}).get(name, {})
        self.profile_selected.emit(name, state)

    def _on_save_clicked(self):
        current_name = self.combo_profiles.currentText() or "Varsayılan"
        dialog = SaveLayoutProfileDialog(
            existing_profiles=self.manager.get_profile_names(),
            current_profile=current_name,
            parent=self
        )
        if dialog.exec() == QDialog.Accepted and dialog.selected_profile_name:
            chosen_name = dialog.selected_profile_name
            self.save_requested.emit(chosen_name)
            self.reload_profiles()
            idx = self.combo_profiles.findText(chosen_name)
            if idx >= 0:
                self.combo_profiles.setCurrentIndex(idx)

    def _on_new_profile_clicked(self):
        current_name = self.combo_profiles.currentText() or "Varsayılan"
        dialog = SaveLayoutProfileDialog(
            existing_profiles=self.manager.get_profile_names(),
            current_profile=current_name,
            parent=self
        )
        if dialog.exec() == QDialog.Accepted and dialog.selected_profile_name:
            chosen_name = dialog.selected_profile_name
            self.save_requested.emit(chosen_name)
            self.reload_profiles()
            idx = self.combo_profiles.findText(chosen_name)
            if idx >= 0:
                self.combo_profiles.setCurrentIndex(idx)

    def _on_delete_profile_clicked(self):
        current_name = self.combo_profiles.currentText()
        if current_name == "Varsayılan":
            QMessageBox.warning(self, "Profil Silinemez", "Varsayılan profil silinemez.")
            return

        confirmed = DeleteConfirmDialog.confirm_deletion(
            parent=self,
            item_name=current_name,
            item_type="Görünüm Profili",
            details=f"Profil Adı: {current_name}\nKayıtlı sütun genişlikleri, sıralamaları ve satır yükseklik ayarları silinecektir.",
            warning_text="Bu işlem geri alınamaz!"
        )
        if confirmed:
            if self.manager.delete_profile(current_name):
                self.reload_profiles()
                self._on_profile_changed(self.combo_profiles.currentText())

    def _toggle_filter_row(self):
        self._is_filter_row_active = not self._is_filter_row_active
        if self._is_filter_row_active:
            self.btn_toggle_filters.setText("🔍 Kolon Filtreleri: Açık")
            self.btn_toggle_filters.setStyleSheet("""
                QPushButton {
                    background-color: #ecfdf5;
                    color: #065f46 !important;
                    border: 1px solid #10b981;
                    border-radius: 4px;
                    padding: 5px 6px;
                    font-size: 10.5px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #d1fae5; }
            """)
        else:
            self.btn_toggle_filters.setText("🔍 Kolon Filtreleri: Kapalı")
            self.btn_toggle_filters.setStyleSheet("""
                QPushButton {
                    background-color: #f1f5f9;
                    color: #64748b !important;
                    border: 1px solid #cbd5e1;
                    border-radius: 4px;
                    padding: 5px 6px;
                    font-size: 10.5px;
                    font-weight: 600;
                }
                QPushButton:hover { background-color: #e2e8f0; }
            """)
        self.filter_row_toggled.emit(self._is_filter_row_active)

    def get_current_profile_name(self) -> str:
        return self.combo_profiles.currentText() or "Varsayılan"
