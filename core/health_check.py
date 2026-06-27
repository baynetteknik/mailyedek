"""
health_check.py — System health checking and configuration validation.

Clean Architecture — Core Service Layer.
Provides diagnostics for: disk space, database integrity, IMAP connectivity,
S3/Google Drive connectivity, audit chain integrity, and quota checks.
"""

import logging
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.database import DatabaseManager
from core.crypto_utils import CryptoManager
from domain.repositories import IAccountRepository, IAuditRepository

logger = logging.getLogger(__name__)


class HealthStatus:
    """Result of a health check operation."""

    def __init__(self, name: str):
        self.name = name
        self.status: str = "unknown"  # "ok", "warning", "error"
        self.message: str = ""
        self.details: Dict[str, Any] = {}
        self.duration_ms: float = 0.0

    def ok(self, message: str = "", **details) -> "HealthStatus":
        self.status = "ok"
        self.message = message or "OK"
        self.details = details
        return self

    def warn(self, message: str, **details) -> "HealthStatus":
        self.status = "warning"
        self.message = message
        self.details = details
        return self

    def error(self, message: str, **details) -> "HealthStatus":
        self.status = "error"
        self.message = message
        self.details = details
        return self

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "duration_ms": round(self.duration_ms, 2),
        }


class HealthChecker:
    """Comprehensive system health checker and config validator."""

    def __init__(self, db: DatabaseManager, crypto: CryptoManager,
                 account_repo: IAccountRepository,
                 audit_repo: IAuditRepository):
        self._db = db
        self._crypto = crypto
        self._account_repo = account_repo
        self._audit_repo = audit_repo

    # ------------------------------------------------------------------
    # Full status check
    # ------------------------------------------------------------------

    def check_all(self) -> Dict[str, Any]:
        """Run all health checks and return aggregated results."""
        checks = [
            self.check_disk_space(),
            self.check_database(),
            self.check_audit_chain(),
            self.check_key_file(),
            self.check_accounts(),
        ]
        return {
            "status": self._aggregate_status(checks),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "checks": [c.to_dict() for c in checks],
        }

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def check_disk_space(self) -> HealthStatus:
        """Check available disk space."""
        check = HealthStatus("disk_space")
        start = time.time()

        try:
            usage = shutil.disk_usage(Path("."))
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            pct_free = (usage.free / usage.total) * 100

            check.details = {
                "total_gb": round(total_gb, 2),
                "free_gb": round(free_gb, 2),
                "free_percent": round(pct_free, 1),
            }

            if pct_free < 5:
                check.error(f"Critical: only {pct_free:.1f}% disk space remaining")
            elif pct_free < 15:
                check.warn(f"Low disk space: {pct_free:.1f}% free")
            else:
                check.ok(f"{free_gb:.1f} GB free ({pct_free:.1f}%)")

        except Exception as exc:
            check.error(str(exc))

        check.duration_ms = (time.time() - start) * 1000
        return check

    def check_database(self) -> HealthStatus:
        """Check database integrity and stats."""
        check = HealthStatus("database")
        start = time.time()

        try:
            with self._db.get_conn() as conn:
                # Integrity check
                cursor = conn.execute("PRAGMA integrity_check")
                integrity = cursor.fetchone()[0]

                # Get stats
                stats = self._db.get_stats()

                check.details = {**stats}

                if integrity != "ok":
                    check.error(f"Database integrity check failed: {integrity}")
                elif stats.get("db_size_bytes", 0) == 0:
                    check.warn("Database is empty")
                else:
                    size_mb = stats.get("db_size_bytes", 0) / (1024 * 1024)
                    check.ok(f"Database OK ({size_mb:.1f} MB, {stats.get('mails', 0)} mails)")

        except Exception as exc:
            check.error(str(exc))

        check.duration_ms = (time.time() - start) * 1000
        return check

    def check_audit_chain(self) -> HealthStatus:
        """Verify audit trail hash chain integrity."""
        check = HealthStatus("audit_chain")
        start = time.time()

        try:
            is_valid = self._audit_repo.verify_chain()
            if is_valid:
                check.ok("Audit chain integrity verified")
            else:
                check.error("Audit chain is BROKEN — possible tampering detected")
        except Exception as exc:
            check.error(str(exc))

        check.duration_ms = (time.time() - start) * 1000
        return check

    def check_key_file(self) -> HealthStatus:
        """Check if encryption key file exists and is valid."""
        check = HealthStatus("encryption_key")
        start = time.time()

        try:
            key_file = Path("data/key.key")
            if key_file.exists():
                key_data = key_file.read_bytes()
                if len(key_data) == 44:  # Fernet key is 44 base64 chars
                    check.ok(f"Key file exists ({key_file})")
                else:
                    check.error("Key file has invalid format")
            else:
                check.warn("No key file found — will be created on first use")
        except Exception as exc:
            check.error(str(exc))

        check.duration_ms = (time.time() - start) * 1000
        return check

    def check_accounts(self) -> HealthStatus:
        """Validate configured accounts."""
        check = HealthStatus("accounts")
        start = time.time()

        try:
            accounts = self._account_repo.get_all()
            check.details = {
                "total_accounts": len(accounts),
                "accounts": [
                    {"id": a["id"], "email": CryptoManager.mask_email(a["email"]),
                     "label": a["label"]}
                    for a in accounts
                ],
            }
            if not accounts:
                check.warn("No accounts configured")
            else:
                check.ok(f"{len(accounts)} account(s) configured")

        except Exception as exc:
            check.error(str(exc))

        check.duration_ms = (time.time() - start) * 1000
        return check

    # ------------------------------------------------------------------
    # Config validation
    # ------------------------------------------------------------------

    def validate_account_config(self, account: Dict) -> Dict[str, Any]:
        """Validate a single account's configuration without saving.

        Tests:
          - Can resolve hostname
          - Can establish IMAP connection
          - Can authenticate

        Returns:
            Dict with validation result and diagnostics.
        """
        import socket

        result: Dict[str, Any] = {
            "valid": False,
            "host_resolution": False,
            "imap_connection": False,
            "authentication": False,
            "errors": [],
        }

        # Test hostname resolution
        try:
            socket.getaddrinfo(account["imap_host"], account["imap_port"])
            result["host_resolution"] = True
        except socket.gaierror as exc:
            result["errors"].append(f"Hostname resolution failed: {exc}")

        # Test IMAP connection
        try:
            import imaplib
            if account.get("use_ssl", True):
                conn = imaplib.IMAP4_SSL(account["imap_host"], account["imap_port"], timeout=15)
            else:
                conn = imaplib.IMAP4(account["imap_host"], account["imap_port"], timeout=15)
                conn.starttls()
            result["imap_connection"] = True

            # Test authentication
            try:
                conn.login(account["username"], account["password"])
                result["authentication"] = True
                conn.logout()
            except imaplib.IMAP4.error as exc:
                result["errors"].append(f"Authentication failed: {exc}")

        except (OSError, ConnectionError, imaplib.IMAP4.error) as exc:
            result["errors"].append(f"IMAP connection failed: {exc}")

        result["valid"] = all([
            result["host_resolution"],
            result["imap_connection"],
            result["authentication"],
        ])
        return result

    def validate_cloud_config(self, provider_type: str, **config) -> Dict[str, Any]:
        """Validate cloud storage configuration.

        Tests connectivity to S3 or Google Drive.
        """
        result: Dict[str, Any] = {
            "valid": False,
            "connection": False,
            "errors": [],
        }

        try:
            if provider_type == "s3":
                from infrastructure.s3_client import S3Client
                client = S3Client(
                    bucket_name=config.get("bucket_name", ""),
                    region=config.get("region", "us-east-1"),
                    access_key_id=config.get("access_key_id"),
                    secret_access_key=config.get("secret_access_key"),
                )
                result["connection"] = client.connect()

            elif provider_type == "gdrive":
                from infrastructure.gdrive_client import GoogleDriveClient
                client = GoogleDriveClient(
                    credentials_path=config.get("credentials_path"),
                )
                result["connection"] = client.connect()
            else:
                result["errors"].append(f"Unknown provider: {provider_type}")

            result["valid"] = result["connection"]

        except Exception as exc:
            result["errors"].append(str(exc))

        return result

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate_status(checks: List[HealthStatus]) -> str:
        if any(c.status == "error" for c in checks):
            return "error"
        if any(c.status == "warning" for c in checks):
            return "warning"
        return "ok"
