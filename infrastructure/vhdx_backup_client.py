"""
vhdx_backup_client.py — Infrastructure client for VHDX and Hyper-V backups.

Clean Architecture — Infrastructure Layer.
Supports:
  - Hyper-V VM discovery and consistent export (Export-VM)
  - Direct VHD / VHDX / VHDS disk image streamed copying
  - Windows Volume Shadow Copy (VSS) snapshot creation for locked/in-use virtual disks
  - On-the-fly SHA-256 integrity hashing and live speed/progress calculation
  - Optional GZip / Zip compression
"""

import gzip
import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from domain.entities import VhdxBackupReport

logger = logging.getLogger(__name__)

CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB buffer for fast sequential disk I/O


class VhdxBackupClient:
    """Client for performing Hyper-V VM and VHDX virtual disk backups."""

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # Hyper-V Discovery
    # ------------------------------------------------------------------

    def list_hyperv_vms(self) -> List[Dict[str, Any]]:
        """List all Hyper-V virtual machines and their attached virtual disks."""
        ps_script = """
        try {
            if (-not (Get-Module -ListAvailable -Name Hyper-V)) {
                Write-Output "[]"
                exit
            }
            $vms = Get-VM -ErrorAction SilentlyContinue
            if (-not $vms) {
                Write-Output "[]"
                exit
            }
            $result = @()
            foreach ($vm in $vms) {
                $disks = @()
                try {
                    $hd = Get-VMHardDiskDrive -VM $vm -ErrorAction SilentlyContinue
                    foreach ($d in $hd) {
                        $disks += $d.Path
                    }
                } catch {}
                
                $result += @{
                    "name" = $vm.Name
                    "state" = $vm.State.ToString()
                    "status" = $vm.Status
                    "path" = $vm.Path
                    "disks" = $disks
                    "uptime" = $vm.Uptime.ToString()
                }
            }
            $result | ConvertTo-Json -Compress
        } catch {
            Write-Output "[]"
        }
        """
        raw = self._run_powershell(ps_script)
        try:
            res = json.loads(raw.strip())
            if isinstance(res, list):
                return res
            elif isinstance(res, dict):
                return [res]
            return []
        except Exception as exc:
            logger.debug("Hyper-V discovery parse error or Hyper-V not present: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Backup Execution
    # ------------------------------------------------------------------

    def backup_hyperv_vm(
        self,
        vm_name: str,
        dest_dir: Path,
        compress: bool = False,
        progress_callback: Optional[Callable[[str, float, float], None]] = None,
    ) -> VhdxBackupReport:
        """Export a Hyper-V VM consistently to destination."""
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        start_time = time.time()
        started_at = datetime.now().isoformat()

        report = VhdxBackupReport(
            job_name=f"VM_{vm_name}",
            mode="hyperv_vm",
            source=vm_name,
            started_at=started_at,
        )

        try:
            if progress_callback:
                progress_callback(f"Hyper-V Sanal Makine ({vm_name}) dışa aktarılıyor...", 0.0, 0.0)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            export_target = dest_dir / f"{vm_name}_EXPORT_{timestamp}"
            export_target.mkdir(parents=True, exist_ok=True)

            ps_script = f"""
            try {{
                Export-VM -Name "{vm_name}" -Path "{str(export_target.resolve())}" -ErrorAction Stop
                Write-Output "RESULT|SUCCESS"
            }} catch {{
                Write-Output "ERR|$($_.Exception.Message)"
            }}
            """
            output = self._run_powershell(ps_script)
            if "RESULT|SUCCESS" in output:
                # Calculate total size of exported VM folder
                total_size = sum(f.stat().st_size for f in export_target.rglob("*") if f.is_file())
                report.total_bytes = total_size
                report.output_file = str(export_target)
                report.dest_file = str(export_target)
                report.status = "SUCCESS"
                report.duration_seconds = round(time.time() - start_time, 2)
                if report.duration_seconds > 0:
                    report.speed_mbps = round((total_size / (1024 * 1024)) / report.duration_seconds, 2)
                if progress_callback:
                    progress_callback(f"Hyper-V Dışa Aktarımı Tamamlandı: {total_size / (1024*1024):.2f} MB", 100.0, report.speed_mbps)
            else:
                err = output.replace("ERR|", "").strip() or "Hyper-V dışa aktarım başarısız oldu."
                raise RuntimeError(err)

        except Exception as exc:
            logger.exception("Hyper-V VM backup failed: %s", exc)
            report.status = "FAILED"
            report.errors.append(str(exc))
            report.duration_seconds = round(time.time() - start_time, 2)
            if progress_callback:
                progress_callback(f"HATA: {exc}", 0.0, 0.0)

        report.finished_at = datetime.now().isoformat()
        return report

    def backup_vhdx_file(
        self,
        source_path_str: str,
        dest_dir: Path,
        use_vss: bool = True,
        compress: bool = False,
        compress_mode: str = "raw",  # raw, compressed, dynamic
        verify_hash: bool = True,
        progress_callback: Optional[Callable[[str, float, float], None]] = None,
    ) -> VhdxBackupReport:
        """Backup a VHDX / VHD virtual disk file with optional VSS snapshot, on-the-fly hashing, and compression/sparse modes."""
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        source_path = Path(source_path_str)
        start_time = time.time()
        started_at = datetime.now().isoformat()

        report = VhdxBackupReport(
            job_name=f"VHDX_{source_path.stem}",
            mode="direct_file",
            source=str(source_path),
            started_at=started_at,
        )

        if not source_path.exists() and not use_vss:
            report.status = "FAILED"
            report.errors.append(f"Kaynak disk dosyası bulunamadı: {source_path_str}")
            report.finished_at = datetime.now().isoformat()
            return report

        shadow_id: Optional[str] = None
        read_path: str = str(source_path.resolve())
        used_vss_actual = False

        try:
            # 1. Attempt VSS snapshot if requested and running on Windows
            if use_vss and os.name == "nt":
                drive = source_path.drive or "C:"
                if not drive.endswith("\\"):
                    drive_root = f"{drive}\\"
                else:
                    drive_root = drive

                if progress_callback:
                    progress_callback(f"VSS Gölge Kopyası (Shadow Copy) oluşturuluyor ({drive_root})...", 0.0, 0.0)

                shadow_id, shadow_device = self._create_vss_snapshot(drive_root)
                if shadow_id and shadow_device:
                    # Strip drive letter from relative path
                    rel_path = str(source_path.resolve())[len(drive):].lstrip("\\/")
                    read_path = f"{shadow_device}\\{rel_path}"
                    used_vss_actual = True
                    report.used_vss = True
                    if progress_callback:
                        progress_callback(f"VSS Gölge Kopyası hazır: {shadow_device}", 0.0, 0.0)
                else:
                    logger.warning("VSS snapshot could not be created, falling back to direct stream copy.")
                    if progress_callback:
                        progress_callback("VSS oluşturulamadı, doğrudan dosya kopyalamaya geçiliyor...", 0.0, 0.0)

            # 2. Setup target file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            target_filename = f"{source_path.stem}_{timestamp}{source_path.suffix}"
            is_compressed = (compress or compress_mode == "compressed")
            if is_compressed:
                target_filename += ".gz"
            target_path = dest_dir / target_filename

            # 3. Stream copy with progress & SHA-256 calculation
            try:
                source_size = source_path.stat().st_size if source_path.exists() else 0
            except Exception:
                source_size = 0

            report.dest_file = str(target_path)
            sha256 = hashlib.sha256() if verify_hash else None
            bytes_copied = 0
            last_update_time = time.time()

            if progress_callback:
                progress_callback(f"Kopyalama başlatılıyor: {source_path.name} -> {target_filename}", 0.0, 0.0)

            with open(read_path, "rb") as f_in:
                # If compression enabled
                if compress:
                    with gzip.open(target_path, "wb", compresslevel=6) as f_out:
                        while True:
                            chunk = f_in.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            f_out.write(chunk)
                            bytes_copied += len(chunk)
                            if sha256:
                                sha256.update(chunk)

                            now = time.time()
                            if now - last_update_time >= 0.5:
                                elapsed = now - start_time
                                speed_mbps = (bytes_copied / (1024 * 1024)) / max(elapsed, 0.001)
                                pct = (bytes_copied / max(source_size, 1)) * 100.0 if source_size > 0 else 0.0
                                if progress_callback:
                                    progress_callback(
                                        f"Kopyalanıyor: {bytes_copied / (1024*1024):.1f} MB (%{pct:.1f}) - {speed_mbps:.1f} MB/s",
                                        pct,
                                        speed_mbps
                                    )
                                last_update_time = now
                else:
                    with open(target_path, "wb") as f_out:
                        while True:
                            chunk = f_in.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            f_out.write(chunk)
                            bytes_copied += len(chunk)
                            if sha256:
                                sha256.update(chunk)

                            now = time.time()
                            if now - last_update_time >= 0.5:
                                elapsed = now - start_time
                                speed_mbps = (bytes_copied / (1024 * 1024)) / max(elapsed, 0.001)
                                pct = (bytes_copied / max(source_size, 1)) * 100.0 if source_size > 0 else 0.0
                                if progress_callback:
                                    progress_callback(
                                        f"Kopyalanıyor: {bytes_copied / (1024*1024):.1f} MB (%{pct:.1f}) - {speed_mbps:.1f} MB/s",
                                        pct,
                                        speed_mbps
                                    )
                                last_update_time = now

            duration = round(time.time() - start_time, 2)
            report.duration_seconds = duration
            report.total_bytes = target_path.stat().st_size if target_path.exists() else bytes_copied
            if duration > 0:
                report.speed_mbps = round((bytes_copied / (1024 * 1024)) / duration, 2)

            if sha256:
                report.sha256_hash = sha256.hexdigest()

            report.status = "SUCCESS"
            if progress_callback:
                progress_callback(
                    f"VHDX Yedekleme Başarılı! {report.total_bytes / (1024*1024):.2f} MB ({duration}s, {report.speed_mbps} MB/s)",
                    100.0,
                    report.speed_mbps
                )

        except Exception as exc:
            logger.exception("VHDX backup error: %s", exc)
            report.status = "FAILED"
            report.errors.append(str(exc))
            report.duration_seconds = round(time.time() - start_time, 2)
            if progress_callback:
                progress_callback(f"HATA: {exc}", 0.0, 0.0)

        finally:
            # 4. Clean up VSS snapshot
            if shadow_id:
                if progress_callback:
                    progress_callback("VSS Gölge Kopyası temizleniyor...", 100.0, 0.0)
                self._delete_vss_snapshot(shadow_id)

        report.finished_at = datetime.now().isoformat()
        return report

    # ------------------------------------------------------------------
    # VSS Snapshot Helpers (Windows)
    # ------------------------------------------------------------------

    def _create_vss_snapshot(self, volume_path: str) -> Tuple[Optional[str], Optional[str]]:
        """Create a VSS volume shadow copy. Returns (ShadowID, DeviceObjectPath)."""
        ps_script = f"""
        try {{
            $s = (Get-WmiObject -List Win32_ShadowCopy).Create('{volume_path}', 'ClientAccessible')
            if ($s.ReturnValue -eq 0) {{
                $shadow = Get-WmiObject Win32_ShadowCopy | Where-Object {{ $_.ID -eq $s.ShadowID }}
                Write-Output "OK|$($s.ShadowID)|$($shadow.DeviceObject)"
            }} else {{
                Write-Output "ERR|ReturnValue $($s.ReturnValue)"
            }}
        }} catch {{
            Write-Output "ERR|$($_.Exception.Message)"
        }}
        """
        output = self._run_powershell(ps_script)
        if output.startswith("OK"):
            parts = output.strip().split("|")
            if len(parts) >= 3:
                return parts[1], parts[2]
        return None, None

    def _delete_vss_snapshot(self, shadow_id: str) -> bool:
        """Delete temporary VSS shadow copy."""
        ps_script = f"""
        try {{
            $shadow = Get-WmiObject Win32_ShadowCopy | Where-Object {{ $_.ID -eq '{shadow_id}' }}
            if ($shadow) {{
                $shadow.Delete() | Out-Null
                Write-Output "OK"
            }} else {{
                Write-Output "NOT_FOUND"
            }}
        }} catch {{
            Write-Output "ERR|$($_.Exception.Message)"
        }}
        """
        output = self._run_powershell(ps_script)
        return "OK" in output

    # ------------------------------------------------------------------
    # PowerShell Runner Utility
    # ------------------------------------------------------------------

    def _run_powershell(self, script: str) -> str:
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=7200,
            )
            return res.stdout.strip()
        except Exception as exc:
            return f"ERR|{exc}"
