"""
main_window.py — Main application window with sidebar navigation.

Uses PySide6 with a modern sidebar + stacked widget layout.
"""

import sys
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal, Slot
from PySide6.QtGui import QIcon, QFont, QAction, QPixmap
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
from gui.widgets.settings_panel import SettingsPanel
from gui.widgets.top_notification_banner import TopNotificationBanner
from gui.dialogs.login_dialog import LoginDialog
from gui.dialogs.disk_arrival_dialog import DiskArrivalDialog
from infrastructure.disk_identifier import (
    get_disk_signature,
    stamp_disk_signature,
    find_registered_disk_on_system,
    inspect_drive_recognition,
)

from PySide6.QtCore import QThread, QTimer

logger = logging.getLogger(__name__)

STYLE_PATH = Path(__file__).parent / "resources" / "style.qss"


class StartupDiskWorker(QThread):
    disk_ready_signal = Signal(dict)
    disk_found_other_signal = Signal(str, str, dict)  # old_path, new_path, sig
    disk_missing_signal = Signal(str)

    def __init__(self, settings: AppSettings, engine: MailEngine, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.engine = engine

    def run(self):
        try:
            raw_path = self.settings._data.get("data_path")
            registered_sig = self.settings.data_disk_signature()

            if not raw_path:
                return

            raw_path_obj = Path(raw_path)
            is_ready = False
            try:
                is_ready = raw_path_obj.exists()
            except OSError:
                is_ready = False

            if is_ready:
                sig = get_disk_signature(raw_path_obj)
                self.disk_ready_signal.emit({
                    "path": str(raw_path_obj),
                    "signature": sig,
                    "is_official": sig is not None,
                    "label": sig.get("label", "Resmi Yedekleme Diski") if sig else "Ana Depolama Alanı",
                })
                return

            # If not accessible at configured raw_path, search without blocking
            target_folder_name = raw_path_obj.name if raw_path_obj.name else "mailyedek"
            auto_found = find_registered_disk_on_system(registered_sig, target_folder_name)

            if auto_found:
                found_path = str(auto_found["found_path"])
                sig = auto_found.get("signature") or {}
                self.disk_found_other_signal.emit(raw_path, found_path, sig)
            else:
                self.disk_missing_signal.emit(raw_path)
        except Exception as e:
            logger.warning("StartupDiskWorker exception: %s", e)


class DiskArrivalScanWorker(QThread):
    finished_signal = Signal(dict, dict)  # drive_info, stats

    def __init__(self, engine: MailEngine, drive_info: dict, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.drive_info = drive_info

    def run(self):
        try:
            drive_path = self.drive_info.get("path", "")
            scan = self.engine.scan_drive_backups(drive_path)
            all_backups = scan.get("all_backups", [])
            sql_cnt = len([i for i in all_backups if "SQL" in i.get("type", "")])
            vhdx_cnt = len([i for i in all_backups if "VHDX" in i.get("type", "") or "Hyper-V" in i.get("type", "")])
            mail_cnt = len([i for i in all_backups if "Mail" in i.get("type", "") or "E-Posta" in i.get("type", "")])
            stats = {
                "total": len(all_backups),
                "sql": sql_cnt,
                "vhdx": vhdx_cnt,
                "mail": mail_cnt,
            }
            self.finished_signal.emit(self.drive_info, stats)
        except Exception as e:
            logger.error("DiskArrivalScanWorker error: %s", e)
            self.finished_signal.emit(self.drive_info, {"total": 0, "sql": 0, "vhdx": 0, "mail": 0})


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

    disk_arrived_signal = Signal(dict)

    def __init__(self, engine: Optional[MailEngine] = None,
                 db_path: Optional[Path] = None,
                 key_file: Optional[Path] = None,
                 settings: Optional[AppSettings] = None):
        super().__init__()
        self.settings = settings or AppSettings()
        self.engine = engine or MailEngine(db_path=db_path, key_file=key_file)
        self.current_user = None

        self.setWindowTitle("Toya Yedek - Kurumsal E-Posta Arşivleme & Yedekleme Sistemi")
        self.setMinimumSize(960, 560)
        self.resize(1260, 700)
        self.setWindowIcon(self._create_app_icon())

        self._startup_worker: Optional[StartupDiskWorker] = None
        self._disk_arrival_workers = []

        self.disk_arrived_signal.connect(self._on_disk_arrived)
        try:
            self.engine.start_disk_watcher(lambda d: self.disk_arrived_signal.emit(d))
        except Exception as e:
            logger.warning("Could not start background disk watcher: %s", e)

        self._init_ui()
        self._load_style()
        self._connect_signals()
        self._init_tray_icon()

        # Schedule non-blocking startup disk verification in background
        QTimer.singleShot(200, self._start_startup_disk_check)

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

        # Top Notification Banner (dismissible, non-blocking)
        self.top_banner = TopNotificationBanner(self)
        content_layout.addWidget(self.top_banner)

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

        # Logo / Brand & Toggle Row
        self.brand_container = QWidget()
        self.brand_layout = QHBoxLayout(self.brand_container)
        self.brand_layout.setContentsMargins(4, 4, 4, 8)
        self.brand_layout.setSpacing(8)

        # Toya Logo Icon
        self.lbl_brand_logo = QLabel()
        self.lbl_brand_logo.setCursor(Qt.PointingHandCursor)
        self.lbl_brand_logo.setToolTip("Toya Yedek")
        
        logo_path = Path("gui/resources/toya_logo_32.png")
        if not logo_path.exists():
            logo_path = Path("gui/resources/toya_logo.png")
        
        if logo_path.exists():
            pix = QPixmap(str(logo_path)).scaled(26, 26, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_brand_logo.setPixmap(pix)
        else:
            self.lbl_brand_logo.setText("🛡️")
            self.lbl_brand_logo.setStyleSheet("font-size: 18px;")
            
        self.lbl_brand_logo.mousePressEvent = lambda e: self._toggle_sidebar()
        self.brand_layout.addWidget(self.lbl_brand_logo)

        # Brand text
        self.brand = QLabel("Toya Yedek")
        self.brand.setStyleSheet("""
            font-size: 16px;
            font-weight: 800;
            color: #ffffff;
            border: none;
            letter-spacing: 0.5px;
        """)
        self.brand.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.brand_layout.addWidget(self.brand, stretch=1)

        # Toggle Button
        self.btn_toggle_sidebar = QPushButton("◀")
        self.btn_toggle_sidebar.setToolTip("Menüyü Daralt / Genişlet")
        self.btn_toggle_sidebar.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_sidebar.setFixedWidth(28)
        self.btn_toggle_sidebar.setMinimumHeight(28)
        self.btn_toggle_sidebar.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                color: #cbd5e1 !important;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
                color: #ffffff !important;
                border-color: #60a5fa;
            }
        """)
        self.btn_toggle_sidebar.clicked.connect(self._toggle_sidebar)
        self.brand_layout.addWidget(self.btn_toggle_sidebar)

        layout.addWidget(self.brand_container)

        # Navigation buttons
        self.nav_buttons = {}
        nav_items = [
            ("mail",      "📧", "Mail İzleyici"),
            ("accounts",  "📮", "E-Posta Hesapları"),
            ("sync",      "🔄", "Senkronizasyon"),
            ("export",    "📤", "Dışa Aktarım"),
            ("backup",    "☁️", "Yedekleme"),
            ("restore",   "📥", "Geri Yükleme"),
            ("search",    "🔍", "Arama"),
            ("audit",     "📋", "Denetim İzi"),
            ("schedule",  "⏰", "Zamanlayıcı"),
            ("report",    "📊", "Raporlar"),
            ("health",    "❤️", "Sistem Sağlığı"),
            ("users",     "👥", "Kullanıcı Yönetimi"),
            ("settings",  "⚙️", "Ayarlar & Depolama"),
        ]

        for key, icon, label in nav_items:
            btn = SidebarButton(label, icon)
            self.nav_buttons[key] = btn
            layout.addWidget(btn)
            btn.clicked.connect(lambda checked, k=key: self._navigate(k))

        layout.addStretch()

        # Footer / Version Section
        self.footer_container = QFrame()
        self.footer_container.setStyleSheet("border: none; background: transparent;")
        footer_layout = QVBoxLayout(self.footer_container)
        footer_layout.setContentsMargins(4, 8, 4, 4)
        footer_layout.setSpacing(4)
        footer_layout.setAlignment(Qt.AlignCenter)

        # Designated Logo Slot / Container
        self.lbl_footer_logo = QLabel("[ TOYA LOGO ]")
        self.lbl_footer_logo.setAlignment(Qt.AlignCenter)
        self.lbl_footer_logo.setStyleSheet("""
            QLabel {
                color: #64748b;
                font-size: 9.5px;
                font-weight: 700;
                letter-spacing: 1px;
                padding: 4px 8px;
                border: 1px dashed rgba(255, 255, 255, 0.12);
                border-radius: 4px;
                background: rgba(255, 255, 255, 0.03);
            }
        """)
        footer_layout.addWidget(self.lbl_footer_logo)

        # Version label only
        from core.version import get_version
        self.lbl_app_ver = QLabel(f"v{get_version()}")
        self.lbl_app_ver.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 600; padding: 2px;")
        self.lbl_app_ver.setAlignment(Qt.AlignCenter)
        footer_layout.addWidget(self.lbl_app_ver)

        layout.addWidget(self.footer_container)

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

        hlayout.addSpacing(10)

        # User and Role Badge
        self.lbl_user_badge = QLabel("👤 Giriş Yapılmadı")
        self.lbl_user_badge.setStyleSheet("""
            background: #ede9fe;
            color: #6d28d9;
            font-size: 11px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 6px;
            border: 1px solid #ddd6fe;
        """)
        hlayout.addWidget(self.lbl_user_badge)

        self.btn_logout = QPushButton("🚪 Kullanıcı Değiştir")
        self.btn_logout.setProperty("outline", True)
        self.btn_logout.setProperty("small", True)
        self.btn_logout.setCursor(Qt.PointingHandCursor)
        self.btn_logout.clicked.connect(self.prompt_login)
        hlayout.addWidget(self.btn_logout)

        # Quick actions
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

    def prompt_login(self) -> bool:
        """Prompt user login dialog."""
        dialog = LoginDialog(self.engine, self)
        if dialog.exec() == QDialog.Accepted and dialog.authenticated_user:
            self.current_user = dialog.authenticated_user
            uname = self.current_user.username
            role = self.current_user.role
            self.lbl_user_badge.setText(f"👤 {uname} ({role})")

            if role == "ADMIN":
                self.lbl_user_badge.setStyleSheet("background: #ede9fe; color: #6d28d9; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 6px; border: 1px solid #ddd6fe;")
            elif role == "OPERATOR":
                self.lbl_user_badge.setStyleSheet("background: #e0f2fe; color: #0369a1; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 6px; border: 1px solid #bae6fd;")
            else:
                self.lbl_user_badge.setStyleSheet("background: #f1f5f9; color: #475569; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 6px; border: 1px solid #cbd5e1;")

            self._apply_permissions()
            return True
        return False

    def _apply_permissions(self):
        """Apply active user role permissions across UI panels."""
        if not self.current_user:
            return
        role = self.current_user.role
        if "accounts" in self.panels and hasattr(self.panels["accounts"], "apply_permissions"):
            self.panels["accounts"].apply_permissions(role)
        if "backup" in self.panels and hasattr(self.panels["backup"], "apply_permissions"):
            self.panels["backup"].apply_permissions(role)
        if "settings" in self.panels and hasattr(self.panels["settings"], "apply_permissions"):
            self.panels["settings"].apply_permissions(role)

    # ------------------------------------------------------------------
    # Background Disk Verification & Notification Banner Handlers
    # ------------------------------------------------------------------

    def _start_startup_disk_check(self):
        """Perform non-blocking verification of data disk in background."""
        raw_path = self.settings._data.get("data_path")
        if not raw_path:
            return

        self.top_banner.show_progress(
            "💾 Depolama Diski Kontrol Ediliyor",
            f"'{raw_path}' veri konumu ve sistemdeki yedekleme sürücüleri denetleniyor...",
            is_indeterminate=True,
        )

        self._startup_worker = StartupDiskWorker(self.settings, self.engine, self)
        self._startup_worker.disk_ready_signal.connect(self._on_startup_disk_ready)
        self._startup_worker.disk_found_other_signal.connect(self._on_startup_disk_found_other)
        self._startup_worker.disk_missing_signal.connect(self._on_startup_disk_missing)
        self._startup_worker.start()

    def _on_startup_disk_ready(self, data: dict):
        path = data.get("path", "")
        label = data.get("label", "Resmi Yedekleme Diski")
        is_official = data.get("is_official", False)
        if is_official:
            self.top_banner.show_success(
                "✅ Resmi Yedekleme Diski Bağlı",
                f"'{path}' konumundaki kayıtlı yedekleme diski ({label}) doğrulandı ve aktif.",
                actions=[
                    ("🔍 Diski İncele", lambda: self._open_disk_dialog_by_path(path)),
                    ("✕ Kapat", self.top_banner.dismiss),
                ],
                auto_dismiss_seconds=8,
            )
        else:
            self.top_banner.show_success(
                "✅ Ana Veri Deposu Hazır",
                f"'{path}' veri konumu aktif olarak kullanılıyor.",
                actions=[
                    ("💾 Resmi Disk Olarak İmzala", lambda: self._stamp_drive_as_official(path, label)),
                    ("✕ Kapat", self.top_banner.dismiss),
                ],
                auto_dismiss_seconds=6,
            )

    def _on_startup_disk_found_other(self, old_path: str, new_path: str, sig: dict):
        label = sig.get("label", "Kayıtlı Yedekleme Diski")
        self.top_banner.show_info(
            "💾 Kayıtlı Yedekleme Diski Algılandı",
            f"Yapılandırılmış konum '{old_path}' yerine, kayıtlı yedek diskiniz ({label}) şu anda '{new_path}' sürücüsünde takılı.",
            actions=[
                ("🔄 Bu Konuma Otomatik Bağlan", lambda: self._connect_and_switch_data_path(new_path)),
                ("✕ Kapat", self.top_banner.dismiss),
            ],
        )

    def _on_startup_disk_missing(self, raw_path: str):
        self.top_banner.show_warning(
            "⚠️ Ana Veri Diski Bağlı Değil",
            f"Yapılandırılmış ana veri dizini ({raw_path}) şu anda takılı veya erişilebilir değil. "
            f"Uygulama yerel depolama ile açıldı (Yedek diskinizi taktığınızda otomatik tanınacaktır).",
            actions=[
                ("📁 Yeni Konum Seç", self._prompt_change_data_path),
                ("✕ Kapat", self.top_banner.dismiss),
            ],
        )

    @Slot(dict)
    def _on_disk_arrived(self, drive_info: dict):
        """Handle newly connected disk in a non-blocking background way."""
        letter = drive_info.get("letter", "")
        label = drive_info.get("label", "Harici Sürücü")
        free_gb = drive_info.get("free_gb", 0)

        logger.info("New disk plugged in: %s (%s - %.1f GB free)", letter, label, free_gb)

        # Show non-blocking progress banner
        self.top_banner.show_progress(
            f"💾 Yeni Harici Disk Algılandı ({letter})",
            f"{label} ({free_gb:.1f} GB Boş) — Yedek durumu ve disk imzası taranıyor...",
            is_indeterminate=True,
        )

        # Start asynchronous background scanner for the newly attached drive
        worker = DiskArrivalScanWorker(self.engine, drive_info, self)
        worker.finished_signal.connect(self._on_disk_arrival_scanned)
        self._disk_arrival_workers.append(worker)
        worker.start()

    def _on_disk_arrival_scanned(self, drive_info: dict, stats: dict):
        letter = drive_info.get("letter", "")
        label = drive_info.get("label", "Harici Sürücü")
        path = drive_info.get("path", "")
        total_backups = stats.get("total", 0)

        reg_sig = self.settings.data_disk_signature()
        cfg_path = str(self.settings.data_path())
        recog = inspect_drive_recognition(path, reg_sig, cfg_path)

        if recog.get("is_recognized"):
            recog_lbl = recog.get("label", "Resmi Yedekleme Diski")
            msg = f"Kayıtlı '{recog_lbl}' ({letter}) takıldı. Toplam {total_backups} adet mevcut yedek dosyası tespit edildi."
            self.top_banner.show_success(
                f"✅ Kayıtlı Yedekleme Diski Bağlandı ({letter})",
                msg,
                actions=[
                    ("🔍 Yedek Raporunu Aç", lambda: self._open_disk_arrival_dialog(drive_info)),
                    ("🚀 Bu Diske Yedek Al", lambda: self._open_disk_arrival_dialog(drive_info)),
                    ("✕ Kapat", self.top_banner.dismiss),
                ],
                auto_dismiss_seconds=15,
            )
        else:
            msg = f"{letter} [{label}] bağlandı. Diskte {total_backups} adet yedek dosyası bulundu. Bu diski resmi yedek diski yapabilir veya yedekleme başlatabilirsiniz."
            self.top_banner.show_info(
                f"ℹ️ Yeni Harici Sürücü Hazır ({letter})",
                msg,
                actions=[
                    ("🔍 Diski İncele / Yedek Al", lambda: self._open_disk_arrival_dialog(drive_info)),
                    ("💾 Resmi Yedek Diski Yap", lambda: self._stamp_drive_as_official(path, label)),
                    ("✕ Kapat", self.top_banner.dismiss),
                ],
                auto_dismiss_seconds=20,
            )

    def _open_disk_arrival_dialog(self, drive_info: dict):
        """Open the detailed DiskArrivalDialog for a drive."""
        try:
            dialog = DiskArrivalDialog(self.engine, drive_info, self, settings=self.settings)
            dialog.exec()
        except Exception as e:
            logger.error("Error opening DiskArrivalDialog: %s", e)

    def _open_disk_dialog_by_path(self, path_str: str):
        """Open DiskArrivalDialog by path."""
        p = Path(path_str)
        drive_letter = p.anchor or path_str[:2]
        d_info = {
            "path": str(p),
            "letter": drive_letter,
            "label": "Yedekleme Deposu",
            "type": "Sabit / Harici Disk",
            "is_removable": True,
            "free_gb": 0.0,
        }
        self._open_disk_arrival_dialog(d_info)

    def _connect_and_switch_data_path(self, new_path_str: str):
        """Connect to a recognized data path."""
        new_path = Path(new_path_str).resolve()
        self.settings.set_data_path(new_path)
        sig = get_disk_signature(new_path)
        if sig:
            self.settings.set_data_disk_signature(sig)
        self.top_banner.show_success(
            "✅ Veri Konumu Güncellendi",
            f"Ana veri konumu '{new_path}' olarak güncellendi ve bağlandı.",
            auto_dismiss_seconds=6,
        )
        self.status.showMessage(f"Veri konumu güncellendi: {new_path}")

    def _stamp_drive_as_official(self, drive_path: str, label: str):
        """Stamp the given drive as official backup disk."""
        try:
            sig = stamp_disk_signature(Path(drive_path), label=f"Resmi Yedek Diski ({label})")
            self.settings.set_data_disk_signature(sig)
            self.top_banner.show_success(
                "✅ Disk Başarıyla İmzalandı",
                f"'{drive_path}' konumu resmi yedekleme diski olarak kaydedildi. Sürücü harfi değişse bile sistem tarafından tanınacaktır.",
                auto_dismiss_seconds=8,
            )
        except Exception as e:
            self.top_banner.show_error("❌ Hata", f"Disk imzalanamadı: {e}")

    def _prompt_change_data_path(self):
        """Prompt the user to select a new data directory."""
        folder = QFileDialog.getExistingDirectory(
            self, "Yeni Veri Dizinini (Ana Depolama Alanı) Seçin", str(Path.cwd())
        )
        if folder:
            self._connect_and_switch_data_path(folder)

    def _register_panels(self):
        self._panel_defs = {
            "mail": (MailViewerPanel, {}),
            "accounts": (AccountPanel, {"settings": self.settings}),
            "sync": (SyncPanel, {"settings": self.settings}),
            "export": (ExportPanel, {}),
            "backup": (BackupPanel, {}),
            "restore": (RestorePanel, {}),
            "search": (SearchPanel, {}),
            "audit": (AuditPanel, {}),
            "schedule": (SchedulePanel, {}),
            "report": (ReportPanel, {}),
            "health": (HealthPanel, {}),
            "settings": (SettingsPanel, {"settings": self.settings}),
        }
        self.panels = {}
        # Only instantiate the initial landing panel immediately
        self._get_or_create_panel("mail")

    def _get_or_create_panel(self, key: str) -> Optional[QWidget]:
        """Lazily instantiate panels only when navigated to."""
        if key in self.panels:
            return self.panels[key]

        if key in self._panel_defs:
            PanelClass, extra_kwargs = self._panel_defs[key]
            kwargs = {"engine": self.engine, "parent": self}
            kwargs.update(extra_kwargs)
            panel = PanelClass(**kwargs)
            self.panels[key] = panel
            self.stack.addWidget(panel)

            if self.current_user and hasattr(panel, "apply_permissions"):
                try:
                    panel.apply_permissions(self.current_user.role)
                except Exception:
                    pass
            return panel
        return None

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate(self, key: str):
        if key == "users":
            for k, btn in self.nav_buttons.items():
                btn.setChecked(k == "users")
            settings_panel = self._get_or_create_panel("settings")
            if settings_panel:
                self.stack.setCurrentWidget(settings_panel)
                if hasattr(settings_panel, "tabs"):
                    settings_panel.tabs.setCurrentIndex(0)
                self.page_title.setText("👥 Program Kullanıcıları & Yetkilendirme (RBAC)")
                self.page_title.setToolTip("Yazılıma giriş yapan kullanıcıları (Admin, Operatör, İzleyici), şifreleri ve yetkileri yönetin.")
                self.status.showMessage("Kullanıcı Yönetimi paneline geçildi.")
                if hasattr(settings_panel, "refresh"):
                    settings_panel.refresh()
            return

        panel = self._get_or_create_panel(key)
        if panel:
            for k, btn in self.nav_buttons.items():
                btn.setChecked(k == key)
            self.stack.setCurrentWidget(panel)
            # Update header title & tooltip hints
            titles = {
                "mail": "Mail İzleyici",
                "accounts": "📮 E-Posta Hesap Yönetimi (Yedeklenecek Mail Hesapları)",
                "sync": "E-Posta Senkronizasyonu",
                "export": "Dışa Aktarım ve Sunucu Göçü Çalışma Alanı",
                "backup": "🛡️ Yedekleme ve Kurtarma Merkezi",
                "restore": "Yedekten Geri Yükleme",
                "search": "Detaylı Mail Arama",
                "audit": "Denetim ve Log İzi",
                "schedule": "Zamanlanmış Görevler",
                "report": "Sistem ve Arşiv Raporları",
                "health": "Sistem Sağlığı",
                "settings": "Uygulama Ayarları ve Port Teşhis Paneli",
            }
            descriptions = {
                "mail": "Arşivlenmiş e-postaları asenkron olarak görüntüleyin.",
                "accounts": "Yedeklenecek şirket e-posta ve IMAP hesaplarını ekleyin, düzenleyin ve yönetin.",
                "sync": "Sunucudan e-postaları indirin, önizleyin ve arşivleyin.",
                "export": "Dışa aktarım tanımları ve IMAP sunucularına aktarım.",
                "backup": "SQL Veritabanları (MSSQL, MySQL, Postgres, SQLite), Canlı VHDX/Hyper-V disk ve E-Posta yedekleme yönetimi.",
                "restore": "Arşivlenmiş verileri aktif çalışma alanına geri yükleyin.",
                "search": "Gönderen, alıcı, konu ve gövdede hızlı arama.",
                "audit": "Veri işlemlerini izleyin ve denetim loglarını denetleyin.",
                "schedule": "Otomatik arşivleme ve yedekleme zamanlayıcıları.",
                "report": "Veritabanı kullanımı ve mesaj boyutları analitiği.",
                "health": "Veritabanı durumu, indeks doğrulaması ve ağ gecikme testleri.",
                "settings": "Uygulama tercihleri, depolama alanları ve port analizörü.",
            }
            self.page_title.setText(titles.get(key, key.title()))
            self.page_title.setToolTip(descriptions.get(key, ""))
            self.status.showMessage(f"Navigated to {titles.get(key, key.title())}")

            # Refresh panel data
            if hasattr(panel, "refresh"):
                panel.refresh()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    @Slot()
    def _open_settings(self):
        """Navigate to settings & diagnostic workspace."""
        self._navigate("settings")

    @Slot()
    def _open_export_dialog(self):
        """Navigate to export workspace."""
        self._navigate("export")

    @Slot()
    def _toggle_sidebar(self):
        """Toggle sidebar collapsed (Icons Only) vs expanded (Full)."""
        collapsed = self.sidebar.width() > 70
        self.sidebar.setFixedWidth(58 if collapsed else 220)
        
        from core.version import get_version
        if collapsed:
            # When collapsed: only logo remains at top
            self.brand.setVisible(False)
            self.btn_toggle_sidebar.setVisible(False)
            self.lbl_brand_logo.setVisible(True)
            self.lbl_brand_logo.setAlignment(Qt.AlignCenter)
            self.brand_layout.setContentsMargins(0, 4, 0, 8)
            self.brand_layout.setAlignment(Qt.AlignCenter)
            if hasattr(self, "lbl_footer_logo"):
                self.lbl_footer_logo.setVisible(False)
            if hasattr(self, "lbl_app_ver"):
                self.lbl_app_ver.setText(f"v{get_version()[:4]}")
        else:
            # When expanded: brand text, logo and toggle button
            self.brand.setVisible(True)
            self.btn_toggle_sidebar.setVisible(True)
            self.btn_toggle_sidebar.setText("◀")
            self.lbl_brand_logo.setVisible(True)
            self.lbl_brand_logo.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.brand_layout.setContentsMargins(4, 4, 4, 8)
            self.brand_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            if hasattr(self, "lbl_footer_logo"):
                self.lbl_footer_logo.setVisible(True)
            if hasattr(self, "lbl_app_ver"):
                self.lbl_app_ver.setText(f"v{get_version()}")

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
            with open(STYLE_PATH, encoding="utf-8") as f:
                qss = f.read()
                app = QApplication.instance()
                if app:
                    app.setStyleSheet(qss)
                else:
                    self.setStyleSheet(qss)


    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if getattr(self, "_force_quit", False):
            self.engine.shutdown()
            event.accept()
            return

        from PySide6.QtWidgets import QMessageBox, QSystemTrayIcon
        
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

        reply = QMessageBox(self)
        reply.setWindowTitle("Program Kapanış Onayı")
        
        if sync_running or export_running:
            reply.setText(
                "<b>⚠️ Arka planda çalışan aktif arşivleme veya dışa aktarım işlemleri mevcut!</b><br/><br/>"
                "Programın arka planda (Sistem Tepsisinde) çalışmaya devam etmesini mi, "
                "yoksa tüm işlemleri durdurarak tamamen kapanmasını mı istersiniz?"
            )
        else:
            reply.setText(
                "<b>Mail Arşivleme Sisteminden çıkmak üzeresiniz.</b><br/><br/>"
                "Zamanlanmış görevlerin ve disk izleyicisinin arka planda çalışmaya devam etmesi için "
                "uygulamayı sistem tepsisine küçültebilir veya tamamen kapatabilirsiniz."
            )
        
        btn_background = reply.addButton("Arka Planda Çalıştır (Tepsiye Küçült)", QMessageBox.ButtonRole.AcceptRole)
        btn_exit = reply.addButton("Tamamen Kapat", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = reply.addButton("Vazgeç (Pencerede Kal)", QMessageBox.ButtonRole.RejectRole)
        
        reply.setStyleSheet("""
            QMessageBox { background-color: #f8fafc; }
            QLabel { font-size: 12px; color: #0f172a; }
            QPushButton { padding: 6px 14px; font-size: 11.5px; border-radius: 6px; font-weight: 600; min-height: 26px; }
        """)
        reply.exec()
        
        clicked_button = reply.clickedButton()
        if clicked_button == btn_background:
            event.ignore()
            self.hide()
            if self.tray_icon.isSystemTrayAvailable():
                self.tray_icon.showMessage(
                    "Toya Mail Arşivleme Sistemi",
                    "Uygulama arka planda çalışmaya devam ediyor. Tekrar açmak için tepsi simgesine çift tıklayabilirsiniz.",
                    QSystemTrayIcon.MessageIcon.Information,
                    4000
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
        self.tray_icon.setToolTip("Toya Yedek - E-Posta Arşivleme Sistemi")
        
        tray_menu = QMenu(self)
        tray_menu.setStyleSheet("""
            QMenu {
                background-color: #1e3a8a;
                color: #ffffff;
                border: 1px solid #1e40af;
                border-radius: 6px;
                padding: 4px;
                font-weight: 600;
                font-size: 11.5px;
            }
            QMenu::item {
                padding: 6px 20px 6px 10px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2563eb;
            }
        """)

        show_action = QAction("🖥️ Pencereyi Göster", self)
        show_action.triggered.connect(self.show_and_activate)
        
        stop_action = QAction("⏹️ Aktif Senkronizasyonları Durdur", self)
        stop_action.triggered.connect(self._stop_all_active_syncs)
        
        exit_action = QAction("🚪 Programı Tamamen Kapat", self)
        exit_action.triggered.connect(self.exit_completely)
        
        tray_menu.addAction(show_action)
        tray_menu.addAction(stop_action)
        tray_menu.addSeparator()
        tray_menu.addAction(exit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_icon_activated)
        self.tray_icon.show()

    def _stop_all_active_syncs(self):
        if hasattr(self, "panels") and "sync" in self.panels:
            try:
                self.panels["sync"]._cancel_sync()
                self.tray_icon.showMessage(
                    "Toya Mail Arşivleme",
                    "Aktif senkronizasyon işlemleri durduruldu.",
                    QSystemTrayIcon.MessageIcon.Warning,
                    3000
                )
            except Exception:
                pass
        
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
        self.engine = getattr(parent, "engine", None)
        self.setWindowTitle("Storage Settings")
        self.setMinimumSize(620, 400)
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

        if self.engine:
            self.btn_reorganize = QPushButton("⚙️ Klasör Yapısını Optimize Et")
            self.btn_reorganize.setStyleSheet(
                "QPushButton { background: #f59e0b; color: white; border: none; "
                "border-radius: 4px; padding: 6px 16px; font-weight: bold; }"
                "QPushButton:hover { background: #d97706; }"
            )
            self.btn_reorganize.clicked.connect(self._on_reorganize_archive)
            btn_row.addWidget(self.btn_reorganize)

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

    def _on_reorganize_archive(self):
        from gui.dialogs.archive_optimizer_dialog import ArchiveOptimizerDialog
        dialog = ArchiveOptimizerDialog(self.engine, self.settings, self)
        dialog.exec()
