"""
test_export_migration.py — Integration test for multi-server export filtering,
incremental append / duplicate skipping, and audit log chain verification.
"""

import tempfile
import unittest
from pathlib import Path

from core.database import DatabaseManager
from core.crypto_utils import CryptoManager
from core.mail_engine import MailEngine


class TestExportMigration(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_export.db"
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

    def test_export_multi_server_filtering_and_audit(self):
        # 1. Add account
        acc_id = self.engine.add_account(
            label="Mehmet Kaya",
            email="mehmet@company.com",
            imap_host="mail.oldserver.com",
            imap_port=993,
            use_ssl=True,
            username="mehmet@company.com",
            password="secretpassword",
        )

        # 2. Add emails from old server
        mail1_id = self.db.upsert_mail_metadata(
            account_id=acc_id,
            folder="INBOX",
            uid=1,
            subject="Mail Old Server 1",
            sender="user1@old.com",
            date="2025-01-01 10:00:00",
            server_host="mail.oldserver.com",
            sha256_hash="hash_old_1"
        )
        self.db.store_raw_mail(mail1_id, b"From: user1@old.com\r\nSubject: Mail Old Server 1\r\n\r\nHello from old server")

        # 3. Add emails from new server
        mail2_id = self.db.upsert_mail_metadata(
            account_id=acc_id,
            folder="INBOX",
            uid=2,
            subject="Mail New Server 2",
            sender="user2@new.com",
            date="2025-02-01 10:00:00",
            server_host="mail.newserver.com",
            sha256_hash="hash_new_2"
        )
        self.db.store_raw_mail(mail2_id, b"From: user2@new.com\r\nSubject: Mail New Server 2\r\n\r\nHello from new server")

        export_target = Path(self.temp_dir.name) / "exported_emls"

        # 4. Export with server_host filter "mail.oldserver.com"
        report_old = self.engine.export_mails(
            account_id=acc_id,
            format_type="DIRECTORY",
            output_path=export_target,
            server_host="mail.oldserver.com"
        )
        self.assertEqual(report_old["total"], 1)
        self.assertEqual(report_old["exported"], 1)

        # 5. Export again to same directory to test duplicate skipping (append/dedup mode)
        report_dup = self.engine.export_mails(
            account_id=acc_id,
            format_type="DIRECTORY",
            output_path=export_target,
            server_host="mail.oldserver.com"
        )
        self.assertEqual(report_dup["total"], 1)
        self.assertEqual(report_dup["exported"], 0)
        self.assertEqual(report_dup["skipped_duplicates"], 1)

        # 6. Verify audit trail entries
        audit_logs = self.db.get_audit_log(limit=50)
        export_logs = [log for log in audit_logs if log["action"].startswith("export.")]
        self.assertGreaterEqual(len(export_logs), 2)
        
        # Verify hash chain integrity
        self.assertTrue(self.db.verify_audit_chain(), "Audit log hash chain must remain valid")


if __name__ == "__main__":
    unittest.main()
