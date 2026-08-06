"""
repositories.py — Abstract repository interfaces (ports).

Clean Architecture — Domain Layer.
Defines the contracts that infrastructure repositories must fulfil.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from domain.entities import (
    EmailAccount, MailMetadata, Attachment,
    SyncState, AuditEntry,
)


class IAccountRepository(ABC):
    @abstractmethod
    def add(self, label: str, email: str, imap_host: str, imap_port: int,
            use_ssl: bool, username_enc: str, password_enc: str, export_subfolder: str = "",
            account_group: str = "") -> int: ...

    @abstractmethod
    def get(self, account_id: int) -> Optional[Dict]: ...

    @abstractmethod
    def get_all(self) -> List[Dict]: ...

    @abstractmethod
    def update(self, account_id: int, **kwargs) -> None: ...

    @abstractmethod
    def delete(self, account_id: int) -> None: ...


class IMailRepository(ABC):
    @abstractmethod
    def upsert(self, account_id: int, folder: str, uid: int,
               **fields) -> int: ...

    @abstractmethod
    def get_by_uid(self, account_id: int, folder: str,
                   uid: int) -> Optional[Dict]: ...

    @abstractmethod
    def get_for_account(self, account_id: int, folder: str = "INBOX",
                        limit: int = 1000, offset: int = 0) -> List[Dict]: ...

    @abstractmethod
    def mark_deleted(self, mail_id: int) -> None: ...

    @abstractmethod
    def store_raw(self, mail_id: int, raw_data: bytes) -> None: ...

    @abstractmethod
    def get_raw(self, mail_id: int) -> Optional[bytes]: ...

    @abstractmethod
    def search(self, query: str, limit: int = 50,
               offset: int = 0,
               account_id: Optional[int] = None,
               folder: Optional[str] = None,
               since_date: Optional[str] = None,
               before_date: Optional[str] = None,
               has_attachments: Optional[bool] = None,
               unread_only: Optional[bool] = None) -> List[Dict]: ...


class ISyncStateRepository(ABC):
    @abstractmethod
    def get(self, account_id: int, folder: str) -> Optional[Dict]: ...

    @abstractmethod
    def update(self, account_id: int, folder: str,
               last_uid: int, uid_validity: int, mail_count: int) -> None: ...


class IAttachmentRepository(ABC):
    @abstractmethod
    def register(self, sha256_hash: str, filename: str, mime_type: str,
                 size_bytes: int, storage_path: str) -> int: ...

    @abstractmethod
    def link(self, mail_id: int, attachment_id: int) -> None: ...


class IDeduplicationRepository(ABC):
    @abstractmethod
    def is_duplicate(self, sha256_hash: str) -> bool: ...

    @abstractmethod
    def register(self, sha256_hash: str, account_id: int, mail_id: int) -> None: ...

    @abstractmethod
    def find_duplicates(self) -> List[Dict]: ...


class IAuditRepository(ABC):
    @abstractmethod
    def append(self, action: str, account_id: int = None,
               mail_id: int = None, details: dict = None) -> str: ...

    @abstractmethod
    def verify_chain(self) -> bool: ...

    @abstractmethod
    def get_log(self, limit: int = 100, offset: int = 0) -> List[Dict]: ...


class IStatsRepository(ABC):
    @abstractmethod
    def get_stats(self) -> Dict: ...
