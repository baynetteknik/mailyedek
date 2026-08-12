"""
test_server_migration.py — Integration test for multi-server account migration,
incremental append, deduplication, and audit chain verification.
"""

import os
import tempfile
import unittest
from pathlib import Path

from core.database import DatabaseManager
from core.crypto_utils import CryptoManager
from core.mail_engine import MailEngine


class TestServerMigration(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_migration.db"
        self.engine = MailEngine(db_path=self.db_path)
        self.db = self.engine.db

    def tearDown(self):
        if hasattr(self.db, "_local") and hasattr(self.db._local, "conn") and self.db._local.conn:
            try:
                self.db._local.conn.close()
                self.db._local.conn = None
            except Exception:
                pass
        self.temp_dir.cleanup()

    def test_server_migration_flow(self):
        # 1. Add account on old server
        acc_id = self.engine.add_account(
            label="Ahmet Yilmaz",
            email="ahmet@company.com",
            imap_host="mail.oldserver.com",
            imap_port=993,
            use_ssl=True,
            username="ahmet@company.com",
            password="secretpassword",
        )
        self.assertIsNotNone(acc_id)

        # 2. Simulate archived email on old server
        old_mail_id = self.db.upsert_mail_metadata(
            account_id=acc_id,
            folder="INBOX",
            uid=101,
            subject="Eski Sunucu Maili",
            sender="boss@company.com",
            sha256_hash="hash_old_mail_101",
            server_host="mail.oldserver.com"
        )
        self.db.update_sync_state(acc_id, "INBOX", last_uid=101, uid_validity=111, mail_count=1, server_host="mail.oldserver.com")
        self.db.register_hash("hash_old_mail_101", acc_id, old_mail_id)

        # Verify old sync state
        old_state = self.db.get_sync_state(acc_id, "INBOX")
        self.assertEqual(old_state["last_uid"], 101)

        # 3. Change account IMAP host to new server (Server Migration)
        self.engine.update_account(
            acc_id,
            imap_host="mail.newserver.com",
            imap_port=993,
        )

        # 4. Verify sync state reset
        new_state = self.db.get_sync_state(acc_id, "INBOX")
        self.assertEqual(new_state["last_uid"], 0)

        # 5. Verify old mail preserved
        mails_in_db = self.db.get_mails_for_account(acc_id, "INBOX")
        self.assertEqual(len(mails_in_db), 1)
        self.assertEqual(mails_in_db[0]["subject"], "Eski Sunucu Maili")

        # 6. Simulate fetching mails from new server (1 duplicate + 1 new)
        is_dup = self.db.is_duplicate_hash("hash_old_mail_101")
        self.assertTrue(is_dup, "Old mail hash should match duplicate check")

        # Insert duplicate mail record from new server
        dup_mail_id = self.db.upsert_mail_metadata(
            account_id=acc_id,
            folder="INBOX",
            uid=1,
            subject="Eski Sunucu Maili (Migrated)",
            sender="boss@company.com",
            sha256_hash="hash_old_mail_101",
            is_duplicate=1,
            server_host="mail.newserver.com"
        )

        # Insert brand new mail record from new server
        is_new_dup = self.db.is_duplicate_hash("hash_new_mail_2")
        self.assertFalse(is_new_dup)

        new_mail_id = self.db.upsert_mail_metadata(
            account_id=acc_id,
            folder="INBOX",
            uid=2,
            subject="Yeni Sunucudan Gelen Yeni Mail",
            sender="client@company.com",
            sha256_hash="hash_new_mail_2",
            is_duplicate=0,
            server_host="mail.newserver.com"
        )
        self.db.register_hash("hash_new_mail_2", acc_id, new_mail_id)
        self.db.update_sync_state(acc_id, "INBOX", last_uid=2, uid_validity=222, mail_count=2, server_host="mail.newserver.com")

        # 7. Verify combined database state
        all_mails = self.db.get_mails_for_account(acc_id, "INBOX", limit=10)
        self.assertEqual(len(all_mails), 3)

        # 8. Verify audit log integrity
        audit_logs = self.db.get_audit_log(limit=50)
        server_changed_entries = [log for log in audit_logs if log["action"] == "account.server_changed"]
        self.assertEqual(len(server_changed_entries), 1)
        self.assertIn("mail.oldserver.com", server_changed_entries[0]["details"])
        self.assertIn("mail.newserver.com", server_changed_entries[0]["details"])

        # Check cryptographic chain verification
        is_audit_valid = self.db.verify_audit_chain()
        self.assertTrue(is_audit_valid, "Audit log hash chain should be valid and tamper-proof")


if __name__ == "__main__":
    unittest.main()
