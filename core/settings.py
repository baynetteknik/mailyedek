"""
settings.py — Application settings manager.

Stores user preferences in a JSON file under the data directory.
"""

import json
import logging
import os
import sys
import ctypes
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_DIR = Path("data")

_DISK_CHECK_CACHE: Dict[str, tuple[bool, float]] = {}


def is_path_accessible_fast(path_str: str, max_cache_age_sec: float = 2.0) -> bool:
    """
    Ultra-fast, non-blocking check for Windows logical drives and directories.
    Prevents multi-second OS hangs when querying unplugged or missing drives.
    """
    if not path_str:
        return True

    now = time.time()
    cached = _DISK_CHECK_CACHE.get(path_str)
    if cached and (now - cached[1]) < max_cache_age_sec:
        return cached[0]

    is_avail = False
    try:
        drive, tail = os.path.splitdrive(path_str)
        if drive and sys.platform.startswith("win"):
            drive_letter = drive.strip(":").upper()
            if len(drive_letter) == 1 and 'A' <= drive_letter <= 'Z':
                bitmask = ctypes.windll.kernel32.GetLogicalDrives()
                drive_index = ord(drive_letter) - ord('A')
                if not (bitmask & (1 << drive_index)):
                    # Drive is physically disconnected, return False immediately (0.01ms)
                    _DISK_CHECK_CACHE[path_str] = (False, now)
                    return False
        is_avail = os.path.exists(path_str)
    except Exception:
        is_avail = False

    _DISK_CHECK_CACHE[path_str] = (is_avail, now)
    return is_avail


class StorageLocation:
    """A named storage location (local disk, NAS, external drive)."""

    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path

    def to_dict(self) -> Dict[str, str]:
        return {"name": self.name, "path": self.path}

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "StorageLocation":
        return cls(name=d.get("name", "Unnamed"), path=d.get("path", ""))


class AppSettings:
    """Persistent application settings stored as JSON."""

    def __init__(self, settings_dir: Optional[Path] = None):
        self._dir = settings_dir or DEFAULT_SETTINGS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "settings.json"
        self._data: Dict[str, Any] = self._load()

    # ------------------------------------------------------------------
    # Internal load / save
    # ------------------------------------------------------------------

    def _load(self) -> Dict[str, Any]:
        if self._file.exists():
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("Failed to load settings: %s", exc)
        return {}

    def save(self):
        try:
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error("Failed to save settings: %s", exc)

    # ------------------------------------------------------------------
    # Getters / setters
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        self._data[key] = value

    def data_path(self) -> Path:
        """Return the configured data directory path if reachable, otherwise DEFAULT_SETTINGS_DIR."""
        raw = self._data.get("data_path")
        if raw:
            if is_path_accessible_fast(raw):
                return Path(raw)
            logger.debug("Configured data_path '%s' is not accessible, falling back to default: %s", raw, DEFAULT_SETTINGS_DIR)
        return DEFAULT_SETTINGS_DIR

    def is_configured_data_path_available(self) -> bool:
        """Return True if the configured data_path is reachable and exists."""
        raw = self._data.get("data_path")
        if not raw:
            return True
        return is_path_accessible_fast(raw)

    def configured_data_path_str(self) -> str:
        """Return the raw string of the configured data_path."""
        return self._data.get("data_path", "data")

    def save_account_cache(self, accounts: List[Dict[str, Any]]):
        """Cache account list locally in JSON and local SQLite DB for offline display."""
        if not accounts:
            return
        try:
            cache_file = Path("data/account_cache.json")
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(accounts, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to save account cache JSON: %s", exc)

        # Also sync to local SQLite fallback database
        try:
            local_db = Path("data/mail_archive.db")
            if local_db.exists():
                import sqlite3
                with sqlite3.connect(str(local_db)) as conn:
                    conn.executescript("""
                        CREATE TABLE IF NOT EXISTS accounts (
                            id              INTEGER PRIMARY KEY AUTOINCREMENT,
                            label           TEXT NOT NULL,
                            email           TEXT NOT NULL,
                            imap_host       TEXT NOT NULL,
                            imap_port       INTEGER NOT NULL DEFAULT 993,
                            use_ssl         INTEGER NOT NULL DEFAULT 1,
                            username_enc    TEXT NOT NULL DEFAULT '',
                            password_enc    TEXT NOT NULL DEFAULT '',
                            is_active       INTEGER NOT NULL DEFAULT 1,
                            export_subfolder TEXT DEFAULT '',
                            account_group   TEXT DEFAULT '',
                            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                        );
                    """)
                    for acc in accounts:
                        conn.execute("""
                            INSERT INTO accounts (id, label, email, imap_host, imap_port, use_ssl, export_subfolder, account_group, is_active, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                            ON CONFLICT(id) DO UPDATE SET
                                label=excluded.label,
                                email=excluded.email,
                                imap_host=excluded.imap_host,
                                imap_port=excluded.imap_port,
                                use_ssl=excluded.use_ssl,
                                export_subfolder=excluded.export_subfolder,
                                account_group=excluded.account_group,
                                is_active=excluded.is_active,
                                updated_at=excluded.updated_at
                        """, (
                            acc.get("id"),
                            acc.get("label", ""),
                            acc.get("email", ""),
                            acc.get("imap_host", ""),
                            acc.get("imap_port", 993),
                            1 if acc.get("use_ssl", True) else 0,
                            acc.get("export_subfolder", ""),
                            acc.get("account_group", ""),
                            1 if acc.get("is_active", True) else 0,
                        ))
        except Exception as exc:
            logger.debug("Failed to sync account cache to local db: %s", exc)

    def load_account_cache(self) -> List[Dict[str, Any]]:
        """Load locally cached accounts when main data disk is not connected."""
        cache_file = Path("data/account_cache.json")
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data:
                        return data
            except Exception as exc:
                logger.warning("Failed to load account cache: %s", exc)

        # Fallback to local SQLite database
        local_db = Path("data/mail_archive.db")
        if local_db.exists():
            try:
                import sqlite3
                with sqlite3.connect(str(local_db)) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute("SELECT * FROM accounts").fetchall()
                    if rows:
                        return [dict(r) for r in rows]
            except Exception as exc:
                logger.debug("Failed to load accounts from local SQLite fallback: %s", exc)
        return []

    def set_data_path(self, path: Path):
        self._data["data_path"] = str(path.resolve())
        self.save()

    def data_disk_signature(self) -> Optional[Dict[str, Any]]:
        """Return registered disk signature information."""
        return self._data.get("data_disk_signature")

    def set_data_disk_signature(self, sig: Dict[str, Any]):
        """Persist registered disk signature information."""
        self._data["data_disk_signature"] = sig
        self.save()

    def clear_data_disk_signature(self):
        """Remove registered disk signature information."""
        self._data.pop("data_disk_signature", None)
        self.save()

    def db_path(self) -> Path:
        """Full path to the SQLite database file."""
        return self.data_path() / "mail_archive.db"

    def key_file_path(self) -> Path:
        """Full path to the Fernet encryption key file."""
        return self.data_path() / "key.key"

    # ------------------------------------------------------------------
    # Storage locations (multi-disk / NAS support)
    # ------------------------------------------------------------------

    def storage_locations(self) -> List[StorageLocation]:
        """Return all configured named storage locations."""
        raw = self._data.get("storage_locations", [])
        return [StorageLocation.from_dict(item) for item in raw]

    def add_storage_location(self, name: str, path: str):
        locs = self._data.get("storage_locations", [])
        # Replace existing with same name
        locs = [l for l in locs if l.get("name") != name]
        locs.append({"name": name, "path": str(Path(path).resolve())})
        self._data["storage_locations"] = locs
        self.save()

    def remove_storage_location(self, name: str):
        locs = self._data.get("storage_locations", [])
        self._data["storage_locations"] = [l for l in locs if l.get("name") != name]
        self.save()

    def account_storage(self, account_id: int) -> Optional[str]:
        """Return the storage location name assigned to an account, or None."""
        mapping = self._data.get("account_storage_map", {})
        return mapping.get(str(account_id))

    def set_account_storage(self, account_id: int, location_name: Optional[str]):
        mapping = self._data.get("account_storage_map", {})
        key = str(account_id)
        if location_name is None:
            mapping.pop(key, None)
        else:
            mapping[key] = location_name
        self._data["account_storage_map"] = mapping
        self.save()

    def account_sync_filters(self, account_id: int) -> Optional[dict]:
        """Return the sync filters assigned to an account, or None."""
        mapping = self._data.get("account_sync_filters_map", {})
        return mapping.get(str(account_id))

    def set_account_sync_filters(self, account_id: int, filters: Optional[dict]):
        mapping = self._data.get("account_sync_filters_map", {})
        key = str(account_id)
        if filters is None:
            mapping.pop(key, None)
        else:
            mapping[key] = filters
        self._data["account_sync_filters_map"] = mapping
        self.save()

    # ------------------------------------------------------------------
    # Custom IMAP Provider Presets
    # ------------------------------------------------------------------

    def custom_presets(self) -> List[Dict[str, Any]]:
        """Return all user-defined custom provider presets."""
        return self._data.get("custom_provider_presets", [])

    def add_custom_preset(self, name: str, host: str, port: int, use_ssl: bool, domains: Optional[List[str]] = None):
        """Add or update a custom provider preset."""
        presets = self._data.get("custom_provider_presets", [])
        presets = [p for p in presets if p.get("name") != name]
        presets.append({
            "id": f"custom_{name.lower().replace(' ', '_')}",
            "name": name,
            "host": host,
            "port": port,
            "use_ssl": use_ssl,
            "domains": domains or []
        })
        self._data["custom_provider_presets"] = presets
        self.save()

    def remove_custom_preset(self, name: str):
        """Remove a custom provider preset by name."""
        presets = self._data.get("custom_provider_presets", [])
        self._data["custom_provider_presets"] = [p for p in presets if p.get("name") != name]
        self.save()

    # ------------------------------------------------------------------
    # Folder Translation Options
    # ------------------------------------------------------------------

    def folder_translation_sync(self) -> str:
        """Mode for incoming server folder names: 'original', 'tr', or 'en'."""
        return self._data.get("folder_translation_sync", "original")

    def set_folder_translation_sync(self, mode: str):
        self._data["folder_translation_sync"] = mode
        self.save()

    def folder_translation_restore(self) -> str:
        """Mode when pushing folders back to server: 'original', 'tr', or 'en'."""
        return self._data.get("folder_translation_restore", "original")

    def set_folder_translation_restore(self, mode: str):
        self._data["folder_translation_restore"] = mode
        self.save()

    # ------------------------------------------------------------------
    # App Language & Port Listener Preferences
    # ------------------------------------------------------------------

    def language(self) -> str:
        """Return application UI language ('tr', 'en', 'ru')."""
        return self._data.get("language", "tr")

    def set_language(self, lang: str):
        self._data["language"] = lang
        self.save()

    def port_listener_enabled(self) -> bool:
        """Return whether background network port monitoring is enabled."""
        return bool(self._data.get("port_listener_enabled", False))

    def set_port_listener_enabled(self, enabled: bool):
        self._data["port_listener_enabled"] = bool(enabled)
        self.save()

    def port_listener_ports(self) -> List[int]:
        """Return target ports to monitor."""
        return self._data.get("port_listener_ports", [993, 143, 995, 110, 465, 587, 2096])

    def set_port_listener_ports(self, ports: List[int]):
        self._data["port_listener_ports"] = ports
        self.save()

    def network_timeout(self) -> int:
        """Return network socket timeout in seconds."""
        return int(self._data.get("network_timeout", 15))

    def set_network_timeout(self, seconds: int):
        self._data["network_timeout"] = max(3, min(120, int(seconds)))
        self.save()

    def ssl_strict_mode(self) -> bool:
        """Return whether SSL certificate validation is strict."""
        return bool(self._data.get("ssl_strict_mode", False))

    def set_ssl_strict_mode(self, strict: bool):
        self._data["ssl_strict_mode"] = bool(strict)
        self.save()

    # ------------------------------------------------------------------
    # Multi-Account Cloud Storage (Amazon S3 & Google Drive)
    # ------------------------------------------------------------------

    def cloud_accounts(self, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all configured cloud storage accounts, optionally filtered by provider ('s3' or 'gdrive')."""
        accounts = self._data.get("cloud_storage_accounts", [])
        if provider:
            p_clean = provider.strip().lower()
            return [acc for acc in accounts if acc.get("provider", "").strip().lower() == p_clean]
        return accounts

    def save_cloud_account(self, account_data: Dict[str, Any]) -> str:
        """Add or update a cloud storage account and persist settings."""
        import uuid
        accounts = self._data.get("cloud_storage_accounts", [])
        acc_id = account_data.get("id")
        if not acc_id:
            provider = account_data.get("provider", "cloud").lower()
            acc_id = f"{provider}_{uuid.uuid4().hex[:8]}"
            account_data["id"] = acc_id

        # If this is marked as default, unset other defaults for this provider
        if account_data.get("is_default", False):
            p = account_data.get("provider", "").lower()
            for acc in accounts:
                if acc.get("provider", "").lower() == p and acc.get("id") != acc_id:
                    acc["is_default"] = False

        # If first account of this provider, make it default automatically
        provider_accounts = [a for a in accounts if a.get("provider", "").lower() == account_data.get("provider", "").lower()]
        if not provider_accounts:
            account_data["is_default"] = True

        existing_idx = next((i for i, a in enumerate(accounts) if a.get("id") == acc_id), None)
        if existing_idx is not None:
            accounts[existing_idx] = account_data
        else:
            accounts.append(account_data)

        self._data["cloud_storage_accounts"] = accounts
        self.save()
        return acc_id

    def remove_cloud_account(self, account_id: str):
        """Remove a cloud account by ID."""
        accounts = self._data.get("cloud_storage_accounts", [])
        self._data["cloud_storage_accounts"] = [a for a in accounts if a.get("id") != account_id]
        self.save()

    def get_cloud_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a cloud account by ID."""
        accounts = self._data.get("cloud_storage_accounts", [])
        return next((a for a in accounts if a.get("id") == account_id), None)

    def set_default_cloud_account(self, account_id: str):
        """Set specified account as the default for its provider."""
        target = self.get_cloud_account(account_id)
        if not target:
            return
        p = target.get("provider", "").lower()
        accounts = self._data.get("cloud_storage_accounts", [])
        for acc in accounts:
            if acc.get("provider", "").lower() == p:
                acc["is_default"] = (acc.get("id") == account_id)
        self._data["cloud_storage_accounts"] = accounts
        self.save()





def get_account_mailbox_dir(base_path: Path, email: str, subfolder: str, folder_name: str) -> Path:
    """Calculates the target directory for an email mailbox folder based on base path and account settings."""
    import re
    folder_clean = re.sub(r'[\/:*?"<>|]', '_', folder_name).strip()
    email_clean = re.sub(r'[\/:*?"<>|]', '_', email.replace("@", "_")).strip()
    if subfolder and subfolder.strip() and subfolder.strip() != ".":
        sub_clean = re.sub(r'[\/:*?"<>|]', '_', subfolder.strip()).strip()
        return base_path / sub_clean / email_clean / folder_clean
    else:
        return base_path / email_clean / folder_clean
