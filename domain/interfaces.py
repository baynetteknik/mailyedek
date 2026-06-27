"""
interfaces.py — Abstract interfaces / ports for the Clean Architecture.

Clean Architecture — Domain Layer.
These are the contracts that infrastructure adapters must implement.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from domain.entities import (
    Attachment, AuditEntry, BackupReport, EmailAccount,
    MailMessage, MailMetadata, SyncReport,
)


# ------------------------------------------------------------------
# Mail Provider Interface (IMAP, Exchange, etc.)
# ------------------------------------------------------------------

class MailProvider(ABC):
    """Abstract mail provider that all mail backends must implement."""

    @abstractmethod
    def connect(self, host: str, port: int, use_ssl: bool,
                username: str, password: str) -> bool:
        """Establish connection to the mail server."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the connection gracefully."""

    @abstractmethod
    def list_folders(self) -> List[Tuple[str, str]]:
        """Return list of (delimiter, folder_name) tuples."""

    @abstractmethod
    def select_folder(self, folder: str) -> Tuple[int, int]:
        """Select a folder. Returns (exists_count, uid_validity)."""

    @abstractmethod
    def fetch_uids(self, folder: str, since_uid: int = 0,
                   since_date: Optional[str] = None,
                   before_date: Optional[str] = None,
                   archive_unread: bool = True) -> List[int]:
        """Fetch UIDs of messages, optionally matching since_uid, since_date, before_date, and read/unread status."""

    @abstractmethod
    def fetch_message(self, uid: int) -> Optional[MailMessage]:
        """Fetch a single message by UID."""

    @abstractmethod
    def fetch_flags(self, uid: int) -> str:
        """Fetch flags for a message by UID."""

    @abstractmethod
    def store_flags(self, uid: int, flags: str) -> None:
        """Set flags on a message by UID."""

    @abstractmethod
    def copy_message(self, uid: int, target_folder: str) -> bool:
        """Copy a message to another folder by UID."""

    @abstractmethod
    def delete_message(self, uid: int) -> bool:
        """Mark a message as deleted by UID."""

    @abstractmethod
    def append_message(self, folder: str, raw_message: bytes,
                       flags: Optional[str] = None) -> bool:
        """Append a raw message to a folder."""

    @abstractmethod
    def search_messages(self, criteria: str) -> List[int]:
        """Search messages by IMAP criteria. Returns UID list."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connection is alive."""

    @abstractmethod
    def get_folder_quota(self, folder: str) -> Tuple[int, int]:
        """Return (used_bytes, quota_bytes) for the folder."""


# ------------------------------------------------------------------
# Cloud Storage Provider Interface (S3, Google Drive, etc.)
# ------------------------------------------------------------------

class CloudStorageProvider(ABC):
    """Abstract cloud storage provider."""

    @abstractmethod
    def connect(self) -> bool:
        """Initialize client and verify connectivity."""

    @abstractmethod
    def upload(self, local_path: Path, remote_key: str) -> bool:
        """Upload a file to cloud storage."""

    @abstractmethod
    def upload_stream(self, stream: Generator[bytes, None, None],
                      remote_key: str, content_length: int) -> bool:
        """Stream-upload a file (multipart for large files)."""

    @abstractmethod
    def download(self, remote_key: str, local_path: Path) -> bool:
        """Download a file from cloud storage."""

    @abstractmethod
    def list_files(self, prefix: str = "") -> List[Dict[str, Any]]:
        """List files under a prefix."""

    @abstractmethod
    def delete_file(self, remote_key: str) -> bool:
        """Delete a file from cloud storage."""

    @abstractmethod
    def file_exists(self, remote_key: str) -> bool:
        """Check if a file exists in cloud storage."""

    @abstractmethod
    def get_quota(self) -> Dict[str, Any]:
        """Return quota/usage info."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the provider client is connected."""


# ------------------------------------------------------------------
# Encryption Provider Interface
# ------------------------------------------------------------------

class EncryptionProvider(ABC):
    """Abstract encryption provider."""

    @abstractmethod
    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string."""

    @abstractmethod
    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a ciphertext string."""

    @abstractmethod
    def hash_content(self, data: bytes) -> str:
        """Return hash of binary data."""

    @abstractmethod
    def hash_file(self, path: Path) -> str:
        """Return hash of a file."""


# ------------------------------------------------------------------
# Database Repository Interface
# ------------------------------------------------------------------

class AccountRepository(ABC):
    @abstractmethod
    def add(self, account: EmailAccount) -> int: ...
    @abstractmethod
    def get(self, account_id: int) -> Optional[EmailAccount]: ...
    @abstractmethod
    def get_all(self) -> List[EmailAccount]: ...
    @abstractmethod
    def update(self, account_id: int, **kwargs) -> None: ...
    @abstractmethod
    def delete(self, account_id: int) -> None: ...


class MailRepository(ABC):
    @abstractmethod
    def upsert_metadata(self, metadata: MailMetadata) -> int: ...
    @abstractmethod
    def get_by_uid(self, account_id: int, folder: str, uid: int) -> Optional[MailMetadata]: ...
    @abstractmethod
    def get_for_account(self, account_id: int, folder: str,
                        limit: int, offset: int) -> List[MailMetadata]: ...
    @abstractmethod
    def mark_deleted(self, mail_id: int) -> None: ...
    @abstractmethod
    def store_raw(self, mail_id: int, raw_data: bytes) -> None: ...
    @abstractmethod
    def get_raw(self, mail_id: int) -> Optional[bytes]: ...


class SyncStateRepository(ABC):
    @abstractmethod
    def get(self, account_id: int, folder: str) -> Optional[SyncState]: ...
    @abstractmethod
    def update(self, state: SyncState) -> None: ...


class AttachmentRepository(ABC):
    @abstractmethod
    def register(self, attachment: Attachment) -> int: ...
    @abstractmethod
    def link(self, mail_id: int, attachment_id: int) -> None: ...


class DeduplicationRepository(ABC):
    @abstractmethod
    def is_duplicate(self, sha256_hash: str) -> bool: ...
    @abstractmethod
    def register(self, sha256_hash: str, account_id: int, mail_id: int) -> None: ...


class AuditRepository(ABC):
    @abstractmethod
    def append(self, action: str, account_id: int = None,
               mail_id: int = None, details: dict = None) -> str: ...
    @abstractmethod
    def verify_chain(self) -> bool: ...
    @abstractmethod
    def get_log(self, limit: int, offset: int) -> List[AuditEntry]: ...


class SearchRepository(ABC):
    @abstractmethod
    def search(self, query: str, limit: int, offset: int) -> List[MailMetadata]: ...
    @abstractmethod
    def rebuild_index(self) -> None: ...


# ------------------------------------------------------------------
# Plugin Provider Interface
# ------------------------------------------------------------------

class PluginProvider(ABC):
    """Base class for all plugin providers."""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def initialize(self) -> None: ...

    @abstractmethod
    def shutdown(self) -> None: ...
