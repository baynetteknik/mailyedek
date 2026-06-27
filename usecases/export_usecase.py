"""
export_usecase.py — Email export use case.

Coordinates exporting raw emails and metadata from local database.
Supports ZIP of EMLs, Directory of EMLs, JSON, MBOX, and IMAP Server pushing.
"""

import json
import zipfile
import logging
import mailbox
import imaplib
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class ExportUseCase:
    def __init__(self, db):
        self._db = db

    def export_mails(self, account_id: int, format_type: str, output_path: Optional[Path] = None,
                     folders: Optional[List[str]] = None,
                     since_date: Optional[str] = None,
                     before_date: Optional[str] = None,
                     progress_callback = None,
                     imap_host: Optional[str] = None,
                     imap_port: Optional[int] = None,
                     imap_ssl: bool = True,
                     imap_username: Optional[str] = None,
                     imap_password: Optional[str] = None) -> Dict[str, Any]:
        """Export emails to the chosen format (ZIP, DIRECTORY, JSON, MBOX, IMAP_SERVER)."""
        # Formulate query conditions
        conditions = ["m.account_id = ?", "m.is_deleted = 0"]
        params = [account_id]
        
        if folders:
            placeholders = ", ".join("?" for _ in folders)
            conditions.append(f"m.folder IN ({placeholders})")
            params.extend(folders)
            
        if since_date:
            conditions.append("m.date >= ?")
            params.append(since_date)
            
        if before_date:
            conditions.append("m.date <= ?")
            params.append(before_date)

        where_clause = " AND ".join(conditions)

        try:
            with self._db.get_conn() as conn:
                rows = conn.execute(
                    f"""SELECT m.id, m.uid, m.folder, m.subject, m.sender, m.date, r.raw_data
                        FROM mail_metadata m
                        LEFT JOIN mail_raw r ON r.mail_id = m.id
                        WHERE {where_clause}
                        ORDER BY m.date""",
                    params
                ).fetchall()
        except Exception as exc:
            logger.exception("Database query for export failed")
            raise exc

        total = len(rows)
        exported = 0
        errors = 0

        # Helper to sanitize filename
        def sanitize(val: str) -> str:
            import re
            val = val or "no_subject"
            sanitized = re.sub(r'[\\/*?:"<>|]', "", val)
            return sanitized.strip()[:60]

        if format_type == "ZIP":
            if not output_path:
                raise ValueError("Output path is required for ZIP format")
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as z:
                for idx, row in enumerate(rows):
                    try:
                        raw = row["raw_data"]
                        if raw:
                            folder = row["folder"]
                            date_str = (row["date"] or "").replace(":", "-").replace(" ", "_")[:19]
                            subject = sanitize(row["subject"])
                            filename = f"{folder}/{date_str}_{row['uid']}_{subject}.eml"
                            z.writestr(filename, raw)
                            exported += 1
                        else:
                            errors += 1
                    except Exception:
                        errors += 1
                    if progress_callback:
                        progress_callback(idx + 1, total)

        elif format_type == "DIRECTORY":
            if not output_path:
                raise ValueError("Output path is required for DIRECTORY format")
            output_path.mkdir(parents=True, exist_ok=True)
            for idx, row in enumerate(rows):
                try:
                    raw = row["raw_data"]
                    if raw:
                        folder_dir = output_path / row["folder"]
                        folder_dir.mkdir(parents=True, exist_ok=True)
                        date_str = (row["date"] or "").replace(":", "-").replace(" ", "_")[:19]
                        subject = sanitize(row["subject"])
                        file_path = folder_dir / f"{date_str}_{row['uid']}_{subject}.eml"
                        file_path.write_bytes(raw)
                        exported += 1
                    else:
                        errors += 1
                except Exception:
                    errors += 1
                if progress_callback:
                    progress_callback(idx + 1, total)

        elif format_type == "JSON":
            if not output_path:
                raise ValueError("Output path is required for JSON format")
            mails_data = []
            for idx, row in enumerate(rows):
                try:
                    raw = row["raw_data"]
                    body = ""
                    if raw:
                        import email
                        msg = email.message_from_bytes(raw)
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                                        break
                        else:
                            payload = msg.get_payload(decode=True)
                            if payload:
                                body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
                    
                    mails_data.append({
                        "id": row["id"],
                        "uid": row["uid"],
                        "folder": row["folder"],
                        "subject": row["subject"],
                        "sender": row["sender"],
                        "date": row["date"],
                        "body": body
                    })
                    exported += 1
                except Exception:
                    errors += 1
                if progress_callback:
                    progress_callback(idx + 1, total)
            output_path.write_text(json.dumps(mails_data, indent=2, ensure_ascii=False), encoding="utf-8")

        elif format_type == "MBOX":
            if not output_path:
                raise ValueError("Output path is required for MBOX format")
            
            # Ensure folder structure exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # If mbox file exists, delete it first to ensure clean start
            if output_path.exists():
                output_path.unlink()
                
            mbox = mailbox.mbox(str(output_path))
            mbox.lock()
            try:
                for idx, row in enumerate(rows):
                    try:
                        raw = row["raw_data"]
                        if raw:
                            msg = mailbox.mboxMessage(raw)
                            # Set status flags if any
                            mbox.add(msg)
                            exported += 1
                        else:
                            errors += 1
                    except Exception:
                        errors += 1
                    if progress_callback:
                        progress_callback(idx + 1, total)
                mbox.flush()
            finally:
                mbox.unlock()

        elif format_type == "IMAP_SERVER":
            if not imap_host or not imap_username or not imap_password:
                raise ValueError("IMAP host, username and password are required for Server Export")
            
            if imap_ssl:
                client = imaplib.IMAP4_SSL(imap_host, imap_port or 993)
            else:
                client = imaplib.IMAP4(imap_host, imap_port or 143)
                
            try:
                client.login(imap_username, imap_password)
                
                created_folders = set()
                for idx, row in enumerate(rows):
                    try:
                        raw = row["raw_data"]
                        if raw:
                            folder = row["folder"]
                            if folder not in created_folders:
                                try:
                                    client.create(folder)
                                except Exception:
                                    pass  # Already exists or no permissions
                                created_folders.add(folder)
                                
                            date_str = row["date"]
                            try:
                                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                                imap_time = imaplib.Time2Internaldate(dt.timestamp())
                            except Exception:
                                imap_time = None
                                
                            client.append(folder, None, imap_time, raw)
                            exported += 1
                        else:
                            errors += 1
                    except Exception:
                        errors += 1
                    if progress_callback:
                        progress_callback(idx + 1, total)
            finally:
                try:
                    client.logout()
                except Exception:
                    pass

        return {"total": total, "exported": exported, "errors": errors}
