"""
login_dialog.py — Enterprise Authentication & Role Login Dialog.
"""

import logging
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QMessageBox,
)

from core.mail_engine import MailEngine
from domain.entities import User

logger = logging.getLogger(__name__)


class LoginDialog(QDialog):
    """Secure login dialog with modern dark/light card aesthetics and RBAC verification."""

    def __init__(self, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.authenticated_user: Optional[User] = None

        self.setWindowTitle("Sistem Girişi — Kurumsal Yedekleme")
        self.setFixedSize(440, 480)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #f1f5f9;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            QFrame#card {
                background-color: #ffffff;
                border-radius: 12px;
                border: 1px solid #e2e8f0;
            }
            QLineEdit {
                background-color: #f8fafc;
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 10px 14px;
                font-size: 13px;
                color: #0f172a;
            }
            QLineEdit:focus {
                border: 1.5px solid #2563eb;
                background-color: #ffffff;
            }
            QPushButton#loginBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #1d4ed8);
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 12px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton#loginBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d4ed8, stop:1 #1e40af);
            }
            QPushButton#loginBtn:pressed {
                background-color: #1e3a8a;
            }
            QPushButton#cancelBtn {
                background-color: transparent;
                color: #64748b;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 12px;
            }
            QPushButton#cancelBtn:hover {
                background-color: #f8fafc;
                color: #334155;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(0)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 24)
        card_layout.setSpacing(14)

        # Header with branding
        icon_label = QLabel("🛡️")
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet("font-size: 38px; margin-bottom: 2px;")
        card_layout.addWidget(icon_label)

        title = QLabel("Yedekleme & Arşiv Sistemi")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #0f172a; margin-bottom: 2px;")
        card_layout.addWidget(title)

        subtitle = QLabel("Lütfen kullanıcı kimliğiniz ile giriş yapın")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 12px; color: #64748b; margin-bottom: 12px;")
        card_layout.addWidget(subtitle)

        # Form fields
        lbl_user = QLabel("Kullanıcı Adı:")
        lbl_user.setStyleSheet("font-size: 12px; font-weight: 600; color: #334155;")
        card_layout.addWidget(lbl_user)

        self.txt_username = QLineEdit()
        self.txt_username.setPlaceholderText("Kullanıcı adınızı girin (ör. admin)")
        self.txt_username.setText("admin")
        card_layout.addWidget(self.txt_username)

        lbl_pass = QLabel("Şifre:")
        lbl_pass.setStyleSheet("font-size: 12px; font-weight: 600; color: #334155;")
        card_layout.addWidget(lbl_pass)

        self.txt_password = QLineEdit()
        self.txt_password.setEchoMode(QLineEdit.Password)
        self.txt_password.setPlaceholderText("Şifrenizi girin")
        self.txt_password.returnPressed.connect(self._handle_login)
        card_layout.addWidget(self.txt_password)

        # Error notification label
        self.lbl_error = QLabel("")
        self.lbl_error.setAlignment(Qt.AlignCenter)
        self.lbl_error.setStyleSheet("color: #dc2626; font-size: 12px; font-weight: 500;")
        self.lbl_error.setVisible(False)
        card_layout.addWidget(self.lbl_error)

        card_layout.addSpacing(6)

        # Login button
        self.btn_login = QPushButton("Giriş Yap")
        self.btn_login.setObjectName("loginBtn")
        self.btn_login.setCursor(Qt.PointingHandCursor)
        self.btn_login.clicked.connect(self._handle_login)
        card_layout.addWidget(self.btn_login)

        # Cancel / Exit button
        btn_layout = QHBoxLayout()
        btn_layout.setAlignment(Qt.AlignCenter)
        self.btn_cancel = QPushButton("Çıkış")
        self.btn_cancel.setObjectName("cancelBtn")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        card_layout.addLayout(btn_layout)

        layout.addWidget(card)

        # Focus password
        self.txt_password.setFocus()

    def _handle_login(self):
        username = self.txt_username.text().strip()
        password = self.txt_password.text()

        if not username:
            self._show_error("Kullanıcı adı boş bırakılamaz.")
            self.txt_username.setFocus()
            return

        if not password:
            self._show_error("Lütfen şifrenizi girin.")
            self.txt_password.setFocus()
            return

        success, user, message = self.engine.login(username, password)
        if success and user:
            self.authenticated_user = user
            logger.info("User logged in successfully: %s (Role: %s)", user.username, user.role)
            self.accept()
        else:
            self._show_error(message or "Hatalı kullanıcı adı veya şifre.")
            self.txt_password.selectAll()
            self.txt_password.setFocus()

    def _show_error(self, message: str):
        self.lbl_error.setText(message)
        self.lbl_error.setVisible(True)
