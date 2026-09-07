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
from typing import Any, Callable, Dict, List, Optional, Union

from core.crypto_utils import CryptoManager
from core.database import DatabaseManager
from core.event_bus import EventBus, Event, Events, get_event_bus
from core.auth_manager import AuthManager, SessionManager
from infrastructure.disk_watcher import DiskWatcher
from infrastructure.email_notifier import EmailNotifier
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
from usecases.sql_backup_usecase import SqlBackupUseCase
from usecases.vhdx_backup_usecase import VhdxBackupUseCase

logger = logging.getLogger(__name__)


class MailEngine:
    """Facade that wires together all components.

    Provides a unified API for CLI, REST API, or GUI consumers.
    """

    def __init__(self, db_path: Optional[Path] = None,
                 key_file: Optional[Path] = None,
                 use_keyring: bool = False,
                 settings: Optional[Any] = None):
        # Core infrastructure
        from core.reporter import ReportGenerator
        from core.settings import AppSettings
        self.settings = settings or AppSettings()
        self.crypto = CryptoManager(key_file=key_file or self.settings.key_file_path(), use_keyring=use_keyring)
        self.db = DatabaseManager(db_path=db_path or self.settings.db_path())
        self.event_bus = get_event_bus()
        self.reporter = ReportGenerator()
        self.auth = AuthManager.get_instance(self.db)
        self.disk_watcher = DiskWatcher()
        self.email_notifier = EmailNotifier()

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
        self.sql_backup_usecase = SqlBackupUseCase(
            db=self.db,
            audit_repo=self.audit,
            event_bus=self.event_bus,
            crypto=self.crypto,
        )
        self.vhdx_backup_usecase = VhdxBackupUseCase(
            db=self.db,
            audit_repo=self.audit,
            event_bus=self.event_bus,
            crypto=self.crypto,
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
            audit_repo=self.audit,
        )

        logger.info("MailEngine initialized")

    # ------------------------------------------------------------------
    # Account management
    # ------------------------------------------------------------------

    def add_account(self, label: str, email: str, imap_host: str,
                    imap_port: int = 993, use_ssl: bool = True,
                    username: str = None, password: str = None,
                    export_subfolder: str = "",
                    account_group: str = "") -> int:
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
            export_subfolder=export_subfolder,
            account_group=account_group,
        )

        self.audit.append("account.added", account_id=account_id)
        self.event_bus.publish(Event(Events.ACCOUNT_ADDED, {
            "account_id": account_id,
            "label": label,
            "email": CryptoManager.mask_email(email),
        }))

        return account_id

    def list_accounts(self) -> List[Dict]:
        """Return all accounts with masked credentials, falling back to cache when offline."""
        try:
            accounts = self.accounts.get_all()
        except Exception as e:
            logger.debug("Error retrieving accounts from DB repo: %s", e)
            accounts = []

        if not accounts and hasattr(self, "settings") and self.settings:
            accounts = self.settings.load_account_cache()
        elif accounts and hasattr(self, "settings") and self.settings:
            try:
                self.settings.save_account_cache(accounts)
            except Exception:
                pass

        for acc in accounts:
            try:
                if "username_enc" in acc and acc["username_enc"]:
                    acc["username"] = self.crypto.decrypt(acc["username_enc"])
                acc.pop("username_enc", None)
            except Exception:
                acc["username"] = "(decryption error)"
                acc.pop("username_enc", None)
            if "password_enc" in acc:
                acc.pop("password_enc", None)
        return accounts

    def update_account(self, account_id: int, **kwargs) -> None:
        """Update account details. Handles server migration detection and audit log chaining."""
        old_acc = self.accounts.get(account_id)
        if not old_acc:
            raise ValueError(f"Account {account_id} not found")

        old_host = old_acc.get("imap_host", "")
        new_host = kwargs.get("imap_host")
        host_changed = new_host and new_host != old_host

        # Encrypt raw credentials if provided
        if "username" in kwargs:
            kwargs["username_enc"] = self.crypto.encrypt(kwargs.pop("username"))
        if "password" in kwargs:
            kwargs["password_enc"] = self.crypto.encrypt(kwargs.pop("password"))

        self.accounts.update(account_id, **kwargs)

        if host_changed:
            self.db.reset_account_sync_state(account_id, reason=f"Server host changed from {old_host} to {new_host}")
            self.audit.append("account.server_changed", account_id=account_id, details={
                "old_host": old_host,
                "new_host": new_host,
                "email": old_acc.get("email", ""),
                "action": "server_migration",
            })
            logger.info("Account %d IMAP host changed: '%s' -> '%s'. Sync state reset for server migration.",
                        account_id, old_host, new_host)
        else:
            self.audit.append("account.updated", account_id=account_id, details=kwargs)

    def reset_account_sync_state(self, account_id: int, reason: str = "server_migration") -> int:
        """Reset sync state for account to force a complete re-sync from server."""
        count = self.db.reset_account_sync_state(account_id, reason=reason)
        self.audit.append("account.sync_state_reset", account_id=account_id, details={"reason": reason, "folders_reset": count})
        return count

    # ------------------------------------------------------------------
    # Server Profiles Management (Multi-Server Endpoints)
    # ------------------------------------------------------------------

    def add_server_profile(self, account_id: int, profile_name: str, imap_host: str,
                           imap_port: int = 993, use_ssl: bool = True,
                           username: str = None, password: str = None,
                           make_default: bool = False) -> int:
        """Add a new server profile (endpoint) for an account."""
        acc = self.accounts.get(account_id)
        if not acc:
            raise ValueError(f"Account {account_id} not found")

        if username is None:
            username = acc.get("email", "")
        if password is None:
            password = ""

        username_enc = self.crypto.encrypt(username)
        password_enc = self.crypto.encrypt(password)

        prof_id = self.db.add_server_profile(
            account_id=account_id,
            profile_name=profile_name,
            imap_host=imap_host,
            imap_port=imap_port,
            use_ssl=use_ssl,
            username_enc=username_enc,
            password_enc=password_enc,
            make_default=make_default,
        )

        self.audit.append("account.server_profile_added", account_id=account_id, details={
            "profile_id": prof_id,
            "profile_name": profile_name,
            "imap_host": imap_host,
            "make_default": make_default,
        })
        return prof_id

    def list_server_profiles(self, account_id: int) -> List[Dict[str, Any]]:
        """Return all server profiles configured for an account with decrypted usernames."""
        profiles = self.db.get_server_profiles(account_id)
        for p in profiles:
            try:
                if "username_enc" in p and p["username_enc"]:
                    p["username"] = self.crypto.decrypt(p["username_enc"])
                p.pop("username_enc", None)
            except Exception:
                p["username"] = "(decryption error)"
            p.pop("password_enc", None)
        return profiles

    def get_server_profile(self, account_id: int, profile_id: int) -> Optional[Dict[str, Any]]:
        """Return a single server profile with decrypted username and password."""
        raw_profiles = self.db.get_server_profiles(account_id)
        prof = next((p for p in raw_profiles if p["id"] == profile_id), None)
        if not prof:
            return None
        res = dict(prof)
        try:
            if "username_enc" in res and res["username_enc"]:
                res["username"] = self.crypto.decrypt(res["username_enc"])
        except Exception:
            res["username"] = ""
        try:
            if "password_enc" in res and res["password_enc"]:
                res["password"] = self.crypto.decrypt(res["password_enc"])
        except Exception:
            res["password"] = ""
        return res

    def test_server_profile_connection(self, account_id: int, profile_id: int) -> Tuple[bool, str]:
        """Test IMAP connection for a specific server profile and return success flag + detail message."""
        prof = self.get_server_profile(account_id, profile_id)
        if not prof:
            return False, "Sunucu profili bulunamadı."
        host = prof.get("imap_host", "").strip()
        port = prof.get("imap_port", 993)
        use_ssl = bool(prof.get("use_ssl", True))
        username = prof.get("username", "").strip()
        password = prof.get("password", "")

        if not host:
            return False, "IMAP sunucu adresi (Host) boş olamaz."
        if not username:
            return False, "Kullanıcı adı boş veya çözülemedi."
        if not password:
            return False, "Parola boş veya çözülemedi."

        from infrastructure.imap_client import ImapClient
        client = ImapClient()
        try:
            ok, detail = client.connect_with_details(host, port, use_ssl, username, password, timeout=10)
            if ok:
                folders = []
                try:
                    folders = client.list_folders()
                except Exception:
                    pass
                client.disconnect()
                f_count = len(folders)
                return True, f"Bağlantı Başarılı ({host}:{port}) — {f_count} klasör bulundu."
            else:
                return False, f"Bağlantı Başarısız ({host}:{port}) — {detail}"
        except Exception as e:
            return False, f"Bağlantı Hatası ({host}:{port}): {str(e)}"

    def set_default_server_profile(self, account_id: int, profile_id: int) -> None:
        """Set the active default server profile for an account."""
        self.db.set_default_server_profile(account_id, profile_id)
        profs = self.db.get_server_profiles(account_id)
        active_prof = next((p for p in profs if p["id"] == profile_id), None)
        active_host = active_prof["imap_host"] if active_prof else "unknown"
        self.audit.append("account.default_server_changed", account_id=account_id, details={
            "profile_id": profile_id,
            "active_host": active_host,
        })

    def delete_server_profile(self, account_id: int, profile_id: int) -> None:
        """Delete a server profile from an account."""
        self.db.delete_server_profile(account_id, profile_id)
        self.audit.append("account.server_profile_deleted", account_id=account_id, details={
            "profile_id": profile_id,
        })

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
                     archive_unread: bool = True,
                     timeout: int = 15) -> Dict:
        """Preview what would be synced."""
        return self.sync_usecase.dry_run(
            account_id, log_callback=log_callback, folder_filter=folder_filter,
            since_date=since_date, before_date=before_date,
            archive_unread=archive_unread, timeout=timeout,
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
    # SQL Database Backup operations
    # ------------------------------------------------------------------

    def test_sql_connection(
        self, engine_type: str, host: str, port: int = 1433,
        auth_type: str = "windows", username: str = "", password: str = "",
        database_name: str = "master"
    ) -> tuple[bool, str]:
        return self.sql_backup_usecase.test_connection(
            engine_type=engine_type,
            host=host,
            port=port,
            auth_type=auth_type,
            username=username,
            password=password,
            database_name=database_name,
        )

    def list_sql_databases(
        self, engine_type: str, host: str, port: int = 1433,
        auth_type: str = "windows", username: str = "", password: str = ""
    ) -> List[str]:
        return self.sql_backup_usecase.list_databases(
            engine_type=engine_type,
            host=host,
            port=port,
            auth_type=auth_type,
            username=username,
            password=password,
        )

    def save_sql_job(self, job_data: Dict[str, Any]) -> int:
        return self.sql_backup_usecase.save_job(job_data)

    def get_sql_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        return self.sql_backup_usecase.get_job(job_id)

    def list_sql_jobs(self) -> List[Dict[str, Any]]:
        return self.sql_backup_usecase.list_jobs()

    def delete_sql_job(self, job_id: int) -> bool:
        return self.sql_backup_usecase.delete_job(job_id)

    def run_sql_backup(
        self, job_params: Union[int, Dict[str, Any]],
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        report = self.sql_backup_usecase.execute_backup(job_params, progress_callback=progress_callback)
        return report.__dict__

    # ------------------------------------------------------------------
    # VHDX & Hyper-V Virtual Disk Backup operations
    # ------------------------------------------------------------------

    def list_hyperv_vms(self) -> List[Dict[str, Any]]:
        return self.vhdx_backup_usecase.list_hyperv_vms()

    def save_vhdx_job(self, job_data: Dict[str, Any]) -> int:
        return self.vhdx_backup_usecase.save_job(job_data)

    def get_vhdx_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        return self.vhdx_backup_usecase.get_job(job_id)

    def list_vhdx_jobs(self) -> List[Dict[str, Any]]:
        return self.vhdx_backup_usecase.list_jobs()

    def delete_vhdx_job(self, job_id: int) -> bool:
        return self.vhdx_backup_usecase.delete_job(job_id)

    def run_vhdx_backup(
        self, job_params: Union[int, Dict[str, Any]],
        progress_callback: Optional[Callable[[str, float, float], None]] = None
    ) -> Dict[str, Any]:
        report = self.vhdx_backup_usecase.execute_backup(job_params, progress_callback=progress_callback)
        return report.__dict__

    def restore_vhdx_backup(
        self,
        source_backup_path: str,
        target_dest_path: str,
        mode: str = "custom",
        progress_callback: Optional[Callable[[str, float, float], None]] = None
    ) -> Dict[str, Any]:
        """Restore a VHDX / Hyper-V backup with on-the-fly streaming decompression."""
        return self.vhdx_backup_usecase.restore_backup(
            source_backup_path=source_backup_path,
            target_dest_path=target_dest_path,
            mode=mode,
            progress_callback=progress_callback
        )

    # ------------------------------------------------------------------
    # Unified Backup History
    # ------------------------------------------------------------------

    def list_backup_history(self, limit: int = 100, offset: int = 0, job_type: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.db.list_backup_history(limit=limit, offset=offset, job_type=job_type)

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
               offset: int = 0,
               account_id: Optional[int] = None,
               folder: Optional[Union[str, List[str]]] = None,
               since_date: Optional[str] = None,
               before_date: Optional[str] = None,
               has_attachments: Optional[bool] = None,
               unread_only: Optional[bool] = None) -> List[Dict]:
        """Full-text search across all archived mails."""
        return self.mails.search(
            query=query, limit=limit, offset=offset,
            account_id=account_id, folder=folder,
            since_date=since_date, before_date=before_date,
            has_attachments=has_attachments, unread_only=unread_only
        )

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
                     imap_password: Optional[str] = None,
                     server_host: Optional[str] = None) -> Dict[str, Any]:
        """Export mails from an account with optional folder, server_host and date filtering."""
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
            imap_password=imap_password,
            server_host=server_host,
        )

    def generate_custom_report(self, account_id: Optional[int] = None,
                               account_group: Optional[str] = None,
                               domain: Optional[str] = None,
                               since_date: Optional[str] = None,
                               before_date: Optional[str] = None,
                               single_email: Optional[str] = None) -> Dict[str, Any]:
        """Query aggregates and write custom JSON/HTML reports to disk."""
        stats = self.db.get_custom_report_stats(
            account_id=account_id,
            account_group=account_group,
            domain=domain,
            since_date=since_date,
            before_date=before_date,
            single_email=single_email
        )
        if not stats or stats.get("total_mails", 0) == 0:
            return {"total_mails": 0}

        # Build human-readable criteria
        criteria = {}
        if account_id is not None:
            acc = self.accounts.get(account_id)
            criteria["filtre_tipi"] = f"Hesap: {acc.get('label', account_id) if acc else account_id}"
            criteria["hesap_adi"] = acc.get("email", "") if acc else ""
        elif account_group:
            criteria["filtre_tipi"] = f"Domain Grubu: {account_group}"
        elif domain:
            criteria["filtre_tipi"] = f"E-Posta Domaini: @{domain}"
        elif single_email:
            criteria["filtre_tipi"] = f"Tek E-Posta Adresi: {single_email}"
        else:
            criteria["filtre_tipi"] = "Tüm Veriler"

        if since_date:
            criteria["baslangic_tarihi"] = since_date[:10]
        if before_date:
            criteria["bitis_tarihi"] = before_date[:10]

        report_path = self.reporter.generate_custom_metadata_report(criteria, stats, output_format="both")
        return {
            "total_mails": stats["total_mails"],
            "total_size_bytes": stats["total_size_bytes"],
            "report_path": str(report_path),
            "stats": stats
        }

    # ------------------------------------------------------------------
    # Portable Backup Import
    # ------------------------------------------------------------------

    def inspect_portable_backup(self, backup_dir: Path) -> Dict[str, Any]:
        """Inspect an external backup directory (e.g. portable drive / backup folder)."""
        backup_dir = Path(backup_dir)
        db_file = backup_dir / "mail_archive.db"
        settings_file = backup_dir / "settings.json"
        
        if not db_file.exists():
            return {
                "is_valid": False,
                "error": "Klasör içerisinde 'mail_archive.db' veritabanı bulunamadı."
            }
            
        import sqlite3
        accounts = []
        conflicting_accounts = []
        total_mails = 0
        total_attachments = 0
        export_profiles = []
        
        try:
            conn = sqlite3.connect(db_file)
            conn.row_factory = sqlite3.Row
            
            # Fetch accounts
            acc_rows = conn.execute("SELECT * FROM accounts").fetchall()
            accounts = [dict(r) for r in acc_rows]
            
            # Check conflicting accounts
            active_emails = {a.get("email", "").lower() for a in self.accounts.list_all()}
            for a in accounts:
                if a.get("email", "").lower() in active_emails:
                    conflicting_accounts.append(a)
                    
            # Count mails
            m_row = conn.execute("SELECT COUNT(*) as cnt FROM mail_metadata WHERE is_deleted=0").fetchone()
            total_mails = m_row["cnt"] if m_row else 0
            
            # Count attachments
            try:
                a_row = conn.execute("SELECT COUNT(*) as cnt FROM attachments").fetchone()
                total_attachments = a_row["cnt"] if a_row else 0
            except Exception:
                pass
            conn.close()
        except Exception as exc:
            return {
                "is_valid": False,
                "error": f"Veritabanı okunamadı: {exc}"
            }
            
        if settings_file.exists():
            try:
                import json
                with open(settings_file, "r", encoding="utf-8") as f:
                    s_data = json.load(f)
                    export_profiles = s_data.get("export_profiles", [])
            except Exception:
                pass
                
        return {
            "is_valid": True,
            "backup_dir": str(backup_dir),
            "accounts": accounts,
            "conflicting_accounts": conflicting_accounts,
            "total_mails": total_mails,
            "total_attachments": total_attachments,
            "export_profiles": export_profiles
        }

    def import_portable_backup(self, backup_dir: Path, progress_callback=None) -> Dict[str, Any]:
        """Merge database records, key, attachments, and export profiles from a portable backup folder."""
        backup_dir = Path(backup_dir)
        db_file = backup_dir / "mail_archive.db"
        settings_file = backup_dir / "settings.json"
        key_file = backup_dir / "key.key"
        
        if not db_file.exists():
            raise FileNotFoundError("Klasör içerisinde 'mail_archive.db' veritabanı bulunamadı.")
            
        import sqlite3, shutil
        
        # Key import check
        if key_file.exists() and not self.crypto._key_file.exists():
            try:
                shutil.copy2(key_file, self.crypto._key_file)
                logger.info("Fernet key file copied from backup directory")
            except Exception as exc:
                logger.warning("Failed to copy key.key: %s", exc)

        ext_conn = sqlite3.connect(db_file)
        ext_conn.row_factory = sqlite3.Row
        
        # 1. Map external account_ids -> active account_ids
        account_id_map = {}
        ext_accounts = [dict(r) for r in ext_conn.execute("SELECT * FROM accounts").fetchall()]
        
        active_accs = {a.get("email", "").lower(): a["id"] for a in self.accounts.list_all()}
        
        imported_acc_count = 0
        for acc in ext_accounts:
            email_clean = acc.get("email", "").strip().lower()
            if email_clean in active_accs:
                account_id_map[acc["id"]] = active_accs[email_clean]
            else:
                # Insert account
                new_id = self.accounts.create({
                    "label": acc.get("label") or email_clean,
                    "email": acc.get("email"),
                    "imap_host": acc.get("imap_host", ""),
                    "imap_port": acc.get("imap_port", 993),
                    "use_ssl": acc.get("use_ssl", True),
                    "username": acc.get("username", ""),
                    "password_encrypted": acc.get("password_encrypted", ""),
                    "export_subfolder": acc.get("export_subfolder", ""),
                    "account_group": acc.get("account_group", ""),
                    "status": "Active"
                })
                account_id_map[acc["id"]] = new_id
                active_accs[email_clean] = new_id
                imported_acc_count += 1

        # 2. Merge mail_metadata & mail_raw
        ext_mails = ext_conn.execute("SELECT m.*, r.raw_data FROM mail_metadata m LEFT JOIN mail_raw r ON r.mail_id=m.id WHERE m.is_deleted=0").fetchall()
        total_mails = len(ext_mails)
        imported_mail_count = 0
        
        if progress_callback:
            progress_callback(0, total_mails, "Mailler içe aktarılıyor...")
            
        with self.db.get_conn() as act_conn:
            for idx, m in enumerate(ext_mails):
                ext_acc_id = m["account_id"]
                act_acc_id = account_id_map.get(ext_acc_id)
                if not act_acc_id:
                    continue
                    
                msg_id = m["message_id"]
                uid = m["uid"]
                folder = m["folder"]
                
                # Check duplicate
                dup = None
                if msg_id:
                    dup = act_conn.execute("SELECT id FROM mail_metadata WHERE account_id=? AND message_id=? AND is_deleted=0", (act_acc_id, msg_id)).fetchone()
                if not dup and uid and folder:
                    dup = act_conn.execute("SELECT id FROM mail_metadata WHERE account_id=? AND folder=? AND uid=? AND is_deleted=0", (act_acc_id, folder, uid)).fetchone()
                    
                if not dup:
                    cur = act_conn.execute(
                        """INSERT INTO mail_metadata (account_id, uid, folder, subject, sender, recipients, date, message_id, size, has_attachments, is_deleted)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                        (act_acc_id, m["uid"], m["folder"], m["subject"], m["sender"], m["recipients"], m["date"], m["message_id"], m["size"], m["has_attachments"])
                    )
                    new_mail_id = cur.lastrowid
                    if m["raw_data"]:
                        act_conn.execute("INSERT OR REPLACE INTO mail_raw (mail_id, raw_data) VALUES (?, ?)", (new_mail_id, m["raw_data"]))
                    imported_mail_count += 1
                    
                if progress_callback and (idx % 20 == 0 or idx == total_mails - 1):
                    progress_callback(idx + 1, total_mails, f"Mail {idx+1}/{total_mails}")

        # 3. Copy Attachments if any
        ext_attach_dir = backup_dir / "attachments"
        act_attach_dir = self.db._db_path.parent / "attachments"
        imported_attach_count = 0
        if ext_attach_dir.exists() and ext_attach_dir.is_dir():
            act_attach_dir.mkdir(parents=True, exist_ok=True)
            for item in ext_attach_dir.glob("*"):
                if item.is_file():
                    target = act_attach_dir / item.name
                    if not target.exists():
                        try:
                            shutil.copy2(item, target)
                            imported_attach_count += 1
                        except Exception:
                            pass

        ext_conn.close()
        
        # 4. Import Export Profiles from settings.json
        imported_profiles_count = 0
        if settings_file.exists():
            try:
                import json
                with open(settings_file, "r", encoding="utf-8") as f:
                    s_data = json.load(f)
                    ext_profiles = s_data.get("export_profiles", [])
                    if ext_profiles:
                        from core.settings import AppSettings
                        settings = AppSettings()
                        act_profiles = settings.get("export_profiles", [])
                        act_names = {p.get("name") for p in act_profiles if isinstance(p, dict)}
                        for p in ext_profiles:
                            if isinstance(p, dict) and p.get("name") and p.get("name") not in act_names:
                                act_profiles.append(p)
                                imported_profiles_count += 1
                        settings.set("export_profiles", act_profiles)
                        settings.save()
            except Exception as exc:
                logger.warning("Failed to import export profiles from settings.json: %s", exc)

        return {
            "imported_accounts": imported_acc_count,
            "imported_mails": imported_mail_count,
            "imported_attachments": imported_attach_count,
            "imported_profiles": imported_profiles_count
        }

    # ------------------------------------------------------------------
    # User Management & Authentication (RBAC)
    # ------------------------------------------------------------------

    def login(self, username: str, password: str) -> tuple[bool, Optional[Any], str]:
        """Authenticate user by username and password."""
        return self.auth.login(username, password)

    def logout(self) -> None:
        """Clear active user session."""
        self.auth.logout()

    def get_current_user(self) -> Optional[Any]:
        """Get currently logged-in user."""
        return self.auth.current_user

    def has_permission(self, permission: str) -> bool:
        """Check if current active user has specific permission."""
        return self.auth.has_permission(permission)

    def list_users(self) -> List[Dict[str, Any]]:
        """List all users in the system."""
        return self.auth.list_users()

    def create_user(self, username: str, password: str, role: str = "OPERATOR",
                    full_name: str = "", email: str = "") -> tuple[bool, str, Optional[int]]:
        """Create a new user."""
        return self.auth.create_user(username=username, password=password, role=role,
                                     full_name=full_name, email=email)

    def update_user_password(self, user_id: int, new_password: str) -> tuple[bool, str]:
        """Update password for a user."""
        return self.auth.update_user_password(user_id, new_password)

    def delete_user(self, user_id: int) -> tuple[bool, str]:
        """Delete a user."""
        return self.auth.delete_user(user_id)

    # ------------------------------------------------------------------
    # Disk Management & USB Arrival Watcher
    # ------------------------------------------------------------------

    def list_available_drives(self) -> List[Dict[str, Any]]:
        """List all accessible drives with metadata (label, free space, drive type)."""
        return self.disk_watcher.list_drives()

    def scan_drive_backups(
        self,
        drive_path: str,
        max_depth: int = 3,
        progress_callback: Optional[Callable[[int, str, Optional[Dict[str, Any]]], None]] = None,
    ) -> Dict[str, Any]:
        """Scan a drive or folder to find all SQL, VHDX, and Mail archives."""
        return self.disk_watcher.scan_drive_backups(
            drive_path, max_depth=max_depth, progress_callback=progress_callback
        )

    def start_disk_watcher(self, callback: Callable[[Dict[str, Any]], None], poll_interval: float = 3.0) -> None:
        """Start background watcher for USB / external drive insertions."""
        self.disk_watcher.start_watching(callback, poll_interval=poll_interval)

    def stop_disk_watcher(self) -> None:
        """Stop background disk arrival watcher."""
        self.disk_watcher.stop_watching()

    # ------------------------------------------------------------------
    # SMTP Notification Settings
    # ------------------------------------------------------------------

    def get_smtp_settings(self) -> Dict[str, Any]:
        """Retrieve stored SMTP notification settings."""
        from core.settings import AppSettings
        settings = AppSettings()
        return settings.get("smtp_notifications", {
            "enabled": False,
            "host": "",
            "port": 587,
            "use_tls": True,
            "username": "",
            "password": "",
            "from_address": "",
            "to_addresses": [],
            "notify_on_success": True,
            "notify_on_failure": True,
        })

    def save_smtp_settings(self, config: Dict[str, Any]) -> None:
        """Save SMTP notification settings."""
        from core.settings import AppSettings
        settings = AppSettings()
        settings.set("smtp_notifications", config)
        settings.save()

    def test_smtp_connection(self, config: Optional[Dict[str, Any]] = None, recipient: Optional[str] = None) -> tuple[bool, str]:
        """Send a test email using provided or saved SMTP configuration."""
        if config is None:
            config = self.get_smtp_settings()
        from domain.entities import SmtpNotificationConfig
        smtp_cfg = SmtpNotificationConfig.from_dict(config)
        to_email = recipient or (smtp_cfg.to_addresses[0] if smtp_cfg.to_addresses else smtp_cfg.username)
        if not to_email:
            return False, "Alıcı e-posta adresi belirtilmedi."
        return self.email_notifier.test_connection(smtp_cfg, to_email)

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
        try:
            self.stop_disk_watcher()
        except Exception:
            pass
        self.db.close()
        logger.info("MailEngine shut down")
