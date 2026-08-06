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
    # Restore report
    # ------------------------------------------------------------------

    def generate_restore_report(self, report: Dict[str, Any],
                               output_format: str = "both") -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        source = report.get("source", "unknown")
        # Sanitize source name for filename
        import re
        safe_source = re.sub(r'[\\/:*?"<>|]', '_', source).strip()
        base_name = f"restore_report_{safe_source}_{timestamp}"

        if output_format in ("json", "both"):
            json_path = self._report_dir / f"{base_name}.json"
            self._write_json(json_path, self._format_restore_report(report))

        if output_format in ("html", "both"):
            html_path = self._report_dir / f"{base_name}.html"
            self._write_html(html_path, "Restore Report",
                             self._format_restore_report(report),
                             self._restore_html_template(report))

        return self._report_dir / f"{base_name}.json"

    def _format_restore_report(self, report: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "restore",
            "source": report.get("source", ""),
            "timestamp": datetime.utcnow().isoformat(),
            "mails_restored": report.get("mails_restored", 0),
            "errors": report.get("errors", 0),
            "hash_verified": report.get("hash_verified", 0),
            "hash_failed": report.get("hash_failed", 0),
            "duration_seconds": report.get("duration_seconds", 0.0),
            "duration_formatted": _format_duration(report.get("duration_seconds", 0.0)),
            "started_at": report.get("started_at", ""),
            "finished_at": report.get("finished_at", ""),
        }

    def _restore_html_template(self, report: Dict[str, Any]) -> str:
        r = self._format_restore_report(report)
        return f"""
        <h2>Restore Report: FROM {r['source']}</h2>
        <table class="report-table">
            <tr><td>Started</td><td>{r['started_at']}</td></tr>
            <tr><td>Finished</td><td>{r['finished_at']}</td></tr>
            <tr><td>Duration</td><td>{r['duration_formatted']}</td></tr>
            <tr><td>Mails Restored</td><td>{r['mails_restored']}</td></tr>
            <tr><td>Hashes Verified</td><td>{r['hash_verified']}</td></tr>
            <tr><td>Hashes Failed</td><td class="{'error' if r['hash_failed'] > 0 else ''}">{r['hash_failed']}</td></tr>
            <tr><td>Errors</td><td class="{'error' if r['errors'] > 0 else ''}">{r['errors']}</td></tr>
        </table>
        """

    # ------------------------------------------------------------------
    # Export report
    # ------------------------------------------------------------------

    def generate_export_report(self, report: Dict[str, Any],
                              output_format: str = "both") -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        account_label = report.get("account_label", "unknown")
        # Sanitize account label for filename
        import re
        safe_acc = re.sub(r'[\\/:*?"<>|]', '_', account_label).strip()
        base_name = f"export_report_{safe_acc}_{timestamp}"

        if output_format in ("json", "both"):
            json_path = self._report_dir / f"{base_name}.json"
            self._write_json(json_path, self._format_export_report(report))

        if output_format in ("html", "both"):
            html_path = self._report_dir / f"{base_name}.html"
            self._write_html(html_path, "Export Report",
                             self._format_export_report(report),
                             self._export_html_template(report))

        return self._report_dir / f"{base_name}.json"

    def _format_export_report(self, report: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "export",
            "account": report.get("account_label", ""),
            "timestamp": datetime.utcnow().isoformat(),
            "format": report.get("format_type", "ZIP"),
            "target": report.get("output_path", "data/exports"),
            "total_mails": report.get("total", 0),
            "exported_mails": report.get("exported", 0),
            "errors": report.get("errors", 0),
            "started_at": report.get("started_at", ""),
            "finished_at": report.get("finished_at", ""),
        }

    def _export_html_template(self, report: Dict[str, Any]) -> str:
        r = self._format_export_report(report)
        return f"""
        <h2>Export Report: {r['account']}</h2>
        <table class="report-table">
            <tr><td>Started</td><td>{r['started_at']}</td></tr>
            <tr><td>Finished</td><td>{r['finished_at']}</td></tr>
            <tr><td>Format</td><td>{r['format']}</td></tr>
            <tr><td>Target Path</td><td>{r['target']}</td></tr>
            <tr><td>Total Mails Found</td><td>{r['total_mails']}</td></tr>
            <tr><td>Exported Mails</td><td>{r['exported_mails']}</td></tr>
            <tr><td>Errors</td><td class="{'error' if r['errors'] > 0 else ''}">{r['errors']}</td></tr>
        </table>
        """

    # ------------------------------------------------------------------
    # Custom report
    # ------------------------------------------------------------------

    def generate_custom_metadata_report(self, criteria: Dict[str, Any],
                                       stats: Dict[str, Any],
                                       output_format: str = "both") -> Path:
        """Generate a custom metadata analysis report."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        base_name = f"custom_report_{timestamp}"

        report_data = {
            "type": "custom",
            "timestamp": datetime.utcnow().isoformat(),
            "account_label": criteria.get("filtre_tipi", "Özel Rapor"),
            "criteria": criteria,
            "stats": stats
        }

        # Add metric counts directly for the table listing
        report_data["total_mails"] = stats.get("total_mails", 0)
        report_data["total_size_bytes"] = stats.get("total_size_bytes", 0)
        report_data["errors"] = 0 # No operation failures, it's a stats query

        if output_format in ("json", "both"):
            json_path = self._report_dir / f"{base_name}.json"
            self._write_json(json_path, report_data)

        if output_format in ("html", "both"):
            html_path = self._report_dir / f"{base_name}.html"
            self._write_html(html_path, "Özel Analiz Raporu",
                             report_data,
                             self._custom_report_html_template(criteria, stats))

        return self._report_dir / f"{base_name}.json"

    def _custom_report_html_template(self, criteria: Dict[str, Any], stats: Dict[str, Any]) -> str:
        # Format size
        total_size = stats.get("total_size_bytes", 0)
        formatted_size = _format_bytes(total_size)
        
        # Build criteria description
        crit_desc = ""
        for k, v in criteria.items():
            if v:
                crit_desc += f"<li><b>{k.replace('_', ' ').title()}:</b> {v}</li>"
        if not crit_desc:
            crit_desc = "<li>Tüm Veriler</li>"

        # Folder list HTML
        folder_rows_html = ""
        folders = stats.get("folders", {})
        for fold, cnt in sorted(folders.items(), key=lambda x: x[1], reverse=True):
            folder_rows_html += f"<tr><td>{fold}</td><td>{cnt}</td></tr>"

        # Senders list HTML
        sender_rows_html = ""
        senders = stats.get("top_senders", {})
        for send, cnt in sorted(senders.items(), key=lambda x: x[1], reverse=True):
            sender_rows_html += f"<tr><td>{send}</td><td>{cnt}</td></tr>"

        return f"""
        <h2>Özel Analiz Raporu</h2>
        <div style="background-color:#f8fafc; padding:12px; border-radius:6px; border:1px solid #cbd5e1; margin-bottom:20px;">
            <h4 style="margin:0 0 6px 0; color:#475569;">Arama Kriterleri:</h4>
            <ul style="margin:0; padding-left:20px; font-size:13px; color:#334155;">
                {crit_desc}
            </ul>
        </div>
        
        <h3>Özet İstatistikler</h3>
        <table class="report-table">
            <tr><td>E-Posta Sayısı</td><td>{stats.get('total_mails', 0)}</td></tr>
            <tr><td>Toplam Veri Boyutu</td><td>{formatted_size}</td></tr>
            <tr><td>Ekli E-Posta Sayısı</td><td>{stats.get('has_attachments', 0)}</td></tr>
        </table>
        
        <div style="margin-top:20px; display: flex; gap: 20px;">
            <div style="flex: 1;">
                <h3>Klasör Dağılımı</h3>
                <table class="report-table" style="font-size: 13px;">
                    <thead>
                        <tr style="background-color:#f1f5f9; font-weight:bold;">
                            <td style="padding:6px; font-weight:bold; color:#475569;">Klasör Adı</td>
                            <td style="padding:6px; font-weight:bold; color:#475569; width:100px;">İleti Sayısı</td>
                        </tr>
                    </thead>
                    <tbody>
                        {folder_rows_html if folder_rows_html else '<tr><td colspan="2" style="padding:6px;">Klasör bulunamadı</td></tr>'}
                    </tbody>
                </table>
            </div>
            
            <div style="flex: 1;">
                <h3>En Çok Gönderenler (İlk 10)</h3>
                <table class="report-table" style="font-size: 13px;">
                    <thead>
                        <tr style="background-color:#f1f5f9; font-weight:bold;">
                            <td style="padding:6px; font-weight:bold; color:#475569;">Gönderen Adresi</td>
                            <td style="padding:6px; font-weight:bold; color:#475569; width:100px;">İleti Sayısı</td>
                        </tr>
                    </thead>
                    <tbody>
                        {sender_rows_html if sender_rows_html else '<tr><td colspan="2" style="padding:6px;">İleti bulunamadı</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
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

    # ------------------------------------------------------------------
    # Multi-format exports (PDF, CSV, Excel, Word)
    # ------------------------------------------------------------------

    def export_pdf(self, html_content: str, output_path: Path) -> bool:
        """Export HTML report content to PDF file using PySide6 native QPdfWriter."""
        try:
            from PySide6.QtGui import QTextDocument, QPdfWriter, QPageSize
            from PySide6.QtWidgets import QApplication
            import sys

            if not QApplication.instance():
                _app = QApplication(sys.argv)

            doc = QTextDocument()
            doc.setHtml(html_content)
            writer = QPdfWriter(str(output_path))
            writer.setPageSize(QPageSize(QPageSize.A4))
            doc.print_(writer)
            logger.info("Exported PDF report to %s", output_path)
            return True
        except Exception as exc:
            logger.exception("Failed to export PDF report: %s", exc)
            return False

    def export_csv(self, report_data: Dict[str, Any], output_path: Path) -> bool:
        """Export report dictionary structure to CSV file."""
        import csv
        try:
            with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["Anahtar / Metrik", "Değer"])
                
                # Top-level keys
                for k, v in report_data.items():
                    if isinstance(v, (dict, list)):
                        continue
                    writer.writerow([str(k).replace("_", " ").title(), str(v)])
                
                # Nested stats if present
                stats = report_data.get("stats", {})
                if isinstance(stats, dict):
                    writer.writerow([])
                    writer.writerow(["--- Analiz İstatistikleri ---", ""])
                    for k, v in stats.items():
                        if isinstance(v, (dict, list)):
                            continue
                        writer.writerow([str(k).replace("_", " ").title(), str(v)])
                    
                    folders = stats.get("folders", {})
                    if isinstance(folders, dict):
                        writer.writerow([])
                        writer.writerow(["--- Klasör Dağılımı ---", "İleti Sayısı"])
                        for fold, cnt in folders.items():
                            writer.writerow([fold, cnt])
            logger.info("Exported CSV report to %s", output_path)
            return True
        except Exception as exc:
            logger.exception("Failed to export CSV report: %s", exc)
            return False

    def export_excel(self, report_data: Dict[str, Any], output_path: Path) -> bool:
        """Export report data to Excel-compatible CSV file with UTF-8 BOM."""
        # Using UTF-8-SIG CSV for native Excel opening compatibility
        return self.export_csv(report_data, output_path)

    def export_word(self, html_content: str, output_path: Path) -> bool:
        """Export HTML report content as Word-compatible HTML / DOC file."""
        try:
            word_html = f"""<!DOCTYPE html>
<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'>
<head>
<meta charset='utf-8'>
<title>Report</title>
<!--[if gte mso 9]>
<xml>
 <w:WordDocument>
  <w:View>Print</w:View>
  <w:Zoom>100</w:Zoom>
 </w:WordDocument>
</xml>
<![endif]-->
<style>
body {{ font-family: Calibri, 'Segoe UI', sans-serif; font-size: 11pt; color: #1e293b; padding: 20px; }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
td, th {{ border: 1px solid #cbd5e1; padding: 8px 12px; font-size: 10pt; }}
th {{ background-color: #f1f5f9; font-weight: bold; text-align: left; }}
h2 {{ color: #1e40af; border-bottom: 2px solid #2563eb; padding-bottom: 6px; }}
h3 {{ color: #3b82f6; margin-top: 18px; }}
</style>
</head>
<body>
{html_content}
</body>
</html>"""
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(word_html)
            logger.info("Exported Word report to %s", output_path)
            return True
        except Exception as exc:
            logger.exception("Failed to export Word report: %s", exc)
            return False

