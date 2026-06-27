"""
entities.py — Domain entities (business objects).

Clean Architecture — Domain Layer.
These are plain Python objects with no dependencies on frameworks, databases,
or infrastructure. They represent the core business concepts.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class EmailAccount:
    """Represents an IMAP email account."""
    id: Optional[int] = None
    label: str = ""
    email: str = ""
    imap_host: str = ""
    imap_port: int = 993
    use_ssl: bool = True
    username_enc: str = ""
    password_enc: str = ""
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class MailMetadata:
    """Core mail metadata (not the raw content)."""
    id: Optional[int] = None
    account_id: int = 0
    folder: str = "INBOX"
    uid: int = 0
    message_id: Optional[str] = None
    subject: Optional[str] = None
    sender: Optional[str] = None
    recipients: Optional[str] = None
    cc: Optional[str] = None
    bcc: Optional[str] = None
    date: Optional[str] = None
    internal_date: Optional[str] = None
    flags: str = ""
    size_bytes: int = 0
    has_attachments: bool = False
    sha256_hash: Optional[str] = None
    is_deleted: bool = False
    is_duplicate: bool = False
    fetched_at: Optional[str] = None


@dataclass
class Attachment:
    """Content-addressable attachment."""
    id: Optional[int] = None
    sha256_hash: str = ""
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: int = 0
    storage_path: Optional[str] = None
    ref_count: int = 0
    created_at: Optional[str] = None
    data: Optional[bytes] = None


@dataclass
class SyncState:
    """Tracks incremental sync progress per account/folder."""
    id: Optional[int] = None
    account_id: int = 0
    folder: str = "INBOX"
    last_uid: int = 0
    uid_validity: int = 0
    last_sync_at: Optional[str] = None
    mail_count: int = 0


@dataclass
class MailMessage:
    """Full email message with metadata and content."""
    metadata: MailMetadata
    raw_content: Optional[bytes] = None
    attachments: List[Attachment] = field(default_factory=list)
    body_text: Optional[str] = None
    body_html: Optional[str] = None


@dataclass
class AuditEntry:
    """Immutable audit trail entry."""
    id: Optional[int] = None
    timestamp: Optional[str] = None
    action: str = ""
    account_id: Optional[int] = None
    mail_id: Optional[int] = None
    details: Optional[str] = None
    previous_hash: str = ""
    current_hash: str = ""


@dataclass
class SyncReport:
    """Summary report after a sync operation."""
    account_label: str = ""
    folders_synced: int = 0
    mails_fetched: int = 0
    mails_updated: int = 0
    duplicates_found: int = 0
    errors: int = 0
    total_bytes: int = 0
    duration_seconds: float = 0.0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    mails_already_archived: int = 0


@dataclass
class BackupReport:
    """Summary report after a backup operation."""
    target: str = ""  # e.g. "s3", "gdrive"
    mails_backed_up: int = 0
    total_bytes: int = 0
    parts_uploaded: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
