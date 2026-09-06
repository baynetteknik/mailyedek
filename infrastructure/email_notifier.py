"""
email_notifier.py — SMTP email notification service for backup status and alert reports.

Clean Architecture — Infrastructure Layer.
Sends rich HTML and plain-text email summaries for:
  - Backup completion success
  - Backup critical error or disk-full failure
  - SMTP connection testing
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EmailNotifier:
    """SMTP Notification client."""

    @staticmethod
    def send_test_email(
        host: str,
        port: int,
        use_tls: bool,
        username: str,
        password: str,
        from_addr: str,
        to_addr: str,
    ) -> Tuple[bool, str]:
        """Send a test email to verify SMTP credentials and network connectivity."""
        if not host:
            return False, "SMTP sunucu adresi belirtilmedi."
        if not to_addr:
            return False, "Alıcı e-posta adresi belirtilmedi."

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🧪 Mail & Yedekleme Sistemi — SMTP Bağlantı Testi"
        msg["From"] = from_addr or username or "backup-system@localhost"
        msg["To"] = to_addr

        text_body = f"""
Mail Archive & Kurumsal Yedekleme Sistemi
---------------------------------------
SMTP E-Posta Bildirim Testi Başarılı!

Sunucu: {host}:{port}
Tarih : {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
        """.strip()

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #f8fafc; padding: 20px; color: #1e293b;">
            <div style="max-width: 550px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden;">
                <div style="background-color: #2563eb; color: #ffffff; padding: 18px 24px;">
                    <h2 style="margin: 0; font-size: 18px;">✅ SMTP Bağlantı Testi Başarılı</h2>
                </div>
                <div style="padding: 24px;">
                    <p>Tebrikler! Yedekleme sistemi e-posta bildirim yapılandırmanız başarıyla doğrulandı.</p>
                    <table style="width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 13px;">
                        <tr><td style="padding: 6px 0; color: #64748b;">SMTP Sunucu:</td><td style="font-weight: bold;">{host}:{port}</td></tr>
                        <tr><td style="padding: 6px 0; color: #64748b;">Gönderici:</td><td style="font-weight: bold;">{msg['From']}</td></tr>
                        <tr><td style="padding: 6px 0; color: #64748b;">Tarih/Saat:</td><td style="font-weight: bold;">{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</td></tr>
                    </table>
                </div>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            if port == 465:
                server = smtplib.SMTP_SSL(host, port, timeout=15)
            else:
                server = smtplib.SMTP(host, port, timeout=15)
                if use_tls:
                    server.starttls()

            if username and password:
                server.login(username, password)

            server.sendmail(msg["From"], [to_addr], msg.as_string())
            server.quit()
            return True, "Test e-postası başarıyla gönderildi."
        except Exception as exc:
            logger.exception("Failed to send test email: %s", exc)
            return False, f"SMTP Hatası: {str(exc)}"

    def format_report_html(
        self, job_type: str, job_name: str, status: str, report_dict: Dict[str, Any]
    ) -> str:
        """Format HTML backup report body."""
        is_success = (status.upper() == "SUCCESS")
        status_text = "BAŞARILI" if is_success else "BAŞARISIZ (HATA)"
        badge_color = "#16a34a" if is_success else "#dc2626"
        icon = "✅" if is_success else "❌"

        total_bytes = report_dict.get("total_bytes", 0)
        size_mb = total_bytes / (1024 * 1024)
        size_str = f"{size_mb:.2f} MB" if size_mb < 1024 else f"{size_mb / 1024:.2f} GB"
        duration = report_dict.get("duration_seconds", 0)
        duration_sec = round(float(duration or 0), 1)
        output_file = report_dict.get("output_file") or report_dict.get("dest_file") or "Belirtilmedi"
        errors = report_dict.get("errors", [])
        error_html = ""
        if errors:
            error_html = f"""
            <div style="margin-top: 15px; padding: 12px; background-color: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; color: #991b1b;">
                <strong>Hata Detayları:</strong><br/>
                {'<br/>'.join(errors)}
            </div>
            """

        sha_hash = report_dict.get("sha256_hash")
        sha_html = f"<tr><td style='padding: 6px 0; color: #64748b;'>SHA-256 Hash:</td><td style='font-family: monospace; font-size: 11px;'>{sha_hash}</td></tr>" if sha_hash else ""

        return f"""
        <html>
        <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #f1f5f9; padding: 24px; color: #1e293b;">
            <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 10px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);">
                <div style="background-color: {badge_color}; color: #ffffff; padding: 20px 24px;">
                    <span style="font-size: 12px; text-transform: uppercase; letter-spacing: 1px; opacity: 0.9;">Yedekleme Raporu</span>
                    <h2 style="margin: 6px 0 0 0; font-size: 20px;">{icon} {job_name} ({job_type.upper()})</h2>
                </div>
                <div style="padding: 24px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                        <tr><td style="padding: 6px 0; color: #64748b;">Durum:</td><td><strong style="color: {badge_color};">{status_text}</strong></td></tr>
                        <tr><td style="padding: 6px 0; color: #64748b;">Yedek Türü:</td><td><strong>{job_type.upper()}</strong></td></tr>
                        <tr><td style="padding: 6px 0; color: #64748b;">Hedef Dosya:</td><td style="word-break: break-all;">{output_file}</td></tr>
                        <tr><td style="padding: 6px 0; color: #64748b;">Toplam Boyut:</td><td><strong>{size_str}</strong></td></tr>
                        <tr><td style="padding: 6px 0; color: #64748b;">İşlem Süresi:</td><td>{duration_sec} saniye</td></tr>
                        <tr><td style="padding: 6px 0; color: #64748b;">Tamamlanma Zamanı:</td><td>{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</td></tr>
                        {sha_html}
                    </table>
                    {error_html}
                    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;" />
                    <p style="font-size: 11px; color: #94a3b8; margin: 0;">Bu bildirim Mail Archive & Kurumsal Yedekleme Sistemi tarafından otomatik olarak oluşturulmuştur.</p>
                </div>
            </div>
        </body>
        </html>
        """

    def test_connection(self, config: Any, recipient: str) -> Tuple[bool, str]:
        """Test SMTP connection with given configuration."""
        host = getattr(config, "host", "") or getattr(config, "smtp_host", "")
        port = getattr(config, "port", 587) or getattr(config, "smtp_port", 587)
        use_tls = getattr(config, "use_tls", True)
        username = getattr(config, "username", "") or getattr(config, "smtp_user", "")
        password = getattr(config, "password", "") or getattr(config, "smtp_pass_enc", "")
        from_addr = getattr(config, "from_address", "") or getattr(config, "smtp_from", "") or username
        return self.send_test_email(host, port, use_tls, username, password, from_addr, recipient)

    def send_report(
        self, config: Any, job_type: str, job_name: str, report_dict: Dict[str, Any], is_success: bool
    ) -> Tuple[bool, str]:
        """Send backup report according to configuration."""
        host = getattr(config, "host", "") or getattr(config, "smtp_host", "")
        port = getattr(config, "port", 587) or getattr(config, "smtp_port", 587)
        use_tls = getattr(config, "use_tls", True)
        username = getattr(config, "username", "") or getattr(config, "smtp_user", "")
        password = getattr(config, "password", "") or getattr(config, "smtp_pass_enc", "")
        from_addr = getattr(config, "from_address", "") or getattr(config, "smtp_from", "") or username
        to_addrs = getattr(config, "to_addresses", [])
        if isinstance(to_addrs, list):
            to_addrs_str = ", ".join(to_addrs)
        else:
            to_addrs_str = str(to_addrs)
        return self.send_backup_notification(
            host, port, use_tls, username, password, from_addr, to_addrs_str,
            job_type, job_name, report_dict, is_success
        )

    def send_backup_notification(
        self,
        host: str,
        port: int,
        use_tls: bool,
        username: str,
        password: str,
        from_addr: str,
        to_addrs_str: str,
        job_type: str,
        job_name: str,
        report_dict: Dict[str, Any],
        is_success: bool,
    ) -> Tuple[bool, str]:
        """Send automated HTML backup report to administrators."""
        if not host or not to_addrs_str:
            return False, "SMTP sunucusu veya alıcı e-posta listesi yapılandırılmamış."

        recipients = [e.strip() for e in to_addrs_str.split(",") if e.strip()]
        if not recipients:
            return False, "Geçerli alıcı bulunamadı."

        status_text = "BAŞARILI" if is_success else "BAŞARISIZ (HATA)"
        icon = "✅" if is_success else "❌"
        subject = f"{icon} [{job_type.upper()}] Yedekleme {status_text} — {job_name}"

        html_body = self.format_report_html(job_type, job_name, "SUCCESS" if is_success else "FAILED", report_dict)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr or username or "backup-system@localhost"
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(f"Yedekleme: {job_name} ({job_type.upper()}) - Durum: {status_text}", "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            if port == 465:
                server = smtplib.SMTP_SSL(host, port, timeout=20)
            else:
                server = smtplib.SMTP(host, port, timeout=20)
                if use_tls:
                    server.starttls()

            if username and password:
                server.login(username, password)

            server.sendmail(msg["From"], recipients, msg.as_string())
            server.quit()
            logger.info("Backup notification email dispatched to: %s", recipients)
            return True, "E-posta bildirimi gönderildi."
        except Exception as exc:
            logger.error("Failed to send backup notification email: %s", exc)
            return False, f"Bildirim gönderilemedi: {exc}"
