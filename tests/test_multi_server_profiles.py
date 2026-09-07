"""
test_multi_server_profiles.py — Integration test for multi-server endpoints per account,
active profile switching, deduplication across servers, and audit log verification.
"""

import tempfile
import unittest
from pathlib import Path

from core.database import DatabaseManager
from core.crypto_utils import CryptoManager
from core.mail_engine import MailEngine


class TestMultiServerProfiles(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_profiles.db"
        self.engine = MailEngine(db_path=self.db_path)
        self.db = self.engine.db

    def tearDown(self):
        try:
            self.engine.db.close()
        except Exception:
            pass
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_multi_server_profiles_flow(self):
        # 1. Create account (creates initial default server profile)
        acc_id = self.engine.add_account(
            label="Ahmet Yilmaz",
            email="ahmet@company.com",
            imap_host="imap.yandex.com",
            imap_port=993,
            use_ssl=True,
            username="ahmet@company.com",
            password="yandex_password",
        )
        self.assertIsNotNone(acc_id)

        # Verify initial server profile
        profiles = self.engine.list_server_profiles(acc_id)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["imap_host"], "imap.yandex.com")
        self.assertTrue(profiles[0]["is_default"])

        # 2. Add secondary server profile (New Company Server)
        new_prof_id = self.engine.add_server_profile(
            account_id=acc_id,
            profile_name="Yeni Şirket Sunucusu",
            imap_host="mail.newcompany.com",
            imap_port=993,
            use_ssl=True,
            username="ahmet@newcompany.com",
            password="new_password",
            make_default=False,
        )
        self.assertIsNotNone(new_prof_id)

        # Verify both profiles listed
        profiles_after_add = self.engine.list_server_profiles(acc_id)
        self.assertEqual(len(profiles_after_add), 2)
        yandex_prof = next(p for p in profiles_after_add if p["imap_host"] == "imap.yandex.com")
        new_prof = next(p for p in profiles_after_add if p["imap_host"] == "mail.newcompany.com")
        self.assertTrue(yandex_prof["is_default"])
        self.assertFalse(new_prof["is_default"])

        # 3. Simulate syncing from Yandex (active profile)
        active_prof = self.db.get_active_server_profile(acc_id)
        self.assertEqual(active_prof["imap_host"], "imap.yandex.com")

        mail1_id = self.db.upsert_mail_metadata(
            account_id=acc_id,
            folder="INBOX",
            uid=1001,
            subject="Yandex Eski Mail 1",
            sender="friend@yandex.com",
            server_host="imap.yandex.com",
            sha256_hash="hash_yandex_1001"
        )
        self.db.register_hash("hash_yandex_1001", acc_id, mail1_id)
        self.db.update_sync_state(acc_id, "INBOX", last_uid=1001, uid_validity=1, mail_count=1, server_host="imap.yandex.com")

        # 4. Switch active default profile to New Company Server
        self.engine.set_default_server_profile(acc_id, new_prof_id)

        # Verify new active profile
        active_prof_after_switch = self.db.get_active_server_profile(acc_id)
        self.assertEqual(active_prof_after_switch["imap_host"], "mail.newcompany.com")
        acc_db = self.db.get_account(acc_id)
        self.assertEqual(acc_db["imap_host"], "mail.newcompany.com")

        # 5. Simulate syncing from New Company Server (1 duplicate + 1 new mail)
        is_yandex_mail_dup = self.db.is_duplicate_hash("hash_yandex_1001")
        self.assertTrue(is_yandex_mail_dup, "Yandex mail should be recognized as duplicate")

        # Insert duplicate record
        self.db.upsert_mail_metadata(
            account_id=acc_id,
            folder="INBOX",
            uid=1,
            subject="Yandex Eski Mail 1 (Migrated)",
            sender="friend@yandex.com",
            server_host="mail.newcompany.com",
            sha256_hash="hash_yandex_1001",
            is_duplicate=1,
        )

        # Insert brand new mail on new server
        mail3_id = self.db.upsert_mail_metadata(
            account_id=acc_id,
            folder="INBOX",
            uid=2,
            subject="Yeni Sunucu Özel Mail",
            sender="boss@newcompany.com",
            server_host="mail.newcompany.com",
            sha256_hash="hash_new_2002",
            is_duplicate=0,
        )
        self.db.register_hash("hash_new_2002", acc_id, mail3_id)
        self.db.update_sync_state(acc_id, "INBOX", last_uid=2, uid_validity=2, mail_count=2, server_host="mail.newcompany.com")

        # 6. Verify unified archive state
        all_mails = self.db.get_mails_for_account(acc_id, "INBOX", limit=10)
        self.assertEqual(len(all_mails), 3)

        # 7. Test identical UID on both servers without conflict (e.g. UID 1001 on both Yandex and NewCompany)
        mail_dup_uid = self.db.upsert_mail_metadata(
            account_id=acc_id,
            folder="INBOX",
            uid=1001,
            subject="New Company Mail with same UID 1001",
            sender="colleague@newcompany.com",
            server_host="mail.newcompany.com",
            sha256_hash="hash_new_1001",
            is_duplicate=0
        )
        self.assertIsNotNone(mail_dup_uid)
        self.assertNotEqual(mail1_id, mail_dup_uid)

        # 8. Verify Audit Log
        audit_logs = self.db.get_audit_log(limit=50)
        actions = [log["action"] for log in audit_logs]
        self.assertIn("account.server_profile_added", actions)
        self.assertIn("account.default_server_changed", actions)

        # Verify cryptographic chain integrity
        self.assertTrue(self.db.verify_audit_chain(), "Audit log hash chain must remain valid")


if __name__ == "__main__":
    unittest.main()
