"""
backup_usecase.py — Cloud backup use case.

Clean Architecture — Use Case Layer.
Coordinates archiving local data to S3 or Google Drive.
Supports filtering, dry-run, multipart upload, and exponential backoff.
"""

import io
import json
import logging
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.crypto_utils import CryptoManager
from core.database import DatabaseManager
from core.event_bus import EventBus, Event, Events
from domain.entities import BackupReport
from domain.interfaces import CloudStorageProvider
from domain.repositories import (
    IAccountRepository, IAuditRepository,
)
from infrastructure.s3_client import S3Client
from infrastructure.gdrive_client import GoogleDriveClient
from plugins.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)

MBOX_DIR = Path("data/exports")
ARCHIVE_DIR = Path("data/archives")


class ArchiveFilter:
    """Filter criteria for selecting mails to back up."""

    def __init__(
        self,
        folders: Optional[List[str]] = None,
        before_date: Optional[str] = None,
        after_date: Optional[str] = None,
        sender_contains: Optional[str] = None,
        subject_contains: Optional[str] = None,
        only_unread: bool = False,
        only_with_attachments: bool = False,
    ):
        self.folders = folders
        self.before_date = before_date
        self.after_date = after_date
        self.sender_contains = sender_contains
        self.subject_contains = subject_contains
        self.only_unread = only_unread
        self.only_with_attachments = only_with_attachments

    def to_sql_conditions(self) -> tuple:
        """Return (WHERE_clause, params) for SQL query."""
        conditions = ["m.is_deleted = 0"]
        params: List[Any] = []

        if self.folders:
            placeholders = ", ".join("?" for _ in self.folders)
            conditions.append(f"m.folder IN ({placeholders})")
            params.extend(self.folders)
        if self.before_date:
            conditions.append("m.date < ?")
            params.append(self.before_date)
        if self.after_date:
            conditions.append("m.date > ?")
            params.append(self.after_date)
        if self.sender_contains:
            conditions.append("m.sender LIKE ?")
            params.append(f"%{self.sender_contains}%")
        if self.subject_contains:
            conditions.append("m.subject LIKE ?")
            params.append(f"%{self.subject_contains}%")
        if self.only_unread:
            conditions.append("m.flags NOT LIKE '%\\Seen%'")
        if self.only_with_attachments:
            conditions.append("m.has_attachments = 1")

        return " AND ".join(conditions), params


class BackupUseCase:
    """Orchestrates backups to cloud providers."""

    def __init__(
        self,
        db: DatabaseManager,
        account_repo: IAccountRepository,
        audit_repo: IAuditRepository,
        event_bus: EventBus,
        crypto: CryptoManager,
        provider_registry: Optional[ProviderRegistry] = None,
    ):
        self._db = db
        self._account_repo = account_repo
        self._audit_repo = audit_repo
        self._event_bus = event_bus
        self._crypto = crypto
        self._provider_registry = provider_registry or ProviderRegistry()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def backup_to_s3(
        self,
        account_id: int,
        bucket_name: str,
        region: str = "us-east-1",
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        archive_filter: Optional[ArchiveFilter] = None,
        dry_run: bool = False,
    ) -> BackupReport:
        """Backup mails from an account to Amazon S3.

        Creates a tar.gz archive of mails and uploads to S3.
        """
        report = BackupReport(target="s3", started_at=datetime.utcnow().isoformat())
        start = time.time()

        client = S3Client(bucket_name, region, access_key_id, secret_access_key)
        if not client.connect():
            report.errors = 1
            return report

        if dry_run:
            count = self._estimate_mail_count(account_id, archive_filter)
            logger.info("DRY RUN: Would backup %d mails to S3 bucket '%s'", count, bucket_name)
            report.mails_backed_up = count
            return report

        try:
            self._event_bus.publish(Event(Events.BACKUP_STARTED, {
                "account_id": account_id,
                "target": "s3",
                "bucket": bucket_name,
            }))

            # Create archive
            archive_path = self._create_archive(account_id, archive_filter, "s3")
            if not archive_path:
                report.errors = 1
                return report

            # Upload to S3
            remote_key = f"backups/{archive_path.name}"
            success = client.upload(archive_path, remote_key)

            if success:
                report.mails_backed_up = self._get_filtered_count(account_id, archive_filter)
                report.total_bytes = archive_path.stat().st_size
                report.parts_uploaded = 1
                archive_path.unlink()  # Clean up local temp file
            else:
                report.errors = 1

            self._audit_repo.append("backup.s3", account_id=account_id, details={
                "bucket": bucket_name,
                "remote_key": remote_key,
                "success": success,
                "size_bytes": report.total_bytes,
            })

        except Exception as exc:
            logger.exception("S3 backup failed: %s", exc)
            report.errors += 1
        finally:
            report.duration_seconds = time.time() - start
            report.finished_at = datetime.utcnow().isoformat()

        self._event_bus.publish(Event(Events.BACKUP_COMPLETED, {
            "account_id": account_id,
            "report": report.__dict__,
        }))

        return report

    def backup_to_gdrive(
        self,
        account_id: int,
        archive_filter: Optional[ArchiveFilter] = None,
        dry_run: bool = False,
        credentials_path: Optional[Path] = None,
    ) -> BackupReport:
        """Backup mails from an account to Google Drive."""
        report = BackupReport(target="gdrive", started_at=datetime.utcnow().isoformat())
        start = time.time()

        client = GoogleDriveClient(credentials_path)
        if not client.connect():
            report.errors = 1
            return report

        if dry_run:
            count = self._estimate_mail_count(account_id, archive_filter)
            logger.info("DRY RUN: Would backup %d mails to Google Drive", count)
            report.mails_backed_up = count
            return report

        try:
            self._event_bus.publish(Event(Events.BACKUP_STARTED, {
                "account_id": account_id,
                "target": "gdrive",
            }))

            archive_path = self._create_archive(account_id, archive_filter, "gdrive")
            if not archive_path:
                report.errors = 1
                return report

            remote_name = f"mail_backup_{account_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.tar.gz"
            success = client.upload(archive_path, remote_name)

            if success:
                report.mails_backed_up = self._get_filtered_count(account_id, archive_filter)
                report.total_bytes = archive_path.stat().st_size
                report.parts_uploaded = 1
                archive_path.unlink()
            else:
                report.errors = 1

            self._audit_repo.append("backup.gdrive", account_id=account_id, details={
                "remote_name": remote_name,
                "success": success,
                "size_bytes": report.total_bytes,
            })

        except Exception as exc:
            logger.exception("GDrive backup failed: %s", exc)
            report.errors += 1
        finally:
            report.duration_seconds = time.time() - start
            report.finished_at = datetime.utcnow().isoformat()

        self._event_bus.publish(Event(Events.BACKUP_COMPLETED, {
            "account_id": account_id,
            "report": report.__dict__,
        }))

        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_archive(self, account_id: int, archive_filter: Optional[ArchiveFilter],
                        prefix: str) -> Optional[Path]:
        """Create a tar.gz archive of filtered mails from the local database."""
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        archive_path = ARCHIVE_DIR / f"{prefix}_backup_{account_id}_{timestamp}.tar.gz"

        where_clause, params = "", []
        if archive_filter:
            where_clause, params = archive_filter.to_sql_conditions()
            params = [account_id] + params
        else:
            where_clause = "m.account_id = ?"
            params = [account_id]

        try:
            with tarfile.open(archive_path, "w:gz") as tar:
                with self._db.get_conn() as conn:
                    rows = conn.execute(
                        f"""SELECT m.id, m.uid, m.folder, m.subject, m.sender, m.date,
                                   m.message_id, m.sha256_hash, r.raw_data
                            FROM mail_metadata m
                            LEFT JOIN mail_raw r ON r.mail_id = m.id
                            WHERE {where_clause}
                            ORDER BY m.date""",
                        params
                    ).fetchall()

                    for row in rows:
                        # Create a JSON metadata file per mail
                        meta = {
                            "uid": row["uid"],
                            "folder": row["folder"],
                            "subject": row["subject"],
                            "sender": row["sender"],
                            "date": row["date"],
                            "message_id": row["message_id"],
                            "sha256": row["sha256_hash"] or "",
                        }
                        meta_bytes = json.dumps(meta).encode("utf-8")
                        info = tarfile.TarInfo(name=f"mails/{row['id']:09d}_meta.json")
                        info.size = len(meta_bytes)
                        tar.addfile(info, io.BytesIO(meta_bytes))

                        # Add raw email if available
                        raw = row["raw_data"]
                        if raw:
                            info = tarfile.TarInfo(name=f"mails/{row['id']:09d}.eml")
                            info.size = len(raw)
                            tar.addfile(info, io.BytesIO(raw))

            logger.info("Created archive: %s (%d mails)", archive_path,
                        len(rows) if 'rows' in dir() else 0)
            return archive_path

        except Exception as exc:
            logger.error("Failed to create archive: %s", exc)
            if archive_path.exists():
                archive_path.unlink()
            return None

    def _estimate_mail_count(self, account_id: int,
                             archive_filter: Optional[ArchiveFilter]) -> int:
        """Count how many mails match the filter (for dry-run)."""
        where_clause, params = "", []
        if archive_filter:
            where_clause, params = archive_filter.to_sql_conditions()
            params = [account_id] + params
        else:
            where_clause = "m.account_id = ?"
            params = [account_id]

        with self._db.get_conn() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM mail_metadata m WHERE {where_clause}",
                params
            ).fetchone()
            return row["cnt"] if row else 0

    def _get_filtered_count(self, account_id: int,
                            archive_filter: Optional[ArchiveFilter]) -> int:
        return self._estimate_mail_count(account_id, archive_filter)
