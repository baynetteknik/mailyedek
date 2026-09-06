"""
disk_watcher.py — Windows drive discovery, USB/HDD arrival detection, and disk backup inspection.

Clean Architecture — Infrastructure Layer.
Supports:
  - Listing all logical drives with volume labels, free space, and drive types (Fixed vs Removable/USB).
  - Background polling / event detection for newly connected external drives.
  - Fast recursive disk scanning for existing SQL (.bak/.sql), VHDX (.vhdx/.gz), and mail archives.
"""

import ctypes
import logging
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Windows Drive Types
DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2  # USB, SD card, Floppy
DRIVE_FIXED = 3      # Internal Hard Disk / SSD
DRIVE_REMOTE = 4     # Network Share / NAS
DRIVE_CDROM = 5      # CD / DVD
DRIVE_RAMDISK = 6

DRIVE_TYPE_NAMES = {
    DRIVE_REMOVABLE: "Taşınabilir USB / Disk",
    DRIVE_FIXED: "Sabit Disk",
    DRIVE_REMOTE: "Ağ Sürücüsü (NAS)",
    DRIVE_CDROM: "CD/DVD",
    DRIVE_RAMDISK: "RAM Disk",
}

_DRIVE_CACHE_DATA: List[Dict[str, Any]] = []
_DRIVE_CACHE_TIME: float = 0.0


def list_available_drives(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """Enumerate all logical drives in Windows with labels, types, and free space (non-blocking & cached)."""
    global _DRIVE_CACHE_DATA, _DRIVE_CACHE_TIME
    now = time.time()
    if not force_refresh and _DRIVE_CACHE_DATA and (now - _DRIVE_CACHE_TIME) < 2.5:
        return _DRIVE_CACHE_DATA

    drives = []
    if os.name != "nt":
        # Fallback for non-Windows (testing)
        root_stat = shutil.disk_usage("/")
        drives.append({
            "letter": "/",
            "root_path": "/",
            "label": "Root",
            "type_code": DRIVE_FIXED,
            "type_name": "Sabit Disk",
            "is_removable": False,
            "total_bytes": root_stat.total,
            "free_bytes": root_stat.free,
            "used_bytes": root_stat.used,
            "free_percent": round((root_stat.free / max(root_stat.total, 1)) * 100, 1),
        })
        _DRIVE_CACHE_DATA = drives
        _DRIVE_CACHE_TIME = now
        return drives

    try:
        kernel32 = ctypes.windll.kernel32
        # SEM_FAILCRITICALERRORS (0x0001) | SEM_NOOPENFILEERRORBOX (0x8000)
        old_err_mode = kernel32.SetErrorMode(0x0001 | 0x8000)
        try:
            bitmask = kernel32.GetLogicalDrives()
            for letter_code in range(26):
                if bitmask & (1 << letter_code):
                    letter = f"{chr(65 + letter_code)}:"
                    root_path = f"{letter}\\"
                    drive_type = kernel32.GetDriveTypeW(root_path)

                    if drive_type in (DRIVE_NO_ROOT_DIR, DRIVE_CDROM, DRIVE_UNKNOWN):
                        continue

                    volume_name = "Yerel Disk"
                    try:
                        vol_name_buf = ctypes.create_unicode_buffer(261)
                        fs_name_buf = ctypes.create_unicode_buffer(261)
                        serial_number = ctypes.c_ulong(0)
                        max_component_len = ctypes.c_ulong(0)
                        file_system_flags = ctypes.c_ulong(0)

                        res = kernel32.GetVolumeInformationW(
                            root_path,
                            vol_name_buf,
                            ctypes.sizeof(vol_name_buf),
                            ctypes.byref(serial_number),
                            ctypes.byref(max_component_len),
                            ctypes.byref(file_system_flags),
                            fs_name_buf,
                            ctypes.sizeof(fs_name_buf)
                        )
                        if res and vol_name_buf.value:
                            volume_name = vol_name_buf.value
                    except Exception:
                        pass

                    total_bytes = 0
                    free_bytes = 0
                    used_bytes = 0
                    free_pct = 0.0
                    try:
                        usage = shutil.disk_usage(root_path)
                        total_bytes = usage.total
                        free_bytes = usage.free
                        used_bytes = usage.used
                        free_pct = round((free_bytes / max(total_bytes, 1)) * 100, 1)
                    except Exception:
                        pass

                    drives.append({
                        "letter": letter,
                        "root_path": root_path,
                        "label": volume_name,
                        "type_code": drive_type,
                        "type_name": DRIVE_TYPE_NAMES.get(drive_type, "Bilinmeyen"),
                        "is_removable": drive_type == DRIVE_REMOVABLE,
                        "total_bytes": total_bytes,
                        "free_bytes": free_bytes,
                        "used_bytes": used_bytes,
                        "free_percent": free_pct,
                    })
        finally:
            kernel32.SetErrorMode(old_err_mode)
    except Exception as exc:
        logger.error("Error enumerating drives: %s", exc)

    _DRIVE_CACHE_DATA = drives
    _DRIVE_CACHE_TIME = now
    return drives


def scan_backups_on_drive(
    drive_path: str,
    max_depth: int = 3,
    max_files: int = 1500,
    max_dirs: int = 400,
    progress_callback: Optional[Callable[[int, str, Optional[Dict[str, Any]]], None]] = None,
) -> List[Dict[str, Any]]:
    """Scan a drive path for existing SQL, VHDX, and Mail archive files with limits and streaming callback."""
    backups = []
    root = Path(drive_path)
    if not root.exists():
        return backups

    known_extensions = {
        ".bak", ".sql", ".vhdx", ".vhd", ".vhds", ".gz", ".zip",
        ".tar.gz", ".dump", ".trn", ".db", ".sqlite", ".sqlite3",
        ".eml", ".mbox", ".pst"
    }

    skip_dir_names = {
        "$recycle.bin", "$winre_backup", "system volume information",
        "windows", "program files", "program files (x86)", "programdata",
        "appdata", "node_modules", ".git", ".venv", "recovery", "msocache",
        "config.msi", "local settings", "winsxs"
    }

    dirs_visited = 0
    files_checked = 0

    try:
        for current_dir, dirs, files in os.walk(drive_path):
            dirs_visited += 1
            if dirs_visited > max_dirs or len(backups) >= max_files:
                dirs.clear()
                break

            # Limit search depth
            try:
                rel = Path(current_dir).relative_to(root)
                depth = len(rel.parts)
            except Exception:
                depth = 0

            if depth > max_depth:
                dirs.clear()
                continue

            # Filter out excluded system / cache directories in-place
            dirs[:] = [
                d for d in dirs
                if not d.startswith("$")
                and d.lower() not in skip_dir_names
                and not d.startswith(".")
            ]

            for file_name in files:
                files_checked += 1
                if files_checked % 50 == 0 and progress_callback:
                    progress_callback(len(backups), f"Taranıyor ({files_checked} dosya incelendi)...", None)

                file_path = Path(current_dir) / file_name
                suffix = file_path.suffix.lower()
                name_lower = file_name.lower()

                if suffix in known_extensions or name_lower.endswith(".tar.gz") or name_lower.endswith(".bak.gz"):
                    try:
                        stat = file_path.stat()
                        size = stat.st_size
                        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()

                        # Determine backup type
                        b_type = "Sıkıştırılmış Yedek"
                        if suffix in (".bak", ".trn") or ".bak.gz" in name_lower or suffix in (".sql", ".dump"):
                            b_type = "SQL Veritabanı"
                        elif suffix in (".vhdx", ".vhd", ".vhds") or ".vhdx.gz" in name_lower:
                            b_type = "VHDX / Hyper-V Disk"
                        elif "mail" in name_lower or suffix in (".eml", ".mbox", ".pst"):
                            b_type = "E-Posta Arşivi"
                        elif suffix in (".db", ".sqlite", ".sqlite3"):
                            b_type = "SQLite Veritabanı"

                        item = {
                            "name": file_name,
                            "type": b_type,
                            "path": str(file_path),
                            "size_bytes": size,
                            "size_mb": round(size / (1024 * 1024), 2),
                            "modified_at": mtime,
                        }
                        backups.append(item)
                        if progress_callback:
                            progress_callback(len(backups), f"Bulundu: {file_name}", item)

                        if len(backups) >= max_files:
                            dirs.clear()
                            break
                    except Exception:
                        pass
    except Exception as exc:
        logger.warning("Error scanning backups on drive %s: %s", drive_path, exc)

    if progress_callback:
        progress_callback(len(backups), f"Tarama tamamlandı ({len(backups)} yedek bulundu)", None)

    return backups


class DiskWatcher:
    """Monitors disk connection/removal events and triggers automated backup handlers."""

    def __init__(self, check_interval_seconds: float = 2.0):
        self._check_interval = check_interval_seconds
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._known_drives: Set[str] = set()
        self._callbacks: List[Callable[[Dict[str, Any]], None]] = []

    def list_drives(self) -> List[Dict[str, Any]]:
        """List all accessible drives with normalized path and space."""
        raw_drives = list_available_drives()
        results = []
        for d in raw_drives:
            letter = d.get("letter", "")
            root = d.get("root_path", f"{letter}\\")
            total_gb = round(d.get("total_bytes", 0) / (1024 ** 3), 2)
            free_gb = round(d.get("free_bytes", 0) / (1024 ** 3), 2)
            results.append({
                "path": root,
                "letter": letter,
                "label": d.get("label", "Yerel Sürücü"),
                "type": d.get("type_name", "Sabit Disk"),
                "is_removable": d.get("is_removable", False),
                "total_gb": total_gb,
                "free_gb": free_gb,
                "free_percent": d.get("free_percent", 0.0),
            })
        return results

    def scan_drive_backups(
        self,
        drive_path: str,
        max_depth: int = 3,
        progress_callback: Optional[Callable[[int, str, Optional[Dict[str, Any]]], None]] = None,
    ) -> Dict[str, Any]:
        """Scan a drive path and return categorized backup files."""
        all_items = scan_backups_on_drive(drive_path, max_depth=max_depth, progress_callback=progress_callback)
        sql_backups = []
        vhdx_backups = []
        mail_backups = []

        for item in all_items:
            b_type = item.get("type", "")
            if "SQL" in b_type:
                sql_backups.append(item)
            elif "VHDX" in b_type or "Hyper-V" in b_type:
                vhdx_backups.append(item)
            elif "Mail" in b_type or "E-Posta" in b_type:
                mail_backups.append(item)

        return {
            "drive_path": drive_path,
            "all_backups": all_items,
            "sql_backups": sql_backups,
            "vhdx_backups": vhdx_backups,
            "mail_backups": mail_backups,
        }

    def add_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._callbacks.append(callback)

    def start_watching(self, callback: Optional[Callable[[Dict[str, Any]], None]] = None, poll_interval: float = 3.0) -> None:
        if callback:
            self.add_callback(callback)
        self._check_interval = poll_interval
        self.start()

    def stop_watching(self) -> None:
        self.stop()

    def start(self) -> None:
        """Start drive monitor thread."""
        if self._running:
            return
        self._running = True
        # Initialize baseline of currently present drives
        self._known_drives = {d["letter"] for d in list_available_drives()}
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("DiskWatcher service started (known drives: %s)", list(self._known_drives))

    def stop(self) -> None:
        self._running = False

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                current_drives = list_available_drives()
                current_letters = {d["letter"] for d in current_drives}

                # Detect newly inserted drives
                new_letters = current_letters - self._known_drives
                if new_letters:
                    for d in current_drives:
                        if d["letter"] in new_letters:
                            logger.info("New drive detected: %s (%s - %s)", d["letter"], d["label"], d["type_name"])
                            total_gb = round(d.get("total_bytes", 0) / (1024 ** 3), 2)
                            free_gb = round(d.get("free_bytes", 0) / (1024 ** 3), 2)
                            d_info = {
                                "path": d.get("root_path", d["letter"] + "\\"),
                                "letter": d["letter"],
                                "label": d.get("label", "Yerel Disk"),
                                "type": d.get("type_name", "Taşınabilir USB / Disk"),
                                "is_removable": d.get("is_removable", True),
                                "total_gb": total_gb,
                                "free_gb": free_gb,
                            }
                            for cb in self._callbacks:
                                try:
                                    cb(d_info)
                                except Exception as exc:
                                    logger.error("Error in DiskWatcher callback: %s", exc)

                self._known_drives = current_letters
            except Exception as exc:
                logger.error("DiskWatcher loop exception: %s", exc)

            time.sleep(self._check_interval)
