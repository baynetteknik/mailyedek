"""
sqlite_repository.py — Concrete implementations of domain repository interfaces
using SQLite as the backing store.

Clean Architecture — Infrastructure Layer.
Implements the repository interfaces defined in domain/repositories.py.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from core.database import DatabaseManager
from domain.repositories import (
    IAccountRepository, IMailRepository, ISyncStateRepository,
    IAttachmentRepository, IDeduplicationRepository,
    IAuditRepository, IStatsRepository,
)

logger = logging.getLogger(__name__)


class SqliteAccountRepository(IAccountRepository):
    def __init__(self, db: DatabaseManager):
        self._db = db

    def add(self, label: str, email: str, imap_host: str, imap_port: int,
            use_ssl: bool, username_enc: str, password_enc: str, export_subfolder: str = "",
            account_group: str = "") -> int:
        return self._db.add_account(label, email, imap_host, imap_port,
                                    use_ssl, username_enc, password_enc, export_subfolder, account_group)

    def get(self, account_id: int) -> Optional[Dict]:
        return self._db.get_account(account_id)

    def get_all(self) -> List[Dict]:
        return self._db.get_all_accounts()

    def update(self, account_id: int, **kwargs) -> None:
        self._db.update_account(account_id, **kwargs)

    def delete(self, account_id: int) -> None:
        self._db.delete_account(account_id)


class SqliteMailRepository(IMailRepository):
    def __init__(self, db: DatabaseManager):
        self._db = db

    def upsert(self, account_id: int, folder: str, uid: int,
               **fields) -> int:
        return self._db.upsert_mail_metadata(account_id, folder, uid, **fields)

    def get_by_uid(self, account_id: int, folder: str,
                   uid: int) -> Optional[Dict]:
        return self._db.get_mail_by_uid(account_id, folder, uid)

    def get_for_account(self, account_id: int, folder: str = "INBOX",
                        limit: int = 1000, offset: int = 0) -> List[Dict]:
        return self._db.get_mails_for_account(account_id, folder, limit, offset)

    def mark_deleted(self, mail_id: int) -> None:
        self._db.mark_mail_deleted(mail_id)

    def store_raw(self, mail_id: int, raw_data: bytes) -> None:
        self._db.store_raw_mail(mail_id, raw_data)

    def get_raw(self, mail_id: int) -> Optional[bytes]:
        return self._db.get_raw_mail(mail_id)

    def search(self, query: str, limit: int = 50,
               offset: int = 0,
               account_id: Optional[int] = None,
               folder: Optional[str] = None,
               since_date: Optional[str] = None,
               before_date: Optional[str] = None,
               has_attachments: Optional[bool] = None,
               unread_only: Optional[bool] = None) -> List[Dict]:
        return self._db.search_mails(
            query=query, limit=limit, offset=offset,
            account_id=account_id, folder=folder,
            since_date=since_date, before_date=before_date,
            has_attachments=has_attachments, unread_only=unread_only
        )


class SqliteSyncStateRepository(ISyncStateRepository):
    def __init__(self, db: DatabaseManager):
        self._db = db

    def get(self, account_id: int, folder: str) -> Optional[Dict]:
        return self._db.get_sync_state(account_id, folder)

    def update(self, account_id: int, folder: str,
               last_uid: int, uid_validity: int, mail_count: int) -> None:
        self._db.update_sync_state(account_id, folder, last_uid,
                                   uid_validity, mail_count)


class SqliteAttachmentRepository(IAttachmentRepository):
    def __init__(self, db: DatabaseManager):
        self._db = db

    def register(self, sha256_hash: str, filename: str, mime_type: str,
                 size_bytes: int, storage_path: str) -> int:
        return self._db.register_attachment(sha256_hash, filename, mime_type,
                                            size_bytes, storage_path)

    def link(self, mail_id: int, attachment_id: int) -> None:
        self._db.link_attachment(mail_id, attachment_id)


class SqliteDeduplicationRepository(IDeduplicationRepository):
    def __init__(self, db: DatabaseManager):
        self._db = db

    def is_duplicate(self, sha256_hash: str) -> bool:
        return self._db.is_duplicate_hash(sha256_hash)

    def register(self, sha256_hash: str, account_id: int, mail_id: int) -> None:
        self._db.register_hash(sha256_hash, account_id, mail_id)

    def find_duplicates(self) -> List[Dict]:
        return self._db.get_duplicate_mails()


class SqliteAuditRepository(IAuditRepository):
    def __init__(self, db: DatabaseManager):
        self._db = db

    def append(self, action: str, account_id: int = None,
               mail_id: int = None, details: dict = None) -> str:
        return self._db.append_audit_log(action, account_id, mail_id, details)

    def verify_chain(self) -> bool:
        return self._db.verify_audit_chain()

    def get_log(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        return self._db.get_audit_log(limit, offset)


class SqliteStatsRepository(IStatsRepository):
    def __init__(self, db: DatabaseManager):
        self._db = db

    def get_stats(self) -> Dict:
        return self._db.get_stats()
