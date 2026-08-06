"""
report_preview_dialog.py — Full-screen report preview window with multi-format export options.
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QIcon, QFont, QDesktopServices, QTextDocument
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QTextBrowser, QMessageBox, QFileDialog, QSizePolicy
)

from core.reporter import ReportGenerator

logger = logging.getLogger(__name__)


class ReportPreviewDialog(QDialog):
    """Full-screen modal / popup dialog to preview reports with export options."""

    def __init__(self, report_title: str, html_content: str, report_data: Optional[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self.report_title = report_title
        self.html_content = html_content
        self.report_data = report_data or {}
        self.reporter = ReportGenerator()

        self.setWindowTitle(f"Rapor Önizleme — {report_title}")
        self.resize(1100, 750)
        self.setMinimumSize(800, 500)

        self._setup_ui()

    def showEvent(self, event):
        super().showEvent(event)
        # Open in full screen (maximized) as requested
        self.showMaximized()

    def _setup_ui(self):
        self.setStyleSheet("QDialog { background-color: #f8fafc; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header toolbar
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 8px 14px;
            }
        """)
        h_layout = QHBoxLayout(header_frame)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(10)

        # Title
        title_lbl = QLabel(f"📊 {self.report_title}")
        title_lbl.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title_lbl.setStyleSheet("color: #1e293b;")
        h_layout.addWidget(title_lbl)

        h_layout.addStretch()

        # Action Buttons
        btn_style_action = """
            QPushButton {
                background-color: #2563eb !important;
                color: #ffffff !important;
                font-weight: 700;
                font-size: 11px;
                border: none;
                border-radius: 6px;
                padding: 7px 14px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #1d4ed8 !important;
            }
        """

        self.btn_export_pdf = QPushButton("📕 PDF Olarak Kaydet")
        self.btn_export_pdf.setStyleSheet(btn_style_action)
        self.btn_export_pdf.setCursor(Qt.PointingHandCursor)
        self.btn_export_pdf.clicked.connect(self._on_export_pdf)
        h_layout.addWidget(self.btn_export_pdf)

        self.btn_export_html = QPushButton("🌐 HTML Olarak Kaydet")
        self.btn_export_html.setStyleSheet(btn_style_action)
        self.btn_export_html.setCursor(Qt.PointingHandCursor)
        self.btn_export_html.clicked.connect(self._on_export_html)
        h_layout.addWidget(self.btn_export_html)

        self.btn_export_excel = QPushButton("📊 Excel Olarak Kaydet")
        self.btn_export_excel.setStyleSheet(btn_style_action)
        self.btn_export_excel.setCursor(Qt.PointingHandCursor)
        self.btn_export_excel.clicked.connect(self._on_export_excel)
        h_layout.addWidget(self.btn_export_excel)

        self.btn_export_word = QPushButton("📝 Word Olarak Kaydet")
        self.btn_export_word.setStyleSheet(btn_style_action)
        self.btn_export_word.setCursor(Qt.PointingHandCursor)
        self.btn_export_word.clicked.connect(self._on_export_word)
        h_layout.addWidget(self.btn_export_word)

        self.btn_export_csv = QPushButton("📄 CSV Olarak Kaydet")
        self.btn_export_csv.setStyleSheet(btn_style_action)
        self.btn_export_csv.setCursor(Qt.PointingHandCursor)
        self.btn_export_csv.clicked.connect(self._on_export_csv)
        h_layout.addWidget(self.btn_export_csv)

        self.btn_print = QPushButton("🖨️ Yazdır")
        self.btn_print.setStyleSheet(btn_style_action.replace("#2563eb", "#475569").replace("#1d4ed8", "#334155"))
        self.btn_print.setCursor(Qt.PointingHandCursor)
        self.btn_print.clicked.connect(self._on_print)
        h_layout.addWidget(self.btn_print)

        self.btn_close = QPushButton("✕ Kapat")
        self.btn_close.setStyleSheet(btn_style_action.replace("#2563eb", "#ef4444").replace("#1d4ed8", "#dc2626"))
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.accept)
        h_layout.addWidget(self.btn_close)

        layout.addWidget(header_frame)

        # Body: Rich HTML viewer
        self.browser = QTextBrowser()
        self.browser.setStyleSheet("""
            QTextBrowser {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 16px;
            }
        """)
        self.browser.setHtml(self.html_content)
        layout.addWidget(self.browser, stretch=1)

    # ------------------------------------------------------------------
    # Export Slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_export_pdf(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "PDF Olarak Kaydet", f"{self._get_safe_filename()}.pdf", "PDF Dosyaları (*.pdf)"
        )
        if file_path:
            if self.reporter.export_pdf(self.html_content, Path(file_path)):
                QMessageBox.information(self, "Başarılı", f"Rapor PDF olarak kaydedildi:\n{file_path}")
            else:
                QMessageBox.critical(self, "Hata", "PDF dosyası oluşturulamadı.")

    @Slot()
    def _on_export_html(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "HTML Olarak Kaydet", f"{self._get_safe_filename()}.html", "HTML Dosyaları (*.html)"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(self.html_content)
                QMessageBox.information(self, "Başarılı", f"Rapor HTML olarak kaydedildi:\n{file_path}")
            except Exception as exc:
                QMessageBox.critical(self, "Hata", f"HTML dosyası yazılamadı: {exc}")

    @Slot()
    def _on_export_excel(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Excel Olarak Kaydet", f"{self._get_safe_filename()}.csv", "Excel CSV Dosyaları (*.csv)"
        )
        if file_path:
            if self.reporter.export_excel(self.report_data, Path(file_path)):
                QMessageBox.information(self, "Başarılı", f"Rapor Excel/CSV olarak kaydedildi:\n{file_path}")
            else:
                QMessageBox.critical(self, "Hata", "Excel dosyası kaydedilemedi.")

    @Slot()
    def _on_export_word(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Word Olarak Kaydet", f"{self._get_safe_filename()}.doc", "Word Belgeleri (*.doc *.docx)"
        )
        if file_path:
            if self.reporter.export_word(self.html_content, Path(file_path)):
                QMessageBox.information(self, "Başarılı", f"Rapor Word belgesi olarak kaydedildi:\n{file_path}")
            else:
                QMessageBox.critical(self, "Hata", "Word dosyası oluşturulamadı.")

    @Slot()
    def _on_export_csv(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "CSV Olarak Kaydet", f"{self._get_safe_filename()}.csv", "CSV Dosyaları (*.csv)"
        )
        if file_path:
            if self.reporter.export_csv(self.report_data, Path(file_path)):
                QMessageBox.information(self, "Başarılı", f"Rapor CSV olarak kaydedildi:\n{file_path}")
            else:
                QMessageBox.critical(self, "Hata", "CSV dosyası oluşturulamadı.")

    @Slot()
    def _on_print(self):
        try:
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter
            printer = QPrinter()
            dialog = QPrintDialog(printer, self)
            if dialog.exec() == QDialog.Accepted:
                self.browser.print_(printer)
        except Exception as exc:
            # Fallback if QtPrintSupport module is not loaded
            QMessageBox.warning(self, "Yazdırma", f"Yazdırma başlatılamadı: {exc}")

    def _get_safe_filename(self) -> str:
        import re
        safe = re.sub(r'[\/:*?"<>|]', '_', self.report_title).strip().replace(" ", "_")
        return safe.lower() or "rapor"
