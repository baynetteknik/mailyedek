"""
network_analyzer.py — Background network port listener and connection analyzer.

Monitors active outgoing mail protocol sockets (IMAP, POP3, SMTP, cPanel)
and measures latency, SSL handshakes, and diagnostic logs in real-time.
"""

import time
import socket
import ssl
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)

PROTOCOL_MAP = {
    993: "IMAP (SSL)",
    143: "IMAP (STARTTLS/Plain)",
    995: "POP3 (SSL)",
    110: "POP3 (Plain)",
    465: "SMTP (SSL)",
    587: "SMTP (STARTTLS)",
    2096: "cPanel Webmail (SSL)",
    2083: "cPanel SSL"
}


class PortListenerThread(QThread):
    """Background thread that monitors target ports and tests connectivity/latency."""

    log_signal = Signal(dict)
    stats_signal = Signal(dict)

    def __init__(self, target_hosts: Optional[List[str]] = None,
                 target_ports: Optional[List[int]] = None,
                 interval_sec: int = 5,
                 parent=None):
        super().__init__(parent)
        self.target_hosts = target_hosts or ["srv10.cenuta.email", "mail.ohmteknik.com", "imap.gmail.com"]
        self.target_ports = target_ports or [993, 143, 995, 110, 465, 587, 2096]
        self.interval_sec = max(2, interval_sec)
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        logger.info("PortListenerThread started monitoring ports: %s", self.target_ports)

        while self._running:
            for host in list(self.target_hosts):
                if not self._running:
                    break

                try:
                    ip = socket.gethostbyname(host)
                except Exception as exc:
                    self.log_signal.emit({
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "host": host,
                        "ip": "DNS Error",
                        "port": "-",
                        "protocol": "DNS Resolution",
                        "status": "🔴 DNS Başarısız",
                        "latency_ms": 0,
                        "details": f"DNS çözümlenemedi: {exc}"
                    })
                    continue

                for port in list(self.target_ports):
                    if not self._running:
                        break

                    proto = PROTOCOL_MAP.get(port, f"Port {port}")
                    self._probe_host_port(host, ip, port, proto)

            for _ in range(self.interval_sec * 10):
                if not self._running:
                    break
                time.sleep(0.1)

        logger.info("PortListenerThread stopped.")

    def _probe_host_port(self, host: str, ip: str, port: int, proto: str):
        start_time = time.time()
        now_str = datetime.now().strftime("%H:%M:%S")

        try:
            sock = socket.create_connection((ip, port), timeout=3.0)
            latency_ms = int((time.time() - start_time) * 1000)

            # SSL handshake test if port uses SSL
            ssl_info = ""
            if port in (993, 995, 465, 2096, 2083):
                try:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    ssl_sock = ctx.wrap_socket(sock, server_hostname=host)
                    cipher = ssl_sock.cipher()
                    ssl_info = f" | SSL: {cipher[0]} ({cipher[1]})" if cipher else " | SSL Aktif"
                    ssl_sock.close()
                except Exception as ssl_exc:
                    ssl_info = f" | SSL Hatası: {ssl_exc}"
                    sock.close()
            else:
                sock.close()

            self.log_signal.emit({
                "timestamp": now_str,
                "host": host,
                "ip": ip,
                "port": port,
                "protocol": proto,
                "status": "🟢 Açık / Erişilebilir",
                "latency_ms": latency_ms,
                "details": f"Bağlantı kuruldu ({latency_ms} ms){ssl_info}"
            })

        except socket.timeout:
            self.log_signal.emit({
                "timestamp": now_str,
                "host": host,
                "ip": ip,
                "port": port,
                "protocol": proto,
                "status": "🔴 Zaman Aşımı (Kapalı/Ban)",
                "latency_ms": 0,
                "details": f"Port yanıt vermiyor. Güvenlik duvarı (CSF/Firewall) engeli veya port kapalı."
            })
        except ConnectionRefusedError:
            self.log_signal.emit({
                "timestamp": now_str,
                "host": host,
                "ip": ip,
                "port": port,
                "protocol": proto,
                "status": "🟡 Bağlantı Reddedildi",
                "latency_ms": 0,
                "details": "Sunucu port dinlemiyor veya erişimi reddetti."
            })
        except Exception as exc:
            self.log_signal.emit({
                "timestamp": now_str,
                "host": host,
                "ip": ip,
                "port": port,
                "protocol": proto,
                "status": f"🔴 Hata",
                "latency_ms": 0,
                "details": str(exc)
            })


def diagnose_windows_network(target_host: str = "srv10.cenuta.email", target_port: int = 993) -> Dict[str, Any]:
    """
    Run comprehensive Windows network diagnostics to detect Kaspersky leftover driver blocks,
    Winsock corruption, DNS resolution, and TCP socket connectivity issues.
    """
    import subprocess
    report = {
        "target_host": target_host,
        "target_port": target_port,
        "dns_ip": None,
        "dns_ok": False,
        "tcp_ok": False,
        "tcp_latency": 0,
        "ssl_ok": False,
        "kaspersky_driver_found": False,
        "winsock_status": "Unknown",
        "recommendations": []
    }

    # 1. DNS Resolution
    start = time.time()
    try:
        ip = socket.gethostbyname(target_host)
        report["dns_ip"] = ip
        report["dns_ok"] = True
    except Exception as e:
        report["recommendations"].append(f"🔴 DNS Çözümleme Hatası: {target_host} adresi IP'ye çevrilemedi ({e}). DNS sunucunuzu 8.8.8.8 olarak değiştirmeyi deneyin.")
        return report

    # 2. Direct TCP Socket Connection
    try:
        sock = socket.create_connection((ip, target_port), timeout=5.0)
        report["tcp_latency"] = int((time.time() - start) * 1000)
        report["tcp_ok"] = True
        
        # Test SSL
        if target_port in (993, 995, 465, 2096, 2083):
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                ssl_sock = ctx.wrap_socket(sock, server_hostname=target_host)
                report["ssl_ok"] = True
                ssl_sock.close()
            except Exception as ssl_err:
                report["recommendations"].append(f"🟡 SSL El Sıkışma Hatası: {ssl_err}")
                sock.close()
        else:
            sock.close()
    except socket.timeout:
        report["recommendations"].append(
            "🔴 TCP Zaman Aşımı (Timeout): Sunucuya 5 saniyede erişilemedi. "
            "Kaspersky sonrasında kalan ağ filtresi veya sunucudaki IP ban (CSF Firewall) neden oluyor olabilir."
        )
    except ConnectionRefusedError:
        report["recommendations"].append(f"🟡 Bağlantı Reddedildi: {target_host}:{target_port} üzerinde bağlantı kabul edilmiyor.")
    except Exception as exc:
        report["recommendations"].append(f"🔴 Socket Hatası: {exc}")

    # 3. Check for leftover Kaspersky NDIS / WFP drivers via driverquery
    try:
        cmd_res = subprocess.run(["driverquery", "/FO", "CSV"], capture_output=True, text=True, errors="replace", timeout=5)
        if "klwfp" in cmd_res.stdout.lower() or "kl1" in cmd_res.stdout.lower() or "kaspersky" in cmd_res.stdout.lower():
            report["kaspersky_driver_found"] = True
            report["recommendations"].append(
                "⚠️ KASPERSKY SÜRÜCÜSÜ ALGISI: Kaspersky kaldırılmasına rağmen ağ filtre sürücüsü (klwfp.sys / kl1.sys) "
                "Windows ağ adaptörünüzde hâlâ aktif! Lütfen Kaspersky'nin resmi 'kavremover.exe' aracını çalıştırın veya "
                "ncpa.cpl -> Ağ Bağdaştırıcı Özellikleri menüsünden Kaspersky filtresini kaldırın."
            )
    except Exception:
        pass

    # 4. Add Winsock Reset Recommendation if TCP connection failed
    if not report["tcp_ok"]:
        report["recommendations"].append(
            "💡 ÇÖZÜM ADIMI 1 (Winsock Sıfırlama): Yönetici olarak Komut İstemi (cmd) açıp şu komutları çalıştırın ve bilgisayarı yeniden başlatın:\n"
            "   netsh winsock reset\n"
            "   netsh int ip reset"
        )
        report["recommendations"].append(
            "💡 ÇÖZÜM ADIMI 2 (Mobil Veri Testi): İnternetinizi telefonunuzun mobil erişim noktasına (Hotspot) bağlayarak test edin. "
            "Eğer telefonda bağlanırsa, mevcut sabit internet IP adresiniz Cenuta sunucusunda güvenlik duvarına (CSF Ban) takılmıştır."
        )

    return report

