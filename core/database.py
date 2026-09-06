"""
database.py — SQLite management, FTS5 full-text search, deduplication,
audit trail (append-only hash chain), delta sync state tracking.

Clean Architecture — Core Layer.
"""

import json
import logging
import sqlite3
import threading
import hashlib
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/mail_archive.db")


class DatabaseManager:
    """Manages all SQLite operations with thread-safe connection pooling.

    Tables:
      - accounts           : Encrypted IMAP credentials
      - mail_metadata      : Core mail metadata (UID, Message-ID, flags, etc.)
      - mail_raw           : Raw RFC 822 content (optional, compressed)
      - attachments        : Content-addressable attachment store
      - attachment_links   : Many-to-many between mails and attachments
      - sync_state         : Per-account delta sync tracking
      - audit_log          : Append-only, hash-chained immutable log
      - mail_fts           : FTS5 virtual table for full-text search
      - dedup_hash         : Hash-based deduplication registry
    """

    _instance: Optional["DatabaseManager"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @contextmanager
    def get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a thread-local connection with WAL mode."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=60.0, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=60000")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        yield self._local.conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a connection with an active transaction and lock retry logic."""
        with self.get_conn() as conn:
            if conn.in_transaction:
                yield conn
                return

            max_retries = 8
            backoff = 0.2
            for attempt in range(max_retries):
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" in str(exc).lower() and attempt < max_retries - 1:
                        time.sleep(backoff)
                        backoff *= 1.5
                    else:
                        raise
            try:
                yield conn
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise

    # ------------------------------------------------------------------
    # Schema initialization
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self.get_conn() as conn:
            conn.executescript("""
                -- Accounts
                CREATE TABLE IF NOT EXISTS accounts (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    label           TEXT NOT NULL,
                    email           TEXT NOT NULL,
                    imap_host       TEXT NOT NULL,
                    imap_port       INTEGER NOT NULL DEFAULT 993,
                    use_ssl         INTEGER NOT NULL DEFAULT 1,
                    username_enc    TEXT NOT NULL,
                    password_enc    TEXT NOT NULL,
                    is_active       INTEGER NOT NULL DEFAULT 1,
                    export_subfolder TEXT DEFAULT '',
                    account_group   TEXT DEFAULT '',
                    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );

                -- Mail metadata
                CREATE TABLE IF NOT EXISTS mail_metadata (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id      INTEGER NOT NULL REFERENCES accounts(id),
                    folder          TEXT NOT NULL DEFAULT 'INBOX',
                    uid             INTEGER NOT NULL,
                    message_id      TEXT,
                    subject         TEXT,
                    sender          TEXT,
                    recipients      TEXT,
                    cc              TEXT,
                    bcc             TEXT,
                    date            TEXT,
                    internal_date   TEXT,
                    flags           TEXT DEFAULT '',
                    size_bytes      INTEGER DEFAULT 0,
                    has_attachments INTEGER DEFAULT 0,
                    sha256_hash     TEXT,
                    is_deleted      INTEGER DEFAULT 0,
                    is_duplicate    INTEGER DEFAULT 0,
                    fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(account_id, folder, uid)
                );

                -- Raw email content (stored optionally, can be reconstructed)
                CREATE TABLE IF NOT EXISTS mail_raw (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    mail_id         INTEGER NOT NULL REFERENCES mail_metadata(id),
                    raw_data        BLOB,
                    compressed      INTEGER DEFAULT 0
                );

                -- Content-addressable attachments
                CREATE TABLE IF NOT EXISTS attachments (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    sha256_hash     TEXT NOT NULL UNIQUE,
                    filename        TEXT,
                    mime_type       TEXT,
                    size_bytes      INTEGER DEFAULT 0,
                    storage_path    TEXT,
                    ref_count       INTEGER DEFAULT 0,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );

                -- Mail <-> Attachment links
                CREATE TABLE IF NOT EXISTS attachment_links (
                    mail_id         INTEGER NOT NULL REFERENCES mail_metadata(id),
                    attachment_id   INTEGER NOT NULL REFERENCES attachments(id),
                    PRIMARY KEY (mail_id, attachment_id)
                );

                -- Delta sync state per account/folder
                CREATE TABLE IF NOT EXISTS sync_state (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id      INTEGER NOT NULL REFERENCES accounts(id),
                    folder          TEXT NOT NULL DEFAULT 'INBOX',
                    last_uid        INTEGER DEFAULT 0,
                    uid_validity    INTEGER DEFAULT 0,
                    last_sync_at    TEXT,
                    mail_count      INTEGER DEFAULT 0,
                    UNIQUE(account_id, folder)
                );

                -- Deduplication registry (hash-based)
                CREATE TABLE IF NOT EXISTS dedup_hash (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    sha256_hash     TEXT NOT NULL,
                    account_id      INTEGER NOT NULL REFERENCES accounts(id),
                    mail_id         INTEGER NOT NULL REFERENCES mail_metadata(id),
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_dedup_hash ON dedup_hash(sha256_hash);

                -- Audit trail (append-only, hash-chained)
                CREATE TABLE IF NOT EXISTS audit_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
                    action          TEXT NOT NULL,
                    account_id      INTEGER,
                    mail_id         INTEGER,
                    details         TEXT,
                    previous_hash   TEXT NOT NULL DEFAULT '',
                    current_hash    TEXT NOT NULL,
                    UNIQUE(current_hash)
                );

                -- FTS5 virtual table for full-text search
                -- Standalone FTS5 table (populated via triggers or rebuild)
                CREATE VIRTUAL TABLE IF NOT EXISTS mail_fts USING fts5(
                    subject, sender, recipients, body_text, attachment_names,
                    tokenize='unicode61'
                );

                -- Indexes
                CREATE INDEX IF NOT EXISTS idx_mail_account_folder
                    ON mail_metadata(account_id, folder);
                CREATE INDEX IF NOT EXISTS idx_mail_uid
                    ON mail_metadata(account_id, folder, uid);
                CREATE INDEX IF NOT EXISTS idx_mail_message_id
                    ON mail_metadata(message_id);
                CREATE INDEX IF NOT EXISTS idx_mail_account_deleted
                    ON mail_metadata(account_id, is_deleted);
                CREATE INDEX IF NOT EXISTS idx_mail_date
                    ON mail_metadata(date);
                CREATE INDEX IF NOT EXISTS idx_mail_sender
                    ON mail_metadata(sender);
                CREATE INDEX IF NOT EXISTS idx_mail_has_attachments
                    ON mail_metadata(has_attachments);
                CREATE INDEX IF NOT EXISTS idx_mail_duplicate
                    ON mail_metadata(is_duplicate);
                CREATE INDEX IF NOT EXISTS idx_sync_state_lookup
                    ON sync_state(account_id, folder);
                CREATE INDEX IF NOT EXISTS idx_audit_action_ts
                    ON audit_log(action, timestamp DESC);

                -- Account Server Profiles (Multiple IMAP Endpoints per Account)
                CREATE TABLE IF NOT EXISTS account_server_profiles (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    profile_name    TEXT NOT NULL,
                    imap_host       TEXT NOT NULL,
                    imap_port       INTEGER NOT NULL DEFAULT 993,
                    use_ssl         INTEGER NOT NULL DEFAULT 1,
                    username_enc    TEXT NOT NULL,
                    password_enc    TEXT NOT NULL,
                    is_default      INTEGER NOT NULL DEFAULT 0,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_server_profiles_account
                    ON account_server_profiles(account_id);

                -- Users & Role-Based Access Control
                CREATE TABLE IF NOT EXISTS users (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    username        TEXT NOT NULL UNIQUE,
                    password_hash   TEXT NOT NULL,
                    salt            TEXT NOT NULL,
                    full_name       TEXT DEFAULT '',
                    email           TEXT DEFAULT '',
                    role            TEXT NOT NULL DEFAULT 'OPERATOR',
                    is_active       INTEGER NOT NULL DEFAULT 1,
                    last_login      TEXT,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );

                -- SQL Backup Jobs
                CREATE TABLE IF NOT EXISTS sql_backup_jobs (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT NOT NULL,
                    engine_type     TEXT NOT NULL DEFAULT 'mssql',
                    host            TEXT NOT NULL DEFAULT 'localhost',
                    port            INTEGER NOT NULL DEFAULT 1433,
                    auth_type       TEXT NOT NULL DEFAULT 'windows',
                    username_enc    TEXT DEFAULT '',
                    password_enc    TEXT DEFAULT '',
                    database_name   TEXT NOT NULL,
                    backup_type     TEXT NOT NULL DEFAULT 'FULL',
                    dest_dir        TEXT NOT NULL,
                    compress        INTEGER NOT NULL DEFAULT 1,
                    compress_mode   TEXT DEFAULT 'compressed',
                    verify          INTEGER NOT NULL DEFAULT 1,
                    retention_mode  TEXT DEFAULT 'count',
                    retention_value INTEGER NOT NULL DEFAULT 10,
                    retention_days  INTEGER NOT NULL DEFAULT 30,
                    auto_on_usb_connect INTEGER DEFAULT 0,
                    target_drive_label TEXT DEFAULT '',
                    cloud_target    TEXT DEFAULT 'none',
                    schedule_cron   TEXT DEFAULT '',
                    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );

                -- VHDX & Hyper-V Backup Jobs
                CREATE TABLE IF NOT EXISTS vhdx_backup_jobs (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT NOT NULL,
                    mode            TEXT NOT NULL DEFAULT 'direct_file',
                    vm_name         TEXT DEFAULT '',
                    source_path     TEXT DEFAULT '',
                    dest_dir        TEXT NOT NULL,
                    use_vss         INTEGER NOT NULL DEFAULT 1,
                    compress        INTEGER NOT NULL DEFAULT 0,
                    compress_mode   TEXT DEFAULT 'raw',
                    verify_hash     INTEGER NOT NULL DEFAULT 1,
                    retention_mode  TEXT DEFAULT 'count',
                    retention_value INTEGER NOT NULL DEFAULT 10,
                    retention_days  INTEGER NOT NULL DEFAULT 30,
                    auto_on_usb_connect INTEGER DEFAULT 0,
                    target_drive_label TEXT DEFAULT '',
                    cloud_target    TEXT DEFAULT 'none',
                    schedule_cron   TEXT DEFAULT '',
                    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );

                -- Unified Backup History
                CREATE TABLE IF NOT EXISTS general_backup_history (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_type        TEXT NOT NULL,
                    job_name        TEXT NOT NULL,
                    status          TEXT NOT NULL,
                    source          TEXT DEFAULT '',
                    target_file     TEXT DEFAULT '',
                    size_bytes      INTEGER DEFAULT 0,
                    duration_seconds REAL DEFAULT 0.0,
                    error_message   TEXT DEFAULT '',
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_backup_hist_type_ts
                    ON general_backup_history(job_type, created_at DESC);
            """)

            # Auto-seed default admin user if users table is empty
            try:
                user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                if user_count == 0:
                    from core.auth_manager import hash_password
                    pwd_hash, salt = hash_password("admin123")
                    conn.execute(
                        """INSERT INTO users (username, password_hash, salt, full_name, email, role, is_active)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        ("admin", pwd_hash, salt, "Sistem Yöneticisi", "admin@localhost", "ADMIN", 1)
                    )
            except Exception as exc:
                logger.warning("Failed to seed initial admin user: %s", exc)

            # Migrations for jobs table new columns
            for table in ["sql_backup_jobs", "vhdx_backup_jobs"]:
                for col, typ in [
                    ("retention_mode", "TEXT DEFAULT 'count'"),
                    ("retention_value", "INTEGER DEFAULT 10"),
                    ("compress_mode", "TEXT DEFAULT 'compressed'"),
                    ("auto_on_usb_connect", "INTEGER DEFAULT 0"),
                    ("target_drive_label", "TEXT DEFAULT ''")
                ]:
                    try:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                    except sqlite3.OperationalError:
                        pass
            try:
                conn.execute("ALTER TABLE accounts ADD COLUMN export_subfolder TEXT DEFAULT ''")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    logger.warning("Failed to add export_subfolder column to accounts: %s", exc)
            try:
                conn.execute("ALTER TABLE accounts ADD COLUMN account_group TEXT DEFAULT ''")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    logger.warning("Failed to add account_group column to accounts: %s", exc)
            try:
                conn.execute("ALTER TABLE mail_metadata ADD COLUMN server_host TEXT DEFAULT ''")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    logger.warning("Failed to add server_host column to mail_metadata: %s", exc)
            try:
                conn.execute("ALTER TABLE sync_state ADD COLUMN server_host TEXT DEFAULT ''")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    logger.warning("Failed to add server_host column to sync_state: %s", exc)

            # Self-healing: Ensure every existing account has at least 1 server profile in account_server_profiles
            try:
                accs = conn.execute("SELECT * FROM accounts").fetchall()
                for acc in accs:
                    existing_p = conn.execute(
                        "SELECT id FROM account_server_profiles WHERE account_id=?", (acc["id"],)
                    ).fetchone()
                    if not existing_p:
                        p_name = f"{acc['imap_host']} (Varsayılan)"
                        conn.execute(
                            """INSERT INTO account_server_profiles
                               (account_id, profile_name, imap_host, imap_port, use_ssl, username_enc, password_enc, is_default)
                               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                            (acc["id"], p_name, acc["imap_host"], acc["imap_port"], acc["use_ssl"], acc["username_enc"], acc["password_enc"])
                        )
            except Exception as p_err:
                logger.warning("Self-healing server profiles failed: %s", p_err)

            logger.info("Database schema initialized at %s", self._db_path)

    # ------------------------------------------------------------------
    # Account operations
    # ------------------------------------------------------------------

    def add_account(self, label: str, email: str, imap_host: str, imap_port: int,
                    use_ssl: bool, username_enc: str, password_enc: str, export_subfolder: str = "",
                    account_group: str = "") -> int:
        with self.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO accounts (label, email, imap_host, imap_port, use_ssl,
                                        username_enc, password_enc, export_subfolder, account_group)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (label, email, imap_host, imap_port, int(use_ssl), username_enc, password_enc, export_subfolder, account_group)
            )
            acc_id = cur.lastrowid
            # Create default server profile
            p_name = f"{imap_host} (Varsayılan)"
            conn.execute(
                """INSERT INTO account_server_profiles
                   (account_id, profile_name, imap_host, imap_port, use_ssl, username_enc, password_enc, is_default)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (acc_id, p_name, imap_host, imap_port, int(use_ssl), username_enc, password_enc)
            )
            return acc_id

    # ------------------------------------------------------------------
    # Server profile operations (Multi-Server Endpoints)
    # ------------------------------------------------------------------

    def add_server_profile(self, account_id: int, profile_name: str, imap_host: str,
                           imap_port: int, use_ssl: bool, username_enc: str, password_enc: str,
                           make_default: bool = False) -> int:
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) as cnt FROM account_server_profiles WHERE account_id=?", (account_id,)
            ).fetchone()
            is_first = (existing["cnt"] == 0)
            should_be_default = 1 if (make_default or is_first) else 0

            if should_be_default:
                conn.execute(
                    "UPDATE account_server_profiles SET is_default=0 WHERE account_id=?", (account_id,)
                )

            cur = conn.execute(
                """INSERT INTO account_server_profiles
                   (account_id, profile_name, imap_host, imap_port, use_ssl, username_enc, password_enc, is_default)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (account_id, profile_name, imap_host, imap_port, int(use_ssl), username_enc, password_enc, should_be_default)
            )
            prof_id = cur.lastrowid

            if should_be_default:
                conn.execute(
                    """UPDATE accounts SET imap_host=?, imap_port=?, use_ssl=?, username_enc=?, password_enc=?
                       WHERE id=?""",
                    (imap_host, imap_port, int(use_ssl), username_enc, password_enc, account_id)
                )
            return prof_id

    def get_server_profiles(self, account_id: int) -> List[Dict[str, Any]]:
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM account_server_profiles WHERE account_id=? ORDER BY is_default DESC, id ASC",
                (account_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_active_server_profile(self, account_id: int) -> Optional[Dict[str, Any]]:
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM account_server_profiles WHERE account_id=? AND is_default=1 LIMIT 1",
                (account_id,)
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT * FROM account_server_profiles WHERE account_id=? ORDER BY id ASC LIMIT 1",
                    (account_id,)
                ).fetchone()
            return dict(row) if row else None

    def set_default_server_profile(self, account_id: int, profile_id: int) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE account_server_profiles SET is_default=0 WHERE account_id=?", (account_id,)
            )
            conn.execute(
                "UPDATE account_server_profiles SET is_default=1 WHERE id=? AND account_id=?",
                (profile_id, account_id)
            )
            prof = conn.execute(
                "SELECT * FROM account_server_profiles WHERE id=?", (profile_id,)
            ).fetchone()
            if prof:
                conn.execute(
                    """UPDATE accounts SET imap_host=?, imap_port=?, use_ssl=?, username_enc=?, password_enc=?
                       WHERE id=?""",
                    (prof["imap_host"], prof["imap_port"], prof["use_ssl"], prof["username_enc"], prof["password_enc"], account_id)
                )

    def delete_server_profile(self, account_id: int, profile_id: int) -> None:
        with self.transaction() as conn:
            prof = conn.execute(
                "SELECT is_default FROM account_server_profiles WHERE id=? AND account_id=?",
                (profile_id, account_id)
            ).fetchone()
            if not prof:
                return

            was_default = bool(prof["is_default"])
            conn.execute("DELETE FROM account_server_profiles WHERE id=?", (profile_id,))

            if was_default:
                remaining = conn.execute(
                    "SELECT id, imap_host, imap_port, use_ssl, username_enc, password_enc "
                    "FROM account_server_profiles WHERE account_id=? ORDER BY id ASC LIMIT 1",
                    (account_id,)
                ).fetchone()
                if remaining:
                    conn.execute("UPDATE account_server_profiles SET is_default=1 WHERE id=?", (remaining["id"],))
                    conn.execute(
                        """UPDATE accounts SET imap_host=?, imap_port=?, use_ssl=?, username_enc=?, password_enc=?
                           WHERE id=?""",
                        (remaining["imap_host"], remaining["imap_port"], remaining["use_ssl"], remaining["username_enc"], remaining["password_enc"], account_id)
                    )

    def get_account(self, account_id: int) -> Optional[Dict[str, Any]]:
        with self.get_conn() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            return dict(row) if row else None

    def get_all_accounts(self, active_only: bool = False) -> List[Dict[str, Any]]:
        with self.get_conn() as conn:
            if active_only:
                rows = conn.execute("SELECT * FROM accounts WHERE is_active = 1").fetchall()
            else:
                rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def update_account(self, account_id: int, **kwargs) -> None:
        fields = {k: v for k, v in kwargs.items() if k in (
            "label", "email", "imap_host", "imap_port", "use_ssl",
            "username_enc", "password_enc", "is_active", "export_subfolder", "account_group"
        )}
        if not fields:
            return
        fields["updated_at"] = datetime.utcnow().isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [account_id]
        with self.transaction() as conn:
            conn.execute(f"UPDATE accounts SET {set_clause} WHERE id = ?", values)

    def delete_account(self, account_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM mail_metadata WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM sync_state WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

    # ------------------------------------------------------------------
    # Mail metadata operations
    # ------------------------------------------------------------------

    def upsert_mail_metadata(self, account_id: int, folder: str, uid: int,
                             **fields) -> int:
        """Insert or update mail metadata. Returns the mail_metadata.id."""
        fields.setdefault("fetched_at", datetime.utcnow().isoformat())
        server_host = fields.get("server_host", "")
        with self.transaction() as conn:
            if server_host:
                existing = conn.execute(
                    "SELECT id FROM mail_metadata WHERE account_id=? AND folder=? AND uid=? AND server_host=?",
                    (account_id, folder, uid, server_host)
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT id FROM mail_metadata WHERE account_id=? AND folder=? AND uid=?",
                    (account_id, folder, uid)
                ).fetchone()

            if existing:
                set_clause = ", ".join(f"{k} = ?" for k in fields)
                values = list(fields.values()) + [existing["id"]]
                conn.execute(f"UPDATE mail_metadata SET {set_clause} WHERE id = ?", values)
                return existing["id"]
            else:
                cols = ["account_id", "folder", "uid"] + list(fields.keys())
                placeholders = ", ".join("?" for _ in cols)
                values = [account_id, folder, uid] + list(fields.values())
                cur = conn.execute(
                    f"INSERT INTO mail_metadata ({', '.join(cols)}) VALUES ({placeholders})",
                    values
                )
                return cur.lastrowid

    def get_mail_by_uid(self, account_id: int, folder: str, uid: int, server_host: str = "") -> Optional[Dict[str, Any]]:
        with self.get_conn() as conn:
            if server_host:
                row = conn.execute(
                    "SELECT * FROM mail_metadata WHERE account_id=? AND folder=? AND uid=? AND server_host=?",
                    (account_id, folder, uid, server_host)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM mail_metadata WHERE account_id=? AND folder=? AND uid=?",
                    (account_id, folder, uid)
                ).fetchone()
            return dict(row) if row else None

    def get_mails_for_account(self, account_id: int, folder: str = "INBOX",
                              limit: int = 1000, offset: int = 0) -> List[Dict[str, Any]]:
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM mail_metadata WHERE account_id=? AND folder=? AND is_deleted=0 "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (account_id, folder, limit, offset)
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_mail_deleted(self, mail_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE mail_metadata SET is_deleted=1 WHERE id=?", (mail_id,))

    # ------------------------------------------------------------------
    # Sync state operations
    # ------------------------------------------------------------------

    def get_sync_state(self, account_id: int, folder: str) -> Optional[Dict[str, Any]]:
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM sync_state WHERE account_id=? AND folder=?",
                (account_id, folder)
            ).fetchone()
            return dict(row) if row else None

    def update_sync_state(self, account_id: int, folder: str,
                          last_uid: int, uid_validity: int, mail_count: int,
                          server_host: str = "") -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO sync_state (account_id, folder, last_uid, uid_validity,
                                           last_sync_at, mail_count, server_host)
                   VALUES (?, ?, ?, ?, datetime('now'), ?, ?)
                   ON CONFLICT(account_id, folder) DO UPDATE SET
                       last_uid=excluded.last_uid,
                       uid_validity=excluded.uid_validity,
                       last_sync_at=excluded.last_sync_at,
                       mail_count=excluded.mail_count,
                       server_host=excluded.server_host""",
                (account_id, folder, last_uid, uid_validity, mail_count, server_host)
            )

    def reset_account_sync_state(self, account_id: int, reason: str = "server_migration") -> int:
        """Reset last_uid and uid_validity for an account to force a fresh re-sync of UIDs from a new server,
        without deleting any previously archived mail_metadata or raw messages.
        """
        with self.transaction() as conn:
            cur = conn.execute(
                "UPDATE sync_state SET last_uid = 0, uid_validity = 0, last_sync_at = datetime('now') "
                "WHERE account_id = ?",
                (account_id,)
            )
            affected = cur.rowcount
            logger.info("Reset sync state for account %d (affected %d folders, reason: %s)",
                        account_id, affected, reason)
            return affected

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def is_duplicate_hash(self, sha256_hash: str) -> bool:
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM dedup_hash WHERE sha256_hash=? LIMIT 1",
                (sha256_hash,)
            ).fetchone()
            return row is not None

    def register_hash(self, sha256_hash: str, account_id: int, mail_id: int) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO dedup_hash (sha256_hash, account_id, mail_id) VALUES (?, ?, ?)",
                (sha256_hash, account_id, mail_id)
            )

    def get_duplicate_mails(self) -> List[Dict[str, Any]]:
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT m.* FROM mail_metadata m
                   WHERE m.is_duplicate = 1 ORDER BY m.fetched_at DESC"""
            ).fetchall()
            return [dict(r) for r in rows]

    def find_duplicates_by_hash(self) -> List[Dict[str, Any]]:
        """Return all mail IDs grouped by hash that appear more than once."""
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT sha256_hash, COUNT(*) as cnt,
                          GROUP_CONCAT(mail_id) as mail_ids
                   FROM dedup_hash GROUP BY sha256_hash HAVING cnt > 1"""
            ).fetchall()
            return [dict(r) for r in rows]

    def deduplicate_by_hash(self, account_id: int) -> int:
        """Mark duplicate mails for *account_id*. Returns number of duplicates found."""
        with self.transaction() as conn:
            rows = conn.execute(
                """SELECT m.id, m.sha256_hash
                   FROM mail_metadata m
                   WHERE m.account_id = ? AND m.sha256_hash IS NOT NULL
                   ORDER BY m.fetched_at ASC""",
                (account_id,)
            ).fetchall()
            seen: set = set()
            dup_count = 0
            for row in rows:
                if row["sha256_hash"] in seen:
                    conn.execute("UPDATE mail_metadata SET is_duplicate=1 WHERE id=?", (row["id"],))
                    dup_count += 1
                else:
                    seen.add(row["sha256_hash"])
            return dup_count

    # ------------------------------------------------------------------
    # Attachment store (content-addressable)
    # ------------------------------------------------------------------

    def register_attachment(self, sha256_hash: str, filename: str,
                            mime_type: str, size_bytes: int,
                            storage_path: str) -> int:
        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT id FROM attachments WHERE sha256_hash=?", (sha256_hash,)
            ).fetchone()
            if existing:
                conn.execute("UPDATE attachments SET ref_count = ref_count + 1 WHERE id=?",
                             (existing["id"],))
                return existing["id"]
            cur = conn.execute(
                """INSERT INTO attachments (sha256_hash, filename, mime_type,
                                            size_bytes, storage_path, ref_count)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (sha256_hash, filename, mime_type, size_bytes, storage_path)
            )
            return cur.lastrowid

    def link_attachment(self, mail_id: int, attachment_id: int) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO attachment_links (mail_id, attachment_id) VALUES (?, ?)",
                (mail_id, attachment_id)
            )

    # ------------------------------------------------------------------
    # FTS5 full-text search
    # ------------------------------------------------------------------

    def rebuild_fts_index(self) -> None:
        """Rebuild the FTS index from mail_metadata."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM mail_fts")
            conn.execute("""
                INSERT INTO mail_fts(rowid, subject, sender, recipients, body_text, attachment_names)
                SELECT m.id, m.subject, m.sender, m.recipients, '', ''
                FROM mail_metadata m
                WHERE m.is_deleted = 0
            """)
            logger.info("FTS index rebuilt")

    def search_mails(self, query: str, limit: int = 50,
                     offset: int = 0,
                     account_id: Optional[int] = None,
                     folder: Optional[str] = None,
                     since_date: Optional[str] = None,
                     before_date: Optional[str] = None,
                     has_attachments: Optional[bool] = None,
                     unread_only: Optional[bool] = None) -> List[Dict[str, Any]]:
        """Search archived emails with metadata filtering and optional FTS5 matching."""
        with self.get_conn() as conn:
            sql = "SELECT * FROM mail_metadata WHERE is_deleted = 0"
            params = []

            if query and query.strip():
                sql += " AND id IN (SELECT rowid FROM mail_fts WHERE mail_fts MATCH ?)"
                params.append(query.strip())

            if account_id is not None:
                sql += " AND account_id = ?"
                params.append(account_id)

            if folder:
                if isinstance(folder, (list, tuple, set)):
                    if len(folder) == 1:
                        sql += " AND folder = ?"
                        params.append(list(folder)[0])
                    elif len(folder) > 1:
                        placeholders = ", ".join("?" for _ in folder)
                        sql += f" AND folder IN ({placeholders})"
                        params.extend(list(folder))
                elif isinstance(folder, str) and folder.strip():
                    sql += " AND folder = ?"
                    params.append(folder.strip())

            if since_date:
                sql += " AND date >= ?"
                params.append(since_date)

            if before_date:
                sql += " AND date <= ?"
                params.append(before_date)

            if has_attachments is not None:
                sql += " AND has_attachments = ?"
                params.append(1 if has_attachments else 0)

            if unread_only is not None:
                if unread_only:
                    sql += " AND flags NOT LIKE '%\\Seen%'"
                else:
                    sql += " AND flags LIKE '%\\Seen%'"

            sql += " ORDER BY date DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Audit trail (append-only, hash-chained)
    # ------------------------------------------------------------------

    def append_audit_log(self, action: str, account_id: Optional[int] = None,
                         mail_id: Optional[int] = None,
                         details: Optional[Dict[str, Any]] = None) -> str:
        """Append an entry to the immutable audit log.

        Returns the current_hash for chaining.
        """
        previous_hash = self._get_last_audit_hash()
        timestamp = datetime.utcnow().isoformat()
        raw = f"{timestamp}|{action}|{account_id}|{mail_id}|{json.dumps(details or {})}|{previous_hash}"
        current_hash = hashlib.sha256(raw.encode()).hexdigest()

        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO audit_log (timestamp, action, account_id, mail_id, details,
                                          previous_hash, current_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (timestamp, action, account_id, mail_id, json.dumps(details or {}),
                 previous_hash, current_hash)
            )
        return current_hash

    def _get_last_audit_hash(self) -> str:
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT current_hash FROM audit_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row["current_hash"] if row else "GENESIS_HASH"

    def verify_audit_chain(self) -> bool:
        """Verify the integrity of the entire audit log hash chain."""
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT id, timestamp, action, account_id, mail_id, details, previous_hash, current_hash "
                "FROM audit_log ORDER BY id"
            ).fetchall()
            prev = "GENESIS_HASH"
            for row in rows:
                raw = f"{row['timestamp']}|{row['action']}|{row['account_id']}|{row['mail_id']}|{row['details']}|{prev}"
                calculated_hash = hashlib.sha256(raw.encode()).hexdigest()

                if row["previous_hash"] != prev:
                    logger.error("Audit chain broken at entry %d: expected previous_hash %s, got %s",
                                 row["id"], prev, row["previous_hash"])
                    return False

                if row["current_hash"] != calculated_hash:
                    logger.error("Audit content tampering detected at entry %d: expected current_hash %s, got %s",
                                 row["id"], calculated_hash, row["current_hash"])
                    return False

                prev = row["current_hash"]
            return True

    def get_audit_log(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Raw content storage
    # ------------------------------------------------------------------

    def store_raw_mail(self, mail_id: int, raw_data: bytes) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO mail_raw (mail_id, raw_data) VALUES (?, ?)",
                (mail_id, raw_data)
            )

    def get_raw_mail(self, mail_id: int) -> Optional[bytes]:
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT raw_data FROM mail_raw WHERE mail_id=?", (mail_id,)
            ).fetchone()
            return row["raw_data"] if row else None

    def clear_archive_data(self) -> None:
        """Clear all downloaded emails, raw data, attachments, sync state, audit logs, and deduplication hashes."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM mail_raw")
            conn.execute("DELETE FROM attachment_links")
            conn.execute("DELETE FROM dedup_hash")
            conn.execute("DELETE FROM mail_metadata")
            conn.execute("DELETE FROM attachments")
            conn.execute("DELETE FROM sync_state")
            conn.execute("DELETE FROM audit_log")
            try:
                conn.execute("DELETE FROM mail_fts")
            except Exception:
                pass
        with self.get_conn() as conn:
            conn.execute("VACUUM")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate statistics about the database contents."""
        with self.get_conn() as conn:
            return {
                "accounts": conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
                "mails": conn.execute("SELECT COUNT(*) FROM mail_metadata WHERE is_deleted=0").fetchone()[0],
                "deleted": conn.execute("SELECT COUNT(*) FROM mail_metadata WHERE is_deleted=1").fetchone()[0],
                "duplicates": conn.execute("SELECT COUNT(*) FROM mail_metadata WHERE is_duplicate=1").fetchone()[0],
                "attachments": conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0],
                "audit_entries": conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
                "db_size_bytes": self._db_path.stat().st_size,
            }

    def get_custom_report_stats(self, account_id: Optional[int] = None,
                                account_group: Optional[str] = None,
                                domain: Optional[str] = None,
                                since_date: Optional[str] = None,
                                before_date: Optional[str] = None,
                                single_email: Optional[str] = None) -> Dict[str, Any]:
        """Aggregate custom metadata statistics based on account, group, domain, email, and dates."""
        with self.get_conn() as conn:
            # 1. Resolve accounts matching group/domain
            account_ids = []
            if account_id is not None:
                account_ids = [account_id]
            elif account_group:
                rows = conn.execute("SELECT id FROM accounts WHERE account_group = ?", (account_group,)).fetchall()
                account_ids = [r["id"] for r in rows]
            elif domain:
                rows = conn.execute("SELECT id FROM accounts WHERE email LIKE ?", (f"%@{domain}",)).fetchall()
                account_ids = [r["id"] for r in rows]
            else:
                rows = conn.execute("SELECT id FROM accounts").fetchall()
                account_ids = [r["id"] for r in rows]

            if not account_ids:
                return {}

            # 2. Build metadata query conditions
            placeholders = ",".join("?" for _ in account_ids)
            conditions = [f"account_id IN ({placeholders})", "is_deleted = 0"]
            params = list(account_ids)

            if since_date:
                conditions.append("date >= ?")
                params.append(since_date)
            if before_date:
                conditions.append("date <= ?")
                params.append(before_date)
            if single_email:
                conditions.append("(sender LIKE ? OR recipients LIKE ? OR cc LIKE ? OR bcc LIKE ?)")
                params.extend([f"%{single_email}%", f"%{single_email}%", f"%{single_email}%", f"%{single_email}%"])

            where_clause = " AND ".join(conditions)

            # Query aggregates
            total_mails = conn.execute(f"SELECT COUNT(*) FROM mail_metadata WHERE {where_clause}", params).fetchone()[0] or 0
            total_size = conn.execute(f"SELECT SUM(size_bytes) FROM mail_metadata WHERE {where_clause}", params).fetchone()[0] or 0
            has_attachments = conn.execute(f"SELECT COUNT(*) FROM mail_metadata WHERE {where_clause} AND has_attachments = 1", params).fetchone()[0] or 0

            # Folder distributions
            folder_rows = conn.execute(f"SELECT folder, COUNT(*) as cnt FROM mail_metadata WHERE {where_clause} GROUP BY folder", params).fetchall()
            folders = {r["folder"]: r["cnt"] for r in folder_rows}

            # Top senders
            sender_rows = conn.execute(f"SELECT sender, COUNT(*) as cnt FROM mail_metadata WHERE {where_clause} GROUP BY sender ORDER BY cnt DESC LIMIT 10", params).fetchall()
            top_senders = {r["sender"]: r["cnt"] for r in sender_rows}

            return {
                "total_mails": total_mails,
                "total_size_bytes": total_size,
                "has_attachments": has_attachments,
                "folders": folders,
                "top_senders": top_senders,
                "account_ids": account_ids,
            }

    # ------------------------------------------------------------------
    # User & RBAC Management
    # ------------------------------------------------------------------

    def save_user(self, user_data: Dict[str, Any]) -> int:
        """Create or update a user."""
        user_id = user_data.get("id")
        fields = {
            "username": user_data.get("username", "").strip(),
            "full_name": user_data.get("full_name", "").strip(),
            "email": user_data.get("email", "").strip(),
            "role": user_data.get("role", "OPERATOR"),
            "is_active": 1 if user_data.get("is_active", True) else 0,
            "updated_at": datetime.now().isoformat(),
        }

        # If password hash is provided
        if "password_hash" in user_data and user_data["password_hash"]:
            fields["password_hash"] = user_data["password_hash"]
        if "salt" in user_data and user_data["salt"]:
            fields["salt"] = user_data["salt"]

        with self.get_conn() as conn:
            if user_id:
                set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
                values = list(fields.values()) + [user_id]
                conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
                return user_id
            else:
                fields["created_at"] = datetime.now().isoformat()
                cols = ", ".join(fields.keys())
                placeholders = ", ".join("?" for _ in fields)
                cursor = conn.execute(
                    f"INSERT INTO users ({cols}) VALUES ({placeholders})",
                    list(fields.values())
                )
                return cursor.lastrowid

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self.get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        with self.get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            return dict(row) if row else None

    def list_users(self) -> List[Dict[str, Any]]:
        with self.get_conn() as conn:
            rows = conn.execute("SELECT id, username, full_name, email, role, is_active, last_login, created_at FROM users ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def delete_user(self, user_id: int) -> bool:
        with self.get_conn() as conn:
            cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            return cursor.rowcount > 0

    def update_user_password(self, user_id: int, password_hash: str, salt: str) -> bool:
        with self.get_conn() as conn:
            cursor = conn.execute(
                "UPDATE users SET password_hash = ?, salt = ?, updated_at = ? WHERE id = ?",
                (password_hash, salt, datetime.now().isoformat(), user_id)
            )
            return cursor.rowcount > 0

    def update_user_last_login(self, user_id: int) -> None:
        with self.get_conn() as conn:
            conn.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now().isoformat(), user_id)
            )

    # ------------------------------------------------------------------
    # SQL Backup Jobs Management
    # ------------------------------------------------------------------

    def save_sql_backup_job(self, job_data: Dict[str, Any]) -> int:
        """Create or update a SQL backup job."""
        job_id = job_data.get("id")
        fields = {
            "name": job_data.get("name", "SQL Backup"),
            "engine_type": job_data.get("engine_type", "mssql"),
            "host": job_data.get("host", "localhost"),
            "port": int(job_data.get("port", 1433)),
            "auth_type": job_data.get("auth_type", "windows"),
            "username_enc": job_data.get("username_enc", ""),
            "password_enc": job_data.get("password_enc", ""),
            "database_name": job_data.get("database_name", ""),
            "backup_type": job_data.get("backup_type", "FULL"),
            "dest_dir": str(job_data.get("dest_dir", "data/backups/sql")),
            "compress": 1 if job_data.get("compress", True) else 0,
            "compress_mode": str(job_data.get("compress_mode", "compressed")),
            "verify": 1 if job_data.get("verify", True) else 0,
            "retention_mode": str(job_data.get("retention_mode", "count")),
            "retention_value": int(job_data.get("retention_value", 10)),
            "retention_days": int(job_data.get("retention_days", 30)),
            "auto_on_usb_connect": 1 if job_data.get("auto_on_usb_connect", False) else 0,
            "target_drive_label": str(job_data.get("target_drive_label", "")),
            "cloud_target": job_data.get("cloud_target", "none"),
            "schedule_cron": job_data.get("schedule_cron", ""),
            "updated_at": datetime.now().isoformat(),
        }

        with self.get_conn() as conn:
            if job_id:
                set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
                values = list(fields.values()) + [job_id]
                conn.execute(f"UPDATE sql_backup_jobs SET {set_clause} WHERE id = ?", values)
                return job_id
            else:
                fields["created_at"] = datetime.now().isoformat()
                cols = ", ".join(fields.keys())
                placeholders = ", ".join("?" for _ in fields)
                cursor = conn.execute(
                    f"INSERT INTO sql_backup_jobs ({cols}) VALUES ({placeholders})",
                    list(fields.values())
                )
                return cursor.lastrowid

    def get_sql_backup_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        with self.get_conn() as conn:
            row = conn.execute("SELECT * FROM sql_backup_jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None

    def list_sql_backup_jobs(self) -> List[Dict[str, Any]]:
        with self.get_conn() as conn:
            rows = conn.execute("SELECT * FROM sql_backup_jobs ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def delete_sql_backup_job(self, job_id: int) -> bool:
        with self.get_conn() as conn:
            cursor = conn.execute("DELETE FROM sql_backup_jobs WHERE id = ?", (job_id,))
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # VHDX & Hyper-V Backup Jobs Management
    # ------------------------------------------------------------------

    def save_vhdx_backup_job(self, job_data: Dict[str, Any]) -> int:
        """Create or update a VHDX backup job."""
        job_id = job_data.get("id")
        fields = {
            "name": job_data.get("name", "VHDX Backup"),
            "mode": job_data.get("mode", "direct_file"),
            "vm_name": job_data.get("vm_name", ""),
            "source_path": job_data.get("source_path", ""),
            "dest_dir": str(job_data.get("dest_dir", "data/backups/vhdx")),
            "use_vss": 1 if job_data.get("use_vss", True) else 0,
            "compress": 1 if job_data.get("compress", False) else 0,
            "compress_mode": str(job_data.get("compress_mode", "raw")),
            "verify_hash": 1 if job_data.get("verify_hash", True) else 0,
            "retention_mode": str(job_data.get("retention_mode", "count")),
            "retention_value": int(job_data.get("retention_value", 10)),
            "retention_days": int(job_data.get("retention_days", 30)),
            "auto_on_usb_connect": 1 if job_data.get("auto_on_usb_connect", False) else 0,
            "target_drive_label": str(job_data.get("target_drive_label", "")),
            "cloud_target": job_data.get("cloud_target", "none"),
            "schedule_cron": job_data.get("schedule_cron", ""),
            "updated_at": datetime.now().isoformat(),
        }

        with self.get_conn() as conn:
            if job_id:
                set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
                values = list(fields.values()) + [job_id]
                conn.execute(f"UPDATE vhdx_backup_jobs SET {set_clause} WHERE id = ?", values)
                return job_id
            else:
                fields["created_at"] = datetime.now().isoformat()
                cols = ", ".join(fields.keys())
                placeholders = ", ".join("?" for _ in fields)
                cursor = conn.execute(
                    f"INSERT INTO vhdx_backup_jobs ({cols}) VALUES ({placeholders})",
                    list(fields.values())
                )
                return cursor.lastrowid

    def get_vhdx_backup_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        with self.get_conn() as conn:
            row = conn.execute("SELECT * FROM vhdx_backup_jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None

    def list_vhdx_backup_jobs(self) -> List[Dict[str, Any]]:
        with self.get_conn() as conn:
            rows = conn.execute("SELECT * FROM vhdx_backup_jobs ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def delete_vhdx_backup_job(self, job_id: int) -> bool:
        with self.get_conn() as conn:
            cursor = conn.execute("DELETE FROM vhdx_backup_jobs WHERE id = ?", (job_id,))
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Unified Backup History
    # ------------------------------------------------------------------

    def add_backup_history_entry(
        self,
        job_type: str,
        job_name: str,
        status: str,
        source: str = "",
        target_file: str = "",
        size_bytes: int = 0,
        duration_seconds: float = 0.0,
        error_message: str = "",
    ) -> int:
        with self.get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO general_backup_history
                   (job_type, job_name, status, source, target_file, size_bytes, duration_seconds, error_message, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_type, job_name, status, source, target_file, size_bytes, duration_seconds, error_message, datetime.now().isoformat())
            )
            return cursor.lastrowid

    def list_backup_history(self, limit: int = 100, offset: int = 0, job_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_conn() as conn:
            if job_type:
                rows = conn.execute(
                    "SELECT * FROM general_backup_history WHERE job_type = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (job_type, limit, offset)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM general_backup_history ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset)
                ).fetchall()
            return [dict(r) for r in rows]

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

