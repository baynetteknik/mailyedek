"""
imap_client.py — IMAP protocol adapter implementing MailProvider interface.

Clean Architecture — Infrastructure Layer.
Handles all IMAP communication: connect, fetch, search, flags, copy, delete.
"""

import base64
import imaplib
import email
import hashlib
import logging
import re
import time
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

from domain.interfaces import MailProvider
from domain.entities import MailMessage, MailMetadata, Attachment

logger = logging.getLogger(__name__)

CHUNK_SIZE = 65536  # 64 KB chunks for streaming


def encode_imap_utf7(s: str) -> str:
    res = []
    in_b64 = False
    b64_buffer = []

    def flush_b64():
        if b64_buffer:
            b64_str = "".join(b64_buffer)
            utf16 = b64_str.encode('utf-16-be')
            b64_enc = base64.b64encode(utf16).decode('ascii')
            b64_enc = b64_enc.rstrip('=').replace('/', ',')
            res.append('&' + b64_enc + '-')
            b64_buffer.clear()

    for char in s:
        ord_c = ord(char)
        if 0x20 <= ord_c <= 0x7E:
            if char == '&':
                flush_b64()
                res.append('&-')
            else:
                if in_b64:
                    flush_b64()
                    in_b64 = False
                res.append(char)
        else:
            in_b64 = True
            b64_buffer.append(char)

    flush_b64()
    return "".join(res)


def decode_imap_utf7(s: str) -> str:
    res = []
    i = 0
    while i < len(s):
        if s[i] == '&':
            j = s.find('-', i + 1)
            if j == -1:
                res.append(s[i:])
                break
            encoded = s[i+1:j]
            if not encoded:
                res.append('&')
            else:
                b64_str = encoded.replace(',', '/')
                pad_len = (4 - len(b64_str) % 4) % 4
                b64_str += '=' * pad_len
                try:
                    utf16 = base64.b64decode(b64_str)
                    decoded = utf16.decode('utf-16-be')
                    res.append(decoded)
                except Exception:
                    res.append(s[i:j+1])
            i = j + 1
        else:
            res.append(s[i])
            i += 1
    return "".join(res)


# Regex to parse IMAP LIST response: (flags) "delimiter" "name" (supporting quoted and unquoted name)
_LIST_RE = re.compile(
    r'\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+(?:"(?P<name_quoted>[^"]*)"|(?P<name_unquoted>[^\s]+))'
)



class ImapClient(MailProvider):
    """IMAP client implementing the MailProvider interface.

    Features:
      - UID-based operations throughout
      - UIDVALIDITY tracking for delta sync
      - Graceful reconnection with retry
      - Streaming fetch for large messages (>25 MB)
    """

    def __init__(self, log_callback: Optional[Callable] = None, timeout: int = 300):
        self._conn: Optional[imaplib.IMAP4_SSL] = None
        self._host: str = ""
        self._port: int = 993
        self._use_ssl: bool = True
        self._username: str = ""
        self._password: str = ""
        self._current_folder: str = ""
        self._uid_validity: int = 0
        self._log_callback: Optional[Callable] = log_callback
        self._timeout: int = timeout

    def _imap_log(self, msg: str):
        """Log to both logger and optional callback."""
        logger.info(msg)
        if self._log_callback:
            try:
                self._log_callback(msg)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self, host: str, port: int, use_ssl: bool,
                username: str, password: str, timeout: Optional[int] = None) -> bool:
        self._host = host
        self._port = port
        self._use_ssl = use_ssl
        self._username = username
        self._password = password
        if timeout is not None:
            self._timeout = timeout

        try:
            if use_ssl:
                self._conn = imaplib.IMAP4_SSL(host, port, timeout=self._timeout)
            else:
                self._conn = imaplib.IMAP4(host, port, timeout=self._timeout)
                self._conn.starttls()

            self._conn.login(username, password)
            logger.info("Connected to %s:%d as %s", host, port,
                        self._mask_username(username))
            return True

        except (imaplib.IMAP4.error, OSError, ConnectionError) as exc:
            logger.error("IMAP connection failed to %s:%d — %s", host, port, exc)
            self._conn = None
            return False

    def disconnect(self) -> None:
        if self._conn:
            try:
                self._conn.logout()
            except Exception:
                self._conn.shutdown()
            finally:
                self._conn = None
            logger.debug("Disconnected from IMAP server")

    def is_connected(self) -> bool:
        if not self._conn:
            return False
        try:
            self._conn.noop()
            return True
        except Exception:
            return False

    def reconnect(self) -> bool:
        self.disconnect()
        ok = self.connect(self._host, self._port, self._use_ssl,
                          self._username, self._password)
        if ok and self._current_folder:
            logger.info("Re-selecting folder '%s' after reconnect...", self._current_folder)
            try:
                folder = self._current_folder
                encoded_folder = encode_imap_utf7(folder)
                quoted_folder = encoded_folder
                if not (encoded_folder.startswith('"') and encoded_folder.endswith('"')):
                    quoted_folder = f'"{encoded_folder}"'
                self._conn.select(quoted_folder)
            except Exception as e:
                logger.error("Failed to re-select folder '%s' after reconnect: %s", self._current_folder, e)
        return ok

    def _run_with_retry(self, cmd_name: str, *args, **kwargs):
        """Run an IMAP command by name. Reconnect and retry if a socket error occurs."""
        try:
            if not self._conn or not self.is_connected():
                logger.info("IMAP disconnected. Reconnecting before '%s' command...", cmd_name)
                self.reconnect()
            func = getattr(self._conn, cmd_name)
            return func(*args, **kwargs)
        except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError, ConnectionError) as exc:
            logger.warning("IMAP error during '%s' (%s). Reconnecting and retrying...", cmd_name, exc)
            time.sleep(2)
            try:
                if self.reconnect():
                    func = getattr(self._conn, cmd_name)
                    return func(*args, **kwargs)
            except Exception as reconnect_exc:
                logger.error("Failed to reconnect during '%s' retry: %s", cmd_name, reconnect_exc)
            raise

    # ------------------------------------------------------------------
    # Folder operations
    # ------------------------------------------------------------------

    def list_folders(self) -> List[Tuple[str, str]]:
        if not self._conn:
            raise RuntimeError("Not connected")
        result: List[Tuple[str, str]] = []
        try:
            status, data = self._run_with_retry("list")
            logger.info("LIST status=%s, items=%d", status, len(data) if data else 0)
            if status != "OK":
                logger.warning("LIST command failed: %s", status)
                return result
            for item in data:
                if item is None:
                    continue
                decoded = item.decode("utf-8", errors="replace")
                logger.info("LIST raw: %s", decoded)
                m = _LIST_RE.search(decoded)
                if m:
                    delimiter = m.group("delim") or "/"
                    raw_name = m.group("name_quoted") if m.group("name_quoted") is not None else m.group("name_unquoted")
                    if raw_name:
                        name = decode_imap_utf7(raw_name)
                        if name and name.strip() not in ("", delimiter):
                            logger.info("LIST folder: delim='%s' name='%s' (raw='%s')", delimiter, name, raw_name)
                            result.append((delimiter, name))
                else:
                    logger.warning("LIST regex FAILED for line: %s", decoded)

            # Ensure INBOX is always in the list
            if not any(name.upper() == "INBOX" for _, name in result):
                logger.info("LIST did not return INBOX — adding it manually")
                result.insert(0, ("/", "INBOX"))

            logger.info("LIST final folders: %s", [r[1] for r in result])
            return result
        except Exception as exc:
            logger.error("Error listing folders: %s", exc)
            return result

    def select_folder(self, folder: str) -> Tuple[int, int]:
        if not self._conn:
            raise RuntimeError("Not connected")
        try:
            encoded_folder = encode_imap_utf7(folder)
            quoted_folder = encoded_folder
            if not (encoded_folder.startswith('"') and encoded_folder.endswith('"')):
                quoted_folder = f'"{encoded_folder}"'

            select_status, select_data = self._run_with_retry("select", quoted_folder)
            self._imap_log(f"SELECT status={select_status} data={select_data}")

            if select_status != "OK":
                self._imap_log(f"SELECT failed with status {select_status}")
                return 0, 0

            exists = 0
            uid_validity = 0

            # Method 1: EXISTS from select_data[0]
            if select_status == "OK" and select_data and select_data[0] is not None:
                raw = select_data[0]
                if isinstance(raw, bytes):
                    try:
                        exists = int(raw)
                        self._imap_log(f"EXISTS={exists} from SELECT data[0]")
                    except (ValueError, TypeError):
                        parts = raw.decode("utf-8", errors="replace").split()
                        if parts and parts[0].isdigit():
                            exists = int(parts[0])

            # Method 2: UIDVALIDITY from untagged responses (Python 3.14 uses
            # self.untagged_responses instead of the old self.responses dict)
            try:
                uv = self._conn.untagged_responses.get('UIDVALIDITY', [None])[0]
                if uv is not None:
                    uid_validity = int(uv)
                    self._imap_log(f"UIDVALIDITY={uid_validity} from untagged_responses")
            except Exception as uve:
                self._imap_log(f"UIDVALIDITY from untagged_responses failed: {uve}")

            # Method 3: STATUS command for UIDVALIDITY and MESSAGES fallback
            if uid_validity == 0 or (exists == 0 and select_status == "OK"):
                try:
                    self._imap_log(f"Getting STATUS for '{quoted_folder}'...")
                    st, sd = self._run_with_retry("status", quoted_folder, "(MESSAGES UIDVALIDITY)")
                    self._imap_log(f"STATUS result={st} data={sd}")
                    if st == "OK" and sd:
                        for item in sd:
                            if isinstance(item, bytes):
                                decoded = item.decode("utf-8", errors="replace")
                                self._imap_log(f"STATUS raw: {decoded}")
                                m = re.search(r"MESSAGES\s+(\d+)", decoded, re.IGNORECASE)
                                if m and exists == 0:
                                    exists = int(m.group(1))
                                    self._imap_log(f"STATUS MESSAGES={exists}")
                                m = re.search(r"UIDVALIDITY\s+(\d+)", decoded, re.IGNORECASE)
                                if m and uid_validity == 0:
                                    uid_validity = int(m.group(1))
                                    self._imap_log(f"STATUS UIDVALIDITY={uid_validity}")
                except Exception as stat_exc:
                    self._imap_log(f"STATUS error: {stat_exc}")

            self._current_folder = folder
            self._uid_validity = uid_validity
            self._imap_log(f"SELECT final: EXISTS={exists} UIDVALIDITY={uid_validity}")
            return exists, uid_validity
        except Exception as exc:
            self._imap_log(f"SELECT EXCEPTION: {exc}")
            raise

    # ------------------------------------------------------------------
    # UID-based fetch operations
    # ------------------------------------------------------------------

    def _format_imap_date(self, date_str: str) -> str:
        """Convert ISO date 'YYYY-MM-DD' to IMAP search date 'DD-MMM-YYYY'."""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            return f"{dt.day:02d}-{months[dt.month - 1]}-{dt.year}"
        except Exception:
            return date_str

    def fetch_uids(self, folder: str, since_uid: int = 0,
                   since_date: Optional[str] = None,
                   before_date: Optional[str] = None,
                   archive_unread: bool = True) -> List[int]:
        """Fetch UIDs of messages in *folder*, optionally matching search filters."""
        if not self._conn:
            raise RuntimeError("Not connected")
        self.select_folder(folder)
        if self._current_folder != folder:
            logger.warning("Folder selection failed for '%s', aborting UID fetch to prevent querying incorrect folder.", folder)
            return []

        try:
            # Build search criteria list
            criteria = []
            if since_uid > 0:
                criteria.extend(["UID", f"{since_uid + 1}:*"])
            if since_date:
                criteria.extend(["SINCE", self._format_imap_date(since_date)])
            if before_date:
                criteria.extend(["BEFORE", self._format_imap_date(before_date)])
            if not archive_unread:
                criteria.append("SEEN")

            if not criteria:
                criteria = ["ALL"]

            logger.debug("UID SEARCH criteria: %s", criteria)
            status, data = self._run_with_retry("uid", "search", *criteria)
            logger.debug("UID SEARCH status=%s data_len=%d", status, len(data) if data else 0)

            if status != "OK":
                logger.warning("UID SEARCH failed for '%s': %s", folder, status)
                return []

            if data[0] is None or data[0] == b"":
                logger.debug("UID SEARCH returned empty result")
                return []

            raw = data[0]
            logger.debug("UID SEARCH raw result (first 200 chars): %s",
                         raw[:200] if isinstance(raw, bytes) else str(raw)[:200])

            uid_list: List[int] = []
            raw_str = data[0] if isinstance(data[0], bytes) else str(data[0]).encode()
            for part in data[0].split():
                try:
                    uid_list.append(int(part))
                except ValueError:
                    continue
            logger.info("UID SEARCH for '%s': %d UIDs found (range [%d..%d], "
                        "raw_preview=%s)",
                        folder, len(uid_list),
                        min(uid_list) if uid_list else 0,
                        max(uid_list) if uid_list else 0,
                        raw_str[:100] if raw_str else b'')
            return uid_list

        except Exception as exc:
            logger.error("Error fetching UIDs from '%s': %s", folder, exc)
            return []

    def fetch_message(self, uid: int) -> Optional[MailMessage]:
        """Fetch a single message by UID and return a MailMessage domain object."""
        if not self._conn:
            raise RuntimeError("Not connected")

        try:
            status, data = self._run_with_retry("uid", "fetch", str(uid), "(RFC822 FLAGS INTERNALDATE)")
            if status != "OK" or not data or data[0] is None:
                logger.warning("UID FETCH %d failed: status=%s, data_len=%d",
                               uid, status, len(data) if data else 0)
                return None

            raw_email = data[0][1]
            flags_data = data[0][0]
            logger.debug("UID FETCH %d: %d bytes, flags=%s",
                         uid, len(raw_email), flags_data[:100] if flags_data else '')

            msg_parsed = email.message_from_bytes(raw_email)
            metadata = self._parse_metadata(uid, msg_parsed, raw_email, flags_data)

            message = MailMessage(metadata=metadata, raw_content=raw_email)

            # Parse body parts
            body_text, body_html = self._extract_bodies(msg_parsed)
            message.body_text = body_text
            message.body_html = body_html

            # Extract attachments
            attachments = self._extract_attachments(msg_parsed)
            message.attachments = attachments
            if attachments:
                metadata.has_attachments = True

            return message

        except Exception as exc:
            logger.error("Error fetching UID %d: %s", uid, exc)
            return None

    def fetch_message_stream(self, uid: int) -> Generator[bytes, None, None]:
        """Stream a large message by UID to avoid loading it entirely in RAM.

        TODO: Implement chunked FETCH for messages > 25 MB.
        """
        raise NotImplementedError("Streaming fetch is not yet implemented.")

    def fetch_flags(self, uid: int) -> str:
        if not self._conn:
            raise RuntimeError("Not connected")
        try:
            status, data = self._run_with_retry("uid", "fetch", str(uid), "(FLAGS)")
            if status != "OK" or not data or data[0] is None:
                return ""
            raw = data[0].decode("utf-8", errors="replace")
            # Extract flags from e.g. *(FLAGS (\\Seen \\Flagged))
            if "FLAGS" in raw:
                start = raw.index("FLAGS") + 6
                end = raw.index(")", start) if ")" in raw[start:] else len(raw)
                return raw[start:end].strip("() ")
            return ""
        except Exception as exc:
            logger.error("Error fetching flags for UID %d: %s", uid, exc)
            return ""

    def store_flags(self, uid: int, flags: str) -> None:
        """Set flags on a message by UID."""
        if not self._conn:
            raise RuntimeError("Not connected")
        try:
            flag_list = flags.replace(",", " ").split()
            flag_str = " ".join(f"\\{f}" if not f.startswith("\\") else f for f in flag_list)
            self._run_with_retry("uid", "store", str(uid), "FLAGS", f"({flag_str})")
        except Exception as exc:
            logger.error("Error setting flags for UID %d: %s", uid, exc)

    # ------------------------------------------------------------------
    # Message operations
    # ------------------------------------------------------------------

    def copy_message(self, uid: int, target_folder: str) -> bool:
        if not self._conn:
            raise RuntimeError("Not connected")
        try:
            encoded = encode_imap_utf7(target_folder)
            quoted = encoded
            if not (encoded.startswith('"') and encoded.endswith('"')):
                quoted = f'"{encoded}"'
            status, _ = self._run_with_retry("uid", "copy", str(uid), quoted)
            return status == "OK"
        except Exception as exc:
            logger.error("Error copying UID %d to '%s': %s", uid, target_folder, exc)
            return False

    def delete_message(self, uid: int) -> bool:
        if not self._conn:
            raise RuntimeError("Not connected")
        try:
            self._run_with_retry("uid", "store", str(uid), "+FLAGS", "(\\Deleted)")
            return True
        except Exception as exc:
            logger.error("Error marking UID %d as deleted: %s", uid, exc)
            return False

    def append_message(self, folder: str, raw_message: bytes,
                       flags: Optional[str] = None) -> bool:
        if not self._conn:
            raise RuntimeError("Not connected")
        try:
            encoded = encode_imap_utf7(folder)
            quoted = encoded
            if not (encoded.startswith('"') and encoded.endswith('"')):
                quoted = f'"{encoded}"'
            flag_str = f"({flags})" if flags else None
            status, _ = self._run_with_retry("append", quoted, flag_str, None, raw_message)
            return status == "OK"
        except Exception as exc:
            logger.error("Error appending to '%s': %s", folder, exc)
            return False

    def search_messages(self, criteria: str) -> List[int]:
        """Search messages by IMAP search criteria. Returns UID list."""
        if not self._conn:
            raise RuntimeError("Not connected")
        try:
            # Split criteria string into separate args to prevent imaplib
            # from double-quoting the entire criteria
            criteria_parts = criteria.split()
            status, data = self._run_with_retry("uid", "search", *criteria_parts)
            if status != "OK" or not data or data[0] is None:
                return []
            return [int(x) for x in data[0].split() if x]
        except Exception as exc:
            logger.error("Error searching: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Quota
    # ------------------------------------------------------------------

    def get_folder_quota(self, folder: str) -> Tuple[int, int]:
        """Return (used_bytes, quota_bytes)."""
        if not self._conn:
            raise RuntimeError("Not connected")
        try:
            encoded = encode_imap_utf7(folder)
            quoted = encoded
            if not (encoded.startswith('"') and encoded.endswith('"')):
                quoted = f'"{encoded}"'
            status, data = self._run_with_retry("getquotaroot", quoted)
            if status != "OK":
                return 0, 0
            for item in data:
                if isinstance(item, bytes) and b"STORAGE" in item:
                    parts = item.decode().split()
                    if len(parts) >= 3:
                        return int(parts[1]), int(parts[2])
            return 0, 0
        except Exception:
            return 0, 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_metadata(self, uid: int, msg: email.message.Message,
                        raw_bytes: bytes, flags_data: bytes) -> MailMetadata:
        """Extract metadata from a parsed email message."""
        subject = self._decode_header_value(msg.get("Subject", ""))
        sender = self._decode_header_value(msg.get("From", ""))
        recipients = self._decode_header_value(msg.get("To", ""))
        cc = self._decode_header_value(msg.get("Cc", ""))
        bcc = self._decode_header_value(msg.get("Bcc", ""))
        message_id = msg.get("Message-ID", "")
        date_str = msg.get("Date", "")

        internal_date = datetime.utcnow().isoformat()

        # Parse flags from response
        flags_str = ""
        try:
            raw = flags_data.decode("utf-8", errors="replace")
            if "FLAGS" in raw:
                start = raw.index("FLAGS") + 6
                end = raw.index(")", start) if ")" in raw[start:] else len(raw)
                flags_str = raw[start:end].strip("() ")
        except Exception:
            pass

        return MailMetadata(
            uid=uid,
            folder=self._current_folder,
            message_id=message_id,
            subject=subject,
            sender=sender,
            recipients=recipients,
            cc=cc,
            bcc=bcc,
            date=date_str,
            internal_date=internal_date,
            flags=flags_str,
            size_bytes=len(raw_bytes),
        )

    def _extract_bodies(self, msg: email.message.Message) -> Tuple[Optional[str], Optional[str]]:
        """Extract plain-text and HTML bodies from a message."""
        text = None
        html = None

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain" and text is None:
                    text = self._decode_payload(part)
                elif content_type == "text/html" and html is None:
                    html = self._decode_payload(part)
        else:
            content_type = msg.get_content_type()
            if content_type == "text/plain":
                text = self._decode_payload(msg)
            elif content_type == "text/html":
                html = self._decode_payload(msg)

        return text, html

    def _extract_attachments(self, msg: email.message.Message) -> List[Attachment]:
        """Extract attachment metadata from a message."""
        attachments: List[Attachment] = []
        if not msg.is_multipart():
            return attachments

        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get("Content-Disposition") is None:
                continue
            filename = part.get_filename()
            if not filename:
                continue

            filename = self._decode_header_value(filename)
            payload = part.get_payload(decode=True)
            if payload is None:
                continue

            sha256_hash = hashlib.sha256(payload).hexdigest()

            attachments.append(Attachment(
                filename=filename,
                mime_type=part.get_content_type(),
                size_bytes=len(payload),
                sha256_hash=sha256_hash,
                data=payload,
            ))

        return attachments

    @staticmethod
    def _decode_header_value(value: str) -> str:
        """Decode RFC 2047 encoded header values."""
        if not value:
            return ""
        decoded_parts = []
        for part, enc in decode_header(value):
            if isinstance(part, bytes):
                try:
                    decoded_parts.append(part.decode(enc or "utf-8", errors="replace"))
                except (LookupError, UnicodeDecodeError):
                    decoded_parts.append(part.decode("utf-8", errors="replace"))
            else:
                decoded_parts.append(part)
        return " ".join(decoded_parts)

    @staticmethod
    def _decode_payload(part: email.message.Message) -> Optional[str]:
        """Decode the payload of a message part."""
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                return None
            charset = part.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
        except Exception:
            return None

    @staticmethod
    def _mask_username(username: str) -> str:
        if "@" in username:
            local, domain = username.split("@", 1)
            return f"{local[:2]}***@{domain}"
        return username[:2] + "***"
