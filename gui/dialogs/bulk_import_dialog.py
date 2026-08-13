"""
bulk_import_dialog.py — Interactive Bulk Account Import Dialog with mapping & preview.
"""

import csv
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame,
    QComboBox, QCheckBox, QLineEdit, QPushButton, QFileDialog,
    QProgressBar, QMessageBox, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QWidget, QAbstractItemView, QSpinBox,
)

from core.mail_engine import MailEngine
from core.settings import AppSettings

logger = logging.getLogger(__name__)


class BulkImportDialog(QDialog):
    """Interactive bulk account importing dialog with column mapping and live preview."""

    def __init__(self, engine: MailEngine, parent=None, settings: AppSettings = None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings or AppSettings()
        self._is_loading = True
        
        # File parsing state
        self.file_path: Optional[str] = None
        self.file_headers: List[str] = []
        self.file_sheet_names: List[str] = []
        self.file_rows: List[List[str]] = []  # raw rows (strings)
        
        # UI mapping target fields
        self.targets = [
            {"id": "label", "name": "Hesap Etiketi (Label)", "required": False, "keys": ["label", "name", "hesap adı", "hesap adi", "başlık", "baslik", "title"]},
            {"id": "email", "name": "E-Posta Adresi (Email)", "required": True, "keys": ["email", "e-mail", "e-posta", "eposta", "mail"]},
            {"id": "imap_host", "name": "IMAP Sunucusu (Host)", "required": True, "keys": ["imap_host", "imap host", "host", "server", "sunucu", "imap sunucu"]},
            {"id": "imap_port", "name": "Bağlantı Noktası (Port)", "required": False, "keys": ["imap_port", "imap port", "port", "bağlantı noktası", "baglanti noktasi"]},
            {"id": "use_ssl", "name": "SSL/TLS Kullan (Use SSL)", "required": False, "keys": ["use_ssl", "use ssl", "ssl", "secure", "güvenli bağlantı", "guvenli baglanti"]},
            {"id": "username", "name": "Kullanıcı Adı (Username)", "required": False, "keys": ["username", "user", "kullanıcı", "kullanici", "kullanıcı adı", "kullanici adi"]},
            {"id": "password", "name": "Şifre (Password)", "required": True, "keys": ["password", "pass", "sifre", "şifre", "pwd"]},
            {"id": "export_subfolder", "name": "Aktarım Alt Klasörü (Subfolder)", "required": False, "keys": ["export_subfolder", "export subfolder", "subfolder", "alt klasör", "alt klasor", "alt_klasor"]},
            {"id": "storage", "name": "Depolama Konumu (Storage)", "required": False, "keys": ["storage", "depo", "storage location", "konum", "storage_location"]},
            {"id": "account_group", "name": "Grup / Domain (Group)", "required": False, "keys": ["account_group", "group", "grup", "domain", "organization", "organizasyon"]},
        ]
        
        self._setup_ui()
        self._is_loading = False

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

    def _populate_sample_account_combo(self):
        self.combo_sample_account.clear()
        self.combo_sample_account.addItem("-- Varsayılan Örnek Şablon Verisi --", None)
        try:
            if self.engine:
                accounts = self.engine.list_accounts()
                for acc in accounts:
                    lbl = acc.get("label") or f"Hesap #{acc.get('id')}"
                    email = acc.get("email", "")
                    display = f"⭐ {lbl} ({email})"
                    self.combo_sample_account.addItem(display, acc["id"])
        except Exception as e:
            logger.warning("Could not list accounts for sample template combo: %s", e)

    def _get_sample_account_data(self) -> Dict[str, str]:
        """Return a dictionary of sample account fields for CSV/Excel template generation."""
        acc_id = self.combo_sample_account.currentData()
        if acc_id and self.engine:
            try:
                acc = self.engine.accounts.get(acc_id)
                if acc:
                    email_val = acc.get("email", "info@baynet.com.tr")
                    username_val = email_val
                    if "username_enc" in acc and acc["username_enc"]:
                        try:
                            username_val = self.engine.crypto.decrypt(acc["username_enc"])
                        except Exception:
                            pass
                    
                    password_val = "password123"
                    if "password_enc" in acc and acc["password_enc"]:
                        try:
                            password_val = self.engine.crypto.decrypt(acc["password_enc"])
                        except Exception:
                            pass

                    storage_loc = self.settings.account_storage(acc_id) or "local_storage"

                    return {
                        "label": acc.get("label", "Main Account"),
                        "email": email_val,
                        "imap_host": acc.get("imap_host", "imap.baynet.com.tr"),
                        "imap_port": str(acc.get("imap_port", 993)),
                        "use_ssl": "1" if acc.get("use_ssl", 1) else "0",
                        "username": username_val,
                        "password": password_val,
                        "export_subfolder": acc.get("export_subfolder", "Baynet"),
                        "storage": storage_loc,
                        "account_group": acc.get("account_group", "Baynet"),
                    }
            except Exception as exc:
                logger.warning("Failed to load sample account %s data: %s", acc_id, exc)

        return {
            "label": "Baynet Main",
            "email": "info@baynet.com.tr",
            "imap_host": "imap.baynet.com.tr",
            "imap_port": "993",
            "use_ssl": "1",
            "username": "info@baynet.com.tr",
            "password": "password123",
            "export_subfolder": "Baynet",
            "storage": "local_storage",
            "account_group": "Baynet",
        }

    def _setup_ui(self):
        self.setWindowTitle("Excel / CSV den Hesap Aktarımı")
        self.resize(880, 680)
        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
            }
            QLabel[heading="true"] {
                font-size: 18px;
                font-weight: bold;
                color: #ffffff;
            }
            QFrame#banner {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1e3a8a, stop:1 #3b82f6);
                border-bottom: 2px solid #2563eb;
            }
            QGroupBox, QFrame#controls_frame {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
            }
            QLabel {
                color: #475569;
                font-weight: bold;
                font-size: 11px;
            }
            QLineEdit, QComboBox, QSpinBox {
                background-color: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border-color: #3b82f6;
            }
            QPushButton {
                background-color: #2563eb !important;
                color: #ffffff !important;
                font-weight: 700 !important;
                font-size: 11px !important;
                padding: 6px 14px !important;
                border: none !important;
                border-radius: 6px !important;
                min-height: 24px !important;
            }
            QPushButton:hover {
                background-color: #1d4ed8 !important;
                color: #ffffff !important;
            }
            QPushButton:pressed {
                background-color: #1e40af !important;
                color: #ffffff !important;
            }
            QPushButton:disabled {
                background-color: #94a3b8 !important;
                color: #f8fafc !important;
            }
            QPushButton[outline="true"] {
                background-color: #2563eb !important;
                color: #ffffff !important;
                border: none !important;
            }
            QPushButton[outline="true"]:hover {
                background-color: #1d4ed8 !important;
                color: #ffffff !important;
            }
            QPushButton[success="true"] {
                background-color: #10b981 !important;
                color: #ffffff !important;
                border: none !important;
            }
            QPushButton[success="true"]:hover {
                background-color: #059669 !important;
                color: #ffffff !important;
            }
            QPushButton[danger="true"] {
                background-color: #dc2626 !important;
                color: #ffffff !important;
                border: none !important;
            }
            QPushButton[danger="true"]:hover {
                background-color: #b91c1c !important;
                color: #ffffff !important;
            }
            QTableWidget {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                gridline-color: #e2e8f0;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #f1f5f9;
                color: #475569;
                padding: 4px;
                font-weight: bold;
                border: 1px solid #e2e8f0;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Top Banner
        banner = QFrame()
        banner.setObjectName("banner")
        banner.setFixedHeight(60)
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(16, 0, 16, 0)
        
        banner_title = QLabel("📂  Excel / CSV den Toplu Hesap Aktarımı")
        banner_title.setProperty("heading", True)
        banner_layout.addWidget(banner_title)
        banner_layout.addStretch()
        
        btn_close_top = QPushButton("Kapat")
        btn_close_top.setProperty("danger", True)
        btn_close_top.clicked.connect(self.reject)
        banner_layout.addWidget(btn_close_top)
        layout.addWidget(banner)

        # Main Scroll / Content Area
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(16, 0, 16, 16)
        content_layout.setSpacing(12)

        # Top Controls Frame
        controls_frame = QFrame()
        controls_frame.setObjectName("controls_frame")
        controls_layout = QVBoxLayout(controls_frame)
        controls_layout.setContentsMargins(12, 12, 12, 12)
        controls_layout.setSpacing(8)

        # File Selector Row
        file_row = QHBoxLayout()
        lbl_file = QLabel("Excel/CSV Dosya Yolu:")
        self.input_file_path = QLineEdit()
        self.input_file_path.setReadOnly(True)
        self.input_file_path.setPlaceholderText("Lütfen aktarılacak dosyayı seçin...")
        btn_browse = QPushButton("Dosya Seç...")
        btn_browse.setProperty("outline", True)
        btn_browse.clicked.connect(self._on_browse_file)
        file_row.addWidget(lbl_file)
        file_row.addWidget(self.input_file_path, stretch=1)
        file_row.addWidget(btn_browse)
        controls_layout.addLayout(file_row)

        # Sample Account Selection & Template Downloads Row
        template_row = QHBoxLayout()
        lbl_sample_acc = QLabel("Örnek Veri İçin Hesap:")
        self.combo_sample_account = QComboBox()
        self.combo_sample_account.setMinimumWidth(220)
        self._populate_sample_account_combo()

        lbl_template = QLabel("Şablon İndir:")
        btn_template_csv = QPushButton("Örnek CSV (.csv)")
        btn_template_csv.setProperty("outline", True)
        btn_template_csv.clicked.connect(self._download_template_csv)
        
        btn_template_xlsx = QPushButton("Örnek Excel (.xlsx)")
        btn_template_xlsx.setProperty("outline", True)
        btn_template_xlsx.clicked.connect(self._download_template_xlsx)
        
        template_row.addWidget(lbl_sample_acc)
        template_row.addWidget(self.combo_sample_account)
        template_row.addSpacing(10)
        template_row.addWidget(lbl_template)
        template_row.addWidget(btn_template_csv)
        template_row.addWidget(btn_template_xlsx)
        template_row.addStretch()
        controls_layout.addLayout(template_row)

        # Sheet & Header configuration Row
        config_row = QHBoxLayout()
        
        self.chk_headers = QCheckBox("İlk satır başlıkları içerir")
        self.chk_headers.setChecked(True)
        self.chk_headers.toggled.connect(self._on_config_changed)
        config_row.addWidget(self.chk_headers)
        
        config_row.addSpacing(20)
        
        self.lbl_sheet = QLabel("Çalışma Sayfası (Excel):")
        self.combo_sheet = QComboBox()
        self.combo_sheet.setEnabled(False)
        self.combo_sheet.currentIndexChanged.connect(self._on_sheet_changed)
        config_row.addWidget(self.lbl_sheet)
        config_row.addWidget(self.combo_sheet)
        
        config_row.addStretch()
        controls_layout.addLayout(config_row)
        content_layout.addWidget(controls_frame)

        # Mapping Grid Frame
        mapping_frame = QFrame()
        mapping_frame.setObjectName("controls_frame")
        mapping_layout = QVBoxLayout(mapping_frame)
        mapping_layout.setContentsMargins(12, 12, 12, 12)
        mapping_layout.setSpacing(6)
        
        lbl_map_title = QLabel("SÜTUN EŞLEŞTİRME AYARLARI")
        lbl_map_title.setStyleSheet("color: #1e3a8a; font-size: 11px; margin-bottom: 2px;")
        mapping_layout.addWidget(lbl_map_title)

        self.table_mapping = QTableWidget()
        self.table_mapping.setColumnCount(4)
        self.table_mapping.setHorizontalHeaderLabels(["Aktar", "Alan Adı", "Dosya Sütunu (Excel/CSV)", "Açıklama"])
        self.table_mapping.setRowCount(len(self.targets))
        self.table_mapping.verticalHeader().setVisible(False)
        self.table_mapping.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_mapping.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_mapping.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_mapping.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_mapping.setFixedHeight(230)
        
        # Populate mapping grid
        self.mapping_combos: Dict[str, QComboBox] = {}
        self.mapping_checkboxes: Dict[str, QCheckBox] = {}
        
        for idx, t in enumerate(self.targets):
            # Checkbox
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk = QCheckBox()
            chk.setChecked(True)
            chk.toggled.connect(self._update_preview)
            chk_layout.addWidget(chk)
            self.table_mapping.setCellWidget(idx, 0, chk_widget)
            self.mapping_checkboxes[t["id"]] = chk
            
            # Field label
            lbl_name = QLabel(t["name"])
            if t["required"]:
                lbl_name.setStyleSheet("color: #dc2626; font-weight: bold;")
            self.table_mapping.setCellWidget(idx, 1, lbl_name)
            
            # Dropdown column selector
            combo = QComboBox()
            combo.addItem("(Eşleştirilmedi)", None)
            combo.currentIndexChanged.connect(self._update_preview)
            self.table_mapping.setCellWidget(idx, 2, combo)
            self.mapping_combos[t["id"]] = combo
            
            # Status / Description label
            desc = "Zorunlu *" if t["required"] else "İsteğe bağlı"
            desc_item = QTableWidgetItem(desc)
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemIsEditable)
            if t["required"]:
                desc_item.setForeground(QColor("#dc2626"))
            else:
                desc_item.setForeground(QColor("#64748b"))
            self.table_mapping.setItem(idx, 3, desc_item)
            
        mapping_layout.addWidget(self.table_mapping)
        content_layout.addWidget(mapping_frame)

        # Preview Grid Frame
        preview_frame = QFrame()
        preview_frame.setObjectName("controls_frame")
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(6)
        
        lbl_preview_title = QLabel("VERİ ÖNİZLEME (İlk 5 Satır)")
        lbl_preview_title.setStyleSheet("color: #1e3a8a; font-size: 11px; margin-bottom: 2px;")
        preview_layout.addWidget(lbl_preview_title)

        self.table_preview = QTableWidget()
        self.table_preview.setColumnCount(len(self.targets))
        self.table_preview.setHorizontalHeaderLabels([t["name"].split(" (")[0] for t in self.targets])
        self.table_preview.setRowCount(5)
        self.table_preview.verticalHeader().setVisible(False)
        self.table_preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_preview.setAlternatingRowColors(True)
        self.table_preview.setFixedHeight(120)
        
        # Adjust resize modes
        for col_idx in range(len(self.targets)):
            self.table_preview.horizontalHeader().setSectionResizeMode(col_idx, QHeaderView.ResizeToContents)
            
        preview_layout.addWidget(self.table_preview)
        content_layout.addWidget(preview_frame)

        # Footer Actions layout
        actions_row = QHBoxLayout()
        actions_row.addStretch()
        
        self.btn_import = QPushButton("💾  Bilgileri Aktar")
        self.btn_import.setProperty("success", True)
        self.btn_import.setEnabled(False)
        self.btn_import.clicked.connect(self._run_import)
        
        btn_reset = QPushButton("🔄  Sıfırla")
        btn_reset.setProperty("outline", True)
        btn_reset.clicked.connect(self._on_reset)
        
        btn_close = QPushButton("İptal")
        btn_close.setProperty("outline", True)
        btn_close.clicked.connect(self.reject)
        
        actions_row.addWidget(btn_reset)
        actions_row.addWidget(btn_close)
        actions_row.addWidget(self.btn_import)
        
        content_layout.addLayout(actions_row)
        layout.addWidget(content_widget, stretch=1)

    @Slot()
    def _download_template_csv(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "CSV Şablonunu Kaydet", "hesap_aktarim_sablonu.csv", "CSV Files (*.csv)"
        )
        if not file_path:
            return
            
        sample = self._get_sample_account_data()
        headers = ["label", "email", "imap_host", "imap_port", "use_ssl", "username", "password", "export_subfolder", "storage", "account_group"]
        
        try:
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerow([sample.get(h, "") for h in headers])
            self._show_styled_msg("Başarılı", "CSV Şablonu seçilen hesap verisiyle başarıyla kaydedildi.")
        except Exception as e:
            self._show_styled_msg("Hata", f"Dosya kaydedilemedi:\n{e}", icon=QMessageBox.Critical)

    @Slot()
    def _download_template_xlsx(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Excel Şablonunu Kaydet", "hesap_aktarim_sablonu.xlsx", "Excel Files (*.xlsx)"
        )
        if not file_path:
            return
            
        sample = self._get_sample_account_data()
        headers = ["label", "email", "imap_host", "imap_port", "use_ssl", "username", "password", "export_subfolder", "storage", "account_group"]
        row_values = [sample.get(h, "") for h in headers]

        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Hesaplar"

            header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
            header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
            header_align = Alignment(horizontal="center", vertical="center")

            ws.append(headers)
            for col_num in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col_num)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_align

            ws.append(row_values)

            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = openpyxl.utils.get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = max(max_len + 4, 15)

            wb.save(file_path)
            self._show_styled_msg("Başarılı", "Excel Şablonu seçilen hesap verisiyle başarıyla kaydedildi.")
        except Exception as e:
            logger.warning("openpyxl template creation failed, falling back: %s", e)
            QMessageBox.critical(self, "Hata", f"Dosya kaydedilemedi:\n{e}")

    @Slot()
    def _on_browse_file(self):
        file_path, selected_filter = QFileDialog.getOpenFileName(
            self, "Hesap Aktarılacak Dosyayı Seçin", "", 
            "Excel/CSV Files (*.csv *.xlsx *.xls);;CSV Files (*.csv);;Excel Files (*.xlsx *.xls);;All Files (*)"
        )
        if not file_path:
            return

        self.file_path = file_path
        self.input_file_path.setText(file_path)
        self._load_file()

    def _load_file(self):
        if not self.file_path:
            return

        path = Path(self.file_path)
        self.file_headers = []
        self.file_sheet_names = []
        self.file_rows = []
        self.combo_sheet.clear()
        self.combo_sheet.setEnabled(False)

        ext = path.suffix.lower()
        if ext == ".csv":
            self._load_csv(path)
        elif ext in (".xlsx", ".xls"):
            self._load_excel(path)
        else:
            QMessageBox.critical(self, "Hata", "Desteklenmeyen dosya formatı!")
            return

        self._populate_column_selectors()
        self._auto_match_columns()
        self._update_preview()

    def _load_csv(self, path: Path):
        try:
            # Detect delimiter
            delimiter = ","
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                head = f.read(2048)
                if ";" in head and head.count(";") > head.count(","):
                    delimiter = ";"
                elif "\t" in head:
                    delimiter = "\t"

            with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                reader = csv.reader(f, delimiter=delimiter)
                all_rows = [row for row in reader if row]
                
            if not all_rows:
                return

            if self.chk_headers.isChecked():
                self.file_headers = [str(h).strip() for h in all_rows[0]]
                self.file_rows = all_rows[1:]
            else:
                col_count = len(all_rows[0])
                self.file_headers = [self._col_letter(i) for i in range(col_count)]
                self.file_rows = all_rows
        except Exception as exc:
            QMessageBox.critical(self, "Dosya Hatası", f"CSV dosyası okunamadı:\n{exc}")

    def _load_excel(self, path: Path):
        try:
            import openpyxl
        except ImportError:
            QMessageBox.warning(
                self, "Excel Hatası",
                "Excel (.xlsx) dosyalarını okumak için 'openpyxl' paketi gereklidir.\n\n"
                "Lütfen bu paketi kurun (pip install openpyxl) veya Excel dosyasını CSV'ye dönüştürüp tekrar deneyin."
            )
            return

        try:
            self._is_loading = True
            # Read worksheet names
            wb = openpyxl.load_workbook(str(path), read_only=True)
            self.file_sheet_names = wb.sheetnames
            wb.close()

            # Populate combo box
            self.combo_sheet.setEnabled(True)
            self.combo_sheet.addItems(self.file_sheet_names)
            self._is_loading = False
            
            # Load active sheet
            self._load_excel_sheet(self.combo_sheet.currentText())
        except Exception as exc:
            self._is_loading = False
            QMessageBox.critical(self, "Excel Hatası", f"Excel dosyası okunamadı:\n{exc}")

    def _load_excel_sheet(self, sheet_name: str):
        if not self.file_path or not sheet_name:
            return
            
        try:
            import openpyxl
            wb = openpyxl.load_workbook(self.file_path, read_only=True, data_only=True)
            if sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                all_rows = []
                for r in sheet.iter_rows(values_only=True):
                    # Filter out completely empty rows
                    if any(v is not None for v in r):
                        all_rows.append([str(v).strip() if v is not None else "" for v in r])
                        
                if all_rows:
                    if self.chk_headers.isChecked():
                        self.file_headers = [str(h).strip() for h in all_rows[0]]
                        self.file_rows = all_rows[1:]
                    else:
                        col_count = len(all_rows[0])
                        self.file_headers = [self._col_letter(i) for i in range(col_count)]
                        self.file_rows = all_rows
            wb.close()
        except Exception as exc:
            logger.error("Failed to load Excel sheet %s: %s", sheet_name, exc)

    def _col_letter(self, index: int) -> str:
        """Convert 0-based column index to letter representation (A, B, C...)."""
        result = ""
        index += 1
        while index > 0:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def _populate_column_selectors(self):
        self._is_loading = True
        for combo in self.mapping_combos.values():
            combo.clear()
            combo.addItem("(Eşleştirilmedi)", None)
            for idx, name in enumerate(self.file_headers):
                letter = self._col_letter(idx)
                display_name = f"{letter} - {name}" if name != letter else letter
                combo.addItem(display_name, idx)
        self._is_loading = False

    def _auto_match_columns(self):
        self._is_loading = True
        for target in self.targets:
            combo = self.mapping_combos[target["id"]]
            matched_idx = None
            
            # 1. Match based on keys
            for idx, h_name in enumerate(self.file_headers):
                clean_name = h_name.lower().strip()
                if clean_name in target["keys"] or any(k in clean_name for k in target["keys"]):
                    matched_idx = idx
                    break
                    
            # 2. Match based on column letters if header name matches column mapping keys (fallback)
            if matched_idx is None:
                for idx, h_name in enumerate(self.file_headers):
                    letter = self._col_letter(idx).lower()
                    if letter in target["keys"]:
                        matched_idx = idx
                        break
                        
            if matched_idx is not None:
                # Add 1 because index 0 is "(Eşleştirilmedi)"
                combo.setCurrentIndex(matched_idx + 1)
        self._is_loading = False

    @Slot()
    def _on_config_changed(self):
        if self._is_loading:
            return
        self._load_file()

    @Slot(int)
    def _on_sheet_changed(self, idx: int):
        if self._is_loading or idx < 0:
            return
        sheet_name = self.combo_sheet.itemText(idx)
        self._load_excel_sheet(sheet_name)
        self._populate_column_selectors()
        self._auto_match_columns()
        self._update_preview()

    @Slot()
    def _on_reset(self):
        self._is_loading = True
        for combo in self.mapping_combos.values():
            combo.setCurrentIndex(0)
        self._is_loading = False
        self._update_preview()

    def _get_mapped_row_data(self, row: List[str]) -> Dict[str, Any]:
        """Map raw row strings to target dictionary keys based on current dropdown selections."""
        mapped = {}
        for target in self.targets:
            t_id = target["id"]
            chk = self.mapping_checkboxes[t_id]
            if not chk.isChecked():
                mapped[t_id] = None
                continue
                
            combo = self.mapping_combos[t_id]
            col_idx = combo.currentData()
            if col_idx is not None and col_idx < len(row):
                mapped[t_id] = row[col_idx]
            else:
                mapped[t_id] = None
        return mapped

    @Slot()
    def _update_preview(self):
        if self._is_loading:
            return
            
        self.table_preview.clearContents()
        
        # Populate live preview rows
        preview_rows = self.file_rows[:5]
        for row_idx, raw_row in enumerate(preview_rows):
            mapped_data = self._get_mapped_row_data(raw_row)
            
            for col_idx, target in enumerate(self.targets):
                val = mapped_data.get(target["id"])
                val_str = str(val) if val is not None else ""
                
                # Highlight missing values for required fields
                item = QTableWidgetItem(val_str)
                if target["required"] and not val_str:
                    item.setBackground(QColor("#fee2e2"))
                    item.setToolTip("Gerekli alan boş olamaz!")
                self.table_preview.setItem(row_idx, col_idx, item)

        # Check required fields mapping state
        all_required_mapped = True
        for target in self.targets:
            if target["required"]:
                chk = self.mapping_checkboxes[target["id"]]
                combo = self.mapping_combos[target["id"]]
                if not chk.isChecked() or combo.currentData() is None:
                    all_required_mapped = False
                    
                    # Highlight required column row red in mapping table
                    row_index = self.targets.index(target)
                    desc_item = self.table_mapping.item(row_index, 3)
                    if desc_item:
                        desc_item.setText("HATA: Eşleştirilmedi! *")
                        desc_item.setForeground(QColor("#dc2626"))
                else:
                    row_index = self.targets.index(target)
                    desc_item = self.table_mapping.item(row_index, 3)
                    if desc_item:
                        desc_item.setText("Eşleştirildi ✓")
                        desc_item.setForeground(QColor("#059669"))

        # Enable/Disable Import button
        self.btn_import.setEnabled(all_required_mapped and len(self.file_rows) > 0)

    @Slot()
    def _run_import(self):
        if not self.file_path or not self.file_rows:
            return

        # Double check mappings
        target_mappings = {}
        for target in self.targets:
            t_id = target["id"]
            chk = self.mapping_checkboxes[t_id]
            combo = self.mapping_combos[t_id]
            col_idx = combo.currentData()
            if chk.isChecked() and col_idx is not None:
                target_mappings[t_id] = col_idx

        # Retrieve existing storage locations
        existing_storages = {loc.name: loc.name for loc in self.settings.storage_locations()}

        # Load existing accounts to detect duplicate email conflicts
        existing_accounts = self.engine.list_accounts()
        existing_emails = {acc["email"].lower(): acc for acc in existing_accounts}

        has_conflicts = False
        for raw_row in self.file_rows:
            mapped_data = {}
            for t_id, col_idx in target_mappings.items():
                if col_idx < len(raw_row):
                    mapped_data[t_id] = raw_row[col_idx].strip()
            email = mapped_data.get("email", "").lower()
            if email in existing_emails:
                has_conflicts = True
                break

        conflict_policy = "SKIP"  # Default skip
        if has_conflicts:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Hesap Çakışması")
            msg_box.setText(
                "Aktarılacak listedeki bazı e-posta hesapları sistemde zaten kayıtlı.\n\n"
                "Bu hesaplar için ne yapılmasını istersiniz?"
            )
            msg_box.setIcon(QMessageBox.Question)
            
            btn_update = msg_box.addButton("Güncelle", QMessageBox.AcceptRole)
            btn_skip = msg_box.addButton("Değişiklik Yapma", QMessageBox.RejectRole)
            btn_cancel = msg_box.addButton("İptal", QMessageBox.DestructiveRole)
            
            msg_box.setStyleSheet("""
                QMessageBox {
                    background-color: #ffffff;
                }
                QLabel {
                    color: #0f172a !important;
                    font-size: 13px !important;
                    font-weight: 600 !important;
                }
                QPushButton {
                    background-color: #2563eb !important;
                    color: #ffffff !important;
                    font-weight: 700 !important;
                    font-size: 12px !important;
                    border: none !important;
                    border-radius: 6px !important;
                    padding: 8px 20px !important;
                    min-height: 28px !important;
                    min-width: 95px !important;
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
            
            msg_box.exec()
            clicked_button = msg_box.clickedButton()
            
            if clicked_button == btn_update:
                conflict_policy = "UPDATE"
            elif clicked_button == btn_skip:
                conflict_policy = "SKIP"
            else:
                return  # Cancel import

        success_count = 0
        skipped: List[tuple] = []  # (row_number, account/email, reason)

        for idx, raw_row in enumerate(self.file_rows):
            row_num = idx + (2 if self.chk_headers.isChecked() else 1)
            
            # Map row data
            mapped_data = {}
            for t_id, col_idx in target_mappings.items():
                if col_idx < len(raw_row):
                    mapped_data[t_id] = raw_row[col_idx].strip()
                else:
                    mapped_data[t_id] = ""

            email = mapped_data.get("email", "")
            
            # Skip if duplicate and policy is SKIP
            if email.lower() in existing_emails and conflict_policy == "SKIP":
                skipped.append((row_num, email, "Hesap zaten kayıtlı (Mükerrer Kayıt Engellendi)"))
                continue

            existing_acc = existing_emails.get(email.lower())
            is_update_run = existing_acc is not None

            # Validation checks
            if not email:
                skipped.append((row_num, "(E-Posta Yok)", "Email alanı eksik"))
                continue
            if "@" not in email:
                skipped.append((row_num, email, "Geçersiz E-Posta formatı (@ eksik)"))
                continue

            password = mapped_data.get("password", "")
            if not password:
                if is_update_run:
                    # Fallback to existing decrypted password
                    pass_enc = existing_acc.get("password_enc", "")
                    try:
                        password = self.engine.crypto.decrypt(pass_enc)
                    except Exception:
                        pass
                if not password:
                    skipped.append((row_num, email, "Şifre alanı eksik"))
                    continue

            host = mapped_data.get("imap_host", "")
            if not host:
                if is_update_run:
                    host = existing_acc.get("imap_host", "")
                if not host:
                    skipped.append((row_num, email, "IMAP Sunucu adresi eksik"))
                    continue

            label = mapped_data.get("label") or f"Hesap {email}"
            
            # Port
            port_val = mapped_data.get("imap_port", "993")
            try:
                port = int(port_val) if port_val else 993
                if not (1 <= port <= 65535):
                    raise ValueError()
            except ValueError:
                skipped.append((row_num, email, f"Geçersiz Port değeri: '{port_val}'"))
                continue

            # SSL
            ssl_val = str(mapped_data.get("use_ssl", "1")).lower()
            use_ssl = ssl_val in ("1", "true", "yes", "evet", "y", "t", "")

            username = mapped_data.get("username") or email
            export_subfolder = mapped_data.get("export_subfolder", "")
            storage_name = mapped_data.get("storage", "")
            account_group = mapped_data.get("account_group", "").strip()
            if not account_group and "@" in email:
                account_group = email.split("@")[-1]

            # Execute save / update
            try:
                if is_update_run:
                    acc_id = existing_acc["id"]
                    username_enc = self.engine.crypto.encrypt(username)
                    password_enc = self.engine.crypto.encrypt(password)
                    
                    update_data = {
                        "label": label,
                        "email": email,
                        "imap_host": host,
                        "imap_port": port,
                        "use_ssl": int(use_ssl),
                        "username_enc": username_enc,
                        "password_enc": password_enc,
                        "export_subfolder": export_subfolder,
                        "account_group": account_group
                    }
                    self.engine.accounts.update(acc_id, **update_data)
                    self.engine.audit.append("account.updated", account_id=acc_id)
                else:
                    acc_id = self.engine.add_account(
                        label=label,
                        email=email,
                        imap_host=host,
                        imap_port=port,
                        use_ssl=use_ssl,
                        username=username,
                        password=password,
                        export_subfolder=export_subfolder,
                        account_group=account_group
                    )

                # Set storage mapping
                if storage_name:
                    if storage_name in existing_storages:
                        self.settings.set_account_storage(acc_id, storage_name)
                    else:
                        matched = None
                        for existing_name in existing_storages:
                            if existing_name.lower() == storage_name.lower():
                                matched = existing_name
                                break
                        if matched:
                            self.settings.set_account_storage(acc_id, matched)
                        else:
                            self.settings.set_account_storage(acc_id, None)
                else:
                    self.settings.set_account_storage(acc_id, None)

                success_count += 1
            except Exception as exc:
                skipped.append((row_num, email, f"Veritabanı Kayıt Hatası: {exc}"))

        # Prepare summary reporting HTML
        msg = f"<h3>Toplu Hesap Aktarımı Tamamlandı</h3>"
        msg += f"<p><b>Başarıyla aktarılan/güncellenen hesap sayısı:</b> {success_count}</p>"
        if skipped:
            msg += f"<p><b>Aktarılmayan / Atlanan Satırlar ({len(skipped)}):</b></p>"
            msg += "<div style='background-color:#fee2e2; border:1px solid #fca5a5; padding:8px; border-radius:4px; max-height:220px; overflow-y:auto;'>"
            msg += "<table cellpadding='4' cellspacing='0' style='font-size:11px; width:100%; border-collapse:collapse;'>"
            msg += "<tr style='background:#fecaca; text-align:left;'><th>Satır No</th><th>Hesap / E-Posta</th><th>Atlama Nedeni</th></tr>"
            for r_num, acc_lbl, reason in skipped:
                msg += f"<tr><td>{r_num}</td><td><b>{acc_lbl}</b></td><td style='color:#dc2626;'>{reason}</td></tr>"
            msg += "</table></div>"

        reply = QMessageBox(self)
        reply.setWindowTitle("Toplu Aktarım Raporu")
        reply.setText(msg)
        reply.setIcon(QMessageBox.Information if not skipped else QMessageBox.Warning)
        reply.setStyleSheet("""
            QMessageBox {
                min-width: 520px;
                background-color: #ffffff;
            }
            QLabel {
                color: #0f172a !important;
                font-size: 12px !important;
            }
            QPushButton {
                background-color: #2563eb !important;
                color: #ffffff !important;
                font-weight: 700 !important;
                font-size: 12px !important;
                border: none !important;
                border-radius: 6px !important;
                padding: 8px 20px !important;
                min-height: 28px !important;
                min-width: 95px !important;
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
        ok_btn = reply.button(QMessageBox.Ok)
        if ok_btn:
            ok_btn.setText("Tamam")
        reply.exec()

        self.accept()
