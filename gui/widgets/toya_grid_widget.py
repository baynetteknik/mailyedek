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
    QScrollBar, QMessageBox, QDialog, QCheckBox, QComboBox
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
        header.geometriesChanged.connect(self.adjust_positions)
        
        scroll_bar = self.table_widget.horizontalScrollBar()
        scroll_bar.valueChanged.connect(self.adjust_positions)

        # Event filters on table, viewport and header to catch resize and layout events
        self.table_widget.installEventFilter(self)
        if self.table_widget.viewport():
            self.table_widget.viewport().installEventFilter(self)
        if header:
            header.installEventFilter(self)

        self.update_filters()

    def eventFilter(self, obj, event):
        try:
            if not self.table_widget:
                return super().eventFilter(obj, event)
            if obj in (self.table_widget, self.table_widget.viewport(), self.table_widget.horizontalHeader()):
                if event.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest, QEvent.Paint):
                    self.adjust_positions()
        except RuntimeError:
            pass
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adjust_positions()

    def showEvent(self, event):
        super().showEvent(event)
        self.adjust_positions()

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

        viewport = self.table_widget.viewport()
        viewport_width = viewport.width() if viewport and viewport.width() > 0 else self.width()

        for col_idx, line_edit in self.line_edits.items():
            if self.table_widget.isColumnHidden(col_idx):
                line_edit.hide()
                continue

            x_pos = header.sectionViewportPosition(col_idx)
            width = header.sectionSize(col_idx)

            if width <= 0:
                width = self.table_widget.columnWidth(col_idx)
                if width <= 0:
                    width = 80

            if viewport_width > 0 and (x_pos + width < 0 or x_pos >= viewport_width):
                line_edit.hide()
            else:
                line_edit.show()
                line_edit.setGeometry(x_pos + 1, 2, max(10, width - 2), 24)

    def clear_all_filters(self):
        for col_idx, edit in self.line_edits.items():
            edit.blockSignals(True)
            edit.clear()
            edit.blockSignals(False)
            self.filter_changed.emit(col_idx, "")


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


class ToyaPaginationBar(QWidget):
    """
    TOYA ERP Standartlarında Sayfalama (Pagination) Kontrol Çubuğu.
    Özellikler:
    - Önceki / Sonraki / İlk / Son sayfa gezintisi.
    - Sayfa başına kayıt adedi seçimi (25, 50, 100, 250, Tümü).
    - Anlık toplam kayıt ve gösterilen aralık rozeti.
    """

    page_changed = Signal(int, int)  # current_page (1-based), page_size (-1 for All)

    def __init__(self, parent=None, page_size: int = 50):
        super().__init__(parent)
        self._current_page = 1
        self._page_size = page_size
        self._total_items = 0
        self._total_pages = 1

        self._init_ui()

    def _init_ui(self):
        self.setFixedHeight(34)
        self.setStyleSheet("""
            QWidget {
                background-color: #f8fafc;
                border-top: 1px solid #e2e8f0;
            }
            QLabel {
                color: #334155;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton {
                background-color: #ffffff;
                color: #1e3a8a;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 11px;
                font-weight: bold;
                min-width: 26px;
                height: 22px;
            }
            QPushButton:hover {
                background-color: #2563eb;
                color: #ffffff;
                border-color: #1d4ed8;
            }
            QPushButton:disabled {
                background-color: #f1f5f9;
                color: #94a3b8;
                border-color: #e2e8f0;
            }
            QComboBox {
                background-color: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 11px;
                font-weight: 600;
                height: 22px;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        # 1. Sol: Toplam kayıt ve görünüm bilgisi
        self.lbl_info = QLabel("📊 Toplam 0 Kayıt")
        self.lbl_info.setStyleSheet("color: #1e3a8a; font-weight: 700;")
        layout.addWidget(self.lbl_info)

        layout.addStretch()

        # 2. Orta: Sayfa Değiştirme Butonları
        self.btn_first = QPushButton("⏮")
        self.btn_first.setToolTip("İlk Sayfa")
        self.btn_first.setCursor(Qt.PointingHandCursor)
        self.btn_first.clicked.connect(self._go_first)
        layout.addWidget(self.btn_first)

        self.btn_prev = QPushButton("◀")
        self.btn_prev.setToolTip("Önceki Sayfa")
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.clicked.connect(self._go_prev)
        layout.addWidget(self.btn_prev)

        self.lbl_page = QLabel("Sayfa 1 / 1")
        self.lbl_page.setStyleSheet("color: #0f172a; font-weight: 700; padding: 0 4px;")
        layout.addWidget(self.lbl_page)

        self.btn_next = QPushButton("▶")
        self.btn_next.setToolTip("Sonraki Sayfa")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.clicked.connect(self._go_next)
        layout.addWidget(self.btn_next)

        self.btn_last = QPushButton("⏭")
        self.btn_last.setToolTip("Son Sayfa")
        self.btn_last.setCursor(Qt.PointingHandCursor)
        self.btn_last.clicked.connect(self._go_last)
        layout.addWidget(self.btn_last)

        layout.addStretch()

        # 3. Sağ: Sayfa Başına Adet Seçici
        layout.addWidget(QLabel("Sayfa Başına:"))
        self.combo_page_size = QComboBox()
        self.combo_page_size.addItem("25", 25)
        self.combo_page_size.addItem("50", 50)
        self.combo_page_size.addItem("100", 100)
        self.combo_page_size.addItem("250", 250)
        self.combo_page_size.addItem("Tümü", -1)

        idx = self.combo_page_size.findData(self._page_size)
        if idx >= 0:
            self.combo_page_size.setCurrentIndex(idx)
        else:
            self.combo_page_size.setCurrentIndex(1)  # 50

        self.combo_page_size.currentIndexChanged.connect(self._on_page_size_changed)
        layout.addWidget(self.combo_page_size)

        self._update_ui_state()

    def set_total_items(self, total: int):
        self._total_items = max(0, total)
        self._recalc_pages()
        self._update_ui_state()

    def current_page(self) -> int:
        return self._current_page

    def page_size(self) -> int:
        return self._page_size

    def total_pages(self) -> int:
        return self._total_pages

    def _recalc_pages(self):
        if self._page_size <= 0:
            self._total_pages = 1
            self._current_page = 1
        else:
            self._total_pages = max(1, (self._total_items + self._page_size - 1) // self._page_size)
            if self._current_page > self._total_pages:
                self._current_page = self._total_pages

    def _update_ui_state(self):
        self.btn_first.setEnabled(self._current_page > 1)
        self.btn_prev.setEnabled(self._current_page > 1)
        self.btn_next.setEnabled(self._current_page < self._total_pages)
        self.btn_last.setEnabled(self._current_page < self._total_pages)

        self.lbl_page.setText(f"Sayfa {self._current_page} / {self._total_pages}")

        if self._total_items == 0:
            self.lbl_info.setText("📊 0 Kayıt Bulundu")
        elif self._page_size <= 0:
            self.lbl_info.setText(f"📊 Toplam {self._total_items} Kayıt (Tümü Gösteriliyor)")
        else:
            start = (self._current_page - 1) * self._page_size + 1
            end = min(self._total_items, self._current_page * self._page_size)
            self.lbl_info.setText(f"📊 Toplam {self._total_items} Kayıt (Gösterilen: {start} - {end})")

    @Slot()
    def _go_first(self):
        if self._current_page != 1:
            self._current_page = 1
            self._update_ui_state()
            self.page_changed.emit(self._current_page, self._page_size)

    @Slot()
    def _go_prev(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._update_ui_state()
            self.page_changed.emit(self._current_page, self._page_size)

    @Slot()
    def _go_next(self):
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._update_ui_state()
            self.page_changed.emit(self._current_page, self._page_size)

    @Slot()
    def _go_last(self):
        if self._current_page != self._total_pages:
            self._current_page = self._total_pages
            self._update_ui_state()
            self.page_changed.emit(self._current_page, self._page_size)

    @Slot(int)
    def _on_page_size_changed(self, idx: int):
        self._page_size = self.combo_page_size.itemData(idx)
        self._current_page = 1
        self._recalc_pages()
        self._update_ui_state()
        self.page_changed.emit(self._current_page, self._page_size)


class ToyaDbGrid(QWidget):
    """
    TOYA ERP Standard DBGrid Component.
    Enables instant multi-column filtering, persistent profile views,
    context menus, responsive column resizing, and integrated pagination.
    """

    selection_changed = Signal()
    page_changed = Signal(int, int)

    def __init__(self, parent=None, enable_pagination: bool = True):
        super().__init__(parent)
        self.column_filters: Dict[int, str] = {}
        self.hidden_columns: Set[int] = set()
        self._filter_row_visible = True
        self._pagination_enabled = enable_pagination

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

        # 3. Pagination Bar
        self.pagination_bar = ToyaPaginationBar(self, page_size=50)
        self.pagination_bar.page_changed.connect(self._on_pagination_page_changed)
        self.pagination_bar.setVisible(self._pagination_enabled)
        layout.addWidget(self.pagination_bar)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "filter_bar"):
            self.filter_bar.adjust_positions()

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "filter_bar"):
            self.filter_bar.adjust_positions()

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

    def set_pagination_visible(self, visible: bool):
        self._pagination_enabled = visible
        self.pagination_bar.setVisible(visible)
        self._apply_row_filters()

    def clear_all_filters(self):
        self.column_filters.clear()
        self.filter_bar.clear_all_filters()
        self._apply_row_filters()

    def _on_filter_changed(self, col_idx: int, text: str):
        if not text:
            self.column_filters.pop(col_idx, None)
        else:
            self.column_filters[col_idx] = text
        self.pagination_bar._current_page = 1
        self._apply_row_filters()

    def _apply_row_filters(self):
        """Applies column filters + pagination slice."""
        matching_rows = []
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
            
            if match:
                matching_rows.append(row)

        total_matching = len(matching_rows)
        self.pagination_bar.set_total_items(total_matching)

        if not self._pagination_enabled or self.pagination_bar.page_size() <= 0:
            # Show all matching rows
            matching_set = set(matching_rows)
            for row in range(self.table.rowCount()):
                self.table.setRowHidden(row, row not in matching_set)
        else:
            p_size = self.pagination_bar.page_size()
            p_num = self.pagination_bar.current_page()
            start_idx = (p_num - 1) * p_size
            end_idx = start_idx + p_size
            visible_rows = set(matching_rows[start_idx:end_idx])

            for row in range(self.table.rowCount()):
                self.table.setRowHidden(row, row not in visible_rows)

    def _on_pagination_page_changed(self, page_num: int, page_size: int):
        self._apply_row_filters()
        self.page_changed.emit(page_num, page_size)

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
            "filter_row_visible": self._filter_row_visible,
            "page_size": self.pagination_bar.page_size()
        }

    def apply_state(self, state: Dict[str, Any]):
        """Applies a saved profile layout state."""
        if not state:
            return
        
        hidden = state.get("hidden_columns", [])
        widths = state.get("column_widths", [])
        row_h = state.get("row_height", 88)
        filter_vis = state.get("filter_row_visible", True)
        p_size = state.get("page_size", 50)

        for c in range(self.table.columnCount()):
            if c < len(widths) and widths[c] > 10:
                self.table.setColumnWidth(c, widths[c])
            self.table.setColumnHidden(c, c in hidden)

        self.table.verticalHeader().setDefaultSectionSize(row_h)
        self.set_filter_row_visible(filter_vis)
        
        idx = self.pagination_bar.combo_page_size.findData(p_size)
        if idx >= 0:
            self.pagination_bar.combo_page_size.setCurrentIndex(idx)

        self.filter_bar.adjust_positions()
        self._apply_row_filters()
