"""
test_auth_and_rbac.py — Unit and integration tests for Authentication and Role-Based Access Control (RBAC).
"""

import tempfile
import unittest
from pathlib import Path

from core.database import DatabaseManager
from core.auth_manager import AuthManager, Permissions, hash_password, verify_password
from core.mail_engine import MailEngine
from domain.entities import Role, User


class TestAuthAndRbac(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_auth.db"
        self.engine = MailEngine(db_path=self.db_path)
        self.auth = self.engine.auth

    def tearDown(self):
        try:
            self.engine.db.close()
        except Exception:
            pass
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_password_hashing_and_salting(self):
        """Test PBKDF2 password hashing produces salt and verifies properly."""
        password = "EnterpriseSecurePassword2026!"
        h, s = hash_password(password)
        self.assertIsNotNone(h)
        self.assertIsNotNone(s)
        self.assertNotEqual(h, password)

        # Verification with correct password
        self.assertTrue(verify_password(password, h, s))

        # Verification with wrong password
        self.assertFalse(verify_password("WrongPassword123", h, s))

    def test_default_admin_seeding(self):
        """Test default admin user is seeded automatically on fresh database."""
        users = self.auth.list_users()
        self.assertGreaterEqual(len(users), 1)

        admin_user = next((u for u in users if u["username"] == "admin"), None)
        self.assertIsNotNone(admin_user)
        self.assertEqual(admin_user["role"], "ADMIN")

        # Verify admin login with default credentials
        success, user, msg = self.auth.login("admin", "admin123")
        self.assertTrue(success)
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "admin")
        self.assertEqual(user.role, Role.ADMIN)

    def test_user_crud_operations(self):
        """Test creating, reading, updating, and deleting users."""
        # Create operator user
        ok, msg, user_id = self.auth.create_user(
            username="operator1",
            password="OperatorPassword123!",
            role="OPERATOR",
            full_name="Mehmet Demir",
            email="mehmet@sirket.com"
        )
        self.assertTrue(ok)
        self.assertIsNotNone(user_id)

        # Test duplicate username rejection
        ok_dup, msg_dup, _ = self.auth.create_user(
            username="operator1",
            password="AnotherPassword",
            role="VIEWER"
        )
        self.assertFalse(ok_dup)
        self.assertIn("zaten mevcut", msg_dup)

        # Update password
        ok_pw, msg_pw = self.auth.update_user_password(user_id, "NewOperatorPass456!")
        self.assertTrue(ok_pw)

        # Test login with new password
        ok_login, user_obj, _ = self.auth.login("operator1", "NewOperatorPass456!")
        self.assertTrue(ok_login)
        self.assertEqual(user_obj.full_name, "Mehmet Demir")

        # Delete user
        ok_del, _ = self.auth.delete_user(user_id)
        self.assertTrue(ok_del)

        # Ensure user can no longer log in
        ok_after_del, _, _ = self.auth.login("operator1", "NewOperatorPass456!")
        self.assertFalse(ok_after_del)

    def test_role_based_permissions(self):
        """Test permission checking across ADMIN, OPERATOR, and VIEWER roles."""
        # 1. Admin login
        self.auth.login("admin", "admin123")
        self.assertTrue(self.auth.has_permission(Permissions.MANAGE_USERS))
        self.assertTrue(self.auth.has_permission(Permissions.BACKUP_TRIGGER))
        self.assertTrue(self.auth.has_permission(Permissions.BACKUP_CREATE_JOB))
        self.assertTrue(self.auth.has_permission(Permissions.RESTORE_TRIGGER))
        self.assertTrue(self.auth.has_permission(Permissions.MANAGE_SETTINGS))

        # 2. Create and login as Operator
        self.auth.create_user("operator_test", "Pass123!", role="OPERATOR")
        self.auth.login("operator_test", "Pass123!")
        self.assertFalse(self.auth.has_permission(Permissions.MANAGE_USERS))
        self.assertFalse(self.auth.has_permission(Permissions.MANAGE_SETTINGS))
        self.assertTrue(self.auth.has_permission(Permissions.BACKUP_TRIGGER))
        self.assertTrue(self.auth.has_permission(Permissions.BACKUP_CREATE_JOB))
        self.assertTrue(self.auth.has_permission(Permissions.RESTORE_TRIGGER))

        # 3. Create and login as Viewer
        self.auth.create_user("viewer_test", "Pass123!", role="VIEWER")
        self.auth.login("viewer_test", "Pass123!")
        self.assertFalse(self.auth.has_permission(Permissions.MANAGE_USERS))
        self.assertFalse(self.auth.has_permission(Permissions.BACKUP_TRIGGER))
        self.assertFalse(self.auth.has_permission(Permissions.BACKUP_CREATE_JOB))
        self.assertFalse(self.auth.has_permission(Permissions.RESTORE_TRIGGER))
        self.assertTrue(self.auth.has_permission(Permissions.VIEW_DASHBOARD))
        self.assertTrue(self.auth.has_permission(Permissions.VIEW_AUDIT))


if __name__ == "__main__":
    unittest.main()
