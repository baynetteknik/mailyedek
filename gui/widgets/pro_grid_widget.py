"""
pro_grid_widget.py — Professional Customizable & Persistent Data Grid Widget.

Features:
- Instant text searching & row filtering
- Right-click column visibility toggle menu on header
- Custom column widths, sorting, and visibility
- Persistent layout settings (Save / Restore / Reset layout via AppSettings)
- High contrast, crisp typography for maximum legibility (fixes cut-off Account Details)
"""

from typing import List, Dict, Any, Optional
from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtGui import QFont, QAction, QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QPushButton, QLabel, QMenu, QWidgetAction,
    QCheckBox, QMessageBox, QFrame
)


class ProHeaderView(QHeaderView):
    """Custom Header View with right-click column visibility menu."""
    
    column_visibility_changed = Signal(int, bool)
    save_requested = Signal()
    reset_requested = Signal()

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_header_menu)

    @Slot(Qt.MouseButton)
    def _show_header_menu(self, pos):
        table: QTableWidget = self.parentWidget()
        if not isinstance(table, QTableWidget):
            return

        menu = QMenu(self)
        menu.setTitle("Sütun Görünürlüğü")
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e3a8a;
                color: #ffffff;
                border: 1px solid #3b82f6;
                border-radius: 6px;
                padding: 6px;
                font-weight: 600;
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 20px 6px 12px;
                border-radius: 4px;
                background-color: transparent;
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

        title_action = menu.addAction("👁️ Sütunları Göster / Gizle")
        title_action.setEnabled(False)
        menu.addSeparator()

        for col in range(table.columnCount()):
            header_item = table.horizontalHeaderItem(col)
            label = header_item.text() if header_item else f"Column {col}"
            
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(not table.isColumnHidden(col))
            
            # Connect toggle
            def _toggle(checked, c=col):
                table.setColumnHidden(c, not checked)
                self.column_visibility_changed.emit(c, checked)

            action.triggered.connect(_toggle)
            menu.addAction(action)

        menu.addSeparator()
        act_save = menu.addAction("💾 Sütun Düzenini Kaydet")
        act_save.triggered.connect(self.save_requested.emit)
        
        act_reset = menu.addAction("🔄 Varsayılan Düzene Sıfırla")
        act_reset.triggered.connect(self.reset_requested.emit)

        menu.exec(QCursor.pos())


class ProGridWidget(QWidget):
    """
    Full-featured customizable grid table with persistent settings,
    search input toolbar, and right-click column management.
    """

    filter_changed = Signal(str)
    row_count_changed = Signal(int, int)  # visible, total

    def __init__(self, settings=None, grid_id: str = "default_grid", parent=None):
        super().__init__(parent)
        self.settings = settings
        self.grid_id = grid_id

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(6)

        # -------------------------------------------------------------------
        # Top Grid Toolbar
        # -------------------------------------------------------------------
        self.toolbar_frame = QFrame()
        self.toolbar_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 2px 6px;
            }
        """)
        tb_layout = QHBoxLayout(self.toolbar_frame)
        tb_layout.setContentsMargins(6, 4, 6, 4)
        tb_layout.setSpacing(8)

        # Quick Search Input
        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("🔍 Tabloda Hızlı Arama...")
        self.input_search.setClearButtonEnabled(True)
        self.input_search.setStyleSheet("""
            QLineEdit {
                background-color: #f8fafc;
                color: #0f172a;
                border: 1.5px solid #cbd5e1;
                border-radius: 5px;
                padding: 5px 10px;
                font-size: 11.5px;
                min-width: 180px;
            }
            QLineEdit:focus {
                border-color: #2563eb;
                background-color: #ffffff;
            }
        """)
        self.input_search.textChanged.connect(self._on_search_text_changed)
        tb_layout.addWidget(self.input_search)

        # Row Counter Label
        self.lbl_counter = QLabel("0 / 0 Kayıt")
        self.lbl_counter.setStyleSheet("font-size: 11.5px; font-weight: bold; color: #475569; background: transparent;")
        tb_layout.addWidget(self.lbl_counter)

        tb_layout.addStretch()

        # Column Config Menu Button
        self.btn_columns = QPushButton("⚙️ Sütun Görünürlüğü")
        self.btn_columns.setToolTip("Görünür sütunları seçin ve düzenleyin")
        self.btn_columns.setStyleSheet(self._btn_toolbar_style())
        self.btn_columns.clicked.connect(self._show_columns_menu)
        tb_layout.addWidget(self.btn_columns)

        # Save Layout Preset Button
        self.btn_save_layout = QPushButton("💾 Düzeni Kaydet")
        self.btn_save_layout.setToolTip("Mevcut sütun genişliklerini ve düzenini varsayılan olarak saklar")
        self.btn_save_layout.setStyleSheet(self._btn_toolbar_style())
        self.btn_save_layout.clicked.connect(self.save_grid_state)
        tb_layout.addWidget(self.btn_save_layout)

        # Reset Layout Preset Button
        self.btn_reset_layout = QPushButton("🔄 Sıfırla")
        self.btn_reset_layout.setToolTip("Varsayılan sütun genişliği ve görünürlüğüne döner")
        self.btn_reset_layout.setStyleSheet(self._btn_toolbar_style())
        self.btn_reset_layout.clicked.connect(self.reset_grid_state)
        tb_layout.addWidget(self.btn_reset_layout)

        main_layout.addWidget(self.toolbar_frame)

        # -------------------------------------------------------------------
        # QTableWidget Engine (TOYA DBGrid Standard)
        # -------------------------------------------------------------------
        self.table = QTableWidget()
        
        # Custom Header
        custom_header = ProHeaderView(Qt.Horizontal, self.table)
        custom_header.setSectionsMovable(True)
        custom_header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        custom_header.setStyleSheet("""
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
        custom_header.save_requested.connect(self.save_grid_state)
        custom_header.reset_requested.connect(self.reset_grid_state)
        self.table.setHorizontalHeader(custom_header)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)  # Generous row height for readability

        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #f8fafc;
                gridline-color: #e2e8f0;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                color: #0f172a;
                font-size: 12px;
                selection-background-color: #3b82f6;
                selection-color: #ffffff;
            }
            QTableWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #f1f5f9;
            }
            QTableWidget::item:selected {
                background-color: #3b82f6;
                color: #ffffff;
            }
        """)

        main_layout.addWidget(self.table, stretch=1)

    def _btn_toolbar_style(self) -> str:
        return """
            QPushButton {
                background-color: #ffffff;
                color: #334155;
                font-weight: 600;
                font-size: 11px;
                border: 1px solid #cbd5e1;
                border-radius: 5px;
                padding: 5px 12px;
            }
            QPushButton:hover {
                background-color: #f1f5f9;
                color: #0f172a;
                border-color: #94a3b8;
            }
        """

    @Slot()
    def _show_columns_menu(self):
        header: ProHeaderView = self.table.horizontalHeader()
        header._show_header_menu(header.rect().bottomLeft())

    @Slot(str)
    def _on_search_text_changed(self, text: str):
        search = text.strip().lower()
        visible_count = 0
        total_count = self.table.rowCount()

        for row in range(total_count):
            row_matches = False
            if not search:
                row_matches = True
            else:
                for col in range(self.table.columnCount()):
                    # Check text items
                    item = self.table.item(row, col)
                    if item and search in item.text().lower():
                        row_matches = True
                        break
                    # Check cell widget labels if any
                    widget = self.table.cellWidget(row, col)
                    if widget:
                        labels = widget.findChildren(QLabel)
                        if any(search in l.text().lower() for l in labels):
                            row_matches = True
                            break

            self.table.setRowHidden(row, not row_matches)
            if row_matches:
                visible_count += 1

        self.lbl_counter.setText(f"{visible_count} / {total_count} Kayıt")
        self.row_count_changed.emit(visible_count, total_count)
        self.filter_changed.emit(text)

    def update_counter(self):
        total_count = self.table.rowCount()
        visible_count = sum(1 for r in range(total_count) if not self.table.isRowHidden(r))
        self.lbl_counter.setText(f"{visible_count} / {total_count} Kayıt")

    def save_grid_state(self):
        if not self.settings:
            return

        state = {
            "hidden_columns": [c for c in range(self.table.columnCount()) if self.table.isColumnHidden(c)],
            "column_widths": [self.table.columnWidth(c) for c in range(self.table.columnCount())]
        }
        self.settings.set(f"grid_state_{self.grid_id}", state)
        self.settings.save()

        QMessageBox.information(self, "Grid Düzeni Kaydedildi", "Tablo sütun genişlikleri ve görünürlük tercihleri kaydedildi.")

    def load_grid_state(self):
        if not self.settings:
            return

        state = self.settings.get(f"grid_state_{self.grid_id}", None)
        if state and isinstance(state, dict):
            hidden = state.get("hidden_columns", [])
            widths = state.get("column_widths", [])

            for c in range(self.table.columnCount()):
                if c < len(widths) and widths[c] > 10:
                    self.table.setColumnWidth(c, widths[c])
                self.table.setColumnHidden(c, c in hidden)

    def reset_grid_state(self):
        for c in range(self.table.columnCount()):
            self.table.setColumnHidden(c, False)
        self.table.resizeColumnsToContents()
        if self.settings:
            self.settings.set(f"grid_state_{self.grid_id}", None)
            self.settings.save()
        QMessageBox.information(self, "Grid Sıfırlandı", "Tablo varsayılan düzenine sıfırlandı.")
