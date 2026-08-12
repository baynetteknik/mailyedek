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
    def __init__(self, db, audit_repo=None):
        self._db = db
        self._audit_repo = audit_repo

    def export_mails(self, account_id: int, format_type: str, output_path: Optional[Path] = None,
                     folders: Optional[List[str]] = None,
                     since_date: Optional[str] = None,
                     before_date: Optional[str] = None,
                     progress_callback = None,
                     imap_host: Optional[str] = None,
                     imap_port: Optional[int] = None,
                     imap_ssl: bool = True,
                     imap_username: Optional[str] = None,
                     imap_password: Optional[str] = None,
                     server_host: Optional[str] = None) -> Dict[str, Any]:
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

        if server_host and server_host.strip():
            conditions.append("(m.server_host = ? OR m.server_host IS NULL OR m.server_host = '')")
            params.append(server_host.strip())

        where_clause = " AND ".join(conditions)

        try:
            with self._db.get_conn() as conn:
                meta_rows = conn.execute(
                    f"""SELECT m.id, m.uid, m.folder, m.subject, m.sender, m.date, m.message_id
                        FROM mail_metadata m
                        WHERE {where_clause}
                        ORDER BY m.date""",
                    params
                ).fetchall()
        except Exception as exc:
            logger.exception("Database query for export metadata failed")
            raise exc

        total = len(meta_rows)

        if progress_callback:
            progress_callback(0, total, {
                "subject": "",
                "sender": "",
                "date": "",
                "folder": "",
                "status": f"Veritabanından {total} mail bulundu, aktarım başlatılıyor..."
            })

        def stream_rows():
            chunk_size = 50
            for i in range(0, total, chunk_size):
                chunk = meta_rows[i:i + chunk_size]
                mail_ids = [r["id"] for r in chunk]
                placeholders = ", ".join("?" for _ in mail_ids)
                blob_map = {}
                try:
                    with self._db.get_conn() as conn:
                        raw_rows = conn.execute(
                            f"SELECT mail_id, raw_data FROM mail_raw WHERE mail_id IN ({placeholders})",
                            mail_ids
                        ).fetchall()
                        blob_map = {r["mail_id"]: r["raw_data"] for r in raw_rows}
                except Exception as b_err:
                    logger.warning("Failed to fetch raw_data chunk: %s", b_err)

                for r in chunk:
                    m_id = r["id"]
                    yield {
                        "id": m_id,
                        "uid": r["uid"],
                        "folder": r["folder"],
                        "subject": r["subject"],
                        "sender": r["sender"],
                        "date": r["date"],
                        "message_id": r["message_id"],
                        "raw_data": blob_map.get(m_id),
                    }

        exported = 0
        skipped_duplicates = 0
        errors = 0

        # Get export subfolder from accounts table
        export_subfolder = ""
        try:
            with self._db.get_conn() as conn:
                row = conn.execute("SELECT export_subfolder FROM accounts WHERE id = ?", (account_id,)).fetchone()
                if row and row["export_subfolder"]:
                    export_subfolder = row["export_subfolder"].strip()
        except Exception as exc:
            logger.warning("Failed to fetch export_subfolder for account %d: %s", account_id, exc)

        # Sanitize export_subfolder to prevent path traversal or bad characters
        if export_subfolder:
            import re
            export_subfolder = re.sub(r'[\\/*?:"<>|]', "", export_subfolder).strip()

        # Helper to sanitize filename
        def sanitize(val: str) -> str:
            import re
            val = val or "no_subject"
            sanitized = re.sub(r'[\\/*?:"<>|]', "", val)
            return sanitized.strip()[:60]

        if format_type == "ZIP":
            if not output_path:
                raise ValueError("Output path is required for ZIP format")
            output_path = Path(output_path)
            if output_path.is_dir() or not output_path.suffix:
                output_path = output_path / f"mails_{account_id}.zip"
            actual_output_path = output_path
            if export_subfolder:
                actual_output_path = output_path.parent / export_subfolder / output_path.name
            actual_output_path.parent.mkdir(parents=True, exist_ok=True)

            if progress_callback:
                progress_callback(0, total, {
                    "subject": "",
                    "sender": "",
                    "date": "",
                    "folder": "",
                    "status": f"ZIP arşivleme başlatılıyor ({total} mail)..."
                })

            with zipfile.ZipFile(actual_output_path, 'w', zipfile.ZIP_DEFLATED) as z:
                for idx, row in enumerate(stream_rows()):
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
                        progress_callback(idx + 1, total, {
                            "subject": row["subject"],
                            "sender": row["sender"],
                            "date": row["date"],
                            "folder": row["folder"],
                            "status": "Dışa Aktarıldı"
                        })

        elif format_type == "DIRECTORY":
            if not output_path:
                raise ValueError("Output path is required for DIRECTORY format")
            output_path = Path(output_path)
            base_dir = output_path / export_subfolder if export_subfolder else output_path
            base_dir.mkdir(parents=True, exist_ok=True)

            if progress_callback:
                progress_callback(0, total, {
                    "subject": "",
                    "sender": "",
                    "date": "",
                    "folder": "",
                    "status": f"Dizine EML aktarımı başlatılıyor ({total} mail)..."
                })

            for idx, row in enumerate(stream_rows()):
                try:
                    raw = row["raw_data"]
                    if raw:
                        folder_dir = base_dir / row["folder"]
                        folder_dir.mkdir(parents=True, exist_ok=True)
                        date_str = (row["date"] or "").replace(":", "-").replace(" ", "_")[:19]
                        subject = sanitize(row["subject"])
                        file_path = folder_dir / f"{date_str}_{row['uid']}_{subject}.eml"
                        if file_path.exists():
                            skipped_duplicates += 1
                            if progress_callback:
                                progress_callback(idx + 1, total, {
                                    "subject": row["subject"],
                                    "sender": row["sender"],
                                    "date": row["date"],
                                    "folder": row["folder"],
                                    "status": "Zaten Mevcut (Atlandı)"
                                })
                            continue
                        file_path.write_bytes(raw)
                        exported += 1
                    else:
                        errors += 1
                except Exception:
                    errors += 1
                if progress_callback:
                    progress_callback(idx + 1, total, {
                        "subject": row["subject"],
                        "sender": row["sender"],
                        "date": row["date"],
                        "folder": row["folder"],
                        "status": "Dışa Aktarıldı"
                    })

        elif format_type == "JSON":
            if not output_path:
                raise ValueError("Output path is required for JSON format")
            output_path = Path(output_path)
            if output_path.is_dir() or not output_path.suffix:
                output_path = output_path / f"mails_{account_id}.json"
            actual_output_path = output_path
            if export_subfolder:
                actual_output_path = output_path.parent / export_subfolder / output_path.name
            actual_output_path.parent.mkdir(parents=True, exist_ok=True)

            if progress_callback:
                progress_callback(0, total, {
                    "subject": "",
                    "sender": "",
                    "date": "",
                    "folder": "",
                    "status": f"JSON aktarımı başlatılıyor ({total} mail)..."
                })

            mails_data = []
            for idx, row in enumerate(stream_rows()):
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
                    progress_callback(idx + 1, total, {
                        "subject": row["subject"],
                        "sender": row["sender"],
                        "date": row["date"],
                        "folder": row["folder"],
                        "status": "Dışa Aktarıldı"
                    })
            actual_output_path.write_text(json.dumps(mails_data, indent=2, ensure_ascii=False), encoding="utf-8")

        elif format_type == "MBOX":
            if not output_path:
                raise ValueError("Output path is required for MBOX format")
            output_path = Path(output_path)
            if output_path.is_dir() or not output_path.suffix:
                output_path = output_path / f"mails_{account_id}.mbox"
            actual_output_path = output_path
            if export_subfolder:
                actual_output_path = output_path.parent / export_subfolder / output_path.name
            actual_output_path.parent.mkdir(parents=True, exist_ok=True)

            if progress_callback:
                progress_callback(0, total, {
                    "subject": "",
                    "sender": "",
                    "date": "",
                    "folder": "",
                    "status": f"MBOX aktarımı başlatılıyor ({total} mail)..."
                })
            
            # If mbox file exists, delete it first to ensure clean start
            if actual_output_path.exists():
                actual_output_path.unlink()
                
            mbox = mailbox.mbox(str(actual_output_path))
            mbox.lock()
            try:
                for idx, row in enumerate(stream_rows()):
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
                        progress_callback(idx + 1, total, {
                            "subject": row["subject"],
                            "sender": row["sender"],
                            "date": row["date"],
                            "folder": row["folder"],
                            "status": "Dışa Aktarıldı"
                        })
                mbox.flush()
            finally:
                mbox.unlock()

        elif format_type == "IMAP_SERVER":
            if not imap_host or not imap_username or not imap_password:
                raise ValueError("IMAP host, username and password are required for Server Export")

            if progress_callback:
                progress_callback(0, total, {
                    "subject": "",
                    "sender": "",
                    "date": "",
                    "folder": "",
                    "status": f"IMAP Sunucusuna aktarım başlatılıyor ({total} mail)..."
                })
            
            if imap_ssl:
                client = imaplib.IMAP4_SSL(imap_host, imap_port or 993)
            else:
                client = imaplib.IMAP4(imap_host, imap_port or 143)
                
            try:
                client.login(imap_username, imap_password)
                
                # Fetch folder list from target server to map local folders to target folders
                from infrastructure.imap_client import encode_imap_utf7, decode_imap_utf7
                import re

                list_re = re.compile(
                    r'\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+(?:"(?P<name_quoted>[^"]*)"|(?P<name_unquoted>[^\s]+))'
                )
                
                folder_map = {}
                folder_map_special = {}
                imap_delim = "/"
                try:
                    status, list_data = client.list()
                    if status == "OK" and list_data:
                        for item in list_data:
                            if not item:
                                continue
                            decoded = item.decode('utf-8', errors='replace')
                            m = list_re.search(decoded)
                            if m:
                                if m.group("delim"):
                                    imap_delim = m.group("delim")
                                flags = m.group("flags") or ""
                                raw_name = m.group("name_quoted") if m.group("name_quoted") is not None else m.group("name_unquoted")
                                if raw_name:
                                    try:
                                        folder_decoded = decode_imap_utf7(raw_name)
                                    except Exception:
                                        folder_decoded = raw_name
                                    
                                    name_lower = folder_decoded.lower()
                                    flags_lower = flags.lower()
                                    
                                    # Map standard names/flags with priority
                                    folder_type = None
                                    is_special_use = False
                                    
                                    # 1. Flag check (highest priority)
                                    if '\\inbox' in flags_lower:
                                        folder_type = 'inbox'
                                        is_special_use = True
                                    elif '\\sent' in flags_lower:
                                        folder_type = 'sent'
                                        is_special_use = True
                                    elif '\\drafts' in flags_lower:
                                        folder_type = 'drafts'
                                        is_special_use = True
                                    elif '\\junk' in flags_lower or '\\spam' in flags_lower:
                                        folder_type = 'spam'
                                        is_special_use = True
                                    elif '\\trash' in flags_lower:
                                        folder_type = 'trash'
                                        is_special_use = True
                                    elif '\\archive' in flags_lower:
                                        folder_type = 'archive'
                                        is_special_use = True
                                        
                                    # 2. Name check (fallback)
                                    if not folder_type:
                                        if name_lower == 'inbox' or name_lower.endswith('.inbox') or name_lower.endswith('/inbox'):
                                            folder_type = 'inbox'
                                        elif any(p in name_lower for p in ('sent', 'gönderilmiş', 'gönderilen')):
                                            folder_type = 'sent'
                                        elif any(p in name_lower for p in ('drafts', 'taslak')):
                                            folder_type = 'drafts'
                                        elif any(p in name_lower for p in ('spam', 'junk', 'istenmeyen', 'önemsiz')):
                                            folder_type = 'spam'
                                        elif any(p in name_lower for p in ('trash', 'çöp', 'silinmiş')):
                                            folder_type = 'trash'
                                        elif any(p in name_lower for p in ('archive', 'arşiv')):
                                            folder_type = 'archive'
                                            
                                    if folder_type:
                                        existing_was_special = folder_map_special.get(folder_type, False)
                                        if is_special_use or folder_type not in folder_map or not existing_was_special:
                                            folder_map[folder_type] = folder_decoded
                                            folder_map_special[folder_type] = is_special_use
                except Exception as list_err:
                    logger.warning("Failed to list target server folders: %s", list_err)

                def format_folder_name(folder_name: str) -> str:
                    enc = encode_imap_utf7(folder_name)
                    if ' ' in enc or '\\' in enc or '/' in enc or '|' in enc:
                        if not (enc.startswith('"') and enc.endswith('"')):
                            return f'"{enc}"'
                    return enc

                current_selected_folder = None

                def reconnect_client():
                    nonlocal client, current_selected_folder
                    logger.info("IMAP disconnected or connection lost. Attempting to reconnect...")
                    try:
                        try:
                            client.logout()
                        except Exception:
                            pass
                        if imap_ssl:
                            new_client = imaplib.IMAP4_SSL(imap_host, imap_port or 993)
                        else:
                            new_client = imaplib.IMAP4(imap_host, imap_port or 143)
                        new_client.login(imap_username, imap_password)
                        client = new_client
                        current_selected_folder = None
                        return True
                    except Exception as rec_err:
                        logger.error("Failed to reconnect IMAP client: %s", rec_err)
                        return False

                created_folders = set()
                for idx, row in enumerate(stream_rows()):
                    try:
                        raw = row["raw_data"]
                        if raw:
                            local_folder = row["folder"]
                            # Map local folder (e.g. 'Spam') to target server folder (e.g. 'İstenmeyen')
                            local_folder_lower = local_folder.lower()
                            folder_type = local_folder_lower
                            
                            # Map Russian/encoded or custom local folder names to standard folder types
                            if 'sent' in local_folder_lower or '_bb4eqgq' in local_folder_lower:
                                folder_type = 'sent'
                            elif 'draft' in local_folder_lower or '_bccenq' in local_folder_lower:
                                folder_type = 'drafts'
                            elif 'spam' in local_folder_lower or 'junk' in local_folder_lower or '_bceepw' in local_folder_lower:
                                folder_type = 'spam'
                            elif 'trash' in local_folder_lower or 'çöp' in local_folder_lower:
                                folder_type = 'trash'
                            elif 'archive' in local_folder_lower or 'arşiv' in local_folder_lower or '_bbaeq' in local_folder_lower:
                                folder_type = 'archive'
                            elif 'inbox' in local_folder_lower:
                                folder_type = 'inbox'
                                
                            target_folder = folder_map.get(folder_type, local_folder)
                            if export_subfolder:
                                target_folder = f"{target_folder}{imap_delim}{export_subfolder}"
                            formatted_folder = format_folder_name(target_folder)
                            
                            if target_folder not in created_folders:
                                for attempt in range(2):
                                    try:
                                        client.create(formatted_folder)
                                        break
                                    except (imaplib.IMAP4.abort, OSError, ConnectionError) as imap_err:
                                        logger.warning("IMAP error during folder creation (attempt %d/2): %s", attempt+1, imap_err)
                                        if attempt == 0:
                                            import time
                                            time.sleep(2)
                                            if not reconnect_client():
                                                break
                                        else:
                                            pass  # Already exists or no permissions
                                    except Exception:
                                        break
                                created_folders.add(target_folder)
                                
                            date_str = row["date"]
                            try:
                                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                                imap_time = imaplib.Time2Internaldate(dt.timestamp())
                            except Exception:
                                imap_time = None

                            # Check duplicate on server
                            is_duplicate_on_server = False
                            message_id = row["message_id"]
                            if message_id:
                                for attempt in range(2):
                                    try:
                                        # Select folder only if it's not already selected
                                        if current_selected_folder != target_folder:
                                            status, select_data = client.select(formatted_folder)
                                            if status == 'OK':
                                                current_selected_folder = target_folder
                                            else:
                                                current_selected_folder = None
                                                
                                        if current_selected_folder == target_folder:
                                            clean_msg_id = message_id.strip()
                                            status, search_data = client.search(None, f'HEADER Message-ID "{clean_msg_id}"')
                                            if status == 'OK' and search_data[0].strip():
                                                is_duplicate_on_server = True
                                        break
                                    except (imaplib.IMAP4.abort, OSError, ConnectionError) as imap_err:
                                        logger.warning("IMAP error during duplicate check (attempt %d/2): %s", attempt+1, imap_err)
                                        current_selected_folder = None
                                        if attempt == 0:
                                            import time
                                            time.sleep(2)
                                            if not reconnect_client():
                                                break
                                        else:
                                            raise
                                    except Exception as other_err:
                                        logger.warning("Other error during duplicate check: %s", other_err)
                                        break

                            if is_duplicate_on_server:
                                skipped_duplicates += 1
                                if progress_callback:
                                    progress_callback(idx + 1, total, {
                                        "subject": row["subject"],
                                        "sender": row["sender"],
                                        "date": row["date"],
                                        "folder": local_folder,
                                        "status": "Zaten Sunucuda Mevcut (Aktarılmadı)"
                                    })
                            else:
                                # Append to server with retry
                                for attempt in range(2):
                                    try:
                                        client.append(formatted_folder, None, imap_time, raw)
                                        exported += 1
                                        if progress_callback:
                                            progress_callback(idx + 1, total, {
                                                "subject": row["subject"],
                                                "sender": row["sender"],
                                                "date": row["date"],
                                                "folder": local_folder,
                                                "status": "Gönderildi"
                                            })
                                        break
                                    except (imaplib.IMAP4.abort, OSError, ConnectionError) as imap_err:
                                        logger.warning("IMAP error during append (attempt %d/2): %s", attempt+1, imap_err)
                                        current_selected_folder = None
                                        if attempt == 0:
                                            import time
                                            time.sleep(2)
                                            if not reconnect_client():
                                                break
                                        else:
                                            raise
                        else:
                            errors += 1
                    except Exception as item_err:
                        logger.exception("Error processing item in export loop: %s", item_err)
                        errors += 1
            finally:
                try:
                    client.logout()
                except Exception:
                    pass

        if self._audit_repo:
            try:
                self._audit_repo.append(
                    f"export.{format_type.lower()}",
                    account_id=account_id,
                    details={
                        "format": format_type,
                        "total": total,
                        "exported": exported,
                        "skipped_duplicates": skipped_duplicates,
                        "errors": errors,
                        "server_host_filter": server_host or "ALL",
                        "target_path": str(output_path) if output_path else imap_host,
                    }
                )
            except Exception as audit_err:
                logger.warning("Failed to record export audit log: %s", audit_err)

        return {
            "total": total,
            "exported": exported,
            "skipped_duplicates": skipped_duplicates,
            "errors": errors
        }
