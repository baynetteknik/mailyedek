"""
sql_backup_client.py — Infrastructure client for database backups.

Clean Architecture — Infrastructure Layer.
Supports:
  - Microsoft SQL Server (MSSQL via PowerShell .NET System.Data.SqlClient or sqlcmd)
  - MySQL / MariaDB (via mysqldump)
  - PostgreSQL (via pg_dump)
  - SQLite (native online backup API)
"""

import gzip
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from domain.entities import SqlBackupReport

logger = logging.getLogger(__name__)


class SqlBackupClient:
    """Client for executing SQL backups, connection tests, and database discoveries."""

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # Connection testing & discovery
    # ------------------------------------------------------------------

    def test_connection(
        self,
        engine_type: str,
        host: str = "localhost",
        port: int = 1433,
        auth_type: str = "windows",
        username: str = "",
        password: str = "",
        database_name: str = "master",
    ) -> Tuple[bool, str]:
        """Test database server connection. Returns (success, message)."""
        engine_type = engine_type.lower()
        try:
            if engine_type == "mssql":
                return self._test_mssql_connection(host, port, auth_type, username, password)
            elif engine_type in ("mysql", "mariadb"):
                return self._test_mysql_connection(host, port, username, password)
            elif engine_type == "postgres" or engine_type == "postgresql":
                return self._test_postgres_connection(host, port, username, password)
            elif engine_type == "sqlite":
                return self._test_sqlite_connection(database_name or host)
            else:
                return False, f"Desteklenmeyen veritabanı motoru: {engine_type}"
        except Exception as exc:
            logger.exception("SQL test connection error: %s", exc)
            return False, f"Bağlantı hatası: {str(exc)}"

    def list_databases(
        self,
        engine_type: str,
        host: str = "localhost",
        port: int = 1433,
        auth_type: str = "windows",
        username: str = "",
        password: str = "",
    ) -> List[str]:
        """Discover databases available on the database server."""
        engine_type = engine_type.lower()
        try:
            if engine_type == "mssql":
                return self._list_mssql_databases(host, port, auth_type, username, password)
            elif engine_type in ("mysql", "mariadb"):
                return self._list_mysql_databases(host, port, username, password)
            elif engine_type in ("postgres", "postgresql"):
                return self._list_postgres_databases(host, port, username, password)
            elif engine_type == "sqlite":
                return ["main"]
            return []
        except Exception as exc:
            logger.error("List databases failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Backup Execution
    # ------------------------------------------------------------------

    def backup(
        self,
        engine_type: str,
        host: str,
        port: int,
        auth_type: str,
        username: str,
        password: str,
        database_name: str,
        dest_dir: Path,
        backup_type: str = "FULL",
        compress: bool = True,
        verify: bool = True,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> SqlBackupReport:
        """Execute database backup."""
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        start_time = time.time()
        started_at = datetime.now().isoformat()

        report = SqlBackupReport(
            engine_type=engine_type,
            database_name=database_name,
            backup_type=backup_type,
            started_at=started_at,
        )

        try:
            if progress_callback:
                progress_callback(f"{engine_type.upper()} ({database_name}) yedekleme başlatılıyor...")

            if engine_type.lower() == "mssql":
                self._backup_mssql(
                    host, port, auth_type, username, password,
                    database_name, dest_dir, backup_type, compress, verify,
                    report, progress_callback
                )
            elif engine_type.lower() == "sqlite":
                candidate = host if (host and Path(host).exists()) else database_name
                self._backup_sqlite(candidate, dest_dir, compress, report, progress_callback)
            elif engine_type.lower() in ("mysql", "mariadb"):
                self._backup_mysql(host, port, username, password, database_name, dest_dir, compress, report, progress_callback)
            elif engine_type.lower() in ("postgres", "postgresql"):
                self._backup_postgres(host, port, username, password, database_name, dest_dir, compress, report, progress_callback)
            else:
                raise ValueError(f"Bilinmeyen veritabanı motoru: {engine_type}")

            report.duration_seconds = round(time.time() - start_time, 2)
            report.finished_at = datetime.now().isoformat()
            if report.output_file and Path(report.output_file).exists():
                report.total_bytes = Path(report.output_file).stat().st_size
                report.status = "SUCCESS"
                if progress_callback:
                    progress_callback(
                        f"Yedekleme tamamlandı: {report.output_file} ({report.total_bytes / (1024*1024):.2f} MB)"
                    )
            else:
                report.status = "FAILED"
                if not report.errors:
                    report.errors.append("Yedekleme dosyası oluşturulamadı.")

        except Exception as exc:
            logger.exception("SQL Backup execution failed: %s", exc)
            report.status = "FAILED"
            report.errors.append(str(exc))
            report.duration_seconds = round(time.time() - start_time, 2)
            report.finished_at = datetime.now().isoformat()
            if progress_callback:
                progress_callback(f"HATA: {exc}")

        return report

    # ------------------------------------------------------------------
    # Microsoft SQL Server (MSSQL) Implementation
    # ------------------------------------------------------------------

    def _build_mssql_conn_string(
        self, host: str, port: int, auth_type: str, username: str, password: str, db: str = "master"
    ) -> str:
        server = host
        if port and port != 1433 and "," not in host and "\\" not in host:
            server = f"{host},{port}"

        if auth_type.lower() == "windows":
            return f"Server={server};Database={db};Integrated Security=True;TrustServerCertificate=True;Connection Timeout=15;"
        else:
            return f"Server={server};Database={db};User Id={username};Password={password};TrustServerCertificate=True;Connection Timeout=15;"

    def _test_mssql_connection(
        self, host: str, port: int, auth_type: str, username: str, password: str
    ) -> Tuple[bool, str]:
        conn_str = self._build_mssql_conn_string(host, port, auth_type, username, password)
        ps_script = f"""
        $connStr = @'
{conn_str}
'@
        try {{
            $conn = New-Object System.Data.SqlClient.SqlConnection($connStr)
            $conn.Open()
            $cmd = $conn.CreateCommand()
            $cmd.CommandText = "SELECT @@VERSION AS ver, SERVERPROPERTY('ServerName') AS srv"
            $reader = $cmd.ExecuteReader()
            if ($reader.Read()) {{
                $srv = $reader["srv"]
                $ver = $reader["ver"].ToString().Split("`n")[0]
                Write-Output "OK|$srv|$ver"
            }} else {{
                Write-Output "OK|Connected"
            }}
            $conn.Close()
        }} catch {{
            Write-Output "ERR|$($_.Exception.Message)"
        }}
        """
        output = self._run_powershell(ps_script)
        if output.startswith("OK"):
            parts = output.split("|")
            info = f"Başarılı. Sunucu: {parts[1] if len(parts)>1 else 'MSSQL'}"
            if len(parts) > 2:
                info += f" ({parts[2]})"
            return True, info
        else:
            msg = output.replace("ERR|", "").strip() or "Bağlantı kurulamadı."
            return False, msg

    def _list_mssql_databases(
        self, host: str, port: int, auth_type: str, username: str, password: str
    ) -> List[str]:
        conn_str = self._build_mssql_conn_string(host, port, auth_type, username, password)
        ps_script = f"""
        $connStr = @'
{conn_str}
'@
        try {{
            $conn = New-Object System.Data.SqlClient.SqlConnection($connStr)
            $conn.Open()
            $cmd = $conn.CreateCommand()
            $cmd.CommandText = "SELECT name FROM sys.databases WHERE state_desc = 'ONLINE' ORDER BY name"
            $reader = $cmd.ExecuteReader()
            $dbs = @()
            while ($reader.Read()) {{
                $dbs += $reader["name"].ToString()
            }}
            $conn.Close()
            $dbs | ConvertTo-Json -Compress
        }} catch {{
            Write-Output "[]"
        }}
        """
        raw = self._run_powershell(ps_script)
        try:
            res = json.loads(raw)
            if isinstance(res, list):
                return res
            elif isinstance(res, str):
                return [res]
            return []
        except Exception:
            return [line.strip() for line in raw.splitlines() if line.strip() and not line.startswith("ERR")]

    def _backup_mssql(
        self,
        host: str,
        port: int,
        auth_type: str,
        username: str,
        password: str,
        database_name: str,
        dest_dir: Path,
        backup_type: str,
        compress: bool,
        verify: bool,
        report: SqlBackupReport,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        ext = "bak" if backup_type.upper() in ("FULL", "DIFFERENTIAL") else "trn"
        target_bak_file = dest_dir / f"{database_name}_{backup_type.upper()}_{timestamp}.{ext}"
        target_path_str = str(target_bak_file.resolve())

        # Generate T-SQL statement
        tsql_options = ["FORMAT", "INIT", "STATS = 10"]
        if compress:
            tsql_options.append("COMPRESSION")

        if backup_type.upper() == "DIFFERENTIAL":
            tsql_options.append("DIFFERENTIAL")
            backup_sql = f"BACKUP DATABASE [{database_name}] TO DISK = N'{target_path_str}' WITH {', '.join(tsql_options)}"
        elif backup_type.upper() == "LOG":
            backup_sql = f"BACKUP LOG [{database_name}] TO DISK = N'{target_path_str}' WITH {', '.join(tsql_options)}"
        else:
            backup_sql = f"BACKUP DATABASE [{database_name}] TO DISK = N'{target_path_str}' WITH {', '.join(tsql_options)}"

        verify_sql = f"RESTORE VERIFYONLY FROM DISK = N'{target_path_str}'" if verify else ""

        conn_str = self._build_mssql_conn_string(host, port, auth_type, username, password, db="master")

        ps_script = f"""
        $connStr = @'
{conn_str}
'@
        $backupSql = @'
{backup_sql}
'@
        $verifySql = @'
{verify_sql}
'@
        try {{
            $conn = New-Object System.Data.SqlClient.SqlConnection($connStr)
            $conn.FireInfoMessageEventOnUserErrors = $true
            Register-ObjectEvent -InputObject $conn -EventName "InfoMessage" -Action {{
                Write-Output "INFO|$($EventArgs.Message)"
            }} | Out-Null

            $conn.Open()
            $cmd = $conn.CreateCommand()
            $cmd.CommandTimeout = 7200 # 2 hours
            $cmd.CommandText = $backupSql
            Write-Output "PROGRESS|Executing T-SQL backup..."
            $cmd.ExecuteNonQuery() | Out-Null

            if ($verifySql -ne "") {{
                Write-Output "PROGRESS|Verifying backup integrity..."
                $cmd.CommandText = $verifySql
                $cmd.ExecuteNonQuery() | Out-Null
                Write-Output "VERIFIED|OK"
            }}

            $conn.Close()
            Write-Output "RESULT|SUCCESS"
        }} catch {{
            Write-Output "ERR|$($_.Exception.Message)"
        }}
        """

        output = self._run_powershell(ps_script, progress_callback)

        if "VERIFIED|OK" in output:
            report.verified = True

        if "RESULT|SUCCESS" in output and target_bak_file.exists():
            report.output_file = str(target_bak_file)
        else:
            errors = [line.replace("ERR|", "").strip() for line in output.splitlines() if line.startswith("ERR|")]
            if errors:
                raise RuntimeError("; ".join(errors))
            elif target_bak_file.exists():
                report.output_file = str(target_bak_file)
            else:
                raise RuntimeError("Yedekleme tamamlanamadı veya çıktı dosyası bulunamadı.")

    # ------------------------------------------------------------------
    # SQLite Implementation
    # ------------------------------------------------------------------

    def _test_sqlite_connection(self, db_path_str: str) -> Tuple[bool, str]:
        path = Path(db_path_str)
        if not path.exists():
            return False, f"SQLite veritabanı dosyası bulunamadı: {db_path_str}"
        try:
            conn = sqlite3.connect(str(path))
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check")
            res = cur.fetchone()
            conn.close()
            status = res[0] if res else "ok"
            return True, f"SQLite bağlantısı başarılı (Bütünlük: {status})"
        except Exception as e:
            return False, f"SQLite hatası: {e}"

    def _backup_sqlite(
        self,
        source_db_str: str,
        dest_dir: Path,
        compress: bool,
        report: SqlBackupReport,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        source_path = Path(source_db_str)
        if not source_path.exists():
            raise FileNotFoundError(f"Kaynak SQLite veritabanı bulunamadı: {source_db_str}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target_name = f"{source_path.stem}_SQLITE_{timestamp}.db"
        target_path = dest_dir / target_name

        if progress_callback:
            progress_callback(f"SQLite Online Backup başlatılıyor: {source_path.name} -> {target_name}")

        def step_callback(status, remaining, total):
            if total > 0 and progress_callback:
                pct = int(((total - remaining) / total) * 100)
                progress_callback(f"SQLite Yedekleme: %{pct} ({total - remaining}/{total} sayfa)")

        src_conn = sqlite3.connect(str(source_path))
        dst_conn = sqlite3.connect(str(target_path))
        try:
            with dst_conn:
                src_conn.backup(dst_conn, pages=100, progress=step_callback)
        finally:
            dst_conn.close()
            src_conn.close()

        # Optional compression
        if compress:
            if progress_callback:
                progress_callback("Yedek dosyası sıkıştırılıyor (.gz)...")
            gz_path = dest_dir / f"{target_name}.gz"
            with open(target_path, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)
            target_path.unlink()  # remove uncompressed
            target_path = gz_path

        report.output_file = str(target_path)
        report.verified = True

    # ------------------------------------------------------------------
    # MySQL Implementation
    # ------------------------------------------------------------------

    def _test_mysql_connection(self, host: str, port: int, username: str, password: str) -> Tuple[bool, str]:
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            result = sock.connect_ex((host, port or 3306))
            sock.close()
            if result == 0:
                return True, f"MySQL bağlantı noktası erişilebilir ({host}:{port or 3306})"
            else:
                return False, f"MySQL bağlantı noktasına erişilemedi ({host}:{port or 3306})"
        except Exception as e:
            return False, str(e)

    def _list_mysql_databases(self, host: str, port: int, username: str, password: str) -> List[str]:
        cmd = ["mysql", f"-h{host}", f"-P{port or 3306}", f"-u{username}", f"-p{password}", "-e", "SHOW DATABASES;"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                lines = [line.strip() for line in res.stdout.splitlines() if line.strip() and line.strip() != "Database"]
                return lines
        except Exception:
            pass
        return []

    def _backup_mysql(
        self, host: str, port: int, username: str, password: str,
        database_name: str, dest_dir: Path, compress: bool,
        report: SqlBackupReport, progress_callback: Optional[Callable[[str], None]] = None
    ) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target_name = f"{database_name}_MYSQL_{timestamp}.sql"
        target_path = dest_dir / target_name

        cmd = [
            "mysqldump",
            f"--host={host}",
            f"--port={port or 3306}",
            f"--user={username}",
            f"--password={password}",
            "--single-transaction",
            "--routines",
            "--triggers",
            database_name
        ]

        if progress_callback:
            progress_callback(f"mysqldump çalıştırılıyor: {database_name}...")

        if compress:
            gz_path = dest_dir / f"{target_name}.gz"
            with open(gz_path, "wb") as f_out:
                p1 = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                p2 = subprocess.Popen(["gzip", "-c"], stdin=p1.stdout, stdout=f_out)
                p1.stdout.close()
                p2.communicate()
            report.output_file = str(gz_path)
        else:
            with open(target_path, "w", encoding="utf-8") as f_out:
                res = subprocess.run(cmd, stdout=f_out, stderr=subprocess.PIPE, text=True)
                if res.returncode != 0:
                    raise RuntimeError(f"mysqldump başarısız: {res.stderr}")
            report.output_file = str(target_path)

    # ------------------------------------------------------------------
    # PostgreSQL Implementation
    # ------------------------------------------------------------------

    def _test_postgres_connection(self, host: str, port: int, username: str, password: str) -> Tuple[bool, str]:
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            result = sock.connect_ex((host, port or 5432))
            sock.close()
            if result == 0:
                return True, f"PostgreSQL bağlantı noktası erişilebilir ({host}:{port or 5432})"
            else:
                return False, f"PostgreSQL bağlantı noktasına erişilemedi ({host}:{port or 5432})"
        except Exception as e:
            return False, str(e)

    def _list_postgres_databases(self, host: str, port: int, username: str, password: str) -> List[str]:
        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password
        cmd = ["psql", "-h", host, "-p", str(port or 5432), "-U", username, "-lqt"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=10)
            if res.returncode == 0:
                return [line.split("|")[0].strip() for line in res.stdout.splitlines() if "|" in line]
        except Exception:
            pass
        return []

    def _backup_postgres(
        self, host: str, port: int, username: str, password: str,
        database_name: str, dest_dir: Path, compress: bool,
        report: SqlBackupReport, progress_callback: Optional[Callable[[str], None]] = None
    ) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target_name = f"{database_name}_POSTGRES_{timestamp}.dump"
        target_path = dest_dir / target_name

        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password

        cmd = [
            "pg_dump",
            "-h", host,
            "-p", str(port or 5432),
            "-U", username,
            "-F", "c",
            "-b",
            "-v",
            "-f", str(target_path),
            database_name
        ]

        if progress_callback:
            progress_callback(f"pg_dump çalıştırılıyor: {database_name}...")

        res = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if res.returncode != 0:
            raise RuntimeError(f"pg_dump başarısız: {res.stderr}")

        report.output_file = str(target_path)

    # ------------------------------------------------------------------
    # PowerShell Runner Utility
    # ------------------------------------------------------------------

    def _run_powershell(
        self, script: str, progress_callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """Run a PowerShell script block and capture stdout/stderr."""
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script]
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        output_lines = []
        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                line_str = line.strip()
                if not line_str:
                    continue
                if line_str.startswith("INFO|") or line_str.startswith("PROGRESS|"):
                    msg = line_str.split("|", 1)[1]
                    if progress_callback:
                        progress_callback(msg)
                else:
                    output_lines.append(line_str)

        process.wait()
        return "\n".join(output_lines)
