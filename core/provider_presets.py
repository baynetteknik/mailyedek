"""
provider_presets.py — Mail provider IMAP presets and Thunderbird-style autoconfig lookup engine.
"""

import logging
import socket
import ssl
import re
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# Built-in IMAP presets for popular providers
BUILTIN_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "yandex_com",
        "name": "Yandex Mail",
        "host": "imap.yandex.com",
        "port": 993,
        "use_ssl": True,
        "domains": ["yandex.com", "ya.ru", "yandex.ru"]
    },
    {
        "id": "yandex_tr",
        "name": "Yandex Mail TR",
        "host": "imap.yandex.com.tr",
        "port": 993,
        "use_ssl": True,
        "domains": ["yandex.com.tr"]
    },
    {
        "id": "gmail",
        "name": "Google Gmail",
        "host": "imap.gmail.com",
        "port": 993,
        "use_ssl": True,
        "domains": ["gmail.com", "googlemail.com"]
    },
    {
        "id": "office365",
        "name": "Microsoft Office 365 / Outlook",
        "host": "outlook.office365.com",
        "port": 993,
        "use_ssl": True,
        "domains": ["office365.com", "microsoft.com"]
    },
    {
        "id": "hotmail",
        "name": "Hotmail / Live / Outlook.com",
        "host": "imap-mail.outlook.com",
        "port": 993,
        "use_ssl": True,
        "domains": ["outlook.com", "hotmail.com", "live.com", "msn.com", "windowslive.com", "hotmail.com.tr"]
    },
    {
        "id": "yahoo",
        "name": "Yahoo Mail",
        "host": "imap.mail.yahoo.com",
        "port": 993,
        "use_ssl": True,
        "domains": ["yahoo.com", "yahoo.co.uk", "yahoo.com.tr", "ymail.com", "rocketmail.com"]
    },
    {
        "id": "icloud",
        "name": "Apple iCloud Mail",
        "host": "imap.mail.me.com",
        "port": 993,
        "use_ssl": True,
        "domains": ["icloud.com", "me.com", "mac.com"]
    },
    {
        "id": "mailru",
        "name": "Mail.ru",
        "host": "imap.mail.ru",
        "port": 993,
        "use_ssl": True,
        "domains": ["mail.ru", "inbox.ru", "list.ru", "bk.ru"]
    },
    {
        "id": "zoho",
        "name": "Zoho Mail",
        "host": "imap.zoho.com",
        "port": 993,
        "use_ssl": True,
        "domains": ["zoho.com", "zohomail.com"]
    },
    {
        "id": "gmx",
        "name": "GMX Mail",
        "host": "imap.gmx.com",
        "port": 993,
        "use_ssl": True,
        "domains": ["gmx.com", "gmx.net"]
    },
    {
        "id": "fastmail",
        "name": "Fastmail",
        "host": "imap.fastmail.com",
        "port": 993,
        "use_ssl": True,
        "domains": ["fastmail.com", "fm.marl.cx"]
    },
    {
        "id": "proton",
        "name": "ProtonMail Bridge",
        "host": "127.0.0.1",
        "port": 1143,
        "use_ssl": True,
        "domains": ["protonmail.com", "proton.me"]
    }
]


def extract_domain(email_address: str) -> str:
    """Extract domain part from an email address or return input if already a domain."""
    email_clean = email_address.strip().lower()
    if "@" in email_clean:
        return email_clean.split("@")[-1].strip()
    return email_clean


def get_preset_by_domain(domain: str, custom_presets: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """Check built-in and custom presets for a matching domain or host match."""
    dom = domain.strip().lower()
    if not dom:
        return None

    # Check custom presets first
    if custom_presets:
        for preset in custom_presets:
            preset_domains = [d.lower() for d in preset.get("domains", [])]
            if dom in preset_domains:
                return preset

    # Check built-in presets
    for preset in BUILTIN_PRESETS:
        if dom in preset["domains"]:
            return preset

    return None


def fetch_thunderbird_ispdb(domain: str, timeout: float = 2.5) -> Optional[Dict[str, Any]]:
    """Query Thunderbird ISPDB REST service for domain configuration."""
    url = f"https://autoconfig.thunderbird.net/v1.1/{domain}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MailArchiveSystem/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                xml_data = resp.read()
                return _parse_autoconfig_xml(xml_data)
    except Exception as e:
        logger.debug("Thunderbird ISPDB lookup failed for %s: %s", domain, e)
    return None


def fetch_direct_autoconfig(domain: str, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    """Query domain's direct autoconfig XML endpoint."""
    urls = [
        f"https://autoconfig.{domain}/mail/config-v1.1.xml",
        f"http://autoconfig.{domain}/mail/config-v1.1.xml",
        f"https://{domain}/.well-known/autoconfig/mail/config-v1.1.xml"
    ]
    # Create unverified SSL context for self-signed dev certificates if needed
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for url in urls:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MailArchiveSystem/1.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                if resp.status == 200:
                    xml_data = resp.read()
                    parsed = _parse_autoconfig_xml(xml_data)
                    if parsed:
                        return parsed
        except Exception:
            continue
    return None


def _parse_autoconfig_xml(xml_bytes: bytes) -> Optional[Dict[str, Any]]:
    """Extract IMAP hostname, port, and SSL setting from Thunderbird autoconfig XML format."""
    try:
        root = ET.fromstring(xml_bytes)
        for provider in root.findall(".//emailProvider"):
            for incoming in provider.findall("incomingServer"):
                if incoming.get("type", "").lower() == "imap":
                    hostname_elem = incoming.find("hostname")
                    port_elem = incoming.find("port")
                    socket_elem = incoming.find("socketType")

                    if hostname_elem is not None and hostname_elem.text:
                        host = hostname_elem.text.strip()
                        port = int(port_elem.text.strip()) if (port_elem is not None and port_elem.text and port_elem.text.strip().isdigit()) else 993
                        socket_type = socket_elem.text.strip().upper() if (socket_elem is not None and socket_elem.text) else "SSL"
                        use_ssl = socket_type in ("SSL", "SSL/TLS", "TLS", "STARTTLS")

                        return {
                            "name": provider.findtext("displayName") or host,
                            "host": host,
                            "port": port,
                            "use_ssl": use_ssl,
                            "source": "autoconfig_xml"
                        }
    except Exception as e:
        logger.debug("Failed to parse autoconfig XML: %s", e)
    return None


def probe_common_imap_hosts(domain: str, timeout: float = 1.5) -> Optional[Dict[str, Any]]:
    """Probe common host patterns (imap.domain, mail.domain) on IMAP SSL port 993."""
    candidates = [
        f"imap.{domain}",
        f"mail.{domain}",
        f"mail1.{domain}",
        domain
    ]

    for host in candidates:
        try:
            # Try SSL connection
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection((host, 993), timeout=timeout) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    return {
                        "name": f"{domain} (IMAP SSL)",
                        "host": host,
                        "port": 993,
                        "use_ssl": True,
                        "source": "socket_probe"
                    }
        except Exception:
            # Try non-SSL connection on 143
            try:
                with socket.create_connection((host, 143), timeout=timeout) as sock:
                    return {
                        "name": f"{domain} (IMAP)",
                        "host": host,
                        "port": 143,
                        "use_ssl": False,
                        "source": "socket_probe"
                    }
            except Exception:
                continue

    return None


def lookup_autoconfig(email_or_domain: str, custom_presets: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """
    Find best IMAP configuration for an email or domain.
    1. Known built-in or custom presets
    2. Thunderbird ISPDB online REST lookup
    3. Domain autoconfig.xml lookup
    4. Socket probe fallback (imap.domain, mail.domain)
    """
    domain = extract_domain(email_or_domain)
    if not domain:
        return None

    # 1. Preset dictionary
    preset_match = get_preset_by_domain(domain, custom_presets)
    if preset_match:
        return {
            "name": preset_match["name"],
            "host": preset_match["host"],
            "port": preset_match["port"],
            "use_ssl": preset_match["use_ssl"],
            "source": "preset"
        }

    # 2. Thunderbird ISPDB
    ispdb_match = fetch_thunderbird_ispdb(domain)
    if ispdb_match:
        return ispdb_match

    # 3. Direct domain autoconfig XML
    direct_match = fetch_direct_autoconfig(domain)
    if direct_match:
        return direct_match

    # 4. Socket probe
    probe_match = probe_common_imap_hosts(domain)
    if probe_match:
        return probe_match

    return None
