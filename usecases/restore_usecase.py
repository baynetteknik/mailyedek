"""
restore_usecase.py — Restore use case.

Clean Architecture — Use Case Layer.
Handles restoring mails from cloud backups (S3, Google Drive)
back to local database or directly to an IMAP server.
"""

import json
import logging
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.crypto_utils import CryptoManager
from core.database import DatabaseManager
from core.event_bus import EventBus, Event, Events
from core.folder_translator import translate_folder_name
from core.settings import AppSettings
from domain.entities import BackupReport, MailMessage, MailMetadata
from domain.interfaces import CloudStorageProvider, MailProvider
from domain.repositories import (
    IAccountRepository, IMailRepository, IAuditRepository,
)
from infrastructure.imap_client import ImapClient
from infrastructure.s3_client import S3Client
from infrastructure.gdrive_client import GoogleDriveClient
from plugins.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)


class RestoreUseCase:
    """Orchestrates restoration from cloud backups."""

    def __init__(
        self,
        db: DatabaseManager,
        account_repo: IAccountRepository,
        mail_repo: IMailRepository,
        audit_repo: IAuditRepository,
        event_bus: EventBus,
        crypto: CryptoManager,
        provider_registry: Optional[ProviderRegistry] = None,
        settings: Optional[AppSettings] = None,
    ):
        self._db = db
        self._account_repo = account_repo
        self._mail_repo = mail_repo
        self._audit_repo = audit_repo
        self._event_bus = event_bus
        self._crypto = crypto
        self._provider_registry = provider_registry or ProviderRegistry()
        self._settings = settings or AppSettings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def restore_from_s3(
        self,
        remote_key: str,
        bucket_name: str,
        region: str = "us-east-1",
        target_account_id: Optional[int] = None,
        target_imap: bool = False,
        dry_run: bool = False,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        folder_lang: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Restore mails from an S3 backup archive."""
        result = {
            "source": f"s3://{bucket_name}/{remote_key}",
            "mails_restored": 0,
            "errors": 0,
            "hash_verified": 0,
            "hash_failed": 0,
            "duration_seconds": 0.0,
        }
        start = time.time()

        client = S3Client(bucket_name, region, access_key_id, secret_access_key)
        if not client.connect():
            result["errors"] = 1
            return result

        self._event_bus.publish(Event(Events.RESTORE_STARTED, {
            "source": f"s3://{bucket_name}/{remote_key}",
        }))

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "backup.tar.gz"

            if not client.download(remote_key, local_path):
                result["errors"] = 1
                return result

            restore_result = self._process_archive(
                local_path, target_account_id, target_imap, dry_run, folder_lang=folder_lang
            )
            result.update(restore_result)

        result["duration_seconds"] = time.time() - start

        self._event_bus.publish(Event(Events.RESTORE_COMPLETED, result))
        self._audit_repo.append("restore.s3", details={
            "source": f"s3://{bucket_name}/{remote_key}",
            **result,
        })

        return result

    def restore_from_gdrive(
        self,
        remote_name: str,
        target_account_id: Optional[int] = None,
        target_imap: bool = False,
        dry_run: bool = False,
        credentials_path: Optional[Path] = None,
        folder_lang: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Restore mails from a Google Drive backup archive."""
        result = {
            "source": f"gdrive://{remote_name}",
            "mails_restored": 0,
            "errors": 0,
            "hash_verified": 0,
            "hash_failed": 0,
            "duration_seconds": 0.0,
        }
        start = time.time()

        client = GoogleDriveClient(credentials_path)
        if not client.connect():
            result["errors"] = 1
            return result

        self._event_bus.publish(Event(Events.RESTORE_STARTED, {
            "source": f"gdrive://{remote_name}",
        }))

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "backup.tar.gz"

            if not client.download(remote_name, local_path):
                result["errors"] = 1
                return result

            restore_result = self._process_archive(
                local_path, target_account_id, target_imap, dry_run, folder_lang=folder_lang
            )
            result.update(restore_result)

        result["duration_seconds"] = time.time() - start

        self._event_bus.publish(Event(Events.RESTORE_COMPLETED, result))
        self._audit_repo.append("restore.gdrive", details={
            "source": f"gdrive://{remote_name}",
            **result,
        })

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _process_archive(
        self,
        archive_path: Path,
        target_account_id: Optional[int],
        target_imap: bool,
        dry_run: bool,
        folder_lang: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a tar.gz archive and restore mails."""
        import tarfile

        lang = folder_lang if folder_lang is not None else self._settings.folder_translation_restore()

        result = {"mails_restored": 0, "errors": 0,
                  "hash_verified": 0, "hash_failed": 0}

        if not archive_path.exists():
            result["errors"] = 1
            return result

        # Connect to IMAP if needed
        imap_provider: Optional[MailProvider] = None
        if target_imap and target_account_id:
            acc = self._account_repo.get(target_account_id)
            if acc:
                imap_provider = ImapClient()
                username = self._crypto.decrypt(acc["username_enc"])
                password = self._crypto.decrypt(acc["password_enc"])
                if not imap_provider.connect(acc["imap_host"], acc["imap_port"],
                                              bool(acc["use_ssl"]), username, password):
                    logger.error("IMAP connection failed for restore target")
                    result["errors"] += 1
                    imap_provider = None

        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                # Group files by mail ID
                mail_files: Dict[str, Dict[str, Any]] = {}
                for member in tar.getmembers():
                    if not member.isfile():
                        continue
                    # Files are named like: mails/000000001_meta.json or mails/000000001.eml
                    parts = member.name.split("/")
                    if len(parts) != 2:
                        continue
                    prefix = parts[1].split("_")[0].split(".")[0]
                    mail_files.setdefault(prefix, {})
                    if "_meta.json" in member.name:
                        mail_files[prefix]["meta"] = member
                    elif ".eml" in member.name:
                        mail_files[prefix]["eml"] = member

                for mail_id, files in mail_files.items():
                    try:
                        if dry_run:
                            if "meta" in files:
                                f = tar.extractfile(files["meta"])
                                if f:
                                    meta = json.loads(f.read())
                                    logger.info(
                                        "DRY RUN: Would restore mail %s — Subject: %s, From: %s",
                                        mail_id, meta.get("subject", "?"), meta.get("sender", "?")
                                    )
                            result["mails_restored"] += 1
                            continue

                        # Read metadata
                        meta_data = {}
                        if "meta" in files:
                            f = tar.extractfile(files["meta"])
                            if f:
                                meta_data = json.loads(f.read())

                        # Read raw email
                        raw_email = None
                        if "eml" in files:
                            f = tar.extractfile(files["eml"])
                            if f:
                                raw_email = f.read()

                        # Verify hash
                        if raw_email:
                            hash_ok = CryptoManager.hash_content(raw_email) == meta_data.get("sha256", "")
                            if hash_ok:
                                result["hash_verified"] += 1
                            else:
                                result["hash_failed"] += 1
                                logger.warning("Hash mismatch for mail %s", mail_id)

                        # Determine target folder name based on translation setting
                        raw_folder = meta_data.get("folder", "INBOX")
                        target_folder = translate_folder_name(raw_folder, lang)

                        # Push to IMAP server
                        if imap_provider and raw_email:
                            if imap_provider.append_message(target_folder, raw_email):
                                result["mails_restored"] += 1
                            else:
                                result["errors"] += 1

                        # Store in local database
                        if target_account_id and not target_imap:
                            folder = target_folder
                            uid = meta_data.get("uid", 0)
                            subject = meta_data.get("subject", "")
                            sender = meta_data.get("sender", "")
                            date = meta_data.get("date", "")
                            message_id = meta_data.get("message_id", "")
                            sha256 = meta_data.get("sha256", "")
                            
                            mail_id_db = self._mail_repo.upsert(
                                account_id=target_account_id,
                                folder=folder,
                                uid=uid,
                                message_id=message_id,
                                subject=subject,
                                sender=sender,
                                date=date,
                                sha256_hash=sha256,
                            )
                            if raw_email:
                                self._mail_repo.store_raw(mail_id_db, raw_email)
                            result["mails_restored"] += 1

                    except Exception as exc:
                        logger.error("Error restoring mail %s: %s", mail_id, exc)
                        result["errors"] += 1

        except Exception as exc:
            logger.error("Error processing archive: %s", exc)
            result["errors"] += 1
        finally:
            if imap_provider:
                imap_provider.disconnect()

        return result
