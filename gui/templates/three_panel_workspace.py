"""
three_panel_workspace.py — Reusable Three-Panel Workspace Template.

Layout Architecture:
- Left Panel (Sol Panel): Filtering & Grouping controls (Domain, Group, Search).
- Center Panel (Orta Panel): Main Work Area / Data Grid.
- Right Panel (Sağ Panel): Operation / Action controls, Stats, and Logs.
"""

from typing import Optional
from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QFrame,
    QLabel, QPushButton, QGroupBox, QScrollArea, QSizePolicy
)


class ThreePanelWorkspaceTemplate(QWidget):
    """
    Reusable 3-panel workspace layout container.
    Provides collapsible/resizable left, center, and right sections via QSplitter.
    """

    panel_toggled = Signal(str, bool)  # panel_name ('left'|'right'), is_visible

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.workspace_title = title

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Header Title Bar (if title provided)
        if self.workspace_title:
            self.header_frame = QFrame()
            self.header_frame.setStyleSheet("""
                QFrame {
                    background-color: #ffffff;
                    border: 1px solid #cbd5e1;
                    border-radius: 8px;
                    padding: 4px 10px;
                }
            """)
            header_layout = QHBoxLayout(self.header_frame)
            header_layout.setContentsMargins(10, 6, 10, 6)

            self.lbl_title = QLabel(self.workspace_title)
            self.lbl_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #1e293b; border: none; background: transparent;")
            header_layout.addWidget(self.lbl_title)

            header_layout.addStretch()

            # Toggle Buttons for Left / Right Sidebars
            self.btn_toggle_left = QPushButton("◄ Sol Panel")
            self.btn_toggle_left.setToolTip("Sol filtre panelini göster/gizle")
            self.btn_toggle_left.setCheckable(True)
            self.btn_toggle_left.setChecked(True)
            self.btn_toggle_left.setStyleSheet(self._btn_toggle_style())
            self.btn_toggle_left.clicked.connect(self._toggle_left)

            self.btn_toggle_right = QPushButton("Sağ Panel ►")
            self.btn_toggle_right.setToolTip("Sağ işlem panelini göster/gizle")
            self.btn_toggle_right.setCheckable(True)
            self.btn_toggle_right.setChecked(True)
            self.btn_toggle_right.setStyleSheet(self._btn_toggle_style())
            self.btn_toggle_right.clicked.connect(self._toggle_right)

            header_layout.addWidget(self.btn_toggle_left)
            header_layout.addWidget(self.btn_toggle_right)

            main_layout.addWidget(self.header_frame)

        # Main Horizontal Splitter
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(6)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #cbd5e1;
                border-radius: 3px;
            }
            QSplitter::handle:hover {
                background-color: #4361ee;
            }
        """)

        # -------------------------------------------------------------------
        # 1. Left Panel Container
        # -------------------------------------------------------------------
        self.left_widget = QWidget()
        self.left_layout = QVBoxLayout(self.left_widget)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(8)

        self.left_group = QGroupBox("🔍 Filtreleme ve Gruplama")
        self.left_group.setStyleSheet(self._group_box_style())
        self.left_inner_layout = QVBoxLayout(self.left_group)
        self.left_inner_layout.setContentsMargins(10, 14, 10, 10)
        self.left_inner_layout.setSpacing(10)
        self.left_layout.addWidget(self.left_group)

        # -------------------------------------------------------------------
        # 2. Center Panel Container
        # -------------------------------------------------------------------
        self.center_widget = QWidget()
        self.center_layout = QVBoxLayout(self.center_widget)
        self.center_layout.setContentsMargins(0, 0, 0, 0)
        self.center_layout.setSpacing(8)

        # -------------------------------------------------------------------
        # 3. Right Panel Container
        # -------------------------------------------------------------------
        self.right_widget = QWidget()
        self.right_layout = QVBoxLayout(self.right_widget)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(8)

        self.right_group = QGroupBox("⚡ İşlem & Aksiyon Paneli")
        self.right_group.setStyleSheet(self._group_box_style())
        self.right_inner_layout = QVBoxLayout(self.right_group)
        self.right_inner_layout.setContentsMargins(10, 14, 10, 10)
        self.right_inner_layout.setSpacing(10)
        self.right_layout.addWidget(self.right_group)

        # Add to Splitter
        self.splitter.addWidget(self.left_widget)
        self.splitter.addWidget(self.center_widget)
        self.splitter.addWidget(self.right_widget)

        # Initial ratio: 20% left, 55% center, 25% right
        self.splitter.setSizes([260, 750, 340])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)

        main_layout.addWidget(self.splitter, stretch=1)

    def _btn_toggle_style(self) -> str:
        return """
            QPushButton {
                background-color: #f1f5f9;
                color: #2563eb;
                font-weight: bold;
                font-size: 11px;
                border: 1px solid #93c5fd;
                border-radius: 5px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background-color: #dbeafe;
                color: #1d4ed8;
            }
            QPushButton:checked {
                background-color: #2563eb;
                color: #ffffff;
                border: 1px solid #1d4ed8;
            }
        """

    def _group_box_style(self) -> str:
        return """
            QGroupBox {
                color: #0f172a;
                font-weight: bold;
                font-size: 12px;
                border: 1.5px solid #2563eb;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 14px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 3px 10px;
                background-color: #2563eb;
                color: #ffffff;
                font-weight: bold;
                border-radius: 4px;
            }
        """

    @Slot()
    def _toggle_left(self):
        visible = self.btn_toggle_left.isChecked()
        self.left_widget.setVisible(visible)
        self.panel_toggled.emit("left", visible)

    @Slot()
    def _toggle_right(self):
        visible = self.btn_toggle_right.isChecked()
        self.right_widget.setVisible(visible)
        self.panel_toggled.emit("right", visible)

    def save_splitter_state(self, settings, key: str):
        try:
            state = [int(s) for s in self.splitter.sizes()]
            settings.set(f"splitter_{key}", state)
            settings.save()
        except Exception:
            pass

    def load_splitter_state(self, settings, key: str):
        try:
            state = settings.get(f"splitter_{key}", None)
            if state and isinstance(state, list) and len(state) == 3:
                self.splitter.setSizes(state)
        except Exception:
            pass
