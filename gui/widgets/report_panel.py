"""
report_panel.py — Redesigned reports panel with Reports History, Custom Reports generator, and DB Stats.
"""

import json
import logging
import glob
import os
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Slot, QUrl, QDate, Signal, QThread
from PySide6.QtGui import QIcon, QFont, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QTextEdit, QMessageBox, QComboBox, QFileDialog, QTabWidget,
    QSplitter, QTextBrowser, QFrame, QLineEdit, QFormLayout, QCheckBox, QDateEdit,
    QListWidget, QListWidgetItem,
)

from core.mail_engine import MailEngine
from core.reporter import ReportGenerator
from gui.dialogs.report_preview_dialog import ReportPreviewDialog

logger = logging.getLogger(__name__)


class CustomReportWorker(QThread):
    """Background worker for custom analytics report generation."""
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, engine: MailEngine, kwargs: dict, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.kwargs = kwargs

    def run(self):
        try:
            res = self.engine.generate_custom_report(**self.kwargs)
            self.finished.emit(res or {})
        except Exception as exc:
            logger.exception("Error generating custom report in worker: %s", exc)
            self.failed.emit(str(exc))


# Style helpers for clean UI
BTN_STYLE_BLUE = """
    QPushButton {
        background-color: #4361ee;
        color: white;
        font-weight: 600;
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 12px;
        border: none;
    }
    QPushButton:hover {
        background-color: #3a56d4;
    }
    QPushButton:disabled {
        background-color: #cbd5e1;
        color: #94a3b8;
    }
"""

BTN_STYLE_RED = """
    QPushButton {
        background-color: #ef4444;
        color: white;
        font-weight: 600;
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 12px;
        border: none;
    }
    QPushButton:hover {
        background-color: #dc2626;
    }
    QPushButton:disabled {
        background-color: #cbd5e1;
        color: #94a3b8;
    }
"""

BTN_STYLE_OUTLINE = """
    QPushButton {
        background-color: transparent;
        color: #4b5563;
        border: 1px solid #cbd5e1;
        font-weight: 600;
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: #f1f5f9;
        border-color: #94a3b8;
    }
"""


class ReportPanel(QWidget):
    """Reports panel listing history, custom reports generator, and database statistics."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._reporter = engine.reporter
        self._reports_list: List[Dict[str, Any]] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Header
        header = QLabel("Reports & Analytics")
        header.setProperty("heading", True)
        header.setStyleSheet("font-size: 22px; font-weight: bold; color: #1a1a2e;")
        layout.addWidget(header)

        sub = QLabel("View system audit logs, custom analytical statistics, and operation reports.")
        sub.setProperty("subheading", True)
        sub.setStyleSheet("font-size: 13px; color: #64748b; margin-bottom: 8px;")
        layout.addWidget(sub)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #e2e8f0;
                background: #ffffff;
                border-radius: 8px;
            }
            QTabBar::tab {
                background: #f1f5f9;
                border: 1px solid #cbd5e1;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 8px 16px;
                margin-right: 4px;
                font-weight: 500;
                color: #475569;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                border-color: #e2e8f0;
                color: #4361ee;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.tabs, stretch=1)

        # Tab 1: Reports History
        self.tab_history = QWidget()
        self._setup_history_tab()
        self.tabs.addTab(self.tab_history, "📊 İşlem Geçmişi & Raporlar")

        # Tab 2: Create Custom Report (New!)
        self.tab_custom = QWidget()
        self._setup_custom_report_tab()
        self.tabs.addTab(self.tab_custom, "⚙️ Özel Rapor Oluştur")

        # Tab 3: Database Stats
        self.tab_stats = QWidget()
        self._setup_stats_tab()
        self.tabs.addTab(self.tab_stats, "📈 Veritabanı İstatistikleri")

    def _setup_history_tab(self):
        main_layout = QHBoxLayout(self.tab_history)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # ------------------------------------------------------------------
        # Collapsible Group / Domain Filter Sidebar (Sol Menü)
        # ------------------------------------------------------------------
        self.sidebar_widget = QWidget()
        self.sidebar_widget.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(self.sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)

        lbl_groups = QLabel("🌐 GRUP / DOMAİN FİLTRESİ")
        lbl_groups.setStyleSheet("font-weight: bold; color: #4361ee; font-size: 11px;")
        sidebar_layout.addWidget(lbl_groups)

        self.group_filter_list = QListWidget()
        self.group_filter_list.setStyleSheet("""
            QListWidget {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-size: 11px;
                color: #1e293b;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #f1f5f9;
            }
            QListWidget::item:selected {
                background-color: #e0e7ff;
                color: #4361ee;
                font-weight: bold;
            }
        """)
        self.group_filter_list.itemSelectionChanged.connect(self._filter_reports)
        sidebar_layout.addWidget(self.group_filter_list)

        self.btn_toggle_sidebar = QPushButton("◀")
        self.btn_toggle_sidebar.setToolTip("Grup / Domain Listesini Gizle/Göster")
        self.btn_toggle_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_sidebar.setFixedWidth(16)
        self.btn_toggle_sidebar.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #475569;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                font-weight: bold;
                font-size: 10px;
                padding: 0px;
                min-height: 100px;
            }
            QPushButton:hover { background-color: #cbd5e1; }
        """)
        self.btn_toggle_sidebar.clicked.connect(self._toggle_sidebar)

        main_layout.addWidget(self.sidebar_widget)
        main_layout.addWidget(self.btn_toggle_sidebar)

        # Content area (Toolbar + Splitter)
        content_area = QWidget()
        layout = QVBoxLayout(content_area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        main_layout.addWidget(content_area, stretch=1)

        # ------------------------------------------------------------------
        # Top Toolbar / In-Report Filter Controls
        # ------------------------------------------------------------------
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("İşlem Türü:"))
        self.combo_filter_type = QComboBox()
        self.combo_filter_type.addItems(["Tümü", "Sync", "Backup", "Restore", "Export", "Custom", "Audit"])
        self.combo_filter_type.setMinimumWidth(110)
        self.combo_filter_type.currentIndexChanged.connect(self._filter_reports)
        toolbar.addWidget(self.combo_filter_type)

        # Errors only checkbox
        self.chk_errors_only = QCheckBox("⚠️ Sadece Hatalar")
        self.chk_errors_only.setStyleSheet("font-weight: bold; color: #ef4444;")
        self.chk_errors_only.toggled.connect(self._filter_reports)
        toolbar.addWidget(self.chk_errors_only)

        # Date range filter
        self.chk_date_filter = QCheckBox("📅 Tarih:")
        self.date_since = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_since.setCalendarPopup(True)
        self.date_since.setEnabled(False)
        self.date_before = QDateEdit(QDate.currentDate())
        self.date_before.setCalendarPopup(True)
        self.date_before.setEnabled(False)

        self.chk_date_filter.toggled.connect(self.date_since.setEnabled)
        self.chk_date_filter.toggled.connect(self.date_before.setEnabled)
        self.chk_date_filter.toggled.connect(self._filter_reports)
        self.date_since.dateChanged.connect(self._filter_reports)
        self.date_before.dateChanged.connect(self._filter_reports)

        toolbar.addWidget(self.chk_date_filter)
        toolbar.addWidget(self.date_since)
        toolbar.addWidget(QLabel("-"))
        toolbar.addWidget(self.date_before)

        toolbar.addWidget(QLabel("Ara:"))
        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("Hesap / Kaynak ara...")
        self.input_search.setMinimumWidth(150)
        self.input_search.textChanged.connect(self._filter_reports)
        toolbar.addWidget(self.input_search)

        toolbar.addStretch()

        self.btn_refresh_reports = QPushButton("🔄 Yenile")
        self.btn_refresh_reports.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_refresh_reports.clicked.connect(self._load_reports_history)
        toolbar.addWidget(self.btn_refresh_reports)

        self.btn_fullscreen_preview = QPushButton("🔍 Tam Ekran Önizleme")
        self.btn_fullscreen_preview.setStyleSheet(BTN_STYLE_BLUE)
        self.btn_fullscreen_preview.setEnabled(False)
        self.btn_fullscreen_preview.clicked.connect(self._open_fullscreen_preview)
        toolbar.addWidget(self.btn_fullscreen_preview)

        self.btn_open_html = QPushButton("🌐 HTML Aç")
        self.btn_open_html.setStyleSheet(BTN_STYLE_OUTLINE)
        self.btn_open_html.setEnabled(False)
        self.btn_open_html.clicked.connect(self._open_html_report)
        toolbar.addWidget(self.btn_open_html)

        self.btn_delete_report = QPushButton("🗑 Sil")
        self.btn_delete_report.setStyleSheet(BTN_STYLE_RED)
        self.btn_delete_report.setEnabled(False)
        self.btn_delete_report.clicked.connect(self._delete_report)
        toolbar.addWidget(self.btn_delete_report)

        layout.addLayout(toolbar)

        # Splitter (Table left, Details right)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background-color: #e2e8f0; width: 2px; }")

        # Table QTableWidget
        self.table_reports = QTableWidget()
        self.table_reports.setColumnCount(6)
        self.table_reports.setHorizontalHeaderLabels([
            "Tarih & Saat", "İşlem Türü", "Hesap / Hedef", "Başarılı Mail", "Hatalar", "Durum"
        ])
        self.table_reports.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_reports.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_reports.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_reports.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_reports.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_reports.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table_reports.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_reports.setSelectionMode(QTableWidget.SingleSelection)
        self.table_reports.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_reports.setAlternatingRowColors(True)
        self.table_reports.verticalHeader().setVisible(False)
        self.table_reports.setStyleSheet("""
            QTableWidget {
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                background-color: #ffffff;
                color: #0f172a;
            }
            QTableWidget::item { padding: 8px 10px; }
            QTableWidget::item:selected { background-color: #cbd5e1; color: #000000; }
        """)
        self.table_reports.itemSelectionChanged.connect(self._on_report_selection_changed)
        self.table_reports.cellDoubleClicked.connect(lambda row, col: self._open_fullscreen_preview())
        splitter.addWidget(self.table_reports)

        # Details QFrame with QTextBrowser
        details_frame = QFrame()
        details_frame.setFrameShape(QFrame.StyledPanel)
        details_frame.setStyleSheet("""
            QFrame {
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                background-color: #f8fafc;
            }
        """)
        details_layout = QVBoxLayout(details_frame)
        details_layout.setContentsMargins(12, 12, 12, 12)

        lbl_details = QLabel("Rapor Detayları")
        lbl_details.setStyleSheet("font-weight: bold; font-size: 13px; color: #1e293b; border: none;")
        details_layout.addWidget(lbl_details)

        self.browser_preview = QTextBrowser()
        self.browser_preview.setStyleSheet("border: none; background-color: transparent;")
        self.browser_preview.setOpenLinks(False)
        details_layout.addWidget(self.browser_preview)

        splitter.addWidget(details_frame)
        splitter.setSizes([750, 450])
        layout.addWidget(splitter)


    def _setup_custom_report_tab(self):
        """Redesign of tab layout with dynamic form filters to run custom metadata reports."""
        layout = QVBoxLayout(self.tab_custom)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        info_lbl = QLabel(
            "<b>Özel Analiz Raporu Oluştur</b><br/>"
            "<span style='color:#64748b;'>Belirleyeceğiniz mail ya da domain grubuna, "
            "tarih aralıklarına göre özel arşiv analiz raporları oluşturabilirsiniz.</span>"
        )
        layout.addWidget(info_lbl)

        form_box = QGroupBox("Arama Kriterleri & Filtreler")
        form_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 18px;
            }
        """)
        form_layout = QFormLayout(form_box)
        form_layout.setSpacing(10)

        # Filter Category
        self.combo_custom_filter = QComboBox()
        self.combo_custom_filter.addItems([
            "Hesap Bazlı",
            "Domain Grubu Bazlı (Account Group)",
            "E-Posta Domaini Bazlı (e.g. @domain.com)",
            "Tek Bir E-Posta Adresi (Sender/Recipient)"
        ])
        self.combo_custom_filter.currentIndexChanged.connect(self._on_custom_filter_changed)
        form_layout.addRow("Filtreleme Kategorisi:", self.combo_custom_filter)

        # Widgets for categories (stacked under form)
        self.combo_custom_account = QComboBox()
        form_layout.addRow("Hesap Seçin:", self.combo_custom_account)

        self.combo_custom_group = QComboBox()
        form_layout.addRow("Domain Grubu Seçin:", self.combo_custom_group)

        self.input_custom_domain = QLineEdit()
        self.input_custom_domain.setPlaceholderText("Örn: company.com")
        form_layout.addRow("E-Posta Domaini:", self.input_custom_domain)

        self.input_custom_email = QLineEdit()
        self.input_custom_email.setPlaceholderText("Örn: name@company.com")
        form_layout.addRow("E-Posta Adresi:", self.input_custom_email)

        # Date Constraints
        self.chk_custom_since = QCheckBox("Şu tarihten yeni:")
        self.date_custom_since = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_custom_since.setCalendarPopup(True)
        self.date_custom_since.setEnabled(False)
        self.chk_custom_since.toggled.connect(self.date_custom_since.setEnabled)
        
        since_row = QHBoxLayout()
        since_row.addWidget(self.chk_custom_since)
        since_row.addWidget(self.date_custom_since)
        since_row.addStretch()
        form_layout.addRow("Başlangıç Tarihi:", since_row)

        self.chk_custom_before = QCheckBox("Şu tarihten eski:")
        self.date_custom_before = QDateEdit(QDate.currentDate())
        self.date_custom_before.setCalendarPopup(True)
        self.date_custom_before.setEnabled(False)
        self.chk_custom_before.toggled.connect(self.date_custom_before.setEnabled)

        before_row = QHBoxLayout()
        before_row.addWidget(self.chk_custom_before)
        before_row.addWidget(self.date_custom_before)
        before_row.addStretch()
        form_layout.addRow("Bitiş Tarihi:", before_row)

        layout.addWidget(form_box)

        btn_row = QHBoxLayout()
        self.btn_generate_custom = QPushButton("📊 Özel Analiz Raporu Oluştur")
        self.btn_generate_custom.setStyleSheet(BTN_STYLE_BLUE)
        self.btn_generate_custom.setMinimumHeight(36)
        self.btn_generate_custom.clicked.connect(self._on_generate_custom)
        btn_row.addWidget(self.btn_generate_custom)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()

        # Hide inputs initially according to category
        self._on_custom_filter_changed(0)

    def _setup_stats_tab(self):
        layout = QVBoxLayout(self.tab_stats)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Top Group Box for manual report generation shortcut
        shortcut_box = QGroupBox("Rapor Oluştur")
        shortcut_box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                color: #4361ee;
            }
        """)
        shortcut_layout = QHBoxLayout(shortcut_box)
        shortcut_layout.setContentsMargins(12, 12, 12, 12)
        shortcut_layout.setSpacing(10)

        self.combo_account = QComboBox()
        self.combo_account.setMinimumWidth(250)
        shortcut_layout.addWidget(QLabel("Hesap Seçin:"))
        shortcut_layout.addWidget(self.combo_account)

        self.btn_sync_report = QPushButton("📊 Sync Raporu Oluştur")
        self.btn_sync_report.setStyleSheet(BTN_STYLE_BLUE)
        shortcut_layout.addWidget(self.btn_sync_report)

        self.btn_stats_report = QPushButton("📈 İstatistikleri Yenile")
        self.btn_stats_report.setStyleSheet(BTN_STYLE_OUTLINE)
        shortcut_layout.addWidget(self.btn_stats_report)

        shortcut_layout.addStretch()
        layout.addWidget(shortcut_box)

        # Database Stats Table
        stats_box = QGroupBox("Veritabanı İstatistikleri")
        stats_box.setStyleSheet(shortcut_box.styleSheet())
        stats_layout = QVBoxLayout(stats_box)
        stats_layout.setContentsMargins(12, 12, 12, 12)

        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(2)
        self.stats_table.setHorizontalHeaderLabels(["Metrik", "Değer"])
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.stats_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.stats_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background-color: #ffffff;
            }
            QTableWidget::item { padding: 6px 10px; }
        """)
        stats_layout.addWidget(self.stats_table)

        layout.addWidget(stats_box, stretch=1)

        # Log output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(90)
        self.log_output.setPlaceholderText("Rapor çıktısı...")
        self.log_output.setStyleSheet("""
            QTextEdit {
                background: #1a1a2e;
                color: #a8d8ea;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
        """)
        layout.addWidget(self.log_output)

        self.btn_sync_report.clicked.connect(self._gen_sync_report)
        self.btn_stats_report.clicked.connect(self._gen_stats_report)

    # ------------------------------------------------------------------
    # Dynamic form filter slots
    # ------------------------------------------------------------------

    @Slot(int)
    def _on_custom_filter_changed(self, index: int):
        self.combo_custom_account.setVisible(False)
        self.combo_custom_group.setVisible(False)
        self.input_custom_domain.setVisible(False)
        self.input_custom_email.setVisible(False)

        if index == 0:
            self.combo_custom_account.setVisible(True)
        elif index == 1:
            self.combo_custom_group.setVisible(True)
        elif index == 2:
            self.input_custom_domain.setVisible(True)
        elif index == 3:
            self.input_custom_email.setVisible(True)

    @Slot()
    def _on_generate_custom(self):
        index = self.combo_custom_filter.currentIndex()
        
        account_id = None
        account_group = None
        domain = None
        single_email = None

        if index == 0:
            account_id = self.combo_custom_account.currentData()
            if account_id is None:
                QMessageBox.warning(self, "Hata", "Lütfen önce geçerli bir hesap seçin.")
                return
        elif index == 1:
            account_group = self.combo_custom_group.currentText()
            if not account_group:
                QMessageBox.warning(self, "Hata", "Lütfen geçerli bir domain grubu seçin (Önce ayarlardan grup atayın).")
                return
        elif index == 2:
            domain = self.input_custom_domain.text().strip()
            if not domain:
                QMessageBox.warning(self, "Hata", "Lütfen bir e-posta domaini yazın (Örn: company.com).")
                return
            if domain.startswith("@"):
                domain = domain[1:]
        elif index == 3:
            single_email = self.input_custom_email.text().strip()
            if not single_email:
                QMessageBox.warning(self, "Hata", "Lütfen analiz edilecek e-posta adresini yazın.")
                return

        since_date = None
        if self.chk_custom_since.isChecked():
            since_date = self.date_custom_since.date().toString("yyyy-MM-dd 00:00:00")
            
        before_date = None
        if self.chk_custom_before.isChecked():
            before_date = self.date_custom_before.date().toString("yyyy-MM-dd 23:59:59")

        self.btn_generate_custom.setEnabled(False)
        self.log_output.append("Özel analiz raporu oluşturuluyor...")

        kwargs = {
            "account_id": account_id,
            "account_group": account_group,
            "domain": domain,
            "since_date": since_date,
            "before_date": before_date,
            "single_email": single_email,
        }

        self._custom_worker = CustomReportWorker(self.engine, kwargs, parent=self)
        self._custom_worker.finished.connect(self._on_custom_worker_finished)
        self._custom_worker.failed.connect(self._on_custom_worker_failed)
        self._custom_worker.start()

    @Slot(dict)
    def _on_custom_worker_finished(self, res: dict):
        self.btn_generate_custom.setEnabled(True)
        if res.get("total_mails", 0) == 0:
            QMessageBox.information(
                self, "Sonuç Yok",
                "Belirtilen arama kriterlerine uygun arşivlenmiş hiçbir e-posta bulunamadı."
            )
            self.log_output.append("Özel analiz raporu oluşturulamadı: Eşleşen e-posta yok.")
        else:
            self.log_output.append(f"Özel analiz raporu kaydedildi: {res.get('report_path')}")
            self._load_reports_history()
            self.tabs.setCurrentIndex(0)

            # Auto-open in full screen preview dialog
            html_content = ""
            html_path = res.get("html_path", "")
            if html_path and os.path.exists(html_path):
                try:
                    with open(html_path, "r", encoding="utf-8") as f:
                        html_content = f.read()
                except Exception:
                    pass
            if not html_content:
                html_content = self._render_virtual_report_html(res)

            dialog = ReportPreviewDialog("Özel Analiz Raporu", html_content, report_data=res, parent=self)
            dialog.exec()

    @Slot(str)
    def _on_custom_worker_failed(self, err_msg: str):
        self.btn_generate_custom.setEnabled(True)
        QMessageBox.critical(self, "Hata", f"Analiz raporu oluşturulurken hata oluştu:\n{err_msg}")
        self.log_output.append(f"HATA: {err_msg}")

    @Slot()
    def _toggle_sidebar(self):
        visible = self.sidebar_widget.isVisible()
        self.sidebar_widget.setVisible(not visible)
        self.btn_toggle_sidebar.setText("▶" if visible else "◀")


    # ------------------------------------------------------------------
    # Data loading and merging (Disk + DB Audit Logs)
    # ------------------------------------------------------------------

    def _load_reports_history(self):
        self._reports_list.clear()

        # 1. Load report JSONs from data/reports
        reports_dir = Path("data/reports")
        if reports_dir.exists():
            json_files = glob.glob(str(reports_dir / "*.json"))
            for path_str in json_files:
                p = Path(path_str)
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    # Store file paths
                    data["file_path"] = str(p)
                    data["html_path"] = str(p.with_suffix(".html"))
                    
                    # Standardize fields if missing
                    if "timestamp" not in data:
                        data["timestamp"] = data.get("started_at", datetime.fromtimestamp(p.stat().st_mtime).isoformat())
                    
                    self._reports_list.append(data)
                except Exception as exc:
                    logger.warning("Failed to load report JSON %s: %s", path_str, exc)

        # 2. Query DB audit_log for historical data fallback
        try:
            with self.engine.db.get_conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM audit_log 
                       WHERE action IN ('sync.completed', 'backup.s3', 'backup.gdrive', 'restore.s3', 'restore.gdrive') 
                       ORDER BY timestamp DESC"""
                ).fetchall()
                
                for r in rows:
                    details_str = r["details"] or "{}"
                    try:
                        details = json.loads(details_str)
                    except Exception:
                        details = {}
                        
                    action = r["action"]
                    timestamp = r["timestamp"]
                    
                    # Convert action types
                    if action == "sync.completed":
                        r_type = "sync"
                    elif action in ("backup.s3", "backup.gdrive"):
                        r_type = "backup"
                    elif action in ("restore.s3", "restore.gdrive"):
                        r_type = "restore"
                    else:
                        r_type = "unknown"
                        
                    # Check for duplicates on disk (within 5 seconds limit)
                    dt_db = self._parse_iso_timestamp(timestamp)
                    is_duplicate = False
                    
                    if dt_db:
                        for disk_rep in self._reports_list:
                            if disk_rep.get("type") == r_type:
                                dt_disk = self._parse_iso_timestamp(disk_rep.get("timestamp", ""))
                                if dt_disk and abs((dt_disk - dt_db).total_seconds()) < 8:
                                    is_duplicate = True
                                    break
                                    
                    if is_duplicate:
                        continue
                        
                    # Reconstruct virtual report
                    acc_label = "Geçmiş Rapor"
                    if r["account_id"]:
                        acc_info = self.engine.accounts.get(r["account_id"])
                        if acc_info:
                            acc_label = acc_info.get("label", f"Hesap #{r['account_id']}")
                            
                    virtual_report = {
                        "type": r_type,
                        "timestamp": timestamp,
                        "account_label": acc_label,
                        "is_virtual": True,
                        "raw_action": action,
                        "details": details,
                    }
                    
                    # Populate type-specific variables for table views
                    if r_type == "sync":
                        virtual_report["mails_fetched"] = details.get("fetched", 0)
                        virtual_report["errors"] = details.get("errors", 0)
                        virtual_report["duplicates_found"] = details.get("duplicates", 0)
                        virtual_report["duration_seconds"] = details.get("duration", 0.0)
                    elif r_type == "backup":
                        virtual_report["target"] = details.get("bucket", "Cloud")
                        virtual_report["mails_backed_up"] = details.get("mails_backed_up", 0)
                        virtual_report["errors"] = 0 if details.get("success", True) else 1
                        virtual_report["total_bytes"] = details.get("size_bytes", 0)
                    elif r_type == "restore":
                        virtual_report["source"] = details.get("source", "Cloud Backup")
                        virtual_report["mails_restored"] = details.get("mails_restored", 0)
                        virtual_report["errors"] = details.get("errors", 0)
                        
                    self._reports_list.append(virtual_report)
        except Exception as exc:
            logger.exception("Failed to query audit_log for report history: %s", exc)

        # Sort reports by timestamp descending
        self._reports_list.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        self._filter_reports()

    def _parse_iso_timestamp(self, ts_str: str) -> Optional[datetime]:
        try:
            # ISO timestamp parser
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            try:
                # Custom format parser
                return datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None

    # ------------------------------------------------------------------
    # Filtering & Table Populating
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Filtering & Table Populating
    # ------------------------------------------------------------------

    def _filter_reports(self):
        filter_type = self.combo_filter_type.currentText().lower()
        search_query = self.input_search.text().strip().lower()
        errors_only = self.chk_errors_only.isChecked()
        date_filter_active = self.chk_date_filter.isChecked()

        since_str = self.date_since.date().toString("yyyy-MM-dd") if date_filter_active else ""
        before_str = self.date_before.date().toString("yyyy-MM-dd") if date_filter_active else ""

        # Sidebar group/domain selection
        selected_items = self.group_filter_list.selectedItems()
        group_filter_val = selected_items[0].data(Qt.UserRole) if selected_items else "ALL"

        filtered: List[Dict[str, Any]] = []
        for r in self._reports_list:
            # Filter type
            r_type = str(r.get("type", "")).lower()
            if filter_type != "tümü" and filter_type != r_type:
                continue

            # Errors only
            if errors_only:
                err = r.get("errors", 0)
                if err <= 0:
                    continue

            # Date filter
            if date_filter_active:
                ts = str(r.get("timestamp", ""))[:10]
                if ts:
                    if since_str and ts < since_str:
                        continue
                    if before_str and ts > before_str:
                        continue

            # Search query
            label = str(r.get("account_label") or r.get("account") or r.get("target") or r.get("source") or "").lower()
            if search_query and search_query not in label:
                continue

            # Sidebar group/domain filter
            if group_filter_val and group_filter_val != "ALL":
                if group_filter_val.startswith("GROUP:"):
                    target_grp = group_filter_val.split("GROUP:")[1].lower()
                    acc_id = r.get("account_id")
                    acc_info = self.engine.accounts.get(acc_id) if acc_id else None
                    grp_match = (acc_info and str(acc_info.get("account_group", "")).lower() == target_grp)
                    if not grp_match and target_grp not in label:
                        continue
                elif group_filter_val.startswith("DOMAIN:"):
                    target_dom = group_filter_val.split("DOMAIN:")[1].lower()
                    if target_dom not in label:
                        continue

            filtered.append(r)

        self._populate_table(filtered)

    def _populate_table(self, reports: List[Dict[str, Any]]):
        self.table_reports.setRowCount(0)
        self.table_reports.setRowCount(len(reports))

        for idx, r in enumerate(reports):
            # 1. Date
            ts = r.get("timestamp", "")
            formatted_date = ts[:16].replace("T", " ")
            item_date = QTableWidgetItem(formatted_date)
            item_date.setData(Qt.UserRole, r)
            self.table_reports.setItem(idx, 0, item_date)

            # 2. Type
            r_type = str(r.get("type", "")).upper()
            is_virtual = r.get("is_virtual", False)
            type_text = f"⚙️ {r_type}"
            if is_virtual:
                type_text += " (Geçmiş)"
            item_type = QTableWidgetItem(type_text)
            item_type.setData(Qt.UserRole, r)
            self.table_reports.setItem(idx, 1, item_type)

            # 3. Account / Target
            label = r.get("account_label") or r.get("account") or r.get("target") or r.get("source") or "Unknown"
            item_label = QTableWidgetItem(str(label))
            item_label.setData(Qt.UserRole, r)
            self.table_reports.setItem(idx, 2, item_label)

            # 4. Success Count
            sc = 0
            if r_type == "SYNC":
                sc = r.get("mails_fetched", 0)
            elif r_type == "BACKUP":
                sc = r.get("mails_backed_up", 0)
            elif r_type == "RESTORE":
                sc = r.get("mails_restored", 0)
            elif r_type == "EXPORT":
                sc = r.get("exported_mails", r.get("exported", 0))
            elif r_type == "CUSTOM":
                sc = r.get("total_mails", 0)
            item_sc = QTableWidgetItem(str(sc))
            item_sc.setData(Qt.UserRole, r)
            self.table_reports.setItem(idx, 3, item_sc)

            # 5. Errors
            err = r.get("errors", 0)
            item_err = QTableWidgetItem(str(err))
            if err > 0:
                item_err.setForeground(QColor("#ef4444"))
                item_err.setFont(QFont("Segoe UI", 10, QFont.Bold))
            item_err.setData(Qt.UserRole, r)
            self.table_reports.setItem(idx, 4, item_err)

            # 6. Status
            status_item = QTableWidgetItem("Başarılı" if err == 0 else "Hatalı")
            status_item.setForeground(QColor("#10b981") if err == 0 else QColor("#ef4444"))
            status_item.setFont(QFont("Segoe UI", 10, QFont.Bold))
            status_item.setData(Qt.UserRole, r)
            self.table_reports.setItem(idx, 5, status_item)

        self.table_reports.resizeColumnsToContents()
        self.table_reports.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        
        # Clear preview if no rows
        if len(reports) == 0:
            self.browser_preview.clear()
            self.btn_open_html.setEnabled(False)
            self.btn_delete_report.setEnabled(False)
            self.btn_fullscreen_preview.setEnabled(False)

    # ------------------------------------------------------------------
    # Selection change & Fullscreen slots
    # ------------------------------------------------------------------

    def _on_report_selection_changed(self):
        row = self.table_reports.currentRow()
        if row < 0:
            self.browser_preview.clear()
            self.btn_open_html.setEnabled(False)
            self.btn_delete_report.setEnabled(False)
            self.btn_fullscreen_preview.setEnabled(False)
            return

        r = self.table_reports.item(row, 0).data(Qt.UserRole)
        if not r:
            return

        is_virtual = r.get("is_virtual", False)
        html_path = r.get("html_path", "")
        
        self.btn_fullscreen_preview.setEnabled(True)
        self.btn_open_html.setEnabled(not is_virtual and bool(html_path) and os.path.exists(html_path))
        self.btn_delete_report.setEnabled(not is_virtual)

        # Display preview details
        if not is_virtual:
            if html_path and os.path.exists(html_path):
                try:
                    with open(html_path, "r", encoding="utf-8") as f:
                        html_content = f.read()
                    self.browser_preview.setHtml(html_content)
                except Exception as exc:
                    self.browser_preview.setHtml(f"<p style='color:red;'>Rapor dosyası okunamadı: {exc}</p>")
            else:
                self.browser_preview.setHtml(f"<pre>{json.dumps(r, indent=2, ensure_ascii=False)}</pre>")
        else:
            self.browser_preview.setHtml(self._render_virtual_report_html(r))

    @Slot()
    def _open_fullscreen_preview(self):
        row = self.table_reports.currentRow()
        if row < 0:
            return
        r = self.table_reports.item(row, 0).data(Qt.UserRole)
        if not r:
            return

        is_virtual = r.get("is_virtual", False)
        html_path = r.get("html_path", "")
        html_content = ""

        if not is_virtual and html_path and os.path.exists(html_path):
            try:
                with open(html_path, "r", encoding="utf-8") as f:
                    html_content = f.read()
            except Exception as exc:
                html_content = f"<p style='color:red;'>Rapor okunamadı: {exc}</p>"
        else:
            html_content = self._render_virtual_report_html(r)

        title = str(r.get("account_label") or r.get("account") or r.get("target") or r.get("type", "İşlem Raporu")).upper()
        dialog = ReportPreviewDialog(f"{title} Raporu", html_content, report_data=r, parent=self)
        dialog.exec()


    def _render_virtual_report_html(self, r: dict) -> str:
        r_type = str(r.get("type", "")).upper()
        ts = r.get("timestamp", "").replace("T", " ")[:19]
        acc_label = r.get("account_label", "Hesap")
        details = r.get("details", {})
        
        html = f"""
        <html>
        <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; padding:10px; color:#1e293b; line-height:1.5;">
            <div style="background-color:#eff6ff; padding:12px; border-radius:6px; border-left:4px solid #3b82f6; margin-bottom:15px;">
                <h3 style="margin:0; color:#1e40af;">🔒 Geçmiş İşlem Kaydı (Veritabanı Audit Log)</h3>
                <p style="margin:4px 0 0 0; font-size:11px; color:#60a5fa;">Bu işlem veritabanı loglarından yüklenmiştir, diskte fiziksel HTML dosyası bulunmamaktadır.</p>
            </div>
            
            <h2 style="color:#1e3a8a; border-bottom:2px solid #cbd5e1; padding-bottom:6px; margin-top:0;">{r_type} İşlem Raporu</h2>
            <table style="width:100%; border-collapse:collapse; margin-top:10px;">
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; width:150px; color:#64748b;">İşlem Zamanı:</td><td style="padding:6px;">{ts}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Hesap/Detay:</td><td style="padding:6px;">{acc_label}</td></tr>
        """
        
        if r_type == "SYNC":
            html += f"""
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Çekilen E-Posta:</td><td style="padding:6px; font-weight:bold; color:#10b981;">{details.get('fetched', 0)}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Mükerrer Silinen:</td><td style="padding:6px;">{details.get('duplicates', 0)}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">İşlem Süresi:</td><td style="padding:6px;">{details.get('duration', 0.0):.1f} saniye</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Hatalar:</td><td style="padding:6px; color:{'#ef4444' if details.get('errors', 0) > 0 else '#1e293b'}; font-weight:bold;">{details.get('errors', 0)}</td></tr>
            """
        elif r_type == "BACKUP":
            html += f"""
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Yedeklenen Mail:</td><td style="padding:6px; font-weight:bold; color:#10b981;">{details.get('mails_backed_up', 0)}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Hedef Depolama:</td><td style="padding:6px;">{details.get('bucket', 'Bulut')}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Veri Boyutu:</td><td style="padding:6px;">{self._fmt_size(details.get('size_bytes', 0))}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Durum:</td><td style="padding:6px; font-weight:bold; color:{'#10b981' if details.get('success', True) else '#ef4444'}">{'BAŞARILI' if details.get('success', True) else 'HATALI'}</td></tr>
            """
        elif r_type == "RESTORE":
            html += f"""
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Kurtarılan Mail:</td><td style="padding:6px; font-weight:bold; color:#10b981;">{details.get('mails_restored', 0)}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Kaynak Dosya:</td><td style="padding:6px;">{details.get('source', 'Bulut Yedek')}</td></tr>
                <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:6px; font-weight:bold; color:#64748b;">Hatalar:</td><td style="padding:6px; color:{'#ef4444' if details.get('errors', 0) > 0 else '#1e293b'}; font-weight:bold;">{details.get('errors', 0)}</td></tr>
            """
            
        html += """
            </table>
        </body>
        </html>
        """
        return html

    def _fmt_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @Slot()
    def _open_html_report(self):
        row = self.table_reports.currentRow()
        if row < 0:
            return
        r = self.table_reports.item(row, 0).data(Qt.UserRole)
        if r and r.get("html_path"):
            path = r["html_path"]
            if os.path.exists(path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))

    @Slot()
    def _delete_report(self):
        row = self.table_reports.currentRow()
        if row < 0:
            return
        r = self.table_reports.item(row, 0).data(Qt.UserRole)
        if not r or r.get("is_virtual"):
            return

        confirm = QMessageBox.question(
            self, "Rapor Sil", 
            "Seçili raporu diskten silmek istediğinize emin misiniz?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            try:
                # Delete JSON & HTML files
                if r.get("file_path") and os.path.exists(r["file_path"]):
                    os.unlink(r["file_path"])
                if r.get("html_path") and os.path.exists(r["html_path"]):
                    os.unlink(r["html_path"])
                self.log_output.append("Rapor başarıyla diskten silindi.")
                self._load_reports_history()
            except Exception as exc:
                QMessageBox.critical(self, "Hata", f"Rapor dosyası silinemedi: {exc}")

    # ------------------------------------------------------------------
    # Legacy/Stats tab methods
    # ------------------------------------------------------------------

    @Slot()
    def _gen_sync_report(self):
        acc_data = self.combo_account.currentData()
        if not acc_data:
            QMessageBox.warning(self, "Hesap Seçilmedi", "Lütfen önce bir hesap seçin.")
            return

        self.btn_sync_report.setEnabled(False)
        self.log_output.append(f"[{acc_data['label']}] Senkronizasyon başlatılıyor ve rapor oluşturuluyor...")
        
        def run_task():
            try:
                # Run sync first to get data
                report_dict = self.engine.sync_account(acc_data["id"])
                path = self._reporter.generate_sync_report(report_dict, output_format="both")
                
                # Emit update back to main thread
                self._reports_list.append(report_dict) # Keep lists updated
                
                def update_ui():
                    self.log_output.append(f"Sync raporu kaydedildi: {path}")
                    self.log_output.append(f"  Çekilen Mail: {report_dict.get('mails_fetched', 0)}, Hatalar: {report_dict.get('errors', 0)}")
                    self.btn_sync_report.setEnabled(True)
                    self._load_reports_history()
                    
                # Safe GUI update
                from PySide6.QtCore import QMetaObject
                QMetaObject.invokeMethod(self, "refresh_ui_after_task", Qt.QueuedConnection)
            except Exception as exc:
                def update_ui_error(e=exc):
                    self.log_output.append(f"HATA: {e}")
                    self.btn_sync_report.setEnabled(True)
                # Fallback to direct call on GUI thread
                update_ui_error()

        import threading
        threading.Thread(target=run_task, daemon=True).start()

    @Slot()
    def refresh_ui_after_task(self):
        self._load_reports_history()

    @Slot()
    def _gen_stats_report(self):
        try:
            stats = self.engine.get_stats()
            self.stats_table.setRowCount(len(stats))
            for i, (k, v) in enumerate(stats.items()):
                self.stats_table.setItem(i, 0, QTableWidgetItem(k.replace("_", " ").title()))
                self.stats_table.setItem(i, 1, QTableWidgetItem(str(v)))
            self.stats_table.resizeColumnsToContents()
            self.log_output.append("Veritabanı istatistikleri güncellendi.")
        except Exception as exc:
            self.log_output.append(f"HATA: {exc}")

    def refresh(self):
        self.combo_account.clear()
        self.combo_custom_account.clear()
        self.combo_custom_group.clear()
        self.group_filter_list.clear()

        # Add "Tümü" item
        item_all = QListWidgetItem("🌐 Tümü (Tüm Hesaplar)")
        item_all.setData(Qt.UserRole, "ALL")
        self.group_filter_list.addItem(item_all)
        self.group_filter_list.setCurrentItem(item_all)

        domains_set = set()

        try:
            accounts = self.engine.list_accounts()
            for acc in accounts:
                self.combo_account.addItem(f"{acc['label']} ({acc['email']})", acc)
                self.combo_custom_account.addItem(f"{acc['label']} ({acc['email']})", acc["id"])
                if "@" in acc.get("email", ""):
                    dom = acc["email"].split("@")[-1].strip().lower()
                    if dom:
                        domains_set.add(dom)

            # Load DISTINCT account groups
            with self.engine.db.get_conn() as conn:
                rows = conn.execute("SELECT DISTINCT account_group FROM accounts WHERE account_group IS NOT NULL AND account_group != ''").fetchall()
                for r in rows:
                    grp = r["account_group"]
                    self.combo_custom_group.addItem(grp)

                    item_grp = QListWidgetItem(f"📁 Grup: {grp}")
                    item_grp.setData(Qt.UserRole, f"GROUP:{grp}")
                    self.group_filter_list.addItem(item_grp)

            # Add domain items
            for dom in sorted(domains_set):
                item_dom = QListWidgetItem(f"@ Domain: {dom}")
                item_dom.setData(Qt.UserRole, f"DOMAIN:{dom}")
                self.group_filter_list.addItem(item_dom)

            self._load_reports_history()
            self._gen_stats_report()
        except Exception as exc:
            logger.error("Refresh error: %s", exc)

