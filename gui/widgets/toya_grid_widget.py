"""
toya_grid_widget.py — TOYA ERP Standartlarında Gelişmiş DBGrid, Sütun Filtreleme & Profil Entegrasyonu.

Özellikler:
- Her sütunun altında bağımsız anlık arama (Column Filter Row).
- Sütun genişliği, sırası, görünürlüğü ve satır yüksekliğini profil bazında saklama.
- Sütun taşıma (reorder) ve yeniden boyutlandırma senkronizasyonu.
- Sağ tık sütun yönetimi ve bağlam menüsü (Navy #1e3a8a tema).
- Excel'e aktarma ve hızlı düzenleme desteği.
"""

import logging
from typing import Dict, Any, List, Optional, Set

from PySide6.QtCore import Qt, Signal, Slot, QPoint, QEvent
from PySide6.QtGui import QFont, QColor, QAction, QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QPushButton, QLabel, QMenu, QFrame,
    QScrollBar, QMessageBox, QDialog, QCheckBox
)

logger = logging.getLogger(__name__)


class ColumnFilterBarWidget(QWidget):
    """
    Sütun başlıklarının altına yerleşen ve tablo sütunlarıyla senkronize
    olarak boyutlanan / kayan sütun filtre kutucukları çubuğu.
    """

    filter_changed = Signal(int, str)  # column_index, filter_text

    def __init__(self, table_widget: QTableWidget, parent=None):
        super().__init__(parent)
        self.table_widget = table_widget
        self.line_edits: Dict[int, QLineEdit] = {}
        self._init_ui()

    def _init_ui(self):
        self.setFixedHeight(28)
        self.setAttribute(Qt.WA_NoSystemBackground)

        # Connect synchronization signals
        header = self.table_widget.horizontalHeader()
        header.sectionResized.connect(self.adjust_positions)
        header.sectionMoved.connect(self.adjust_positions)
        
        scroll_bar = self.table_widget.horizontalScrollBar()
        scroll_bar.valueChanged.connect(self.adjust_positions)

        self.update_filters()

    def update_filters(self):
        """Re-creates or updates filter inputs matching current table columns."""
        col_count = self.table_widget.columnCount()
        
        # Remove extra inputs if column count decreased
        existing_cols = list(self.line_edits.keys())
        for c in existing_cols:
            if c >= col_count:
                self.line_edits[c].deleteLater()
                del self.line_edits[c]

        for col_idx in range(col_count):
            if col_idx not in self.line_edits:
                header_item = self.table_widget.horizontalHeaderItem(col_idx)
                col_name = header_item.text() if header_item else f"Kolon {col_idx+1}"
                
                edit = QLineEdit(self)
                edit.setPlaceholderText(f"🔍 {col_name} ara...")
                edit.setClearButtonEnabled(True)
                edit.setStyleSheet("""
                    QLineEdit {
                        border: 1px solid #cbd5e1;
                        border-radius: 4px;
                        padding: 2px 6px;
                        background-color: #ffffff;
                        color: #0f172a;
                        font-size: 11px;
                    }
                    QLineEdit:focus {
                        border: 1.5px solid #2563eb;
                        background-color: #ffffff;
                    }
                """)
                # Capture column index
                edit.textChanged.connect(lambda text, idx=col_idx: self._on_text_changed(idx, text))
                self.line_edits[col_idx] = edit

        self.adjust_positions()

    def _on_text_changed(self, col_idx: int, text: str):
        self.filter_changed.emit(col_idx, text.strip().lower())

    def adjust_positions(self):
        """Repositions and resizes QLineEdits to match the visual geometry of QHeaderView sections."""
        header = self.table_widget.horizontalHeader()
        if not header:
            return

        viewport_width = self.table_widget.viewport().width()

        for col_idx, line_edit in self.line_edits.items():
            if self.table_widget.isColumnHidden(col_idx):
                line_edit.hide()
                continue

            x_pos = header.sectionViewportPosition(col_idx)
            width = header.sectionSize(col_idx)

            if x_pos + width < 0 or x_pos > viewport_width:
                line_edit.hide()
            else:
                line_edit.show()
                line_edit.setGeometry(x_pos + 1, 2, max(10, width - 2), 24)

    def clear_all_filters(self):
        for edit in self.line_edits.values():
            edit.blockSignals(True)
            edit.clear()
            edit.blockSignals(False)


class ToyaHeaderView(QHeaderView):
    """TOYA ERP Professional DBGrid Header with column visibility context menu."""

    column_visibility_changed = Signal(int, bool)
    save_requested = Signal()
    reset_requested = Signal()

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setSectionsMovable(True)
        self.setSectionResizeMode(QHeaderView.Interactive)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_header_menu)
        
        self.setStyleSheet("""
            QHeaderView::section {
                background-color: #2563eb;
                color: #ffffff;
                font-weight: 700;
                font-size: 12px;
                border: 1px solid #1d4ed8;
                padding: 6px 10px;
                min-height: 36px;
                height: 36px;
            }
            QHeaderView::section:hover {
                background-color: #1e3a8a;
            }
        """)

    @Slot(QPoint)
    def _show_header_menu(self, pos: QPoint):
        table: QTableWidget = self.parentWidget()
        if not isinstance(table, QTableWidget):
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e3a8a;
                color: #ffffff;
                border: 1px solid #1e40af;
                border-radius: 8px;
                padding: 6px;
                font-weight: 600;
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 20px 6px 12px;
                border-radius: 4px;
                color: #ffffff;
            }
            QMenu::item:selected {
                background-color: #2563eb;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background-color: #3b82f6;
                margin: 4px 8px;
            }
        """)

        title_action = menu.addAction("👁️ Sütun Görünürlüğü (Kolon Aç/Kapa)")
        title_action.setEnabled(False)
        menu.addSeparator()

        for col in range(table.columnCount()):
            header_item = table.horizontalHeaderItem(col)
            label = header_item.text() if header_item else f"Kolon {col+1}"
            
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(not table.isColumnHidden(col))
            
            def _toggle(checked, c=col):
                table.setColumnHidden(c, not checked)
                self.column_visibility_changed.emit(c, checked)

            action.triggered.connect(_toggle)
            menu.addAction(action)

        menu.addSeparator()
        act_save = menu.addAction("💾 Görünüm Düzenini Kaydet")
        act_save.triggered.connect(self.save_requested.emit)
        
        act_reset = menu.addAction("🔄 Varsayılan Sütunlara Sıfırla")
        act_reset.triggered.connect(self.reset_requested.emit)

        menu.exec(self.mapToGlobal(pos))


class ToyaDbGrid(QWidget):
    """
    TOYA ERP Standard DBGrid Component.
    Enables instant multi-column filtering, persistent profile views,
    context menus, and responsive column resizing.
    """

    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.column_filters: Dict[int, str] = {}
        self.hidden_columns: Set[int] = set()
        self._filter_row_visible = True

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Main QTableWidget
        self.table = QTableWidget(self)
        self.header = ToyaHeaderView(Qt.Horizontal, self.table)
        self.header.column_visibility_changed.connect(self._on_column_visibility_changed)
        self.table.setHorizontalHeader(self.header)
        
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(88)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self.selection_changed.emit)

        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #f8fafc;
                gridline-color: #e2e8f0;
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                color: #0f172a;
                selection-background-color: #3b82f6;
                selection-color: #ffffff;
                font-size: 12px;
            }
            QTableWidget::item {
                border-bottom: 1px solid #f1f5f9;
            }
            QTableWidget::item:selected {
                background-color: #3b82f6;
                color: #ffffff;
            }
        """)

        # 2. Filter Bar Widget (Header under-row)
        self.filter_bar = ColumnFilterBarWidget(self.table, self)
        self.filter_bar.filter_changed.connect(self._on_filter_changed)

        layout.addWidget(self.filter_bar)
        layout.addWidget(self.table, stretch=1)

    def set_columns(self, labels: List[str], default_widths: Optional[List[int]] = None):
        self.table.setColumnCount(len(labels))
        self.table.setHorizontalHeaderLabels(labels)
        if default_widths:
            for i, w in enumerate(default_widths):
                if i < self.table.columnCount():
                    self.table.setColumnWidth(i, w)
        self.filter_bar.update_filters()

    def set_filter_row_visible(self, visible: bool):
        self._filter_row_visible = visible
        self.filter_bar.setVisible(visible)
        if not visible:
            self.clear_all_filters()

    def clear_all_filters(self):
        self.column_filters.clear()
        self.filter_bar.clear_all_filters()
        self._apply_row_filters()

    def _on_filter_changed(self, col_idx: int, text: str):
        if not text:
            self.column_filters.pop(col_idx, None)
        else:
            self.column_filters[col_idx] = text
        self._apply_row_filters()

    def _apply_row_filters(self):
        for row in range(self.table.rowCount()):
            match = True
            for col_idx, filter_text in self.column_filters.items():
                if self.table.isColumnHidden(col_idx):
                    continue
                
                # Check cell widget or table item
                cell_text = ""
                widget = self.table.cellWidget(row, col_idx)
                if widget:
                    labels = widget.findChildren(QLabel)
                    cell_text = " ".join(lbl.text() for lbl in labels).lower()
                else:
                    item = self.table.item(row, col_idx)
                    cell_text = item.text().lower() if item else ""
                
                if filter_text not in cell_text:
                    match = False
                    break
            self.table.setRowHidden(row, not match)

    def _on_column_visibility_changed(self, col_idx: int, visible: bool):
        if not visible:
            self.hidden_columns.add(col_idx)
        else:
            self.hidden_columns.discard(col_idx)
        self.filter_bar.adjust_positions()

    def get_state(self) -> Dict[str, Any]:
        """Returns current grid layout state for profile saving."""
        return {
            "hidden_columns": [c for c in range(self.table.columnCount()) if self.table.isColumnHidden(c)],
            "column_widths": [self.table.columnWidth(c) for c in range(self.table.columnCount())],
            "row_height": self.table.verticalHeader().defaultSectionSize(),
            "filter_row_visible": self._filter_row_visible
        }

    def apply_state(self, state: Dict[str, Any]):
        """Applies a saved profile layout state."""
        if not state:
            return
        
        hidden = state.get("hidden_columns", [])
        widths = state.get("column_widths", [])
        row_h = state.get("row_height", 88)
        filter_vis = state.get("filter_row_visible", True)

        for c in range(self.table.columnCount()):
            if c < len(widths) and widths[c] > 10:
                self.table.setColumnWidth(c, widths[c])
            self.table.setColumnHidden(c, c in hidden)

        self.table.verticalHeader().setDefaultSectionSize(row_h)
        self.set_filter_row_visible(filter_vis)
        self.filter_bar.adjust_positions()
