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
    export_subfolder: str = ""
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
    error_details: List[str] = field(default_factory=list)



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


class Role:
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"

    ALL = [ADMIN, OPERATOR, VIEWER]


@dataclass
class User:
    """Represents a system user with role-based permissions."""
    id: Optional[int] = None
    username: str = ""
    password_hash: str = ""
    salt: str = ""
    full_name: str = ""
    email: str = ""
    role: str = Role.OPERATOR  # ADMIN, OPERATOR, VIEWER
    is_active: bool = True
    last_login: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class SmtpNotificationConfig:
    """SMTP Email Notification Configuration."""
    enabled: bool = False
    host: str = ""
    port: int = 587
    use_tls: bool = True
    username: str = ""
    password: str = ""
    from_address: str = ""
    to_addresses: List[str] = field(default_factory=list)
    notify_on_success: bool = True
    notify_on_failure: bool = True

    @property
    def smtp_host(self) -> str:
        return self.host

    @property
    def smtp_port(self) -> int:
        return self.port

    @property
    def smtp_user(self) -> str:
        return self.username

    @property
    def smtp_from(self) -> str:
        return self.from_address

    @property
    def notify_emails(self) -> str:
        return ", ".join(self.to_addresses)

    @classmethod
    def from_dict(cls, data: dict) -> "SmtpNotificationConfig":
        to_addr = data.get("to_addresses", [])
        if isinstance(to_addr, str):
            to_addr = [x.strip() for x in to_addr.split(",") if x.strip()]
        elif not isinstance(to_addr, list):
            to_addr = []
        return cls(
            enabled=bool(data.get("enabled", False)),
            host=str(data.get("host") or data.get("smtp_host") or ""),
            port=int(data.get("port") or data.get("smtp_port") or 587),
            use_tls=bool(data.get("use_tls", True)),
            username=str(data.get("username") or data.get("smtp_user") or ""),
            password=str(data.get("password") or data.get("smtp_pass") or ""),
            from_address=str(data.get("from_address") or data.get("smtp_from") or ""),
            to_addresses=to_addr,
            notify_on_success=bool(data.get("notify_on_success", True)),
            notify_on_failure=bool(data.get("notify_on_failure", data.get("notify_on_error", True))),
        )


@dataclass
class SqlBackupJob:
    """Configuration for a SQL Database backup job."""
    id: Optional[int] = None
    name: str = ""
    engine_type: str = "mssql"  # mssql, mysql, mariadb, postgres, sqlite
    host: str = "localhost"
    port: int = 1433
    auth_type: str = "windows"  # windows, sql
    username_enc: str = ""
    password_enc: str = ""
    database_name: str = ""
    backup_type: str = "FULL"  # FULL, DIFFERENTIAL, LOG, INCREMENTAL
    dest_dir: str = "data/backups/sql"
    compress_mode: str = "compressed"  # raw, compressed
    verify: bool = True
    retention_mode: str = "count"  # count, days
    retention_value: int = 10  # e.g. keep last 10 backups
    retention_days: int = 30
    auto_on_usb_connect: bool = False
    target_drive_label: str = ""
    cloud_target: str = "none"  # none, s3, gdrive
    schedule_cron: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class VhdxBackupJob:
    """Configuration for a VHDX / Hyper-V Virtual Disk backup job."""
    id: Optional[int] = None
    name: str = ""
    mode: str = "direct_file"  # hyperv_vm, direct_file
    vm_name: str = ""
    source_path: str = ""
    dest_dir: str = "data/backups/vhdx"
    use_vss: bool = True
    compress_mode: str = "raw"  # raw, compressed, dynamic
    verify_hash: bool = True
    retention_mode: str = "count"  # count, days
    retention_value: int = 10  # e.g. keep last 10 backups
    retention_days: int = 30
    auto_on_usb_connect: bool = False
    target_drive_label: str = ""
    cloud_target: str = "none"  # none, s3, gdrive
    schedule_cron: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class SqlBackupReport:
    """Summary report after a SQL backup operation."""
    job_name: str = ""
    engine_type: str = ""
    database_name: str = ""
    backup_type: str = "FULL"
    output_file: Optional[str] = None
    total_bytes: int = 0
    duration_seconds: float = 0.0
    verified: bool = False
    status: str = "SUCCESS"  # SUCCESS, FAILED, PARTIAL
    errors: List[str] = field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


@dataclass
class VhdxBackupReport:
    """Summary report after a VHDX / Hyper-V backup operation."""
    job_name: str = ""
    mode: str = "direct_file"
    source: str = ""
    dest_file: Optional[str] = None
    total_bytes: int = 0
    duration_seconds: float = 0.0
    speed_mbps: float = 0.0
    used_vss: bool = False
    sha256_hash: Optional[str] = None
    status: str = "SUCCESS"  # SUCCESS, FAILED
    errors: List[str] = field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


@dataclass
class BackupHistoryEntry:
    """Unified entry in the backup execution history log."""
    id: Optional[int] = None
    job_type: str = ""  # mail, sql, vhdx
    job_name: str = ""
    status: str = "SUCCESS"  # SUCCESS, FAILED, IN_PROGRESS
    source: str = ""
    target_file: str = ""
    size_bytes: int = 0
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    created_at: Optional[str] = None

