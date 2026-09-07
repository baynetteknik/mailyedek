"""
delete_confirm_dialog.py — Royal Blue Standard Deletion & Action Confirmation Dialog.
High-contrast light theme, prominent Royal Blue Header Banner, task details badge,
and clear action buttons (Evet, Sil / İptal).
"""

from typing import Optional, Dict, Any
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QFont
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGroupBox
)


class DeleteConfirmDialog(QDialog):
    """
    Standard Royal Blue Deletion Confirmation Dialog.
    Replaces standard unreadable OS message boxes with a styled, high-contrast modal.
    """

    def __init__(
        self,
        title: str = "Silme Onayı",
        item_name: str = "",
        item_type: str = "Yedekleme Görevi",
        target_info: str = "",
        warning_message: str = "Bu işlem seçili kaydı sistemden kalıcı olarak kaldıracaktır. Bu işlem geri alınamaz.",
        details: Optional[Dict[str, str]] = None,
        confirm_button_text: str = "🗑️ Evet, Sil",
        cancel_button_text: str = "✕ İptal",
        banner_title: str = "Kayıt / Görev Silme Onayı",
        banner_subtitle: str = "Lütfen silmek istediğiniz öğeyi ve işlem detaylarını onaylayın",
        parent=None
    ):
        super().__init__(parent)
        self.item_name = item_name
        self.item_type = item_type
        self.target_info = target_info
        self.warning_message = warning_message
        self.details = details or {}
        self.confirm_button_text = confirm_button_text
        self.cancel_button_text = cancel_button_text
        self.banner_title = banner_title
        self.banner_subtitle = banner_subtitle

        self.setWindowTitle(title)
        self.setMinimumWidth(500)
        self.setMaximumWidth(580)
        self._setup_theme()
        self._setup_ui()

    def _setup_theme(self):
        # Force explicit light palette to avoid dark OS inheritance issues
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor("#f8fafc"))
        pal.setColor(QPalette.WindowText, QColor("#0f172a"))
        pal.setColor(QPalette.Base, QColor("#ffffff"))
        pal.setColor(QPalette.AlternateBase, QColor("#f1f5f9"))
        pal.setColor(QPalette.Text, QColor("#0f172a"))
        pal.setColor(QPalette.Button, QColor("#ffffff"))
        pal.setColor(QPalette.ButtonText, QColor("#0f172a"))
        self.setPalette(pal)
        self.setAutoFillBackground(True)

        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
                color: #0f172a;
            }
            QWidget {
                color: #0f172a;
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }
            QLabel {
                color: #0f172a;
                font-size: 12px;
                background: transparent;
            }
        """)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 18)
        main_layout.setSpacing(14)

        # -------------------------------------------------------------
        # 1. Royal Blue Header Banner
        # -------------------------------------------------------------
        header_banner = QFrame()
        header_banner.setStyleSheet("""
            QFrame {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1e3a8a, stop:1 #2563eb
                );
                border-radius: 8px;
                border: none;
            }
        """)
        h_layout = QHBoxLayout(header_banner)
        h_layout.setContentsMargins(14, 12, 14, 12)
        h_layout.setSpacing(12)

        lbl_icon = QLabel("🗑️")
        lbl_icon.setStyleSheet("font-size: 26px; background: transparent; color: #ffffff;")
        h_layout.addWidget(lbl_icon)

        v_text = QVBoxLayout()
        v_text.setSpacing(3)
        lbl_title = QLabel(self.banner_title)
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff; background: transparent;")
        lbl_sub = QLabel(self.banner_subtitle)
        lbl_sub.setStyleSheet("font-size: 11.5px; color: #dbeafe; background: transparent;")
        v_text.addWidget(lbl_title)
        v_text.addWidget(lbl_sub)
        h_layout.addLayout(v_text, stretch=1)
        main_layout.addWidget(header_banner)

        # -------------------------------------------------------------
        # 2. Item Information Card
        # -------------------------------------------------------------
        info_card = QFrame()
        info_card.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(12, 10, 12, 10)
        info_layout.setSpacing(8)

        # Name row with badge
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        lbl_name_tag = QLabel("Silinecek Öğe:")
        lbl_name_tag.setStyleSheet("font-weight: 600; color: #475569; font-size: 12px;")
        name_row.addWidget(lbl_name_tag)

        lbl_name_val = QLabel(self.item_name or "Belirtilmedi")
        lbl_name_val.setStyleSheet("font-weight: 700; color: #0f172a; font-size: 13px;")
        lbl_name_val.setWordWrap(True)
        name_row.addWidget(lbl_name_val, stretch=1)

        if self.item_type:
            lbl_type_badge = QLabel(f" {self.item_type} ")
            lbl_type_badge.setStyleSheet("""
                background-color: #e0e7ff;
                color: #1e3a8a;
                font-size: 11px;
                font-weight: 700;
                padding: 3px 8px;
                border-radius: 4px;
                border: 1px solid #c7d2fe;
            """)
            name_row.addWidget(lbl_type_badge)

        info_layout.addLayout(name_row)

        # Target info row if present
        if self.target_info:
            target_row = QHBoxLayout()
            target_row.setSpacing(8)
            lbl_target_tag = QLabel("Hedef / Konum:")
            lbl_target_tag.setStyleSheet("font-weight: 600; color: #475569; font-size: 11.5px;")
            target_row.addWidget(lbl_target_tag)

            lbl_target_val = QLabel(self.target_info)
            lbl_target_val.setStyleSheet("color: #334155; font-size: 11.5px;")
            lbl_target_val.setWordWrap(True)
            target_row.addWidget(lbl_target_val, stretch=1)
            info_layout.addLayout(target_row)

        # Additional details
        for key, val in self.details.items():
            d_row = QHBoxLayout()
            d_row.setSpacing(8)
            lbl_k = QLabel(f"{key}:")
            lbl_k.setStyleSheet("font-weight: 600; color: #475569; font-size: 11.5px;")
            d_row.addWidget(lbl_k)

            lbl_v = QLabel(str(val))
            lbl_v.setStyleSheet("color: #334155; font-size: 11.5px;")
            lbl_v.setWordWrap(True)
            d_row.addWidget(lbl_v, stretch=1)
            info_layout.addLayout(d_row)

        main_layout.addWidget(info_card)

        # -------------------------------------------------------------
        # 3. Warning Callout Box
        # -------------------------------------------------------------
        warn_card = QFrame()
        warn_card.setStyleSheet("""
            QFrame {
                background-color: #fef2f2;
                border: 1.5px solid #fecaca;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        warn_layout = QHBoxLayout(warn_card)
        warn_layout.setContentsMargins(10, 8, 10, 8)
        warn_layout.setSpacing(10)

        lbl_warn_icon = QLabel("⚠️")
        lbl_warn_icon.setStyleSheet("font-size: 20px; background: transparent; color: #b91c1c;")
        warn_layout.addWidget(lbl_warn_icon)

        lbl_warn_text = QLabel(self.warning_message)
        lbl_warn_text.setStyleSheet("color: #991b1b; font-size: 12px; font-weight: 600; background: transparent;")
        lbl_warn_text.setWordWrap(True)
        warn_layout.addWidget(lbl_warn_text, stretch=1)

        main_layout.addWidget(warn_card)

        # -------------------------------------------------------------
        # 4. Action Buttons (Evet, Sil / İptal)
        # -------------------------------------------------------------
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 8, 0, 0)
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        btn_cancel = QPushButton(self.cancel_button_text)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setMinimumWidth(100)
        btn_cancel.setMinimumHeight(34)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #334155;
                font-weight: 600;
                font-size: 12px;
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background-color: #f1f5f9;
                border-color: #94a3b8;
                color: #0f172a;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_confirm = QPushButton(self.confirm_button_text)
        btn_confirm.setCursor(Qt.PointingHandCursor)
        btn_confirm.setMinimumWidth(115)
        btn_confirm.setMinimumHeight(34)
        btn_confirm.setStyleSheet("""
            QPushButton {
                background-color: #ef4444;
                color: #ffffff;
                font-weight: 700;
                font-size: 12px;
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
            }
            QPushButton:hover {
                background-color: #dc2626;
            }
        """)
        btn_confirm.clicked.connect(self.accept)
        btn_confirm.setDefault(True)
        btn_layout.addWidget(btn_confirm)

        main_layout.addLayout(btn_layout)

    @classmethod
    def confirm_deletion(
        cls,
        parent=None,
        title: str = "Silme Onayı",
        item_name: str = "",
        item_type: str = "Yedekleme Görevi",
        target_info: str = "",
        warning_message: str = "Bu işlem seçili kaydı sistemden kalıcı olarak kaldıracaktır. Bu işlem geri alınamaz.",
        details: Optional[Dict[str, str]] = None,
        confirm_button_text: str = "🗑️ Evet, Sil",
        cancel_button_text: str = "✕ İptal",
        banner_title: str = "Kayıt / Görev Silme Onayı",
        banner_subtitle: str = "Lütfen silmek istediğiniz öğeyi ve işlem detaylarını onaylayın"
    ) -> bool:
        """Helper static method to show the Royal Blue deletion dialog and return True if accepted."""
        dialog = cls(
            title=title,
            item_name=item_name,
            item_type=item_type,
            target_info=target_info,
            warning_message=warning_message,
            details=details,
            confirm_button_text=confirm_button_text,
            cancel_button_text=cancel_button_text,
            banner_title=banner_title,
            banner_subtitle=banner_subtitle,
            parent=parent
        )
        return dialog.exec() == QDialog.Accepted
