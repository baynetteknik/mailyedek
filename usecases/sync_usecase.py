"""
sync_usecase.py — Email synchronization use case with detailed logging.

Clean Architecture — Use Case Layer.
Orchestrates the full sync flow with step-by-step diagnostics.
Supports a log_callback for real-time UI updates.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.crypto_utils import CryptoManager
from core.database import DatabaseManager
from core.event_bus import EventBus, Event, Events
from core.folder_translator import translate_folder_name
from domain.entities import MailMessage, SyncReport
from domain.interfaces import MailProvider
from domain.repositories import (
    IAccountRepository, IMailRepository, ISyncStateRepository,
    IAttachmentRepository, IDeduplicationRepository, IAuditRepository,
)
from infrastructure.imap_client import ImapClient
from plugins.provider_registry import ProviderRegistry


logger = logging.getLogger(__name__)


def _log(msg: str, callback: Optional[Callable] = None):
    """Log to both standard logger and optional callback."""
    logger.info(msg)
    if callback:
        try:
            callback(msg)
        except Exception:
            pass


class SyncUseCase:
    """Orchestrates the incremental email sync process."""

    def __init__(
        self,
        db: DatabaseManager,
        account_repo: IAccountRepository,
        mail_repo: IMailRepository,
        sync_state_repo: ISyncStateRepository,
        attachment_repo: IAttachmentRepository,
        dedup_repo: IDeduplicationRepository,
        audit_repo: IAuditRepository,
        event_bus: EventBus,
        crypto: CryptoManager,
        provider_registry: Optional[ProviderRegistry] = None,
        max_workers: int = 3,
    ):
        self._db = db
        self._account_repo = account_repo
        self._mail_repo = mail_repo
        self._sync_state_repo = sync_state_repo
        self._attachment_repo = attachment_repo
        self._dedup_repo = dedup_repo
        self._audit_repo = audit_repo
        self._event_bus = event_bus
        self._crypto = crypto
        self._provider_registry = provider_registry or ProviderRegistry()
        self._max_workers = max_workers

    # ------------------------------------------------------------------
    # Public API
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
                 ) -> List[SyncReport]:
        """Synchronize all (or specified) accounts.

        When cancel_event is provided, accounts are processed sequentially
        so cancellation can take effect between accounts.
        """
        accounts = self._account_repo.get_all()
        if account_ids:
            accounts = [a for a in accounts if a["id"] in account_ids]
        else:
            accounts = [a for a in accounts if a.get("is_active", 1)]

        if not accounts:
            _log("No accounts to sync", log_callback)
            return []

        _log(f"Starting sync for {len(accounts)} account(s)", log_callback)
        reports: List[SyncReport] = []
        self._event_bus.publish(Event(Events.SYNC_STARTED, {"account_count": len(accounts)}))

        if cancel_event is not None:
            # Sequential mode for cancellation support
            for acc in accounts:
                if cancel_event.is_set():
                    _log("Sync cancelled by user", log_callback)
                    break
                label = acc.get("label", "?")
                if account_callback:
                    account_callback(label)
                try:
                    report = self._sync_single(acc, log_callback, cancel_event, folder_filter, pause_event, since_date, before_date, archive_unread, timeout, progress_callback)
                    reports.append(report)
                    _log(f"Done: {label} — {report.mails_fetched} fetched, "
                         f"{report.errors} errors", log_callback)
                except Exception as exc:
                    logger.exception("Sync failed for account %d", acc["id"])
                    _log(f"FAILED: {label} — {exc}", log_callback)
                    reports.append(SyncReport(
                        account_label=label,
                        errors=1,
                    ))
        else:
            # Parallel mode (legacy)
            with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                futures = {
                    executor.submit(self._sync_single, acc, log_callback, None, folder_filter, pause_event, since_date, before_date, archive_unread, timeout, progress_callback): acc
                    for acc in accounts
                }
                for future in as_completed(futures):
                    acc = futures[future]
                    try:
                        report = future.result()
                        reports.append(report)
                        _log(f"Done: {acc.get('label','?')} — {report.mails_fetched} fetched, "
                             f"{report.errors} errors", log_callback)
                    except Exception as exc:
                        logger.exception("Sync failed for account %d", acc["id"])
                        _log(f"FAILED: {acc.get('label','?')} — {exc}", log_callback)
                        reports.append(SyncReport(
                            account_label=acc.get("label", "unknown"),
                            errors=1,
                        ))

        self._event_bus.publish(Event(Events.SYNC_COMPLETED, {
            "accounts": len(accounts),
            "reports": [r.__dict__ for r in reports],
        }))
        return reports

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
                      ) -> SyncReport:
        """Synchronize a single account by ID."""
        acc = self._account_repo.get(account_id)
        if not acc:
            raise ValueError(f"Account {account_id} not found")
        _log(f"Starting sync for account '{acc.get('label','?')}' (ID: {account_id})",
             log_callback)
        return self._sync_single(acc, log_callback, cancel_event, folder_filter, pause_event, since_date, before_date, archive_unread, timeout, progress_callback)

    def dry_run(self, account_id: int,
                log_callback: Optional[Callable] = None,
                folder_filter: Optional[List[str]] = None,
                since_date: Optional[str] = None,
                before_date: Optional[str] = None,
                archive_unread: bool = True,
                timeout: int = 15) -> Dict[str, Any]:
        """Simulate a sync without storing anything."""
        acc = self._account_repo.get(account_id)
        if not acc:
            raise ValueError(f"Account {account_id} not found")

        _log(f"Dry-run for account '{acc.get('label','?')}'...", log_callback)
        provider = self._get_provider(acc, log_callback, timeout=timeout)
        try:
            username = self._crypto.decrypt(acc["username_enc"])
            password = self._crypto.decrypt(acc["password_enc"])

            _log(f"Connecting to {acc['imap_host']}:{acc['imap_port']}...", log_callback)
            if not provider.connect(acc["imap_host"], acc["imap_port"],
                                    bool(acc["use_ssl"]), username, password, timeout=timeout):
                _log("CONNECTION FAILED", log_callback)
                return {"error": "Connection failed"}

            _log("Connected. Listing folders...", log_callback)
            folders = provider.list_folders()
            _log(f"Found {len(folders)} folder(s)", log_callback)

            # Resolve target path for reporting
            import re
            from core.settings import AppSettings
            settings = AppSettings()
            base_path = settings.data_path()
            # Fallback: if data_path returned default (data/), use DB parent
            if base_path == Path("data") and self._db._db_path.parent != Path("data"):
                base_path = self._db._db_path.parent
            stor_name = settings.account_storage(account_id)
            if stor_name:
                for loc in settings.storage_locations():
                    if loc.name == stor_name:
                        base_path = Path(loc.path)
                        break
            
            # Resolve group/domain
            group_val = acc.get("account_group", "").strip()
            if not group_val and "@" in acc.get("email", ""):
                group_val = acc["email"].split("@")[-1]
            group_clean = re.sub(r'[\/:*?"<>|]', '_', group_val).strip()

            raw_sub = acc.get("export_subfolder") or ""
            subfolder = re.sub(r'[\/:*?"<>|]', '_', raw_sub).strip()
            
            from core.settings import get_account_mailbox_dir
            target_dir = get_account_mailbox_dir(base_path, acc.get("email", ""), subfolder, "_").parent

            result: Dict[str, Any] = {
                "account": acc["label"],
                "email": acc.get("email", ""),
                "target_dir": str(target_dir),
                "folders": [],
                "total_estimated": 0,
            }

            for _, folder_name in folders:
                if folder_filter is not None and folder_name not in folder_filter:
                    logger.debug("Skipping folder '%s' (not in filter)", folder_name)
                    continue

                _log(f"  Checking folder '{folder_name}'...", log_callback)
                imap_host = acc.get("imap_host", "")
                state = self._sync_state_repo.get(acc["id"], folder_name, server_host=imap_host)
                since_uid = state["last_uid"] if state else 0
                search_since_uid = 0 if (since_date or before_date) else since_uid
                uids = provider.fetch_uids(folder_name, search_since_uid, since_date=since_date, before_date=before_date, archive_unread=archive_unread)
                
                # Fetch archived UIDs from local DB to filter
                try:
                    with self._db.get_conn() as conn:
                        if imap_host:
                            existing_rows = conn.execute(
                                "SELECT uid FROM mail_metadata WHERE account_id=? AND server_host=? AND (folder=? OR folder=?) AND is_deleted=0",
                                (acc["id"], imap_host, folder_name, translate_folder_name(folder_name, "tr"))
                            ).fetchall()
                        else:
                            existing_rows = conn.execute(
                                "SELECT uid FROM mail_metadata WHERE account_id=? AND (folder=? OR folder=?) AND is_deleted=0",
                                (acc["id"], folder_name, translate_folder_name(folder_name, "tr"))
                            ).fetchall()
                        archived_uids = {r["uid"] for r in existing_rows}
                except Exception:
                    archived_uids = set()

                new_uids = [uid for uid in uids if uid > since_uid and uid not in archived_uids]
                _log(f"  -> {len(new_uids)} new message(s) (since UID {since_uid})", log_callback)
                result["folders"].append({
                    "folder": folder_name,
                    "new_mails": len(new_uids),
                    "since_uid": since_uid,
                })
                result["total_estimated"] += len(new_uids)

            _log(f"Dry-run total: ~{result['total_estimated']} message(s)", log_callback)
            return result

        except Exception as exc:
            _log(f"Dry-run ERROR: {exc}", log_callback)
            return {"error": str(exc)}
        finally:
            provider.disconnect()
            _log("Disconnected.", log_callback)

    # ------------------------------------------------------------------
    # Internal: single account sync
    # ------------------------------------------------------------------

    def _sync_single(self, acc: Dict,
                      log_callback: Optional[Callable] = None,
                      cancel_event: Optional[threading.Event] = None,
                      folder_filter: Optional[List[str]] = None,
                      pause_event: Optional[threading.Event] = None,
                      since_date: Optional[str] = None,
                      before_date: Optional[str] = None,
                      archive_unread: bool = True,
                      timeout: int = 300,
                      progress_callback: Optional[Callable[[int, str, int, int], None]] = None
                      ) -> SyncReport:
        """Synchronize one account. Returns a SyncReport."""
        report = SyncReport(
            account_label=acc.get("label", "unknown"),
            started_at=datetime.utcnow().isoformat(),
        )
        start_time = time.time()

        provider = self._get_provider(acc, log_callback)
        if hasattr(provider, "_timeout"):
            provider._timeout = timeout

        try:
            active_profile = self._db.get_active_server_profile(acc["id"])
            if active_profile:
                imap_host = active_profile["imap_host"]
                imap_port = active_profile["imap_port"]
                use_ssl = bool(active_profile["use_ssl"])
                username_enc = active_profile["username_enc"]
                password_enc = active_profile["password_enc"]
                prof_name = active_profile.get("profile_name", imap_host)
            else:
                imap_host = acc["imap_host"]
                imap_port = acc["imap_port"]
                use_ssl = bool(acc["use_ssl"])
                username_enc = acc["username_enc"]
                password_enc = acc["password_enc"]
                prof_name = imap_host

            # Store active host on acc dictionary for sub-methods
            acc["imap_host"] = imap_host

            username = self._crypto.decrypt(username_enc)
            password = self._crypto.decrypt(password_enc)

            _log(f"[{acc['label']}] Connecting to {prof_name} ({imap_host}:{imap_port}, SSL={use_ssl})...", log_callback)

            if not provider.connect(imap_host, imap_port, use_ssl, username, password):
                _log(f"[{acc['label']}] CONNECTION FAILED — check host {imap_host}:{imap_port}",
                     log_callback)
                report.errors = 1
                return report

            _log(f"[{acc['label']}] Connected. Listing folders...", log_callback)
            folders = provider.list_folders()
            _log(f"[{acc['label']}] Found {len(folders)} folder(s): "
                 f"{[f[1] for f in folders[:10]]}", log_callback)

            if not folders:
                _log(f"[{acc['label']}] WARNING: No folders returned by IMAP LIST command. "
                     f"Server may use unsupported list format.", log_callback)

            report.mails_already_archived = 0

            for _, folder_name in folders:
                if folder_filter is not None and folder_name not in folder_filter:
                    logger.debug("Skipping folder '%s' (not in filter)", folder_name)
                    continue

                if cancel_event and cancel_event.is_set():
                    _log(f"[{acc['label']}] Cancelled before syncing folder "
                         f"'{folder_name}'", log_callback)
                    break

                # Pause check
                if pause_event:
                    while pause_event.is_set() and not (cancel_event and cancel_event.is_set()):
                        time.sleep(0.2)

                try:
                    folder_report = self._sync_folder(
                        provider, acc["id"], folder_name, log_callback, cancel_event, pause_event, since_date, before_date, archive_unread, progress_callback
                    )
                    report.mails_fetched += folder_report["fetched"]
                    report.mails_updated += folder_report["updated"]
                    report.duplicates_found += folder_report["duplicates"]
                    report.errors += folder_report["errors"]
                    report.total_bytes += folder_report["bytes"]
                    report.mails_already_archived += folder_report.get("already_archived", 0)
                    report.folders_synced += 1

                    if folder_report.get("error_details"):
                        report.error_details.extend(folder_report["error_details"])

                    _log(f"[{acc['label']}]  Folder '{folder_name}' summary: "
                         f"{folder_report['fetched']} new, "
                         f"{folder_report.get('already_archived', 0)} already archived, "
                         f"{folder_report['duplicates']} dupes, "
                         f"{folder_report['errors']} errors",
                         log_callback)

                except Exception as exc:
                    logger.exception("Error syncing folder '%s': %s", folder_name, exc)
                    err_msg = f"[{acc['label']}] Klasör '{folder_name}' Hata: {exc}"
                    _log(err_msg, log_callback)
                    report.errors += 1
                    report.error_details.append(err_msg)

            # Deduplicate (cross-folder cleanup — already counted per-folder)
            dup_count = self._db.deduplicate_by_hash(acc["id"])
            if dup_count > 0:
                _log(f"[{acc['label']}] Deduplication cleanup: {dup_count} "
                     f"cross-folder dupes removed (already counted in per-folder)",
                     log_callback)

            # Rebuild FTS index
            self._db.rebuild_fts_index()
            _log(f"[{acc['label']}] FTS search index rebuilt", log_callback)

        except Exception as exc:
            logger.exception("Sync failed for account %d", acc["id"])
            _log(f"[{acc['label']}] SYNC ERROR: {exc}", log_callback)
            report.errors += 1
        finally:
            try:
                provider.disconnect()
                _log(f"[{acc['label']}] Disconnected.", log_callback)
            except Exception:
                pass

        report.duration_seconds = time.time() - start_time
        report.finished_at = datetime.utcnow().isoformat()

        _log(f"[{acc['label']}] Sync complete: {report.mails_fetched} fetched, "
             f"{report.duplicates_found} dupes, {report.errors} errors "
             f"in {report.duration_seconds:.1f}s", log_callback)

        self._audit_repo.append("sync.completed", account_id=acc["id"], details={
            "fetched": report.mails_fetched,
            "duplicates": report.duplicates_found,
            "errors": report.errors,
            "duration": report.duration_seconds,
        })

        self._event_bus.publish(Event(Events.SYNC_COMPLETED, {
            "account_id": acc["id"],
            "report": report.__dict__,
        }))
        return report

    def _sync_folder(self, provider: MailProvider, account_id: int,
                     folder_name: str,
                     log_callback: Optional[Callable] = None,
                     cancel_event: Optional[threading.Event] = None,
                     pause_event: Optional[threading.Event] = None,
                     since_date: Optional[str] = None,
                     before_date: Optional[str] = None,
                     archive_unread: bool = True,
                     progress_callback: Optional[Callable[[int, str, int, int], None]] = None
                     ) -> Dict[str, int]:
        result = {"fetched": 0, "updated": 0, "duplicates": 0, "errors": 0, "bytes": 0, "already_archived": 0, "error_details": []}
        acc = self._account_repo.get(account_id) or {}

        from core.settings import AppSettings
        folder_lang = AppSettings().folder_translation_sync()
        display_folder = translate_folder_name(folder_name, folder_lang)

        # Count existing archived UIDs and get the list
        imap_host = acc.get("imap_host", "")
        try:
            with self._db.get_conn() as conn:
                if imap_host:
                    existing_rows = conn.execute(
                        "SELECT uid FROM mail_metadata WHERE account_id=? AND server_host=? AND (folder=? OR folder=?) AND is_deleted=0",
                        (account_id, imap_host, folder_name, display_folder)
                    ).fetchall()
                else:
                    existing_rows = conn.execute(
                        "SELECT uid FROM mail_metadata WHERE account_id=? AND (folder=? OR folder=?) AND is_deleted=0",
                        (account_id, folder_name, display_folder)
                    ).fetchall()
                archived_uids = {r["uid"] for r in existing_rows}
        except Exception:
            archived_uids = set()

        result["already_archived"] = len(archived_uids)

        # Get previous sync state for this server host
        state = self._sync_state_repo.get(account_id, folder_name, server_host=imap_host)

        # Select folder
        _log(f"    [{folder_name}] Selecting folder...", log_callback)
        exists, uid_validity = provider.select_folder(folder_name)
        _log(f"    [{folder_name}] EXISTS={exists}, UIDVALIDITY={uid_validity}",
             log_callback)

        if exists == 0:
            _log(f"    [{folder_name}] Folder is empty, skipping.", log_callback)
            return result

        # Handle UIDVALIDITY change
        since_uid = 0
        if state:
            _log(f"    [{folder_name}] Previous sync: last_uid={state['last_uid']}, "
                 f"uid_validity={state['uid_validity']}", log_callback)
            if state["uid_validity"] and state["uid_validity"] != uid_validity:
                _log(f"    [{folder_name}] WARNING: UIDVALIDITY changed "
                     f"({state['uid_validity']} -> {uid_validity})! Re-syncing folder.",
                     log_callback)
                since_uid = 0
            else:
                since_uid = state["last_uid"]
        else:
            _log(f"    [{folder_name}] First sync (no previous state)", log_callback)
            since_uid = 0

        # Fetch message UIDs
        search_since_uid = 0 if (since_date or before_date) else since_uid
        _log(f"    [{folder_name}] Searching for UIDs (since UID {search_since_uid})...",
             log_callback)
        uids = provider.fetch_uids(folder_name, search_since_uid, since_date=since_date, before_date=before_date, archive_unread=archive_unread)

        new_uids = [u for u in uids if u > since_uid and u not in archived_uids]
        if uids:
            result["already_archived"] = len(set(uids).intersection(archived_uids))
        _log(f"    [{folder_name}] Total server messages: {len(uids)}, new to fetch: {len(new_uids)}, already archived: {result['already_archived']}",
             log_callback)

        if not new_uids:
            self._sync_state_repo.upsert(account_id, folder_name, max(uids, default=since_uid), uid_validity, server_host=imap_host)
            return result

        last_uid = since_uid
        max_uid_on_server = max(uids) if uids else since_uid

        try:
            for i, uid in enumerate(new_uids):
                if cancel_event and cancel_event.is_set():
                    _log(f"    [{folder_name}] Cancelled during message loop", log_callback)
                    break

                # Pause check
                if pause_event:
                    while pause_event.is_set() and not (cancel_event and cancel_event.is_set()):
                        time.sleep(0.2)

                try:
                    if progress_callback:
                        try:
                            progress_callback(account_id, folder_name, i + 1, len(new_uids))
                        except Exception:
                            pass
                    _log(f"    [{folder_name}] Fetching UID {uid} ({i+1}/{len(new_uids)})...",
                         log_callback)
                    message = provider.fetch_message(uid)

                    if message is None:
                        _log(f"    [{folder_name}] UID {uid}: fetch returned None (message may be deleted)",
                             log_callback)
                        continue

                    # Compute SHA-256
                    sha256 = None
                    if message.raw_content:
                        sha256 = CryptoManager.hash_content(message.raw_content)
                        message.metadata.sha256_hash = sha256
                        subj = message.metadata.subject or ""
                    _log(f"    [{folder_name}] UID {uid}: {message.metadata.size_bytes} bytes, "
                         f"subject='{subj[:50]}'", log_callback)

                    # Check duplicate
                    is_dup = False
                    if sha256:
                        is_dup = self._dedup_repo.is_duplicate(sha256)
                        if is_dup:
                            _log(f"    [{folder_name}] UID {uid}: DUPLICATE (hash match)", log_callback)

                    # Store metadata (use display_folder for folder column)
                    mail_id = self._mail_repo.upsert(
                        account_id=account_id,
                        folder=display_folder,
                        uid=uid,
                        message_id=message.metadata.message_id,
                        subject=message.metadata.subject,
                        sender=message.metadata.sender,
                        recipients=message.metadata.recipients,
                        cc=message.metadata.cc,
                        bcc=message.metadata.bcc,
                        date=message.metadata.date,
                        internal_date=message.metadata.internal_date,
                        flags=message.metadata.flags,
                        size_bytes=message.metadata.size_bytes,
                        has_attachments=int(message.metadata.has_attachments),
                        sha256_hash=sha256,
                        is_duplicate=int(is_dup),
                        server_host=imap_host,
                    )

                    # Store raw content
                    if message.raw_content:
                        self._mail_repo.store_raw(mail_id, message.raw_content)
                        
                        # Export/write raw email as EML file
                        try:
                            import re
                            from core.settings import AppSettings, get_account_mailbox_dir
                            settings = AppSettings()
                            
                            # Resolve base storage path using account_storage
                            base_path = settings.data_path()
                            if base_path == Path("data") and self._db._db_path.parent != Path("data"):
                                base_path = self._db._db_path.parent
                            stor_name = settings.account_storage(account_id)
                            if stor_name:
                                for loc in settings.storage_locations():
                                    if loc.name == stor_name:
                                        base_path = Path(loc.path)
                                        break
                                        
                            # Check group/domain
                            group_val = acc.get("account_group", "").strip()
                            if not group_val and "@" in acc.get("email", ""):
                                group_val = acc["email"].split("@")[-1]
                            group_clean = re.sub(r'[\/:*?"<>|]', '_', group_val).strip()

                            # Check subfolder
                            raw_sub = acc.get("export_subfolder") or ""
                            subfolder = re.sub(r'[\/:*?"<>|]', '_', raw_sub).strip()
                            
                            mailbox_dir = get_account_mailbox_dir(base_path, acc.get("email", ""), subfolder, display_folder)
                            mailbox_dir.mkdir(parents=True, exist_ok=True)
                            
                            # Format filename: {date}_{uid}_{subject}.eml
                            date_str = ""
                            if message.metadata.date:
                                try:
                                    dt = datetime.fromisoformat(message.metadata.date.replace('Z', '+00:00'))
                                    date_str = dt.strftime("%Y%m%d_%H%M%S")
                                except Exception:
                                    date_str = re.sub(r'[\/:*?"<>|]', '_', message.metadata.date).strip()
                            
                            if not date_str:
                                date_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                                
                            subj_clean = re.sub(r'[\/:*?"<>|]', '_', message.metadata.subject or "NoSubject").strip()[:60]
                            eml_filename = f"{date_str}_{uid}_{subj_clean}.eml"
                            eml_path = mailbox_dir / eml_filename
                            
                            eml_path.write_bytes(message.raw_content)
                        except Exception as eml_exc:
                            logger.exception("Failed to save EML file for mail %d: %s", mail_id, eml_exc)

                    # Store attachments
                    if message.attachments:
                        attachments_dir = mailbox_dir / "Attachments" if 'mailbox_dir' in locals() else Path("data") / "Attachments"
                        attachments_dir.mkdir(parents=True, exist_ok=True)
                        
                        for att in message.attachments:
                            if not att.sha256_hash or not att.data:
                                continue
                            
                            att_filename = re.sub(r'[\/:*?"<>|]', '_', att.filename or "unknown").strip()
                            d_str = date_str if 'date_str' in locals() else ""
                            storage_path = attachments_dir / f"{d_str}_{uid}_{att_filename}"
                            
                            try:
                                if not storage_path.exists():
                                    storage_path.write_bytes(att.data)
                                
                                att_id = self._attachment_repo.register(
                                     sha256_hash=att.sha256_hash,
                                     filename=att.filename or "unknown",
                                     mime_type=att.mime_type or "application/octet-stream",
                                     size_bytes=att.size_bytes,
                                     storage_path=str(storage_path),
                                )
                                
                                self._attachment_repo.link(mail_id, att_id)
                            except Exception as att_exc:
                                logger.exception("Failed to save/register attachment %s: %s", att.filename, att_exc)
                                _log(f"    [{folder_name}] Failed to save attachment {att.filename}: {att_exc}", log_callback)

                    # Register hash for dedup
                    if sha256:
                        self._dedup_repo.register(sha256, account_id, mail_id)

                    last_uid = uid
                    result["bytes"] += message.metadata.size_bytes
                    if is_dup:
                        result["duplicates"] += 1
                    else:
                        result["fetched"] += 1

                    # Fire event
                    self._event_bus.publish(Event(Events.MAIL_FETCHED, {
                        "account_id": account_id,
                        "mail_id": mail_id,
                        "uid": uid,
                        "folder": display_folder,
                        "sha256": sha256,
                        "is_duplicate": is_dup,
                    }))

                except Exception as exc:
                    logger.exception("Error fetching UID %d in '%s'", uid, folder_name)
                    err_msg = f"[{folder_name}] UID {uid} Alınırken Hata Oluştu: {exc}"
                    _log(f"    {err_msg}", log_callback)
                    result["errors"] += 1
                    result["error_details"].append(err_msg)
            else:
                last_uid = max(max_uid_on_server, last_uid)
        finally:
            # Update sync state to the last successfully processed UID
            self._sync_state_repo.upsert(account_id, folder_name, last_uid, uid_validity, server_host=imap_host)
            _log(f"    [{folder_name}] Sync state updated: last_uid={last_uid}", log_callback)

        _log(f"    [{folder_name}] === Folder done: {result['fetched']} new, "
             f"{result['duplicates']} dupes, {result['errors']} errors, "
             f"{result['bytes']} bytes ===", log_callback)

        return result

    # ------------------------------------------------------------------
    # Provider resolution
    # ------------------------------------------------------------------

    def _get_provider(self, acc: Dict,
                      log_callback: Optional[Callable] = None,
                      timeout: int = 300) -> MailProvider:
        provider = self._provider_registry.get_mail_provider(acc.get("provider_type", "imap"))
        if provider:
            if hasattr(provider, '_log_callback'):
                provider._log_callback = log_callback  # type: ignore
            if hasattr(provider, '_timeout'):
                provider._timeout = timeout
            return provider
        return ImapClient(log_callback=log_callback, timeout=timeout)
