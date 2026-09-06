"""
sql_backup_usecase.py — SQL Database backup use case.

Clean Architecture — Use Case Layer.
Coordinates:
  - Execution of database backups across MSSQL, MySQL, Postgres, SQLite
  - Retention policy cleanup (deleting backups older than N days)
  - Optional cloud uploads (S3, Google Drive)
  - Cryptographic audit trail logging and event publishing
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from core.crypto_utils import CryptoManager
from core.database import DatabaseManager
from core.event_bus import EventBus, Event, Events
from domain.entities import SqlBackupJob, SqlBackupReport
from domain.repositories import IAuditRepository
from infrastructure.sql_backup_client import SqlBackupClient

logger = logging.getLogger(__name__)


class SqlBackupUseCase:
    """Use case for managing and executing SQL database backup operations."""

    def __init__(
        self,
        db: DatabaseManager,
        audit_repo: IAuditRepository,
        event_bus: EventBus,
        crypto: CryptoManager,
        client: Optional[SqlBackupClient] = None,
    ):
        self._db = db
        self._audit_repo = audit_repo
        self._event_bus = event_bus
        self._crypto = crypto
        self._client = client or SqlBackupClient()

    # ------------------------------------------------------------------
    # Connection & Discovery
    # ------------------------------------------------------------------

    def test_connection(
        self,
        engine_type: str,
        host: str,
        port: int,
        auth_type: str,
        username: str = "",
        password: str = "",
        database_name: str = "master",
    ) -> tuple[bool, str]:
        return self._client.test_connection(
            engine_type=engine_type,
            host=host,
            port=port,
            auth_type=auth_type,
            username=username,
            password=password,
            database_name=database_name,
        )

    def list_databases(
        self,
        engine_type: str,
        host: str,
        port: int,
        auth_type: str,
        username: str = "",
        password: str = "",
    ) -> List[str]:
        return self._client.list_databases(
            engine_type=engine_type,
            host=host,
            port=port,
            auth_type=auth_type,
            username=username,
            password=password,
        )

    # ------------------------------------------------------------------
    # Job Management
    # ------------------------------------------------------------------

    def save_job(self, job_data: Dict[str, Any]) -> int:
        data = dict(job_data)
        # Encrypt credentials if raw username / password passed
        if "username" in data and data["username"]:
            data["username_enc"] = self._crypto.encrypt(data.pop("username"))
        if "password" in data and data["password"]:
            data["password_enc"] = self._crypto.encrypt(data.pop("password"))

        return self._db.save_sql_backup_job(data)

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        job = self._db.get_sql_backup_job(job_id)
        if job:
            job = dict(job)
            try:
                job["username"] = self._crypto.decrypt(job.get("username_enc", "")) if job.get("username_enc") else ""
            except Exception:
                job["username"] = ""
            try:
                job["password"] = self._crypto.decrypt(job.get("password_enc", "")) if job.get("password_enc") else ""
            except Exception:
                job["password"] = ""
        return job

    def list_jobs(self) -> List[Dict[str, Any]]:
        jobs = self._db.list_sql_backup_jobs()
        results = []
        for j in jobs:
            job = dict(j)
            try:
                job["username"] = self._crypto.decrypt(job.get("username_enc", "")) if job.get("username_enc") else ""
            except Exception:
                job["username"] = ""
            results.append(job)
        return results

    def delete_job(self, job_id: int) -> bool:
        return self._db.delete_sql_backup_job(job_id)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_backup(
        self,
        job_params: Union[int, Dict[str, Any]],
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> SqlBackupReport:
        """Run a SQL backup by job ID or ad-hoc parameter dict."""
        if isinstance(job_params, int):
            job = self.get_job(job_params)
            if not job:
                raise ValueError(f"SQL yedekleme görevi bulunamadı: ID={job_params}")
        else:
            job = dict(job_params)

        engine_type = job.get("engine_type", "mssql")
        host = job.get("host", "localhost")
        port = int(job.get("port", 1433))
        auth_type = job.get("auth_type", "windows")
        db_name = job.get("database_name", "")
        dest_dir = Path(job.get("dest_dir", "data/backups/sql"))
        backup_type = job.get("backup_type", "FULL")
        compress = bool(job.get("compress", True))
        verify = bool(job.get("verify", True))
        retention_mode = job.get("retention_mode", "count")
        retention_value = int(job.get("retention_value", 10))
        retention_days = int(job.get("retention_days", 30))
        cloud_target = job.get("cloud_target", "none")
        job_name = job.get("name", f"SQL_{db_name}")

        username = job.get("username", "")
        password = job.get("password", "")
        if not username and job.get("username_enc"):
            try:
                username = self._crypto.decrypt(job["username_enc"])
            except Exception:
                pass
        if not password and job.get("password_enc"):
            try:
                password = self._crypto.decrypt(job["password_enc"])
            except Exception:
                pass

        # Execute backup via client
        report = self._client.backup(
            engine_type=engine_type,
            host=host,
            port=port,
            auth_type=auth_type,
            username=username,
            password=password,
            database_name=db_name,
            dest_dir=dest_dir,
            backup_type=backup_type,
            compress=compress,
            verify=verify,
            progress_callback=progress_callback,
        )
        report.job_name = job_name

        # Enforce retention policy if backup succeeded
        if report.status == "SUCCESS" and dest_dir.exists():
            self._enforce_retention(dest_dir, db_name, retention_mode, retention_value, retention_days, progress_callback)

        # Audit log entry
        self._audit_repo.append(
            "backup.sql",
            details={
                "job_name": job_name,
                "engine_type": engine_type,
                "database": db_name,
                "backup_type": backup_type,
                "status": report.status,
                "size_bytes": report.total_bytes,
                "duration_seconds": report.duration_seconds,
                "output_file": report.output_file,
                "errors": report.errors,
            }
        )

        # Unified backup history entry
        self._db.add_backup_history_entry(
            job_type="sql",
            job_name=job_name,
            status=report.status,
            source=f"{engine_type.upper()}://{host}/{db_name}",
            target_file=report.output_file or "",
            size_bytes=report.total_bytes,
            duration_seconds=report.duration_seconds,
            error_message="; ".join(report.errors) if report.errors else "",
        )

        # Send email notification if configured
        self._send_email_notification("sql", job_name, report)

        # Publish event
        self._event_bus.publish(Event(Events.BACKUP_COMPLETED, {
            "type": "sql",
            "report": report.__dict__,
        }))

        return report

    def _enforce_retention(
        self, dest_dir: Path, db_name: str, retention_mode: str,
        retention_value: int, retention_days: int,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> None:
        """Enforce retention policy: keep last N backups or delete files older than X days."""
        try:
            matching_files = [
                f for f in dest_dir.iterdir()
                if f.is_file() and f.name.startswith(db_name) and not f.name.endswith(".tmp")
            ]

            if retention_mode == "count" and retention_value > 0:
                # Sort by modification time descending (newest first)
                matching_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                if len(matching_files) > retention_value:
                    to_delete = matching_files[retention_value:]
                    for f in to_delete:
                        f.unlink()
                        msg = f"En son {retention_value} yedek saklama kuralı gereği eski yedek silindi: {f.name}"
                        logger.info(msg)
                        if progress_callback:
                            progress_callback(msg)

            elif retention_mode == "days" and retention_days > 0:
                cutoff = datetime.now() - timedelta(days=retention_days)
                for f in matching_files:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime < cutoff:
                        f.unlink()
                        msg = f"{retention_days} günden eski yedek silindi: {f.name}"
                        logger.info(msg)
                        if progress_callback:
                            progress_callback(msg)
        except Exception as exc:
            logger.warning("Retention enforcement failed: %s", exc)

    def _send_email_notification(self, job_type: str, job_name: str, report: SqlBackupReport) -> None:
        """Dispatch email notification according to AppSettings."""
        try:
            from core.settings import AppSettings
            from infrastructure.email_notifier import EmailNotifier
            settings = AppSettings()
            smtp_host = settings.get("smtp_host", "")
            if not smtp_host:
                return

            notify_emails = settings.get("notify_emails", "")
            notify_on_success = settings.get("notify_on_success", True)
            notify_on_error = settings.get("notify_on_error", True)

            is_success = (report.status == "SUCCESS")
            if (is_success and not notify_on_success) or (not is_success and not notify_on_error):
                return

            pwd = ""
            if settings.get("smtp_pass_enc"):
                try:
                    pwd = self._crypto.decrypt(settings.get("smtp_pass_enc"))
                except Exception:
                    pass

            EmailNotifier.send_backup_notification(
                host=smtp_host,
                port=int(settings.get("smtp_port", 587)),
                use_tls=bool(settings.get("smtp_use_tls", True)),
                username=settings.get("smtp_user", ""),
                password=pwd,
                from_addr=settings.get("smtp_from", ""),
                to_addrs_str=notify_emails,
                job_type=job_type,
                job_name=job_name,
                report_dict=report.__dict__,
                is_success=is_success,
            )
        except Exception as exc:
            logger.warning("Could not dispatch backup notification email: %s", exc)
