"""
test_sql_vhdx_backup.py — Comprehensive unit and integration tests for SQL and VHDX backups.
"""

import gzip
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.database import DatabaseManager
from core.crypto_utils import CryptoManager
from core.mail_engine import MailEngine
from infrastructure.sql_backup_client import SqlBackupClient
from infrastructure.vhdx_backup_client import VhdxBackupClient


class TestSqlVhdxBackup(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_backup.db"
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

    # ------------------------------------------------------------------
    # SQL Backup Tests
    # ------------------------------------------------------------------

    def test_sql_job_crud(self):
        """Test creating, reading, listing, and deleting SQL backup jobs."""
        job_id = self.engine.save_sql_job({
            "name": "MSSQL Daily Job",
            "engine_type": "mssql",
            "host": "sqlserver.corp",
            "port": 1433,
            "auth_type": "sql",
            "username": "backup_user",
            "password": "SuperSecretPassword123!",
            "database_name": "AccountingDB",
            "backup_type": "FULL",
            "dest_dir": str(Path(self.temp_dir.name) / "sql_dest"),
            "compress": True,
            "verify": True,
            "retention_days": 15,
        })
        self.assertIsNotNone(job_id)
        self.assertGreater(job_id, 0)

        # Retrieve and verify decrypted fields
        job = self.engine.get_sql_job(job_id)
        self.assertEqual(job["name"], "MSSQL Daily Job")
        self.assertEqual(job["engine_type"], "mssql")
        self.assertEqual(job["username"], "backup_user")
        self.assertEqual(job["password"], "SuperSecretPassword123!")
        self.assertEqual(job["retention_days"], 15)

        # List jobs
        jobs = self.engine.list_sql_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], job_id)

        # Delete job
        del_success = self.engine.delete_sql_job(job_id)
        self.assertTrue(del_success)
        self.assertEqual(len(self.engine.list_sql_jobs()), 0)

    def test_sqlite_backup_execution_and_history(self):
        """Test running an actual SQLite database backup with compression and verification."""
        # Create a sample SQLite DB to back up
        sample_db_path = Path(self.temp_dir.name) / "sample_data.db"
        with sqlite3.connect(str(sample_db_path)) as conn:
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO users (name) VALUES ('Ahmet Yilmaz'), ('Ayse Demir')")

        dest_dir = Path(self.temp_dir.name) / "sql_backups"

        # Run backup
        report = self.engine.run_sql_backup({
            "name": "SQLite Sample Backup",
            "engine_type": "sqlite",
            "host": str(sample_db_path),
            "database_name": "sample_data",
            "dest_dir": str(dest_dir),
            "compress": True,
            "verify": True,
            "retention_days": 30,
        })

        self.assertEqual(report["status"], "SUCCESS")
        self.assertTrue(report["verified"])
        self.assertGreater(report["total_bytes"], 0)
        self.assertTrue(Path(report["output_file"]).exists())
        self.assertTrue(report["output_file"].endswith(".gz"))

        # Verify history was recorded
        history = self.engine.list_backup_history(job_type="sql")
        self.assertGreaterEqual(len(history), 1)
        self.assertEqual(history[0]["job_name"], "SQLite Sample Backup")
        self.assertEqual(history[0]["status"], "SUCCESS")

        # Verify audit log chain
        self.assertTrue(self.db.verify_audit_chain(), "Audit log hash chain must remain valid")

    # ------------------------------------------------------------------
    # VHDX Backup Tests
    # ------------------------------------------------------------------

    def test_vhdx_job_crud(self):
        """Test creating, reading, listing, and deleting VHDX backup jobs."""
        job_id = self.engine.save_vhdx_job({
            "name": "Web VM VHDX Backup",
            "mode": "direct_file",
            "source_path": "D:\\VirtualMachines\\Web01\\Virtual Hard Disks\\Disk1.vhdx",
            "dest_dir": str(Path(self.temp_dir.name) / "vhdx_dest"),
            "use_vss": True,
            "compress": False,
            "verify_hash": True,
            "retention_days": 7,
        })
        self.assertIsNotNone(job_id)
        self.assertGreater(job_id, 0)

        job = self.engine.get_vhdx_job(job_id)
        self.assertEqual(job["name"], "Web VM VHDX Backup")
        self.assertEqual(job["mode"], "direct_file")
        self.assertEqual(job["retention_days"], 7)

        jobs = self.engine.list_vhdx_jobs()
        self.assertEqual(len(jobs), 1)

        del_success = self.engine.delete_vhdx_job(job_id)
        self.assertTrue(del_success)
        self.assertEqual(len(self.engine.list_vhdx_jobs()), 0)

    def test_vhdx_file_stream_backup_and_hash(self):
        """Test streaming copy of a virtual disk file with SHA-256 calculation and progress tracking."""
        # Create a mock 4 MB VHDX disk file with random content
        source_vhdx = Path(self.temp_dir.name) / "test_vm_disk.vhdx"
        test_payload = b"VHDX_HEADER_TEST_BLOCK_DATA" * (1024 * 128)  # ~3.45 MB
        source_vhdx.write_bytes(test_payload)
        expected_sha256 = hashlib.sha256(test_payload).hexdigest()

        dest_dir = Path(self.temp_dir.name) / "vhdx_backups"

        progress_events = []

        def on_progress(msg, pct, speed):
            progress_events.append((msg, pct, speed))

        report = self.engine.run_vhdx_backup({
            "name": "Test Disk Backup",
            "mode": "direct_file",
            "source_path": str(source_vhdx),
            "dest_dir": str(dest_dir),
            "use_vss": False,  # Direct stream for test
            "compress": False,
            "verify_hash": True,
            "retention_days": 30,
        }, progress_callback=on_progress)

        self.assertEqual(report["status"], "SUCCESS")
        self.assertEqual(report["sha256_hash"], expected_sha256)
        self.assertEqual(report["total_bytes"], len(test_payload))
        self.assertTrue(Path(report["dest_file"]).exists())
        self.assertGreater(len(progress_events), 0)

        # Verify history entry
        history = self.engine.list_backup_history(job_type="vhdx")
        self.assertGreaterEqual(len(history), 1)
        self.assertEqual(history[0]["job_name"], "Test Disk Backup")
        self.assertEqual(history[0]["status"], "SUCCESS")

        # Verify audit log chain
        self.assertTrue(self.db.verify_audit_chain(), "Audit log hash chain must remain valid")

    def test_vhdx_compressed_stream_backup(self):
        """Test streaming copy with gzip compression and verify payload matches after decompression."""
        source_vhdx = Path(self.temp_dir.name) / "compress_test.vhdx"
        test_payload = b"COMPRESSION_TEST_DATA_PAYLOAD_1234567890" * 50000
        source_vhdx.write_bytes(test_payload)

        dest_dir = Path(self.temp_dir.name) / "vhdx_compressed"

        report = self.engine.run_vhdx_backup({
            "name": "Compressed VHDX Test",
            "mode": "direct_file",
            "source_path": str(source_vhdx),
            "dest_dir": str(dest_dir),
            "use_vss": False,
            "compress": True,
            "verify_hash": True,
            "retention_days": 30,
        })

        self.assertEqual(report["status"], "SUCCESS")
        self.assertTrue(Path(report["dest_file"]).exists())
        self.assertTrue(report["dest_file"].endswith(".gz"))

        # Decompress and verify content
        with gzip.open(report["dest_file"], "rb") as f_gz:
            decompressed = f_gz.read()
        self.assertEqual(decompressed, test_payload)

    def test_vhdx_size_modes_raw_and_dynamic(self):
        """Test VHDX size modes: raw (1:1 copy) vs dynamic (sparse mode)."""
        source_vhdx = Path(self.temp_dir.name) / "size_mode_test.vhdx"
        test_payload = b"DYNAMIC_SPARSE_TEST_BLOCK_12345" * 10000
        source_vhdx.write_bytes(test_payload)

        # 1. Raw mode (1:1 uncompressed)
        dest_raw = Path(self.temp_dir.name) / "vhdx_raw"
        rep_raw = self.engine.run_vhdx_backup({
            "name": "Raw VHDX Test",
            "mode": "direct_file",
            "source_path": str(source_vhdx),
            "dest_dir": str(dest_raw),
            "use_vss": False,
            "compress_mode": "raw",
            "verify_hash": True,
        })
        self.assertEqual(rep_raw["status"], "SUCCESS")
        self.assertTrue(rep_raw["dest_file"].endswith(".vhdx"))
        self.assertEqual(Path(rep_raw["dest_file"]).stat().st_size, len(test_payload))

        # 2. Dynamic mode (sparse transfer)
        dest_dyn = Path(self.temp_dir.name) / "vhdx_dynamic"
        rep_dyn = self.engine.run_vhdx_backup({
            "name": "Dynamic VHDX Test",
            "mode": "direct_file",
            "source_path": str(source_vhdx),
            "dest_dir": str(dest_dyn),
            "use_vss": False,
            "compress_mode": "dynamic",
            "verify_hash": True,
        })
        self.assertEqual(rep_dyn["status"], "SUCCESS")
        self.assertTrue(rep_dyn["dest_file"].endswith(".vhdx"))
        self.assertEqual(Path(rep_dyn["dest_file"]).stat().st_size, len(test_payload))

    def test_count_based_retention_keeping_last_10(self):
        """Test count-based retention policy ('En son 10 yedeği sakla')."""
        sample_db_path = Path(self.temp_dir.name) / "retention_test.db"
        with sqlite3.connect(str(sample_db_path)) as conn:
            conn.execute("CREATE TABLE t (id INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")

        dest_dir = Path(self.temp_dir.name) / "count_retention_backups"
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Run backup 12 times with count retention = 5 to verify it keeps only the newest 5
        for i in range(12):
            report = self.engine.run_sql_backup({
                "name": "RetentionJob",
                "engine_type": "sqlite",
                "host": str(sample_db_path),
                "database_name": "retention_test",
                "dest_dir": str(dest_dir),
                "compress": True,
                "verify": True,
                "retention_mode": "count",
                "retention_value": 5,
            })
            self.assertEqual(report["status"], "SUCCESS")

        # Verify only 5 files exist in destination directory
        existing_files = list(dest_dir.glob("*.gz"))
        self.assertEqual(len(existing_files), 5, f"Expected 5 files to be retained, found {len(existing_files)}")

    def test_disk_watcher_and_backup_scanner(self):
        """Test DiskWatcher drive enumeration and recursive backup scanning."""
        from infrastructure.disk_watcher import DiskWatcher

        watcher = DiskWatcher()
        drives = watcher.list_drives()
        self.assertIsInstance(drives, list)
        self.assertGreater(len(drives), 0, "At least one drive (e.g. C:) must be found on Windows")

        # Create mock backups in temp directory
        mock_drive = Path(self.temp_dir.name) / "MockUSB"
        mock_drive.mkdir(parents=True, exist_ok=True)
        (mock_drive / "Accounting_20260904.bak").write_bytes(b"MOCK_SQL_BACKUP")
        (mock_drive / "ServerDC.vhdx").write_bytes(b"MOCK_VHDX_DATA")
        (mock_drive / "mail_archive.db").write_bytes(b"MOCK_MAIL_DB")

        scan_result = watcher.scan_drive_backups(str(mock_drive))
        self.assertEqual(len(scan_result["sql_backups"]), 1)
        self.assertEqual(len(scan_result["vhdx_backups"]), 1)
        self.assertEqual(len(scan_result["mail_backups"]), 1)
        self.assertEqual(len(scan_result["all_backups"]), 3)

    def test_email_notifier_template_and_config(self):
        """Test EmailNotifier HTML / text formatting for backup reports."""
        from infrastructure.email_notifier import EmailNotifier
        from domain.entities import SmtpNotificationConfig, SqlBackupReport

        notifier = EmailNotifier()
        cfg = SmtpNotificationConfig(
            enabled=True,
            host="smtp.example.com",
            port=587,
            username="backup@example.com",
            password="secretpassword",
            from_address="backup@example.com",
            to_addresses=["admin@example.com"],
            notify_on_success=True,
            notify_on_failure=True,
        )

        report = SqlBackupReport(
            job_name="Daily SQL Backup",
            engine_type="mssql",
            database_name="CustomerDB",
            backup_type="FULL",
            output_file="D:\\Backups\\SQL\\CustomerDB.bak",
            total_bytes=104857600,  # 100 MB
            duration_seconds=12.5,
            status="SUCCESS",
            verified=True,
        )

        html_body = notifier.format_report_html("SQL Veritabanı", report.job_name, report.status, report.__dict__)
        self.assertIn("Daily SQL Backup", html_body)
        self.assertIn("BAŞARILI", html_body)
        self.assertIn("100.00 MB", html_body)
        self.assertIn("D:\\Backups\\SQL\\CustomerDB.bak", html_body)

    def test_disk_signature_stamping_and_recognition(self):
        """Test stamping .mail_yedek_disk_id signature and recognizing backup drives."""
        from infrastructure.disk_identifier import (
            stamp_disk_signature,
            get_disk_signature,
            inspect_drive_recognition,
            remove_disk_signature,
        )
        from core.settings import AppSettings

        mock_disk_path = Path(self.temp_dir.name) / "MyOfficialBackupDrive"
        mock_disk_path.mkdir(parents=True, exist_ok=True)

        # Before stamping: should be unrecognized
        sig_before = get_disk_signature(mock_disk_path)
        self.assertIsNone(sig_before)

        recog_before = inspect_drive_recognition(str(mock_disk_path))
        self.assertFalse(recog_before["is_recognized"])

        # Stamp signature
        stamped = stamp_disk_signature(mock_disk_path, label="Şirket Ana Yedek Diski")
        self.assertIsNotNone(stamped.get("disk_id"))
        self.assertEqual(stamped["label"], "Şirket Ana Yedek Diski")

        # After stamping: should be recognized
        sig_after = get_disk_signature(mock_disk_path)
        self.assertIsNotNone(sig_after)
        self.assertEqual(sig_after["disk_id"], stamped["disk_id"])

        # Test AppSettings persistence
        settings_dir = Path(self.temp_dir.name) / "settings"
        settings = AppSettings(settings_dir=settings_dir)
        settings.set_data_disk_signature(stamped)
        loaded_sig = settings.data_disk_signature()
        self.assertEqual(loaded_sig["disk_id"], stamped["disk_id"])

        # Test inspection with registered signature
        recog_after = inspect_drive_recognition(
            str(mock_disk_path), registered_signature=loaded_sig
        )
        self.assertTrue(recog_after["is_recognized"])
        self.assertEqual(recog_after["match_type"], "official_signature_match")

        # Clean up
        removed = remove_disk_signature(mock_disk_path)
        self.assertTrue(removed)
        self.assertIsNone(get_disk_signature(mock_disk_path))

    def test_backup_panel_layout_and_interactions(self):
        """Test BackupPanel widget initialization, 2-column form extraction, and collapsible log."""
        import sys
        from PySide6.QtWidgets import QApplication
        from gui.widgets.backup_panel import BackupPanel

        app = QApplication.instance() or QApplication(sys.argv)
        panel = BackupPanel(self.engine)
        
        # Test collapsible log
        self.assertTrue(panel.log_output.isHidden())
        panel._toggle_live_log()
        self.assertFalse(panel.log_output.isHidden())
        panel._toggle_live_log()
        self.assertTrue(panel.log_output.isHidden())

        # Test drive refresh
        panel._refresh_all_drive_combos()
        self.assertGreaterEqual(panel.sql_drive_combo.count(), 1)
        self.assertGreaterEqual(panel.vhdx_drive_combo.count(), 1)

        # Test SQL Form extraction
        sql_data = panel._get_sql_form_data()
        self.assertIn("engine_type", sql_data)
        self.assertIn("dest_dir", sql_data)
        self.assertIn("retention_mode", sql_data)

        # Test VHDX Form extraction
        vhdx_data = panel._get_vhdx_form_data()
        self.assertIn("mode", vhdx_data)
        self.assertIn("compress_mode", vhdx_data)
        self.assertIn("dest_dir", vhdx_data)


if __name__ == "__main__":
    unittest.main()

