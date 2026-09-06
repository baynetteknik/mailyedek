"""
Test script for AccountGroupSidebarWidget, AccountRightSidebarWidget, and AccountPanel.
"""

import sys
import unittest
import tempfile
import shutil
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from core.database import DatabaseManager
from core.crypto_utils import CryptoManager
from core.mail_engine import MailEngine
from core.settings import AppSettings
from gui.widgets.account_group_sidebar_widget import AccountGroupSidebarWidget, CollapsibleSection
from gui.widgets.account_right_sidebar_widget import AccountRightSidebarWidget
from gui.widgets.account_panel import AccountPanel

# Ensure QApplication exists
app = QApplication.instance() or QApplication(sys.argv)


from gui.widgets.view_profile_widget import SaveLayoutProfileDialog


class TestAccountWidgets(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="account_test_")
        self.temp_dir_path = Path(self.temp_dir)
        self.temp_db_path = self.temp_dir_path / "test_account.db"
        self.temp_key_path = self.temp_dir_path / "test_account.key"
        
        self.settings = AppSettings(settings_dir=self.temp_dir_path)
        self.engine = MailEngine(db_path=self.temp_db_path, key_file=self.temp_key_path)

    def tearDown(self):
        self.engine.db.close()
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    def test_save_layout_profile_dialog(self):
        existing = ["Varsayılan", "Kompakt", "Geniş"]
        
        # 1. Test with existing profile -> warning should be shown
        dlg1 = SaveLayoutProfileDialog(existing_profiles=existing, current_profile="Kompakt")
        self.assertFalse(dlg1.lbl_warning.isHidden())
        self.assertIn("üzerine yaz", dlg1.btn_save.text().lower())
        self.assertIn("değiştirilecektir", dlg1.lbl_warning.text().lower())
        self.assertEqual(dlg1.list_profiles.count(), 3)

        # 2. Test typing new profile -> warning hidden, new text on button
        dlg1.txt_profile_name.setText("Yeni_Duzen_2026")
        self.assertTrue(dlg1.lbl_warning.isHidden())
        self.assertIn("yeni", dlg1.btn_save.text().lower())

        # 3. Test clicking existing profile from list widget
        item = dlg1.list_profiles.item(0) # "Varsayılan"
        dlg1._on_list_item_clicked(item)
        self.assertEqual(dlg1.txt_profile_name.text(), "Varsayılan")
        self.assertFalse(dlg1.lbl_warning.isHidden())
        self.assertIn("değiştirilecektir", dlg1.lbl_warning.text().lower())

    def test_account_group_sidebar_widget(self):
        sidebar = AccountGroupSidebarWidget()
        
        # 1. Sections should be collapsed by default
        self.assertTrue(sidebar.sec_filter.is_collapsed())
        self.assertTrue(sidebar.sec_bulk.is_collapsed())

        # Test expanding
        sidebar.sec_filter.toggle()
        self.assertFalse(sidebar.sec_filter.is_collapsed())

        groups_data = {
            "4umedical.com.tr": {"is_active": True, "count": 10},
            "baynet.com.tr": {"is_active": True, "count": 5},
            "pasifdomain.com": {"is_active": False, "count": 2},
        }
        sidebar.populate_groups(groups_data, total_accounts_count=17)

        # 2. Total items should be 4 (Tüm Gruplar + 3 domains)
        self.assertEqual(sidebar.group_list.count(), 4)
        self.assertEqual(sidebar.get_selected_group(), "__ALL__")

        # 3. Select group
        sidebar.select_group("4umedical.com.tr")
        self.assertEqual(sidebar.get_selected_group(), "4umedical.com.tr")

        # 4. RBAC permissions
        sidebar.apply_permissions("viewer")
        self.assertTrue(sidebar.sec_bulk.isHidden())

        sidebar.apply_permissions("admin")
        self.assertFalse(sidebar.sec_bulk.isHidden())
        self.assertTrue(sidebar.btn_open_group_mgmt.isEnabled())
        self.assertTrue(sidebar.btn_bulk_subfolder.isEnabled())

    def test_account_right_sidebar_widget(self):
        sidebar = AccountRightSidebarWidget()

        # 1. Sections should be collapsed by default
        self.assertTrue(sidebar.sec_layout.is_collapsed())
        self.assertTrue(sidebar.sec_email.is_collapsed())
        self.assertTrue(sidebar.sec_excel.is_collapsed())

        # 2. Selection state
        sidebar.update_selection_state(has_selection=True, is_active=True)
        self.assertTrue(sidebar.btn_edit.isEnabled())
        self.assertTrue(sidebar.btn_copy.isEnabled())
        self.assertTrue(sidebar.btn_delete.isEnabled())
        self.assertIn("Pasif Yap", sidebar.btn_toggle_active.text())

        sidebar.update_selection_state(has_selection=False)
        self.assertFalse(sidebar.btn_edit.isEnabled())
        self.assertFalse(sidebar.btn_delete.isEnabled())

        # 3. Excel mode toggle
        self.assertFalse(sidebar.is_excel_mode_enabled())
        sidebar.set_excel_mode(True)
        self.assertTrue(sidebar.is_excel_mode_enabled())
        sidebar.set_excel_mode(False)
        self.assertFalse(sidebar.is_excel_mode_enabled())

        # 4. RBAC
        sidebar.apply_permissions("operator")
        self.assertTrue(sidebar.btn_add.isEnabled())
        self.assertFalse(sidebar.btn_clean_start.isEnabled())

        sidebar.apply_permissions("viewer")
        self.assertFalse(sidebar.btn_add.isEnabled())
        self.assertFalse(sidebar.sec_excel.isEnabled())

    def test_account_panel_integration(self):
        # Add test accounts
        acc1 = self.engine.add_account("Test 1", "info@4umedical.com.tr", "imap.4umedical.com.tr", 993, 1, "info@4umedical.com.tr", "secret")
        acc2 = self.engine.add_account("Test 2", "sales@baynet.com.tr", "imap.baynet.com.tr", 993, 1, "sales@baynet.com.tr", "secret")
        
        with self.engine.db.transaction() as conn:
            conn.execute("UPDATE accounts SET account_group = '4umedical.com.tr' WHERE id = ?", (acc1,))
            conn.execute("UPDATE accounts SET account_group = 'baynet.com.tr' WHERE id = ?", (acc2,))

        panel = AccountPanel(self.engine, settings=self.settings)
        self.assertEqual(panel.table.rowCount(), 2)

        # Verify middle toggle buttons exist
        self.assertIsNotNone(panel.btn_middle_toggle_left)
        self.assertIsNotNone(panel.btn_middle_toggle_right)

        # Test middle toggle buttons & logo behavior on collapse
        self.assertFalse(panel.left_sidebar.isHidden())
        panel.btn_middle_toggle_left.click()
        self.assertTrue(panel.left_sidebar.isHidden())
        
        # When collapsed, Toya logo is set if available
        logo_path = Path("gui/resources/toya_logo.png")
        if logo_path.exists():
            self.assertFalse(panel.btn_middle_toggle_left.icon().isNull())
            self.assertIn("TOYA ERP", panel.btn_toggle_left.text())
        else:
            self.assertEqual(panel.btn_middle_toggle_left.text(), "▶")

        panel.btn_middle_toggle_left.click()
        self.assertFalse(panel.left_sidebar.isHidden())
        self.assertEqual(panel.btn_middle_toggle_left.text(), "◀")

        # Test setting row heights
        panel.set_row_height(28)
        self.assertEqual(panel._current_row_height, 28)
        self.assertEqual(panel.table.rowHeight(0), 28)

        panel.set_row_height(44)
        self.assertEqual(panel._current_row_height, 44)
        self.assertEqual(panel.table.rowHeight(0), 44)

        # Test layout profile save & load
        panel._save_grid_profile("Kompakt_Test")
        profiles = panel.right_sidebar.view_profile_widget.manager.get_profiles()
        self.assertIn("Kompakt_Test", profiles.get("profiles", {}))
        self.assertEqual(profiles["profiles"]["Kompakt_Test"]["row_height"], 44)

        # Test RBAC
        panel.apply_permissions("viewer")
        self.assertEqual(panel._current_role, "viewer")

    def test_main_window_sidebar_branding_and_collapse(self):
        from gui.main_window import MainWindow
        win = MainWindow(engine=self.engine, settings=self.settings)

        # 1. Branding should be Toya Yedek
        self.assertIn("Toya Yedek", win.brand.text())
        self.assertIn("Toya Yedek", win.windowTitle())

        # 2. Version label should only show version, without 'Baynet Teknik'
        from core.version import get_version
        self.assertNotIn("Baynet Teknik", win.lbl_app_ver.text())
        self.assertIn(get_version()[:4], win.lbl_app_ver.text())

        # 3. Dedicated footer logo slot should exist
        self.assertIsNotNone(win.lbl_footer_logo)

        # 4. Collapse behavior: when collapsed, brand text and toggle button are hidden, logo is visible
        if not win.sidebar.width() < 70:
            win._toggle_sidebar()
        
        self.assertTrue(win.sidebar.width() <= 60)
        self.assertTrue(win.brand.isHidden())
        self.assertTrue(win.btn_toggle_sidebar.isHidden())
        self.assertFalse(win.lbl_brand_logo.isHidden())

        # 5. Expand behavior: when expanded, brand text and toggle button are visible
        win._toggle_sidebar()
        self.assertTrue(win.sidebar.width() >= 200)
        self.assertFalse(win.brand.isHidden())
        self.assertFalse(win.btn_toggle_sidebar.isHidden())
        self.assertFalse(win.lbl_brand_logo.isHidden())

        win.close()


if __name__ == "__main__":
    unittest.main()
