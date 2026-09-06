"""
numeric_stepper.py — Custom ergonomic numeric stepper component.
Features:
- Physical [-] and [+] push buttons for quick increment / decrement
- Direct keyboard editing with strict digit-only validation (QIntValidator)
- Fixed right-side suffix label (e.g. "adet", "gün") positioned beside the input
- Signal emission on value changes
"""

from typing import Optional
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QIntValidator, QFont
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLineEdit, QLabel, QFrame
)


class NumericStepperWidget(QWidget):
    """
    Ergonomic numeric stepper widget.
    Layout: [ - ] [  10  ] [ + ]  adet
    """
    valueChanged = Signal(int)

    def __init__(
        self,
        value: int = 10,
        minimum: int = 1,
        maximum: int = 9999,
        suffix: str = "adet",
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum
        self._step = 1
        self._value = max(self._minimum, min(self._maximum, value))
        self._suffix_text = suffix

        self._setup_ui()
        self.setValue(self._value)

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(4)
        main_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Container frame for buttons + edit box
        self.box_frame = QFrame(self)
        self.box_frame.setObjectName("stepperFrame")
        self.box_frame.setStyleSheet("""
            QFrame#stepperFrame {
                background-color: #ffffff !important;
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
            }
            QFrame#stepperFrame:hover {
                border-color: #94a3b8;
            }
            QFrame#stepperFrame:focus-within {
                border-color: #2563eb;
            }
        """)

        frame_layout = QHBoxLayout(self.box_frame)
        frame_layout.setContentsMargins(2, 2, 2, 2)
        frame_layout.setSpacing(2)

        # Minus button [-]
        self.btn_minus = QPushButton("－", self.box_frame)
        self.btn_minus.setToolTip("Değeri azalt (-1)")
        self.btn_minus.setFixedSize(26, 26)
        self.btn_minus.setCursor(Qt.PointingHandCursor)
        self.btn_minus.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #334155;
                font-weight: bold;
                font-size: 14px;
                border: 1px solid #e2e8f0;
                border-radius: 4px;
                padding: 0;
            }
            QPushButton:hover {
                background-color: #e2e8f0;
                color: #0f172a;
            }
            QPushButton:pressed {
                background-color: #cbd5e1;
            }
            QPushButton:disabled {
                background-color: #f8fafc;
                color: #cbd5e1;
                border-color: #f1f5f9;
            }
        """)
        self.btn_minus.clicked.connect(self._on_minus_clicked)
        frame_layout.addWidget(self.btn_minus)

        # Digits-only LineEdit [ 10 ]
        self.line_edit = QLineEdit(self.box_frame)
        self.line_edit.setAlignment(Qt.AlignCenter)
        self.line_edit.setFixedWidth(52)
        self.line_edit.setFixedHeight(26)
        self.line_edit.setStyleSheet("""
            QLineEdit {
                background: transparent;
                border: none;
                color: #0f172a;
                font-weight: bold;
                font-size: 13px;
                font-family: 'Consolas', 'Segoe UI', monospace;
                padding: 0 4px;
            }
            QLineEdit:focus {
                background-color: #f8fafc;
                border-radius: 3px;
            }
        """)
        # Strict integer validator
        self._validator = QIntValidator(self._minimum, self._maximum, self.line_edit)
        self.line_edit.setValidator(self._validator)
        self.line_edit.textEdited.connect(self._on_text_edited)
        self.line_edit.editingFinished.connect(self._on_editing_finished)
        frame_layout.addWidget(self.line_edit)

        # Plus button [+]
        self.btn_plus = QPushButton("＋", self.box_frame)
        self.btn_plus.setToolTip("Değeri artır (+1)")
        self.btn_plus.setFixedSize(26, 26)
        self.btn_plus.setCursor(Qt.PointingHandCursor)
        self.btn_plus.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #334155;
                font-weight: bold;
                font-size: 14px;
                border: 1px solid #e2e8f0;
                border-radius: 4px;
                padding: 0;
            }
            QPushButton:hover {
                background-color: #e2e8f0;
                color: #0f172a;
            }
            QPushButton:pressed {
                background-color: #cbd5e1;
            }
            QPushButton:disabled {
                background-color: #f8fafc;
                color: #cbd5e1;
                border-color: #f1f5f9;
            }
        """)
        self.btn_plus.clicked.connect(self._on_plus_clicked)
        frame_layout.addWidget(self.btn_plus)

        main_layout.addWidget(self.box_frame)

        # Fixed Suffix Label (e.g. "adet")
        self.lbl_suffix = QLabel(self._suffix_text, self)
        self.lbl_suffix.setStyleSheet("""
            QLabel {
                color: #475569;
                font-weight: 600;
                font-size: 12px;
                padding-left: 3px;
            }
        """)
        main_layout.addWidget(self.lbl_suffix)

    # ------------------------------------------------------------------
    # Value getters / setters
    # ------------------------------------------------------------------

    def value(self) -> int:
        return self._value

    @Slot(int)
    def setValue(self, val: int):
        clamped = max(self._minimum, min(self._maximum, int(val)))
        if self._value != clamped or self.line_edit.text() != str(clamped):
            self._value = clamped
            self.line_edit.setText(str(self._value))
            self._update_button_states()
            self.valueChanged.emit(self._value)

    def setRange(self, minimum: int, maximum: int):
        self._minimum = minimum
        self._maximum = maximum
        self._validator.setBottom(minimum)
        self._validator.setTop(maximum)
        self.setValue(self._value)

    def setSuffix(self, suffix: str):
        self._suffix_text = suffix
        self.lbl_suffix.setText(suffix)

    def suffix(self) -> str:
        return self._suffix_text

    def setSingleStep(self, step: int):
        self._step = max(1, step)

    # ------------------------------------------------------------------
    # Internal Handlers
    # ------------------------------------------------------------------

    def _update_button_states(self):
        self.btn_minus.setEnabled(self._value > self._minimum and self.isEnabled())
        self.btn_plus.setEnabled(self._value < self._maximum and self.isEnabled())

    @Slot()
    def _on_minus_clicked(self):
        new_val = max(self._minimum, self._value - self._step)
        self.setValue(new_val)

    @Slot()
    def _on_plus_clicked(self):
        new_val = min(self._maximum, self._value + self._step)
        self.setValue(new_val)

    @Slot(str)
    def _on_text_edited(self, text: str):
        if not text.strip():
            return
        try:
            val = int(text.strip())
            if self._minimum <= val <= self._maximum:
                self._value = val
                self._update_button_states()
                self.valueChanged.emit(self._value)
        except ValueError:
            pass

    @Slot()
    def _on_editing_finished(self):
        text = self.line_edit.text().strip()
        try:
            val = int(text) if text else self._minimum
            self.setValue(val)
        except ValueError:
            self.setValue(self._value)

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self.line_edit.setEnabled(enabled)
        self.box_frame.setEnabled(enabled)
        self.lbl_suffix.setEnabled(enabled)
        self._update_button_states()
