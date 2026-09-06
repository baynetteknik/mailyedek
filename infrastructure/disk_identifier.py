"""
disk_identifier.py — Disk signature stamping, fingerprinting, and auto-discovery.

Clean Architecture — Infrastructure Layer.
Provides:
  - Stamping a unique marker file (.mail_yedek_disk_id) on backup drives/folders.
  - Reading disk signatures to verify if an attached drive is the user's registered backup disk.
  - Auto-discovering registered backup drives when drive letters change (e.g., D: -> E: -> F:).
"""

import ctypes
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from infrastructure.disk_watcher import list_available_drives

logger = logging.getLogger(__name__)

SIGNATURE_FILE_NAME = ".mail_yedek_disk_id"


def get_disk_signature(target_path: Path) -> Optional[Dict[str, Any]]:
    """Read .mail_yedek_disk_id signature from target folder or its drive root."""
    try:
        p = Path(target_path)
        candidates = [
            p / SIGNATURE_FILE_NAME,
            p.parent / SIGNATURE_FILE_NAME,
        ]
        # Also check root of drive if path is on a Windows drive
        try:
            drive_root = Path(p.anchor)
            if drive_root not in candidates:
                candidates.append(drive_root / SIGNATURE_FILE_NAME)
        except Exception:
            pass

        for sig_file in candidates:
            if sig_file.exists() and sig_file.is_file():
                try:
                    with open(sig_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict) and "disk_id" in data:
                            data["_sig_file_path"] = str(sig_file)
                            return data
                except Exception as e:
                    logger.warning("Error reading signature file %s: %s", sig_file, e)
    except Exception as exc:
        logger.warning("Error checking disk signature at %s: %s", target_path, exc)
    return None


def stamp_disk_signature(
    folder_path: Path,
    label: str = "Resmi Yedekleme Diski",
    is_primary: bool = True,
    custom_disk_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write .mail_yedek_disk_id signature file to folder."""
    p = Path(folder_path).resolve()
    p.mkdir(parents=True, exist_ok=True)

    sig_id = custom_disk_id or uuid.uuid4().hex
    sig_data: Dict[str, Any] = {
        "disk_id": sig_id,
        "label": label,
        "folder_name": p.name,
        "original_full_path": str(p),
        "is_primary_backup_disk": is_primary,
        "created_at": datetime.now().isoformat(),
        "app_signature": "mail_yedek_enterprise_backup_v1",
    }

    sig_file = p / SIGNATURE_FILE_NAME
    with open(sig_file, "w", encoding="utf-8") as f:
        json.dump(sig_data, f, indent=2, ensure_ascii=False)

    # On Windows, set hidden attribute so it doesn't clutter user view
    if os.name == "nt":
        try:
            FILE_ATTRIBUTE_HIDDEN = 0x02
            ctypes.windll.kernel32.SetFileAttributesW(str(sig_file), FILE_ATTRIBUTE_HIDDEN)
        except Exception:
            pass

    logger.info("Stamped disk signature %s at %s", sig_id, sig_file)
    return sig_data


def remove_disk_signature(folder_path: Path) -> bool:
    """Remove .mail_yedek_disk_id from folder."""
    try:
        sig_file = Path(folder_path) / SIGNATURE_FILE_NAME
        if sig_file.exists():
            sig_file.unlink()
            return True
    except Exception as exc:
        logger.warning("Failed to remove disk signature at %s: %s", folder_path, exc)
    return False


def find_registered_disk_on_system(
    registered_signature: Optional[Dict[str, Any]] = None,
    target_folder_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Scan all connected Windows drives to find if a registered backup disk is attached."""
    drives = list_available_drives()
    target_id = registered_signature.get("disk_id") if registered_signature else None
    target_folder = (
        target_folder_name
        or (registered_signature.get("folder_name") if registered_signature else None)
        or "mailyedek"
    )

    for d in drives:
        root_path = Path(d.get("root_path", d.get("letter", "") + "\\"))
        if not root_path.exists():
            continue

        # 1. Check drive root signature
        root_sig = get_disk_signature(root_path)
        if root_sig:
            if target_id and root_sig.get("disk_id") == target_id:
                return {
                    "matched_by": "disk_id_root",
                    "drive": d,
                    "found_path": root_path,
                    "signature": root_sig,
                }

        # 2. Check {root}\{target_folder}
        if target_folder:
            candidate_folder = root_path / target_folder
            if candidate_folder.exists() and candidate_folder.is_dir():
                folder_sig = get_disk_signature(candidate_folder)
                if folder_sig:
                    if target_id and folder_sig.get("disk_id") == target_id:
                        return {
                            "matched_by": "disk_id_folder",
                            "drive": d,
                            "found_path": candidate_folder,
                            "signature": folder_sig,
                        }
                    elif not target_id:
                        return {
                            "matched_by": "folder_signature",
                            "drive": d,
                            "found_path": candidate_folder,
                            "signature": folder_sig,
                        }
                elif not target_id:
                    # Folder exists with the expected name
                    return {
                        "matched_by": "folder_name_match",
                        "drive": d,
                        "found_path": candidate_folder,
                        "signature": None,
                    }

    return None


def inspect_drive_recognition(
    drive_path: str,
    registered_signature: Optional[Dict[str, Any]] = None,
    configured_data_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate whether an attached drive or path is recognized as a known backup location."""
    p = Path(drive_path)
    sig = get_disk_signature(p)

    target_id = registered_signature.get("disk_id") if registered_signature else None

    # Check if signature matches registered ID
    if sig and target_id and sig.get("disk_id") == target_id:
        return {
            "is_recognized": True,
            "is_primary": bool(sig.get("is_primary_backup_disk", True)),
            "match_type": "official_signature_match",
            "label": sig.get("label", "Resmi Yedekleme Diski"),
            "signature": sig,
            "folder_path": str(p),
        }

    # Check if folder name or path matches configured_data_path
    if configured_data_path:
        try:
            cfg_name = Path(configured_data_path).name.lower()
            if p.name.lower() == cfg_name or (p / cfg_name).exists():
                matched_p = p if p.name.lower() == cfg_name else (p / cfg_name)
                matched_sig = get_disk_signature(matched_p)
                return {
                    "is_recognized": True,
                    "is_primary": True,
                    "match_type": "folder_match",
                    "label": (matched_sig.get("label") if matched_sig else "Tanınan Veri Klasörü"),
                    "signature": matched_sig,
                    "folder_path": str(matched_p),
                }
        except Exception:
            pass

    # Unrecognized
    return {
        "is_recognized": sig is not None,
        "is_primary": bool(sig.get("is_primary_backup_disk", False)) if sig else False,
        "match_type": "existing_signature" if sig else "unrecognized",
        "label": sig.get("label", "Tanımsız Harici Disk") if sig else "Tanımsız Harici Disk",
        "signature": sig,
        "folder_path": str(p),
    }
