"""
vhdx_backup_usecase.py — VHDX / Hyper-V backup use case.

Clean Architecture — Use Case Layer.
Coordinates:
  - Execution of Hyper-V VM export and direct VHDX disk backup
  - Retention policy enforcement
  - Audit logging and event publishing
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from core.crypto_utils import CryptoManager
from core.database import DatabaseManager
from core.event_bus import EventBus, Event, Events
from domain.entities import VhdxBackupJob, VhdxBackupReport
from domain.repositories import IAuditRepository
from infrastructure.vhdx_backup_client import VhdxBackupClient

logger = logging.getLogger(__name__)


class VhdxBackupUseCase:
    """Use case for managing and executing VHDX and Hyper-V VM backups."""

    def __init__(
        self,
        db: DatabaseManager,
        audit_repo: IAuditRepository,
        event_bus: EventBus,
        crypto: CryptoManager,
        client: Optional[VhdxBackupClient] = None,
    ):
        self._db = db
        self._audit_repo = audit_repo
        self._event_bus = event_bus
        self._crypto = crypto
        self._client = client or VhdxBackupClient()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_hyperv_vms(self) -> List[Dict[str, Any]]:
        return self._client.list_hyperv_vms()

    # ------------------------------------------------------------------
    # Job Management
    # ------------------------------------------------------------------

    def save_job(self, job_data: Dict[str, Any]) -> int:
        return self._db.save_vhdx_backup_job(job_data)

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        return self._db.get_vhdx_backup_job(job_id)

    def list_jobs(self) -> List[Dict[str, Any]]:
        return self._db.list_vhdx_backup_jobs()

    def delete_job(self, job_id: int) -> bool:
        return self._db.delete_vhdx_backup_job(job_id)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_backup(
        self,
        job_params: Union[int, Dict[str, Any]],
        progress_callback: Optional[Callable[[str, float, float], None]] = None,
    ) -> VhdxBackupReport:
        """Run a VHDX / Hyper-V backup by job ID or ad-hoc parameter dict."""
        if isinstance(job_params, int):
            job = self.get_job(job_params)
            if not job:
                raise ValueError(f"VHDX yedekleme görevi bulunamadı: ID={job_params}")
        else:
            job = dict(job_params)

        mode = job.get("mode", "direct_file")
        vm_name = job.get("vm_name", "")
        source_path = job.get("source_path", "")
        dest_dir = Path(job.get("dest_dir", "data/backups/vhdx"))
        use_vss = bool(job.get("use_vss", True))
        compress = bool(job.get("compress", False))
        compress_mode = str(job.get("compress_mode", "raw"))
        verify_hash = bool(job.get("verify_hash", True))
        retention_mode = str(job.get("retention_mode", "count"))
        retention_value = int(job.get("retention_value", 10))
        retention_days = int(job.get("retention_days", 30))
        job_name = job.get("name", f"VHDX_{Path(source_path).stem if source_path else vm_name}")

        if mode == "hyperv_vm":
            report = self._client.backup_hyperv_vm(
                vm_name=vm_name,
                dest_dir=dest_dir,
                compress=(compress or compress_mode == "compressed"),
                progress_callback=progress_callback,
            )
        else:
            report = self._client.backup_vhdx_file(
                source_path_str=source_path,
                dest_dir=dest_dir,
                use_vss=use_vss,
                compress=compress,
                compress_mode=compress_mode,
                verify_hash=verify_hash,
                progress_callback=progress_callback,
            )

        report.job_name = job_name

        # Enforce retention policy if backup succeeded
        if report.status == "SUCCESS" and dest_dir.exists():
            stem_match = vm_name if mode == "hyperv_vm" else Path(source_path).stem
            self._enforce_retention(dest_dir, stem_match, retention_mode, retention_value, retention_days, progress_callback)

        # Audit log entry
        self._audit_repo.append(
            "backup.vhdx",
            details={
                "job_name": job_name,
                "mode": mode,
                "source": report.source,
                "status": report.status,
                "size_bytes": report.total_bytes,
                "duration_seconds": report.duration_seconds,
                "speed_mbps": report.speed_mbps,
                "used_vss": report.used_vss,
                "sha256": report.sha256_hash,
                "dest_file": report.dest_file,
                "errors": report.errors,
            }
        )

        # Unified backup history entry
        self._db.add_backup_history_entry(
            job_type="vhdx",
            job_name=job_name,
            status=report.status,
            source=report.source,
            target_file=report.dest_file or "",
            size_bytes=report.total_bytes,
            duration_seconds=report.duration_seconds,
            error_message="; ".join(report.errors) if report.errors else "",
        )

        # Send email notification if configured
        self._send_email_notification("vhdx", job_name, report)

        # Publish event
        self._event_bus.publish(Event(Events.BACKUP_COMPLETED, {
            "type": "vhdx",
            "report": report.__dict__,
        }))

        return report

    def _enforce_retention(
        self, dest_dir: Path, stem_match: str, retention_mode: str,
        retention_value: int, retention_days: int,
        progress_callback: Optional[Callable[[str, float, float], None]] = None
    ) -> None:
        """Enforce retention policy: keep last N backups or delete files older than X days."""
        try:
            matching_items = [
                item for item in dest_dir.iterdir()
                if item.name.startswith(stem_match) and not item.name.endswith(".tmp")
            ]

            if retention_mode == "count" and retention_value > 0:
                matching_items.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                if len(matching_items) > retention_value:
                    to_delete = matching_items[retention_value:]
                    for item in to_delete:
                        if item.is_dir():
                            import shutil
                            shutil.rmtree(item, ignore_errors=True)
                        else:
                            item.unlink()
                        msg = f"En son {retention_value} yedek saklama kuralı gereği eski imaj silindi: {item.name}"
                        logger.info(msg)
                        if progress_callback:
                            progress_callback(msg, 100.0, 0.0)

            elif retention_mode == "days" and retention_days > 0:
                cutoff = datetime.now() - timedelta(days=retention_days)
                for item in matching_items:
                    mtime = datetime.fromtimestamp(item.stat().st_mtime)
                    if mtime < cutoff:
                        if item.is_dir():
                            import shutil
                            shutil.rmtree(item, ignore_errors=True)
                        else:
                            item.unlink()
                        msg = f"{retention_days} günden eski imaj silindi: {item.name}"
                        logger.info(msg)
                        if progress_callback:
                            progress_callback(msg, 100.0, 0.0)
        except Exception as exc:
            logger.warning("VHDX retention enforcement failed: %s", exc)

    def _send_email_notification(self, job_type: str, job_name: str, report: VhdxBackupReport) -> None:
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
            logger.warning("Could not dispatch VHDX backup notification email: %s", exc)
