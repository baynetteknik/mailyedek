"""
main_window.py — Main application window with sidebar navigation.

Uses PySide6 with a modern sidebar + stacked widget layout.
"""

import sys
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal, Slot
from PySide6.QtGui import QIcon, QFont, QAction
from PySide6.QtCore import Qt, QSize, Signal, Slot
from PySide6.QtGui import QIcon, QFont, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QListWidget, QListWidgetItem, QPushButton,
    QLabel, QFrame, QStatusBar, QMessageBox, QSplitter,
    QSizePolicy, QSpacerItem, QFileDialog, QDialog, QDialogButtonBox,
    QTableWidget, QTableWidgetItem, QInputDialog, QHeaderView,
)

from core.mail_engine import MailEngine
from core.settings import AppSettings

from gui.widgets.account_panel import AccountPanel
from gui.widgets.sync_panel import SyncPanel
from gui.widgets.backup_panel import BackupPanel
from gui.widgets.restore_panel import RestorePanel
from gui.widgets.search_panel import SearchPanel
from gui.widgets.audit_panel import AuditPanel
from gui.widgets.health_panel import HealthPanel
from gui.widgets.report_panel import ReportPanel
from gui.widgets.schedule_panel import SchedulePanel
from gui.widgets.mail_viewer_panel import MailViewerPanel
from gui.widgets.export_panel import ExportPanel

logger = logging.getLogger(__name__)

STYLE_PATH = Path(__file__).parent / "resources" / "style.qss"


class SidebarButton(QPushButton):
    """A styled sidebar navigation button that supports collapsing."""

    def __init__(self, text: str, icon_char: str = ""):
        super().__init__()
        self.icon_char = icon_char
        self.text_label = text
        
        self.setProperty("sidebar", True)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self.setMinimumHeight(44)
        self.set_collapsed(False)

    def set_collapsed(self, collapsed: bool):
        if collapsed:
            self.setText(self.icon_char)
            self.setToolTip(self.text_label)
            self.setMaximumWidth(45)
            self.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #c0c4d0;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 0px;
                    text-align: center;
                    font-size: 14px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background: rgba(255,255,255,0.08);
                    color: #ffffff;
                }
                QPushButton:checked {
                    background: rgba(67,97,238,0.25);
                    color: #ffffff;
                    font-weight: 700;
                    border-left: 3px solid #4361ee;
                }
            """)
        else:
            self.setText(f"  {self.icon_char}  {self.text_label}" if self.icon_char else self.text_label)
            self.setToolTip("")
            self.setMaximumWidth(200)
            self.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #c0c4d0;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 16px;
                    text-align: left;
                    font-size: 13px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background: rgba(255,255,255,0.08);
                    color: #ffffff;
                }
                QPushButton:checked {
                    background: rgba(67,97,238,0.25);
                    color: #ffffff;
                    font-weight: 700;
                    border-left: 3px solid #4361ee;
                }
            """)


class MainWindow(QMainWindow):
    """Main application window with sidebar navigation."""

    def __init__(self, engine: Optional[MailEngine] = None,
                 db_path: Optional[Path] = None,
                 key_file: Optional[Path] = None,
                 settings: Optional[AppSettings] = None):
        super().__init__()
        self.settings = settings or AppSettings()
        self.engine = engine or MailEngine(db_path=db_path, key_file=key_file)

        self.setWindowTitle("Mail Archive System v1.0")
        self.setMinimumSize(1200, 760)
        self.resize(1400, 860)
        self.setWindowIcon(self._create_app_icon())

        self._init_ui()
        self._load_style()
        self._connect_signals()
        self._init_tray_icon()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = self._create_sidebar()
        main_layout.addWidget(sidebar)

        # Content area
        content = QWidget()
        content.setStyleSheet("background: #f0f2f5;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # Header bar
        header = self._create_header()
        content_layout.addWidget(header)

        # Stacked panels
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")
        content_layout.addWidget(self.stack, stretch=1)

        # Register panels
        self.panels = {}
        self._register_panels()

        main_layout.addWidget(content, stretch=1)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready  |  System initialized")

        # Collapse sidebar by default
        self._toggle_sidebar()

    def _create_sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(220)
        self.sidebar.setStyleSheet("""
            QFrame {
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1a1a2e, stop:1 #16213e
                );
                border-right: 1px solid #2a2a4e;
            }
        """)

        layout = QVBoxLayout(self.sidebar)
        layout.setContentsMargins(10, 16, 10, 16)
        layout.setSpacing(4)

        # Logo / Brand & Toggle
        brand_row = QHBoxLayout()
        self.brand = QLabel("📧  Mail Archive")
        self.brand.setStyleSheet("""
            font-size: 16px;
            font-weight: 800;
            color: #ffffff;
            border: none;
        """)
        self.brand.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        self.btn_toggle_sidebar = QPushButton("☰")
        self.btn_toggle_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_sidebar.setFixedWidth(34)
        self.btn_toggle_sidebar.setMinimumHeight(30)
        self.btn_toggle_sidebar.setStyleSheet("""
            QPushButton {
                background: #4361ee;
                color: #ffffff !important;
                border: 1.5px solid #ffffff;
                border-radius: 6px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #3a56d4;
            }
        """)
        self.btn_toggle_sidebar.clicked.connect(self._toggle_sidebar)
        
        brand_row.addWidget(self.brand, stretch=1)
        brand_row.addWidget(self.btn_toggle_sidebar)
        layout.addLayout(brand_row)

        # Navigation buttons
        self.nav_buttons = {}
        nav_items = [
            ("mail",      "📧", "Mail Viewer"),
            ("accounts",  "👤", "Accounts"),
            ("sync",      "🔄", "Sync"),
            ("export",    "📤", "Export Workspace"),
            ("backup",    "☁️", "Backup"),
            ("restore",   "📥", "Restore"),
            ("search",    "🔍", "Search"),
            ("audit",     "📋", "Audit Trail"),
            ("schedule",  "⏰", "Schedule"),
            ("report",    "📊", "Reports"),
            ("health",    "❤️", "Health"),
        ]

        for key, icon, label in nav_items:
            btn = SidebarButton(label, icon)
            self.nav_buttons[key] = btn
            layout.addWidget(btn)
            btn.clicked.connect(lambda checked, k=key: self._navigate(k))

        layout.addStretch()

        # Settings button
        self.btn_settings = SidebarButton("Storage", "⚙")
        self.btn_settings.setMinimumHeight(36)
        self.btn_settings.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #a0a4b0;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                text-align: left;
                font-size: 12px;
                font-weight: 400;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.08);
                color: #ffffff;
            }
        """)
        self.btn_settings.clicked.connect(self._open_settings)
        layout.addWidget(self.btn_settings)

        # Version label
        ver = QLabel("v1.0  —  Clean Architecture")
        ver.setStyleSheet("color: #555; font-size: 11px; padding: 8px;")
        ver.setAlignment(Qt.AlignCenter)
        layout.addWidget(ver)

        return self.sidebar

    def _create_header(self):
        header = QFrame()
        header.setFixedHeight(48)
        header.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border-bottom: 1px solid #e0e3e8;
            }
        """)
        hlayout = QHBoxLayout(header)
        hlayout.setContentsMargins(20, 0, 20, 0)

        self.page_title = QLabel("Dashboard")
        self.page_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #1a1a2e;")
        self.page_title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        hlayout.addWidget(self.page_title)

        hlayout.addStretch()

        # Data path indicator
        dp = self.settings.data_path()
        self.label_data_path = QLabel(f"📁 {dp}")
        self.label_data_path.setStyleSheet(
            "font-size: 11px; color: #6b7280; padding: 4px 10px; "
            "background: #f0f2f5; border-radius: 4px;"
        )
        self.label_data_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label_data_path.setToolTip("Current data directory")
        hlayout.addWidget(self.label_data_path)

        hlayout.addStretch()

        # Quick actions
        from PySide6.QtWidgets import QPushButton

        self.btn_export = QPushButton("📤 Export")
        self.btn_export.setProperty("outline", True)
        self.btn_export.setProperty("small", True)
        self.btn_export.setCursor(Qt.PointingHandCursor)
        hlayout.addWidget(self.btn_export)

        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setProperty("outline", True)
        self.btn_refresh.setProperty("small", True)
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        hlayout.addWidget(self.btn_refresh)

        self.btn_exit = QPushButton("✕ Exit")
        self.btn_exit.setProperty("danger", True)
        self.btn_exit.setProperty("small", True)
        self.btn_exit.setCursor(Qt.PointingHandCursor)
        hlayout.addWidget(self.btn_exit)

        return header

    def _register_panels(self):
        panels_def = [
            ("mail", "Mail Viewer", MailViewerPanel),
            ("accounts", "Accounts", AccountPanel),
            ("sync", "Sync", SyncPanel),
            ("export", "Export Workspace", ExportPanel),
            ("backup", "Backup", BackupPanel),
            ("restore", "Restore", RestorePanel),
            ("search", "Search", SearchPanel),
            ("audit", "Audit Trail", AuditPanel),
            ("schedule", "Schedule", SchedulePanel),
            ("report", "Reports", ReportPanel),
            ("health", "Health", HealthPanel),
        ]

        for key, title, PanelClass in panels_def:
            kwargs = {"engine": self.engine, "parent": self}
            if PanelClass is AccountPanel:
                kwargs["settings"] = self.settings
            panel = PanelClass(**kwargs)
            self.panels[key] = panel
            self.stack.addWidget(panel)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate(self, key: str):
        if key in self.panels:
            for k, btn in self.nav_buttons.items():
                btn.setChecked(k == key)
            self.stack.setCurrentWidget(self.panels[key])
            # Update header title & tooltip hints
            titles = {
                "mail": "Mail Viewer",
                "accounts": "Account Management",
                "sync": "Email Synchronization",
                "export": "Export & Server Migration Workspace",
                "backup": "Cloud Backup",
                "restore": "Restore from Backup",
                "search": "Full-Text Search",
                "audit": "Audit Trail",
                "schedule": "Task Scheduler",
                "report": "Reports",
                "health": "System Health",
            }
            descriptions = {
                "mail": "View local archived mails asynchronously.",
                "accounts": "Manage IMAP archive accounts and storage paths.",
                "sync": "Download, preview, and update emails from server.",
                "export": "Configure export definitions, push archives to target IMAP servers, and check file/inode details.",
                "backup": "Save archives to secondary files or cloud backups.",
                "restore": "Load archived data back into active workspace.",
                "search": "Fast search across sender, recipient, subject, and body.",
                "audit": "Trace data actions and verify audit blockchain integrity.",
                "schedule": "Define auto-run archiving timers and schedules.",
                "report": "Summary analytics of database usage and message sizes.",
                "health": "Database status, index validation, and network latency checks.",
            }
            self.page_title.setText(titles.get(key, key.title()))
            self.page_title.setToolTip(descriptions.get(key, ""))
            self.status.showMessage(f"Navigated to {titles.get(key, key.title())}")

            # Refresh panel data
            if hasattr(self.panels[key], "refresh"):
                self.panels[key].refresh()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    @Slot()
    def _open_settings(self):
        """Open storage settings dialog with path + locations management."""
        dialog = StorageSettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.label_data_path.setText(f"📁 {self.settings.data_path()}")

    @Slot()
    def _open_export_dialog(self):
        """Navigate to export workspace."""
        self._navigate("export")

    @Slot()
    def _toggle_sidebar(self):
        """Toggle sidebar collapsed (Icons Only) vs expanded (Full)."""
        collapsed = self.sidebar.width() > 70
        self.sidebar.setFixedWidth(55 if collapsed else 220)
        self.brand.setText("📧" if collapsed else "📧  Mail Archive")
        for btn in self.nav_buttons.values():
            btn.set_collapsed(collapsed)

    # ------------------------------------------------------------------
    # Signals / slots
    # ------------------------------------------------------------------

    def _connect_signals(self):
        self.btn_exit.clicked.connect(self.close)
        self.btn_refresh.clicked.connect(self._on_refresh)
        self.btn_export.clicked.connect(self._open_export_dialog)

        # Default: show accounts
        self._navigate("accounts")

    def _on_refresh(self):
        current = self.stack.currentWidget()
        if hasattr(current, "refresh"):
            current.refresh()
            self.status.showMessage("Refreshed", 3000)

    # ------------------------------------------------------------------
    # Style
    # ------------------------------------------------------------------

    def _load_style(self):
        if STYLE_PATH.exists():
            with open(STYLE_PATH) as f:
                self.setStyleSheet(f.read())

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if getattr(self, "_force_quit", False):
            self.engine.shutdown()
            event.accept()
            return

        from PySide6.QtWidgets import QMessageBox, QSystemTrayIcon
        
        # Check if background sync or export is running
        sync_running = False
        if "sync" in self.panels:
            sync_panel = self.panels["sync"]
            if hasattr(sync_panel, "_active_syncs") and sync_panel._active_syncs:
                sync_running = True

        export_running = False
        if "export" in self.panels:
            export_panel = self.panels["export"]
            if hasattr(export_panel, "_active_exports") and export_panel._active_exports:
                export_running = True

        if not sync_running and not export_running:
            # Exit directly
            self.exit_completely()
            event.accept()
            return
            
        reply = QMessageBox(self)
        reply.setWindowTitle("Exit Confirmation")
        reply.setText("Active sync or export tasks are running in the background. Do you want to minimize to system tray or exit completely?")
        
        btn_background = reply.addButton("Run in Background", QMessageBox.ButtonRole.AcceptRole)
        btn_exit = reply.addButton("Exit Completely", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = reply.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        
        # Style message box buttons slightly for premium look
        reply.setStyleSheet("""
            QMessageBox { background-color: #f8f9fa; }
            QPushButton { padding: 6px 14px; font-size: 12px; border-radius: 4px; font-weight: 600; }
        """)
        reply.exec()
        
        clicked_button = reply.clickedButton()
        if clicked_button == btn_background:
            event.ignore()
            self.hide()
            if self.tray_icon.isSystemTrayAvailable():
                self.tray_icon.showMessage(
                    "Mail Archive System",
                    "The application is running in the background. Click the icon to restore.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000
                )
        elif clicked_button == btn_exit:
            self.exit_completely()
            event.accept()
        else:
            event.ignore()

    def _init_tray_icon(self):
        from PySide6.QtWidgets import QSystemTrayIcon, QMenu
        from PySide6.QtGui import QAction
        
        self._force_quit = False
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self._create_app_icon())
        self.tray_icon.setToolTip("Mail Archive System")
        
        tray_menu = QMenu(self)
        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self.show_and_activate)
        exit_action = QAction("Exit Completely", self)
        exit_action.triggered.connect(self.exit_completely)
        
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(exit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_icon_activated)
        self.tray_icon.show()
        
    def _create_app_icon(self):
        from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter, QBrush
        from PySide6.QtCore import Qt
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        # Draw background circle
        painter.setBrush(QBrush(QColor("#4361ee")))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(2, 2, 28, 28)
        # Draw white envelope
        painter.setPen(QColor("#ffffff"))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(8, 10, 16, 12)
        painter.drawLine(8, 10, 16, 16)
        painter.drawLine(24, 10, 16, 16)
        painter.end()
        return QIcon(pixmap)

    def show_and_activate(self):
        self.show()
        self.showNormal()
        self.activateWindow()

    def exit_completely(self):
        self._force_quit = True
        if hasattr(self, "panels") and "sync" in self.panels:
            try:
                self.panels["sync"]._cancel_sync()
            except Exception:
                pass
        self.close()

    def _on_tray_icon_activated(self, reason):
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.Trigger:
            self.show_and_activate()


class StorageSettingsDialog(QDialog):
    """Dialog for managing data path + named storage locations."""

    def __init__(self, settings: "AppSettings", parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Storage Settings")
        self.setMinimumSize(520, 400)
        self._build_ui()
        self._populate()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- Current data path ---
        path_group = QFrame()
        path_group.setStyleSheet("QFrame { background: #f8f9fa; border-radius: 6px; padding: 8px; }")
        gl = QVBoxLayout(path_group)

        lbl = QLabel("Default Data Directory")
        lbl.setStyleSheet("font-weight: 600; color: #1a1a2e;")
        gl.addWidget(lbl)

        p_row = QHBoxLayout()
        self.lbl_path = QLabel(str(self.settings.data_path()))
        self.lbl_path.setStyleSheet("color: #374151;")
        p_row.addWidget(self.lbl_path, 1)

        btn_change = QPushButton("Change…")
        btn_change.setStyleSheet(
            "QPushButton { background: #4f46e5; color: white; border: none; "
            "border-radius: 4px; padding: 4px 12px; }"
            "QPushButton:hover { background: #4338ca; }"
        )
        btn_change.clicked.connect(self._on_change_path)
        p_row.addWidget(btn_change)
        gl.addLayout(p_row)

        hint = QLabel("Database and encryption key are stored here. Restart required after change.")
        hint.setStyleSheet("font-size: 11px; color: #9ca3af;")
        hint.setWordWrap(True)
        gl.addWidget(hint)
        layout.addWidget(path_group)

        layout.addSpacing(16)

        # --- Storage locations table ---
        tbl_label = QLabel("Named Storage Locations (for per-account disk/NAS assignment)")
        tbl_label.setStyleSheet("font-weight: 600; color: #1a1a2e;")
        layout.addWidget(tbl_label)

        self.tbl_locations = QTableWidget(0, 2)
        self.tbl_locations.setHorizontalHeaderLabels(["Name", "Path"])
        self.tbl_locations.horizontalHeader().setStretchLastSection(True)
        self.tbl_locations.setStyleSheet(
            "QTableWidget { border: 1px solid #e0e3e8; gridline-color: #f0f2f5; }"
            "QHeaderView::section { background: #f8f9fa; font-weight: 600; padding: 4px; }"
        )
        self.tbl_locations.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_locations.setSelectionMode(QTableWidget.SingleSelection)
        self.tbl_locations.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.tbl_locations, 1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Add")
        btn_add.setStyleSheet(
            "QPushButton { background: #10b981; color: white; border: none; "
            "border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #059669; }"
        )
        btn_add.clicked.connect(self._on_add_location)
        btn_row.addWidget(btn_add)

        btn_remove = QPushButton("Remove")
        btn_remove.setStyleSheet(
            "QPushButton { background: #ef4444; color: white; border: none; "
            "border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #dc2626; }"
        )
        btn_remove.clicked.connect(self._on_remove_location)
        btn_row.addWidget(btn_remove)

        btn_row.addStretch()

        btn_close = QPushButton("Close")
        btn_close.setStyleSheet(
            "QPushButton { background: #6b7280; color: white; border: none; "
            "border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #4b5563; }"
        )
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)

        layout.addLayout(btn_row)

    def _populate(self):
        self.tbl_locations.setRowCount(0)
        for loc in self.settings.storage_locations():
            row = self.tbl_locations.rowCount()
            self.tbl_locations.insertRow(row)
            self.tbl_locations.setItem(row, 0, QTableWidgetItem(loc.name))
            self.tbl_locations.setItem(row, 1, QTableWidgetItem(loc.path))

    def _on_change_path(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Data Directory", str(self.settings.data_path()),
        )
        if not folder:
            return
        self.settings.set_data_path(Path(folder))
        self.lbl_path.setText(str(self.settings.data_path()))
        QMessageBox.information(
            self, "Saved",
            "Data directory changed. Please restart the application.\n\n"
            "Existing data will NOT be moved automatically — "
            "copy the contents of the old 'data/' folder manually.",
        )

    def _is_path_outside_default(self, folder_path: str) -> bool:
        try:
            data_path = self.settings.data_path().resolve()
            target_path = Path(folder_path).resolve()
            return not str(target_path).startswith(str(data_path))
        except Exception:
            return False

    def _on_add_location(self):
        name, ok = QInputDialog.getText(self, "Add Location", "Location name:")
        if not ok or not name.strip():
            return
        folder = QFileDialog.getExistingDirectory(
            self, f"Select path for '{name}'",
        )
        if not folder:
            return
        if self._is_path_outside_default(folder):
            QMessageBox.warning(
                self, "Uyarı: Harici Dizin",
                f"Uyarı: Seçilen yedekleme/depolama klasörü varsayılan veri dizininin dışındadır.\n\n"
                f"Senkronizasyon (aktif veritabanı ve önbellek) yalnızca varsayılan veri dizini ({self.settings.data_path()}) içinde çalışacaktır. "
                f"Bu konum sadece harici yedeklemeler/aktarımlar için kullanılacaktır."
            )
        self.settings.add_storage_location(name.strip(), folder)
        self._populate()

    def _on_remove_location(self):
        row = self.tbl_locations.currentRow()
        if row < 0:
            QMessageBox.information(self, "Remove", "Select a location first.")
            return
        name = self.tbl_locations.item(row, 0).text()
        reply = QMessageBox.question(
            self, "Remove", f"Remove storage location '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.settings.remove_storage_location(name)
            self._populate()
