import logging
import re
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QMessageBox, QDialogButtonBox, QGroupBox,
    QHeaderView, QInputDialog
)

logger = logging.getLogger(__name__)

class GroupDomainDialog(QDialog):
    """Redesigned Dialog for managing Group Domains using a table interface."""

    def __init__(self, engine, settings, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings
        self._is_loading = True
        self.selected_group = ""

        self.setWindowTitle("Grup / Domain Yönetimi")
        self.resize(550, 400)
        self.setModal(True)

        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
            }
            QGroupBox {
                color: #1e293b;
                font-weight: bold;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 6px;
                padding-top: 18px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
                color: #1e3a8a;
            }
            QTableWidget {
                background-color: #ffffff;
                gridline-color: #f1f5f9;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                color: #1e293b;
            }
            QHeaderView::section {
                background-color: #f8fafc;
                color: #475569;
                font-weight: bold;
                border: none;
                border-bottom: 1.5px solid #cbd5e1;
                padding: 6px;
                font-size: 11px;
            }
            QPushButton {
                background-color: #2563eb !important;
                color: #ffffff !important;
                border: none !important;
                border-radius: 6px !important;
                padding: 6px 14px !important;
                font-weight: 700 !important;
                font-size: 11px !important;
                min-height: 24px !important;
            }
            QPushButton:hover {
                background-color: #1d4ed8 !important;
                color: #ffffff !important;
            }
            QPushButton:disabled {
                background-color: #cbd5e1 !important;
                color: #94a3b8 !important;
            }
        """)

        self._setup_ui()
        self._load_groups()
        self._is_loading = False

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Main Table Group Box
        group_box = QGroupBox("Grup / Domain Tanımları")
        gb_layout = QVBoxLayout(group_box)
        gb_layout.setContentsMargins(12, 16, 12, 12)
        gb_layout.setSpacing(8)

        # Table + Buttons horizontal layout
        content_layout = QHBoxLayout()
        content_layout.setSpacing(10)

        # Table
        self.tbl_groups = QTableWidget()
        self.tbl_groups.setColumnCount(2)
        self.tbl_groups.setHorizontalHeaderLabels(["Grup / Domain Adı", "Durum"])
        self.tbl_groups.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_groups.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tbl_groups.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_groups.setSelectionMode(QTableWidget.SingleSelection)
        self.tbl_groups.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_groups.setAlternatingRowColors(True)
        self.tbl_groups.itemSelectionChanged.connect(self._on_selection_changed)
        self.tbl_groups.doubleClicked.connect(self._on_select_group)
        content_layout.addWidget(self.tbl_groups, stretch=1)

        # Actions Sidebar Layout
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(6)
        actions_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_add = QPushButton("➕ Yeni Ekle")
        self.btn_add.clicked.connect(self._add_group)

        self.btn_edit = QPushButton("✏️ Düzenle")
        self.btn_edit.setEnabled(False)
        self.btn_edit.clicked.connect(self._edit_group)

        self.btn_toggle_active = QPushButton("⏸️ Aktif / Pasif")
        self.btn_toggle_active.setEnabled(False)
        self.btn_toggle_active.clicked.connect(self._toggle_active)

        self.btn_delete = QPushButton("🗑 Sil")
        self.btn_delete.setEnabled(False)
        self.btn_delete.setStyleSheet("background-color: #dc2626 !important; color: white !important;")
        self.btn_delete.clicked.connect(self._delete_group)

        self.btn_auto_sync = QPushButton("⚡ Domainleri Eşitle")
        self.btn_auto_sync.setToolTip("Sistemdeki tüm hesapların gruplarını e-posta domain adlarına göre otomatik günceller")
        self.btn_auto_sync.clicked.connect(self._auto_sync_account_groups)

        self.btn_select = QPushButton("✔️ Seç")
        self.btn_select.setEnabled(False)
        self.btn_select.clicked.connect(self._on_select_group)

        actions_layout.addWidget(self.btn_add)
        actions_layout.addWidget(self.btn_edit)
        actions_layout.addWidget(self.btn_toggle_active)
        actions_layout.addWidget(self.btn_delete)
        actions_layout.addWidget(self.btn_auto_sync)
        actions_layout.addWidget(self.btn_select)
        actions_layout.addStretch()

        content_layout.addLayout(actions_layout)
        gb_layout.addLayout(content_layout)
        layout.addWidget(group_box)

        # Bottom Close Button Box
        self.button_box = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.button_box.setStyleSheet("""
            QPushButton {
                background-color: #2563eb !important;
                color: #ffffff !important;
                min-width: 90px;
                padding: 6px 16px;
                border-radius: 6px;
                font-weight: bold;
            }
        """)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _get_groups_from_settings(self) -> list:
        raw = self.settings.get("group_domains", [])
        groups = []
        for g in raw:
            if isinstance(g, str):
                groups.append({"name": g.strip(), "is_active": True})
            elif isinstance(g, dict):
                name = g.get("name", "").strip()
                if name:
                    groups.append({"name": name, "is_active": g.get("is_active", True)})
        return groups

    def _save_groups_to_settings(self, groups_list: list):
        self.settings.set("group_domains", groups_list)
        self.settings.save()

    def _load_groups(self):
        self._is_loading = True
        self.tbl_groups.setRowCount(0)

        # Merge groups from settings, database account_groups AND email domains
        groups_dict = {}  # name -> is_active

        # 1. From settings
        for g in self._get_groups_from_settings():
            groups_dict[g["name"]] = g["is_active"]

        # 2. From database account_group column
        try:
            with self.engine.db.get_conn() as conn:
                rows = conn.execute("SELECT DISTINCT account_group FROM accounts WHERE account_group IS NOT NULL AND account_group != ''").fetchall()
                for r in rows:
                    name = r["account_group"].strip()
                    if name not in groups_dict:
                        groups_dict[name] = True
        except Exception as e:
            logger.error("Failed to query database for groups: %s", e)

        # Populate table
        sorted_names = sorted(groups_dict.keys())
        self.tbl_groups.setRowCount(len(sorted_names))
        for i, name in enumerate(sorted_names):
            is_active = groups_dict[name]
            
            # Col 0: Name
            item_name = QTableWidgetItem(name)
            item_name.setData(Qt.UserRole, name)
            self.tbl_groups.setItem(i, 0, item_name)

            # Col 1: Status
            item_status = QTableWidgetItem("Aktif" if is_active else "Pasif")
            item_status.setTextAlignment(Qt.AlignCenter)
            if not is_active:
                item_status.setForeground(Qt.gray)
            self.tbl_groups.setItem(i, 1, item_status)

        self._is_loading = False
        self._on_selection_changed()

    @Slot()
    def _on_selection_changed(self):
        row = self.tbl_groups.currentRow()
        has_sel = (row >= 0)
        self.btn_edit.setEnabled(has_sel)
        self.btn_toggle_active.setEnabled(has_sel)
        self.btn_delete.setEnabled(has_sel)
        self.btn_select.setEnabled(has_sel)

    @Slot()
    def _add_group(self):
        text, ok = QInputDialog.getMultiLineText(
            self, "Grup Ekle",
            "Grup / Domain İsimleri (Satır, virgül veya noktalı virgül ile ayırarak birden fazla girebilirsiniz):"
        )
        if not ok or not text.strip():
            return

        raw_names = re.split(r'[;,\n]', text)
        names = [n.strip() for n in raw_names if n.strip()]
        if not names:
            return

        groups = self._get_groups_from_settings()
        added = 0
        for name in names:
            if not any(g["name"] == name for g in groups):
                groups.append({"name": name, "is_active": True})
                added += 1

        if added > 0:
            self._save_groups_to_settings(groups)
            self._load_groups()
            QMessageBox.information(self, "Başarılı", f"{added} grup başarıyla eklendi.")

    @Slot()
    def _edit_group(self):
        row = self.tbl_groups.currentRow()
        if row < 0:
            return
        old_name = self.tbl_groups.item(row, 0).data(Qt.UserRole)

        new_name, ok = QInputDialog.getText(
            self, "Grup Düzenle", "Yeni Grup İsmi:", text=old_name
        )
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()

        if new_name == old_name:
            return

        groups = self._get_groups_from_settings()
        # Rename in settings
        found_in_settings = False
        for g in groups:
            if g["name"] == old_name:
                g["name"] = new_name
                found_in_settings = True
                break

        if not found_in_settings:
            # Add to settings as active
            groups.append({"name": new_name, "is_active": True})

        self._save_groups_to_settings(groups)

        # Update accounts in database
        try:
            with self.engine.db.get_conn() as conn:
                conn.execute("UPDATE accounts SET account_group = ? WHERE account_group = ?", (new_name, old_name))
        except Exception as e:
            logger.error("Failed to update database accounts during group rename: %s", e)

        self._load_groups()
        QMessageBox.information(self, "Başarılı", f"'{old_name}' grubu '{new_name}' olarak güncellendi ve ilgili tüm hesaplar güncellendi.")

    @Slot()
    def _auto_sync_account_groups(self):
        """Automatically set account_group = email domain for all accounts."""
        reply = QMessageBox.question(
            self, "Domain Eşitleme Onayı",
            "Tüm kayıtlı hesapların grup adları, e-posta adreslerinin domain uzantılarına (örn. ozmedmedikal.com.tr) göre otomatik güncellenecek.\n\nOnaylıyor musunuz?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        updated_count = 0
        try:
            with self.engine.db.get_conn() as conn:
                accounts = conn.execute("SELECT id, email, account_group FROM accounts").fetchall()
                for acc in accounts:
                    email_str = (acc["email"] or "").strip().lower()
                    if "@" in email_str:
                        dom = email_str.split("@")[-1].strip()
                        if dom and dom != acc["account_group"]:
                            conn.execute("UPDATE accounts SET account_group = ? WHERE id = ?", (dom, acc["id"]))
                            updated_count += 1
            self._load_groups()
            QMessageBox.information(self, "Başarılı", f"{updated_count} hesabın grup adı domain uzantısına göre başarıyla eşcellendi.")
        except Exception as exc:
            logger.error("Failed to auto-sync account groups: %s", exc)
            QMessageBox.critical(self, "Hata", f"Domain eşitleme hatası:\n{exc}")

    @Slot()
    def _toggle_active(self):
        row = self.tbl_groups.currentRow()
        if row < 0:
            return
        name = self.tbl_groups.item(row, 0).data(Qt.UserRole)

        groups = self._get_groups_from_settings()
        found = False
        for g in groups:
            if g["name"] == name:
                g["is_active"] = not g["is_active"]
                found = True
                break

        if not found:
            # If it was database-only, add to settings and make passive (since it default-loaded as active)
            groups.append({"name": name, "is_active": False})

        self._save_groups_to_settings(groups)
        self._load_groups()

    @Slot()
    def _delete_group(self):
        row = self.tbl_groups.currentRow()
        if row < 0:
            return
        name = self.tbl_groups.item(row, 0).data(Qt.UserRole)

        # Check database usage
        count = 0
        try:
            with self.engine.db.get_conn() as conn:
                count_row = conn.execute("SELECT COUNT(*) as cnt FROM accounts WHERE account_group = ?", (name,)).fetchone()
                count = count_row["cnt"] if count_row else 0
        except Exception:
            count = 0

        if count > 0:
            reply = QMessageBox.question(
                self, "Grup Kullanımda",
                f"'{name}' grubu şu an {count} hesap tarafından kullanılmaktadır.\n\n"
                "Grubu silip bu hesapların grup bilgisini temizlemek istiyor musunuz?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            try:
                with self.engine.db.get_conn() as conn:
                    conn.execute("UPDATE accounts SET account_group = '' WHERE account_group = ?", (name,))
            except Exception as e:
                logger.error("Failed to clear account_group on delete: %s", e)

        reply = QMessageBox.question(
            self, "Silme Onayı",
            f"'{name}' grubunu silmek istediğinize emin misiniz?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            groups = self._get_groups_from_settings()
            groups = [g for g in groups if g["name"] != name]
            self._save_groups_to_settings(groups)
            self._load_groups()
            QMessageBox.information(self, "Başarılı", f"'{name}' grubu silindi.")

    @Slot()
    def _on_select_group(self):
        row = self.tbl_groups.currentRow()
        if row >= 0:
            self.selected_group = self.tbl_groups.item(row, 0).data(Qt.UserRole)
            self.accept()
