"""
settings.py — Application settings manager.

Stores user preferences in a JSON file under the data directory.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_DIR = Path("data")


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
        """Return the configured data directory path."""
        raw = self._data.get("data_path")
        if raw:
            try:
                p = Path(raw)
                # Check if the path exists or is writable (missing drive letter will raise OSError here or on mkdir)
                if p.exists():
                    return p
                else:
                    p.mkdir(parents=True, exist_ok=True)
                    return p
            except OSError as exc:
                logger.error("Configured data_path '%s' is not accessible, falling back to default: %s", raw, exc)
        return DEFAULT_SETTINGS_DIR


    def set_data_path(self, path: Path):
        self._data["data_path"] = str(path.resolve())
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
