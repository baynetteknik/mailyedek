"""
top_notification_banner.py — Modern dismissible top notification banner for background operations.
"""

from typing import Callable, List, Optional, Tuple
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QProgressBar, QWidget, QSizePolicy
)


class TopNotificationBanner(QFrame):
    """A sleek, non-blocking notification banner positioned at the top of the application window.

    Supports:
      - Progress bar (indeterminate or percentage)
      - Status styles: scanning, success, info, warning, error
      - Action buttons (e.g. 'Raporu Gör', 'Resmi Disk Yap')
      - Dismiss ('✕') button to close anytime without blocking the user
    """

    STYLE_CONFIGS = {
        "scanning": {
            "bg": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #eff6ff, stop:1 #dbeafe)",
            "border": "#93c5fd",
            "title_color": "#1e40af",
            "msg_color": "#1e3a8a",
            "icon": "💾",
        },
        "success": {
            "bg": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ecfdf5, stop:1 #d1fae5)",
            "border": "#6ee7b7",
            "title_color": "#065f46",
            "msg_color": "#047857",
            "icon": "✅",
        },
        "warning": {
            "bg": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #fffbeb, stop:1 #fef3c7)",
            "border": "#fcd34d",
            "title_color": "#92400e",
            "msg_color": "#b45309",
            "icon": "⚠️",
        },
        "info": {
            "bg": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f8fafc, stop:1 #f1f5f9)",
            "border": "#cbd5e1",
            "title_color": "#1e293b",
            "msg_color": "#334155",
            "icon": "ℹ️",
        },
        "error": {
            "bg": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #fff1f2, stop:1 #ffe4e6)",
            "border": "#fda4af",
            "title_color": "#9f1239",
            "msg_color": "#be123c",
            "icon": "❌",
        },
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_dismiss_timer = QTimer(self)
        self._auto_dismiss_timer.setSingleShot(True)
        self._auto_dismiss_timer.timeout.connect(self.dismiss)

        self._action_buttons: List[QPushButton] = []
        self._current_type = "info"

        self._setup_ui()
        self.hide()

    def _setup_ui(self):
        self.setObjectName("topNotificationBanner")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 10, 16, 10)
        root_layout.setSpacing(6)

        # Top content row: [Icon] [Title + Message] [Action Buttons] [Dismiss ✕]
        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(12)

        # Icon
        self.lbl_icon = QLabel("ℹ️")
        self.lbl_icon.setStyleSheet("font-size: 20px; background: transparent;")
        self.lbl_icon.setAlignment(Qt.AlignCenter)
        content_row.addWidget(self.lbl_icon)

        # Text container
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_title = QLabel("Bildirim")
        self.lbl_title.setStyleSheet("font-weight: 700; font-size: 13px; background: transparent;")
        text_layout.addWidget(self.lbl_title)

        self.lbl_message = QLabel("")
        self.lbl_message.setStyleSheet("font-size: 11px; background: transparent;")
        self.lbl_message.setWordWrap(True)
        text_layout.addWidget(self.lbl_message)

        content_row.addLayout(text_layout, stretch=1)

        # Actions container
        self.actions_layout = QHBoxLayout()
        self.actions_layout.setSpacing(8)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        content_row.addLayout(self.actions_layout)

        # Dismiss Button
        self.btn_dismiss = QPushButton("✕")
        self.btn_dismiss.setToolTip("Bu bildirimi kapat")
        self.btn_dismiss.setCursor(Qt.PointingHandCursor)
        self.btn_dismiss.setFixedSize(26, 26)
        self.btn_dismiss.setStyleSheet("""
            QPushButton {
                background: rgba(0, 0, 0, 0.06);
                color: #475569;
                border: 1px solid rgba(0, 0, 0, 0.1);
                border-radius: 13px;
                font-size: 13px;
                font-weight: bold;
                padding: 0;
            }
            QPushButton:hover {
                background: #ef4444;
                color: #ffffff;
                border-color: #dc2626;
            }
        """)
        self.btn_dismiss.clicked.connect(self.dismiss)
        content_row.addWidget(self.btn_dismiss)

        root_layout.addLayout(content_row)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(5)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: rgba(0, 0, 0, 0.08);
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #2563eb);
                border-radius: 2px;
            }
        """)
        root_layout.addWidget(self.progress_bar)

    def _apply_theme(self, status_type: str):
        self._current_type = status_type
        cfg = self.STYLE_CONFIGS.get(status_type, self.STYLE_CONFIGS["info"])
        self.lbl_icon.setText(cfg["icon"])
        self.lbl_title.setStyleSheet(f"font-weight: 700; font-size: 13px; color: {cfg['title_color']}; background: transparent;")
        self.lbl_message.setStyleSheet(f"font-size: 11px; color: {cfg['msg_color']}; background: transparent;")

        self.setStyleSheet(f"""
            QFrame#topNotificationBanner {{
                background: {cfg['bg']};
                border-bottom: 1.5px solid {cfg['border']};
                border-top: 1px solid {cfg['border']};
                border-left: none;
                border-right: none;
            }}
        """)

    def _clear_action_buttons(self):
        while self.actions_layout.count():
            item = self.actions_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._action_buttons.clear()

    def _add_action_button(self, label: str, callback: Callable, is_primary: bool = False):
        btn = QPushButton(label)
        btn.setCursor(Qt.PointingHandCursor)
        if is_primary:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2563eb;
                    color: #ffffff;
                    border: none;
                    border-radius: 5px;
                    padding: 5px 12px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover { background-color: #1d4ed8; }
            """)
        else:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #ffffff;
                    color: #1e293b;
                    border: 1px solid #cbd5e1;
                    border-radius: 5px;
                    padding: 5px 12px;
                    font-size: 11px;
                    font-weight: 600;
                }
                QPushButton:hover { background-color: #f1f5f9; }
            """)
        btn.clicked.connect(callback)
        self.actions_layout.addWidget(btn)
        self._action_buttons.append(btn)

    # ------------------------------------------------------------------
    # Public Display Methods
    # ------------------------------------------------------------------

    def show_progress(self, title: str, message: str, is_indeterminate: bool = True, progress: int = 0):
        """Display an active progress notification banner."""
        self._auto_dismiss_timer.stop()
        self._clear_action_buttons()
        self._apply_theme("scanning")

        self.lbl_title.setText(title)
        self.lbl_message.setText(message)

        self.progress_bar.setVisible(True)
        if is_indeterminate:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(progress)

        self.show()

    def update_progress(self, progress: int, message: Optional[str] = None):
        """Update progress bar value and optionally the message text."""
        if self.progress_bar.maximum() == 0 and progress > 0:
            self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(progress)
        if message:
            self.lbl_message.setText(message)

    def show_success(
        self,
        title: str,
        message: str,
        actions: Optional[List[Tuple[str, Callable]]] = None,
        auto_dismiss_seconds: Optional[int] = 10,
    ):
        """Display a success notification banner."""
        self._clear_action_buttons()
        self._apply_theme("success")
        self.lbl_title.setText(title)
        self.lbl_message.setText(message)
        self.progress_bar.setVisible(False)

        if actions:
            for idx, (lbl, cb) in enumerate(actions):
                self._add_action_button(lbl, cb, is_primary=(idx == 0))

        if auto_dismiss_seconds:
            self._auto_dismiss_timer.start(auto_dismiss_seconds * 1000)

        self.show()

    def show_warning(
        self,
        title: str,
        message: str,
        actions: Optional[List[Tuple[str, Callable]]] = None,
    ):
        """Display a warning notification banner."""
        self._auto_dismiss_timer.stop()
        self._clear_action_buttons()
        self._apply_theme("warning")
        self.lbl_title.setText(title)
        self.lbl_message.setText(message)
        self.progress_bar.setVisible(False)

        if actions:
            for idx, (lbl, cb) in enumerate(actions):
                self._add_action_button(lbl, cb, is_primary=(idx == 0))

        self.show()

    def show_info(
        self,
        title: str,
        message: str,
        actions: Optional[List[Tuple[str, Callable]]] = None,
        auto_dismiss_seconds: Optional[int] = None,
    ):
        """Display an informational notification banner."""
        self._clear_action_buttons()
        self._apply_theme("info")
        self.lbl_title.setText(title)
        self.lbl_message.setText(message)
        self.progress_bar.setVisible(False)

        if actions:
            for idx, (lbl, cb) in enumerate(actions):
                self._add_action_button(lbl, cb, is_primary=(idx == 0))

        if auto_dismiss_seconds:
            self._auto_dismiss_timer.start(auto_dismiss_seconds * 1000)

        self.show()

    def show_error(
        self,
        title: str,
        message: str,
        actions: Optional[List[Tuple[str, Callable]]] = None,
    ):
        """Display an error notification banner."""
        self._auto_dismiss_timer.stop()
        self._clear_action_buttons()
        self._apply_theme("error")
        self.lbl_title.setText(title)
        self.lbl_message.setText(message)
        self.progress_bar.setVisible(False)

        if actions:
            for idx, (lbl, cb) in enumerate(actions):
                self._add_action_button(lbl, cb, is_primary=(idx == 0))

        self.show()

    def dismiss(self):
        """Dismiss/hide the banner."""
        self._auto_dismiss_timer.stop()
        self.hide()
