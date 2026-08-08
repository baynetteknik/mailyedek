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
            conn = sqlite3.connect(str(self._db_path), timeout=60.0)
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
            """)
            # Self-healing column addition for existing databases
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
            return cur.lastrowid

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
        with self.transaction() as conn:
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

    def get_mail_by_uid(self, account_id: int, folder: str, uid: int) -> Optional[Dict[str, Any]]:
        with self.get_conn() as conn:
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
                "ORDER BY uid DESC LIMIT ? OFFSET ?",
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
                          last_uid: int, uid_validity: int, mail_count: int) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO sync_state (account_id, folder, last_uid, uid_validity,
                                           last_sync_at, mail_count)
                   VALUES (?, ?, ?, ?, datetime('now'), ?)
                   ON CONFLICT(account_id, folder) DO UPDATE SET
                       last_uid=excluded.last_uid,
                       uid_validity=excluded.uid_validity,
                       last_sync_at=excluded.last_sync_at,
                       mail_count=excluded.mail_count""",
                (account_id, folder, last_uid, uid_validity, mail_count)
            )

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
                sql += " AND folder = ?"
                params.append(folder)

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

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
