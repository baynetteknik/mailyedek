"""
mail_engine.py — High-level mail engine facade.

Clean Architecture — Core Service Layer.
Provides a simplified interface for the CLI/GUI/API to interact with
the mail system without knowing about use cases or infrastructure.

This is the main entry point for the application logic.
"""

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.crypto_utils import CryptoManager
from core.database import DatabaseManager
from core.event_bus import EventBus, Event, Events, get_event_bus
from domain.repositories import (
    IAccountRepository, IMailRepository, ISyncStateRepository,
    IAttachmentRepository, IDeduplicationRepository,
    IAuditRepository, IStatsRepository,
)
from infrastructure.sqlite_repository import (
    SqliteAccountRepository, SqliteMailRepository,
    SqliteSyncStateRepository, SqliteAttachmentRepository,
    SqliteDeduplicationRepository, SqliteAuditRepository,
    SqliteStatsRepository,
)
from plugins.provider_registry import ProviderRegistry
from usecases.sync_usecase import SyncUseCase
from usecases.backup_usecase import ArchiveFilter
from usecases.backup_usecase import BackupUseCase
from usecases.restore_usecase import RestoreUseCase
from usecases.export_usecase import ExportUseCase

logger = logging.getLogger(__name__)


class MailEngine:
    """Facade that wires together all components.

    Provides a unified API for CLI, REST API, or GUI consumers.
    """

    def __init__(self, db_path: Optional[Path] = None,
                 key_file: Optional[Path] = None,
                 use_keyring: bool = False):
        # Core infrastructure
        self.crypto = CryptoManager(key_file=key_file, use_keyring=use_keyring)
        self.db = DatabaseManager(db_path=db_path)
        self.event_bus = get_event_bus()

        # Repositories
        self.accounts = SqliteAccountRepository(self.db)
        self.mails = SqliteMailRepository(self.db)
        self.sync_states = SqliteSyncStateRepository(self.db)
        self.attachments = SqliteAttachmentRepository(self.db)
        self.dedup = SqliteDeduplicationRepository(self.db)
        self.audit = SqliteAuditRepository(self.db)
        self.stats = SqliteStatsRepository(self.db)

        # Plugin registry
        self.provider_registry = ProviderRegistry()

        # Use cases
        self.sync_usecase = SyncUseCase(
            db=self.db,
            account_repo=self.accounts,
            mail_repo=self.mails,
            sync_state_repo=self.sync_states,
            attachment_repo=self.attachments,
            dedup_repo=self.dedup,
            audit_repo=self.audit,
            event_bus=self.event_bus,
            crypto=self.crypto,
            provider_registry=self.provider_registry,
        )
        self.backup_usecase = BackupUseCase(
            db=self.db,
            account_repo=self.accounts,
            audit_repo=self.audit,
            event_bus=self.event_bus,
            crypto=self.crypto,
            provider_registry=self.provider_registry,
        )
        self.restore_usecase = RestoreUseCase(
            db=self.db,
            account_repo=self.accounts,
            mail_repo=self.mails,
            audit_repo=self.audit,
            event_bus=self.event_bus,
            crypto=self.crypto,
            provider_registry=self.provider_registry,
        )
        self.export_usecase = ExportUseCase(
            db=self.db,
        )

        logger.info("MailEngine initialized")

    # ------------------------------------------------------------------
    # Account management
    # ------------------------------------------------------------------

    def add_account(self, label: str, email: str, imap_host: str,
                    imap_port: int = 993, use_ssl: bool = True,
                    username: str = None, password: str = None) -> int:
        """Add a new email account. Credentials are encrypted before storage."""
        if username is None:
            username = email
        if password is None:
            raise ValueError("Password is required")

        username_enc = self.crypto.encrypt(username)
        password_enc = self.crypto.encrypt(password)

        account_id = self.accounts.add(
            label=label,
            email=email,
            imap_host=imap_host,
            imap_port=imap_port,
            use_ssl=use_ssl,
            username_enc=username_enc,
            password_enc=password_enc,
        )

        self.audit.append("account.added", account_id=account_id)
        self.event_bus.publish(Event(Events.ACCOUNT_ADDED, {
            "account_id": account_id,
            "label": label,
            "email": CryptoManager.mask_email(email),
        }))

        return account_id

    def list_accounts(self) -> List[Dict]:
        """Return all accounts with masked credentials."""
        accounts = self.accounts.get_all()
        for acc in accounts:
            try:
                if "username_enc" in acc and acc["username_enc"]:
                    acc["username"] = self.crypto.decrypt(acc["username_enc"])
                del acc["username_enc"]
            except Exception:
                acc["username"] = "(decryption error)"
                acc.pop("username_enc", None)
            if "password_enc" in acc:
                del acc["password_enc"]
        return accounts

    def remove_account(self, account_id: int) -> None:
        self.accounts.delete(account_id)
        self.audit.append("account.removed", account_id=account_id)
        self.event_bus.publish(Event(Events.ACCOUNT_REMOVED, {
            "account_id": account_id,
        }))

    # ------------------------------------------------------------------
    # Sync operations
    # ------------------------------------------------------------------

    def sync_all(self, account_ids: Optional[List[int]] = None,
                 log_callback: Optional[Callable] = None,
                 cancel_event: Optional[threading.Event] = None,
                 account_callback: Optional[Callable[[str], None]] = None,
                 folder_filter: Optional[List[str]] = None,
                 pause_event: Optional[threading.Event] = None,
                 since_date: Optional[str] = None,
                 before_date: Optional[str] = None,
                 archive_unread: bool = True,
                 timeout: int = 300,
                 progress_callback: Optional[Callable[[int, str, int, int], None]] = None
                 ) -> List[Dict]:
        """Synchronize all (or specified) accounts."""
        reports = self.sync_usecase.sync_all(
            account_ids, log_callback=log_callback,
            cancel_event=cancel_event, account_callback=account_callback,
            folder_filter=folder_filter, pause_event=pause_event,
            since_date=since_date, before_date=before_date,
            archive_unread=archive_unread, timeout=timeout,
            progress_callback=progress_callback,
        )
        return [r.__dict__ for r in reports]

    def sync_account(self, account_id: int,
                      log_callback: Optional[Callable] = None,
                      cancel_event: Optional[threading.Event] = None,
                      folder_filter: Optional[List[str]] = None,
                      pause_event: Optional[threading.Event] = None,
                      since_date: Optional[str] = None,
                      before_date: Optional[str] = None,
                      archive_unread: bool = True,
                      timeout: int = 300,
                      progress_callback: Optional[Callable[[int, str, int, int], None]] = None
                      ) -> Dict:
        """Synchronize a single account."""
        report = self.sync_usecase.sync_account(
            account_id, log_callback=log_callback, cancel_event=cancel_event,
            folder_filter=folder_filter, pause_event=pause_event,
            since_date=since_date, before_date=before_date,
            archive_unread=archive_unread, timeout=timeout,
            progress_callback=progress_callback,
        )
        return report.__dict__

    def sync_dry_run(self, account_id: int,
                     log_callback: Optional[Callable] = None,
                     folder_filter: Optional[List[str]] = None,
                     since_date: Optional[str] = None,
                     before_date: Optional[str] = None,
                     archive_unread: bool = True) -> Dict:
        """Preview what would be synced."""
        return self.sync_usecase.dry_run(
            account_id, log_callback=log_callback, folder_filter=folder_filter,
            since_date=since_date, before_date=before_date,
            archive_unread=archive_unread,
        )

    # ------------------------------------------------------------------
    # Backup operations
    # ------------------------------------------------------------------

    def backup_to_s3(self, account_id: int, bucket_name: str,
                     region: str = "us-east-1",
                     access_key_id: str = None,
                     secret_access_key: str = None,
                     before_date: str = None,
                     dry_run: bool = False) -> Dict:
        archive_filter = ArchiveFilter(before_date=before_date) if before_date else None
        report = self.backup_usecase.backup_to_s3(
            account_id=account_id,
            bucket_name=bucket_name,
            region=region,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            archive_filter=archive_filter,
            dry_run=dry_run,
        )
        return report.__dict__

    def backup_to_gdrive(self, account_id: int,
                         before_date: str = None,
                         dry_run: bool = False,
                         credentials_path: Path = None) -> Dict:
        archive_filter = ArchiveFilter(before_date=before_date) if before_date else None
        report = self.backup_usecase.backup_to_gdrive(
            account_id=account_id,
            archive_filter=archive_filter,
            dry_run=dry_run,
            credentials_path=credentials_path,
        )
        return report.__dict__

    # ------------------------------------------------------------------
    # Restore operations
    # ------------------------------------------------------------------

    def restore_from_s3(self, remote_key: str, bucket_name: str,
                        target_account_id: int = None,
                        target_imap: bool = False,
                        dry_run: bool = False) -> Dict:
        return self.restore_usecase.restore_from_s3(
            remote_key=remote_key,
            bucket_name=bucket_name,
            target_account_id=target_account_id,
            target_imap=target_imap,
            dry_run=dry_run,
        )

    def restore_from_gdrive(self, remote_name: str,
                            target_account_id: int = None,
                            target_imap: bool = False,
                            dry_run: bool = False) -> Dict:
        return self.restore_usecase.restore_from_gdrive(
            remote_name=remote_name,
            target_account_id=target_account_id,
            target_imap=target_imap,
            dry_run=dry_run,
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 50,
               offset: int = 0) -> List[Dict]:
        """Full-text search across all archived mails."""
        return self.mails.search(query, limit, offset)

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def find_duplicates(self) -> List[Dict]:
        return self.dedup.find_duplicates()

    def run_deduplication(self, account_id: int) -> int:
        """Run hash-based deduplication for an account."""
        count = self.db.deduplicate_by_hash(account_id)
        self.audit.append("dedup.completed", account_id=account_id,
                          details={"duplicates_found": count})
        return count

    # ------------------------------------------------------------------
    # Audit & Stats
    # ------------------------------------------------------------------

    def get_audit_log(self, limit: int = 100,
                      offset: int = 0) -> List[Dict]:
        return self.audit.get_log(limit, offset)

    def verify_audit_chain(self) -> bool:
        return self.audit.verify_chain()

    def clear_archive_data(self) -> None:
        """Clear all archived email data from database and delete attachment files."""
        self.db.clear_archive_data()
        attachments_dir = self.db._db_path.parent / "attachments"
        if attachments_dir.exists() and attachments_dir.is_dir():
            import shutil
            for item in attachments_dir.iterdir():
                try:
                    if item.is_file() or item.is_symlink():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                except Exception as exc:
                    logger.warning("Failed to delete attachment item %s: %s", item, exc)

    def get_stats(self) -> Dict[str, Any]:
        return self.stats.get_stats()

    def export_mails(self, account_id: int, format_type: str, output_path: Optional[Path] = None,
                     folders: Optional[List[str]] = None,
                     since_date: Optional[str] = None,
                     before_date: Optional[str] = None,
                     progress_callback = None,
                     imap_host: Optional[str] = None,
                     imap_port: Optional[int] = None,
                     imap_ssl: bool = True,
                     imap_username: Optional[str] = None,
                     imap_password: Optional[str] = None) -> Dict[str, Any]:
        """Export mails from an account with optional folder and date filtering."""
        return self.export_usecase.export_mails(
            account_id=account_id,
            format_type=format_type,
            output_path=output_path,
            folders=folders,
            since_date=since_date,
            before_date=before_date,
            progress_callback=progress_callback,
            imap_host=imap_host,
            imap_port=imap_port,
            imap_ssl=imap_ssl,
            imap_username=imap_username,
            imap_password=imap_password
        )

    # ------------------------------------------------------------------
    # Event bus
    # ------------------------------------------------------------------

    def on(self, event_name: str, callback: Callable[[Event], Any]) -> None:
        """Register an event handler."""
        self.event_bus.subscribe_fn(event_name, callback)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Gracefully shut down the engine."""
        self.db.close()
        logger.info("MailEngine shut down")
