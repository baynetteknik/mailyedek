"""
reporter.py — Report generation (JSON and HTML).

Clean Architecture — Core Service Layer.
Generates structured reports after sync, backup, and restore operations.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

REPORT_DIR = Path("data/reports")


def _format_duration(seconds: float) -> str:
    """Format duration in a human-readable format."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {secs:.0f}s"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h {minutes}m {secs:.0f}s"


def _format_bytes(size: int) -> str:
    """Format byte count in human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


class ReportGenerator:
    """Generates JSON and HTML reports for operations."""

    def __init__(self, report_dir: Optional[Path] = None):
        self._report_dir = report_dir or REPORT_DIR
        self._report_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Sync report
    # ------------------------------------------------------------------

    def generate_sync_report(self, report: Dict[str, Any],
                             output_format: str = "both") -> Path:
        """Generate a sync report. Returns the path to the report file.

        Args:
            report: SyncReport as dict (from SyncUseCase)
            output_format: "json", "html", or "both"

        Returns:
            Path to the generated report file.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        account_label = report.get("account_label", "unknown")
        base_name = f"sync_report_{account_label}_{timestamp}"

        if output_format in ("json", "both"):
            json_path = self._report_dir / f"{base_name}.json"
            self._write_json(json_path, self._format_sync_report(report))
            logger.info("Sync report written to %s", json_path)

        if output_format in ("html", "both"):
            html_path = self._report_dir / f"{base_name}.html"
            self._write_html(html_path, "Sync Report", self._format_sync_report(report),
                             self._sync_html_template(report))
            logger.info("Sync report written to %s", html_path)

        return self._report_dir / f"{base_name}.json"

    def _format_sync_report(self, report: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "sync",
            "account": report.get("account_label", ""),
            "timestamp": datetime.utcnow().isoformat(),
            "folders_synced": report.get("folders_synced", 0),
            "mails_fetched": report.get("mails_fetched", 0),
            "mails_updated": report.get("mails_updated", 0),
            "duplicates_found": report.get("duplicates_found", 0),
            "errors": report.get("errors", 0),
            "total_bytes": report.get("total_bytes", 0),
            "total_bytes_formatted": _format_bytes(report.get("total_bytes", 0)),
            "duration_seconds": report.get("duration_seconds", 0),
            "duration_formatted": _format_duration(report.get("duration_seconds", 0)),
            "started_at": report.get("started_at", ""),
            "finished_at": report.get("finished_at", ""),
        }

    def _sync_html_template(self, report: Dict[str, Any]) -> str:
        r = self._format_sync_report(report)
        return f"""
        <h2>Sync Report: {r['account']}</h2>
        <table class="report-table">
            <tr><td>Started</td><td>{r['started_at']}</td></tr>
            <tr><td>Finished</td><td>{r['finished_at']}</td></tr>
            <tr><td>Duration</td><td>{r['duration_formatted']}</td></tr>
            <tr><td>Folders Synced</td><td>{r['folders_synced']}</td></tr>
            <tr><td>Mails Fetched</td><td>{r['mails_fetched']}</td></tr>
            <tr><td>Duplicates Found</td><td>{r['duplicates_found']}</td></tr>
            <tr><td>Total Data</td><td>{r['total_bytes_formatted']}</td></tr>
            <tr><td>Errors</td><td class="{'error' if r['errors'] > 0 else ''}">{r['errors']}</td></tr>
        </table>
        """

    # ------------------------------------------------------------------
    # Backup report
    # ------------------------------------------------------------------

    def generate_backup_report(self, report: Dict[str, Any],
                               output_format: str = "both") -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        target = report.get("target", "unknown")
        base_name = f"backup_report_{target}_{timestamp}"

        if output_format in ("json", "both"):
            json_path = self._report_dir / f"{base_name}.json"
            self._write_json(json_path, self._format_backup_report(report))

        if output_format in ("html", "both"):
            html_path = self._report_dir / f"{base_name}.html"
            self._write_html(html_path, "Backup Report",
                             self._format_backup_report(report),
                             self._backup_html_template(report))

        return self._report_dir / f"{base_name}.json"

    def _format_backup_report(self, report: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "backup",
            "target": report.get("target", ""),
            "timestamp": datetime.utcnow().isoformat(),
            "mails_backed_up": report.get("mails_backed_up", 0),
            "total_bytes": report.get("total_bytes", 0),
            "total_bytes_formatted": _format_bytes(report.get("total_bytes", 0)),
            "parts_uploaded": report.get("parts_uploaded", 0),
            "errors": report.get("errors", 0),
            "duration_seconds": report.get("duration_seconds", 0),
            "duration_formatted": _format_duration(report.get("duration_seconds", 0)),
            "started_at": report.get("started_at", ""),
            "finished_at": report.get("finished_at", ""),
        }

    def _backup_html_template(self, report: Dict[str, Any]) -> str:
        r = self._format_backup_report(report)
        return f"""
        <h2>Backup Report: {r['target'].upper()}</h2>
        <table class="report-table">
            <tr><td>Started</td><td>{r['started_at']}</td></tr>
            <tr><td>Finished</td><td>{r['finished_at']}</td></tr>
            <tr><td>Duration</td><td>{r['duration_formatted']}</td></tr>
            <tr><td>Mails Backed Up</td><td>{r['mails_backed_up']}</td></tr>
            <tr><td>Total Size</td><td>{r['total_bytes_formatted']}</td></tr>
            <tr><td>Parts Uploaded</td><td>{r['parts_uploaded']}</td></tr>
            <tr><td>Errors</td><td class="{'error' if r['errors'] > 0 else ''}">{r['errors']}</td></tr>
        </table>
        """

    # ------------------------------------------------------------------
    # Dry-run report
    # ------------------------------------------------------------------

    def generate_dry_run_report(self, results: List[Dict[str, Any]],
                                output_format: str = "both") -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        base_name = f"dry_run_{timestamp}"

        report_data = {
            "type": "dry_run",
            "timestamp": timestamp,
            "operations": results,
            "total_operations": len(results),
        }

        if output_format in ("json", "both"):
            json_path = self._report_dir / f"{base_name}.json"
            self._write_json(json_path, report_data)

        if output_format in ("html", "both"):
            html_path = self._report_dir / f"{base_name}.html"
            html = "<h2>Dry Run Results</h2>\n"
            for op in results:
                html += f"<h3>{op.get('account', 'N/A')}</h3>\n"
                html += "<table class='report-table'>\n"
                for k, v in op.items():
                    html += f"<tr><td>{k}</td><td>{v}</td></tr>\n"
                html += "</table>\n"
            self._write_html(html_path, "Dry Run Report", report_data, html)

        return self._report_dir / f"{base_name}.json"

    # ------------------------------------------------------------------
    # Internal I/O
    # ------------------------------------------------------------------

    def _write_json(self, path: Path, data: Dict) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _write_html(self, path: Path, title: str, data: Dict,
                    body_html: str) -> None:
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           margin: 40px; background: #f5f5f5; color: #333; }}
    .container {{ max-width: 800px; margin: auto; background: white;
                 padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    .report-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
    .report-table td {{ padding: 10px; border-bottom: 1px solid #eee; }}
    .report-table td:first-child {{ font-weight: 600; width: 200px; color: #555; }}
    .error {{ color: #d32f2f; font-weight: bold; }}
    h2 {{ color: #1976d2; border-bottom: 2px solid #1976d2; padding-bottom: 8px; }}
    .meta {{ color: #888; font-size: 0.9em; margin-top: 30px; }}
</style>
</head>
<body>
<div class="container">
    {body_html}
    <div class="meta">Generated at {datetime.utcnow().isoformat()}</div>
</div>
</body>
</html>"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
