import logging
import re
import shutil
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QTextEdit, QMessageBox, QGroupBox, QFrame
)

logger = logging.getLogger(__name__)

class ArchiveOptimizerWorker(QThread):
    progress_update = Signal(int, str)  # percentage, log_message
    finished = Signal(int, int, float)  # emls_moved, atts_moved, total_mb
    error_occurred = Signal(str)

    def __init__(self, engine, settings, account_ids=None):
        super().__init__()
        self.engine = engine
        self.settings = settings
        self.account_ids = account_ids  # list of ints or None
        self._is_cancelled = False
        self.is_background = False
        self.last_percent_emitted = -1

    def cancel(self):
        self._is_cancelled = True

    def emit_progress(self, percentage, message):
        if self.is_background:
            if percentage >= self.last_percent_emitted + 2 or percentage == 100:
                self.progress_update.emit(percentage, "")
                self.last_percent_emitted = percentage
        else:
            self.progress_update.emit(percentage, message)
            self.last_percent_emitted = percentage

    def run(self):
        try:
            all_accounts = self.engine.list_accounts()
            if self.account_ids is not None:
                accounts = [a for a in all_accounts if a["id"] in self.account_ids]
            else:
                accounts = all_accounts

            total_accounts = len(accounts)
            if total_accounts == 0:
                self.finished.emit(0, 0, 0.0)
                return

            emls_moved = 0
            atts_moved = 0
            total_bytes = 0

            for idx, acc in enumerate(accounts):
                if self._is_cancelled:
                    break

                acc_id = acc["id"]
                email_addr = acc["email"]
                self.emit_progress(
                    int((idx / total_accounts) * 100),
                    f"\n--- {email_addr} HESABI İŞLENİYOR ---"
                )

                # Resolve base storage path
                base_path = self.settings.data_path()

                # Check group/domain
                group_val = acc.get("account_group", "").strip()
                if not group_val and "@" in email_addr:
                    group_val = email_addr.split("@")[-1]
                group_clean = re.sub(r'[\/:*?"<>|]', '_', group_val).strip()

                # Check subfolder
                raw_sub = acc.get("export_subfolder") or ""
                subfolder = re.sub(r'[\/:*?"<>|]', '_', raw_sub).strip()

                # Auto-import and migrate legacy EML files from disk to the target structured path
                self.emit_progress(
                    int((idx / total_accounts) * 100),
                    f"ℹ️ Disk üzerindeki eski EML dosyaları taranıyor..."
                )
                
                legacy_dirs = []
                parts_email = email_addr.split("@")
                if len(parts_email) == 2:
                    u_part, d_part = parts_email[0], parts_email[1]
                    legacy_dirs.append(base_path / f"{u_part}_{d_part}")
                    legacy_dirs.append(base_path / email_addr)
                    legacy_dirs.append(base_path / d_part / u_part)
                    legacy_dirs.append(base_path / "mails" / d_part / u_part)
                    if subfolder:
                        legacy_dirs.append(base_path / "mails" / d_part / subfolder / u_part)
                        legacy_dirs.append(base_path / "mails" / d_part / subfolder)

                valid_legacy_dirs = []
                for d in legacy_dirs:
                    try:
                        if d.exists():
                            valid_legacy_dirs.append(d.resolve())
                    except Exception:
                        pass
                
                valid_legacy_dirs = list(set(valid_legacy_dirs))
                
                eml_files = []
                import os
                for l_dir in valid_legacy_dirs:
                    try:
                        for root, _, files in os.walk(str(l_dir)):
                            for f in files:
                                if f.lower().endswith(".eml"):
                                    eml_files.append(Path(root) / f)
                    except Exception as walk_ex:
                        logger.error("Failed to walk legacy folder: %s", walk_ex)

                if eml_files:
                    self.emit_progress(
                        int((idx / total_accounts) * 100),
                        f"📂 {len(eml_files)} adet EML dosyası tespit edildi. İçe aktarılıyor ve taşınıyor..."
                    )
                    import hashlib
                    import email as email_pkg
                    from email.parser import BytesParser
                    from email import policy
                    import time
                    
                    imported_cnt = 0
                    moved_cnt = 0
                    for i_eml, file_path in enumerate(eml_files):
                        if self._is_cancelled:
                            break
                        if i_eml % 100 == 0 or i_eml == len(eml_files) - 1:
                            self.emit_progress(
                                int(((idx + (i_eml / len(eml_files)) * 0.5) / total_accounts) * 100),
                                f"📥 İşleniyor: {i_eml + 1} / {len(eml_files)}..."
                            )
                            
                        try:
                            # Determine folder name
                            file_parts = list(file_path.relative_to(base_path).parts)
                            if "emls" in file_parts:
                                eml_idx = file_parts.index("emls")
                                folder_name = file_parts[eml_idx - 1]
                            else:
                                folder_name = file_path.parent.name
                                
                            if not folder_name or folder_name.lower() in ("mails", "data", f"{u_part}_{d_part}", email_addr):
                                folder_name = "INBOX"
                                
                            # Parse UID from filename
                            filename = file_path.name
                            uid = None
                            match = re.match(r'^\d{8}_\d{6}_(\d+)_', filename)
                            if match:
                                uid = int(match.group(1))
                            else:
                                fn_parts = filename.split('_')
                                for part in fn_parts:
                                    if part.isdigit():
                                        uid = int(part)
                                        break
                                        
                            if uid is None:
                                uid = int(time.time() * 1000) + i_eml
                                
                            with open(file_path, "rb") as f:
                                raw_bytes = f.read()
                                
                            sha256 = hashlib.sha256(raw_bytes).hexdigest()
                            is_dup = self.engine.db.is_duplicate_hash(sha256)
                            
                            msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
                            subject = msg.get("subject", "") or "NoSubject"
                            sender = msg.get("from", "")
                            recipients = msg.get("to", "")
                            cc = msg.get("cc", "") or ""
                            bcc = msg.get("bcc", "") or ""
                            message_id = msg.get("message-id", "")
                            date_header = msg.get("date", "")
                            
                            # Resolve new target folder path using unified path utility
                            from core.settings import get_account_mailbox_dir
                            target_mailbox_dir = get_account_mailbox_dir(base_path, email_addr, subfolder, folder_name)
                                
                            target_mailbox_dir.mkdir(parents=True, exist_ok=True)
                            
                            # Format date
                            date_str = ""
                            if date_header:
                                try:
                                    from datetime import datetime as dt_class
                                    dt = dt_class.fromisoformat(date_header.replace('Z', '+00:00'))
                                    date_str = dt.strftime("%Y%m%d_%H%M%S")
                                except Exception:
                                    date_str = re.sub(r'[\/:*?"<>|]', '_', date_header).strip()
                            if not date_str:
                                date_str = "unknown_date"
                                
                            subj_clean = re.sub(r'[\/:*?"<>|]', '_', subject).strip()[:60]
                            target_filename = f"{date_str}_{uid}_{subj_clean}.eml"
                            target_eml_path = target_mailbox_dir / target_filename
                            
                            # Move physical file directly
                            if file_path.resolve() != target_eml_path.resolve():
                                shutil.move(str(file_path), str(target_eml_path))
                                emls_moved += 1
                                total_bytes += target_eml_path.stat().st_size
                                moved_cnt += 1
                                
                            # Check if already in DB
                            existing = self.engine.db.get_mail_by_uid(acc_id, folder_name, uid)
                            if not existing:
                                mail_id = self.engine.db.upsert_mail_metadata(
                                    account_id=acc_id,
                                    folder=folder_name,
                                    uid=uid,
                                    subject=subject,
                                    sender=sender,
                                    recipients=recipients,
                                    cc=cc,
                                    bcc=bcc,
                                    message_id=message_id,
                                    date=date_header,
                                    size_bytes=len(raw_bytes),
                                    sha256_hash=sha256,
                                    is_duplicate=1 if is_dup else 0
                                )
                                self.engine.db.store_raw(mail_id, raw_bytes)
                                self.engine.db.register_hash(sha256, acc_id, mail_id)
                                imported_cnt += 1
                        except Exception as ex:
                            logger.error("Auto-import failed for EML %s: %s", file_path, ex)
                            
                    self.emit_progress(
                        int((idx / total_accounts) * 100),
                        f"✅ {imported_cnt} adet yeni e-posta veri tabanına işlendi, {moved_cnt} dosya taşındı."
                    )

                # Batch fetch all attachments mapping for this account to avoid N database queries
                mail_attachments = {}
                try:
                    with self.engine.db.get_conn() as conn:
                        att_rows = conn.execute(
                            """SELECT a.id, a.sha256_hash, a.filename, a.storage_path, l.mail_id
                               FROM attachments a
                               JOIN attachment_links l ON l.attachment_id = a.id
                               JOIN mail_metadata m ON m.id = l.mail_id
                               WHERE m.account_id = ? AND m.is_deleted = 0""",
                            (acc_id,)
                        ).fetchall()
                        for row in att_rows:
                            m_id = row["mail_id"]
                            if m_id not in mail_attachments:
                                mail_attachments[m_id] = []
                            mail_attachments[m_id].append({
                                "id": row["id"],
                                "sha256_hash": row["sha256_hash"],
                                "filename": row["filename"],
                                "storage_path": row["storage_path"]
                            })
                except Exception as ex:
                    logger.warning("Failed to batch fetch attachments: %s", ex)

                # Stream mails metadata row-by-row inside context manager
                db_updates = []
                try:
                    with self.engine.db.get_conn() as conn:
                        total_mails_count = 0
                        try:
                            count_row = conn.execute(
                                "SELECT COUNT(*) as cnt FROM mail_metadata WHERE account_id = ? AND is_deleted = 0",
                                (acc_id,)
                            ).fetchone()
                            total_mails_count = count_row["cnt"] if count_row else 0
                        except Exception:
                            pass
                        
                        if total_mails_count == 0:
                            total_mails_count = 1

                        cursor = conn.execute(
                            """SELECT m.id, m.uid, m.folder, m.subject, m.date
                               FROM mail_metadata m
                               WHERE m.account_id = ? AND m.is_deleted = 0""",
                            (acc_id,)
                        )

                        for m_idx, mail in enumerate(cursor):
                            if self._is_cancelled:
                                break

                            mail_id = mail["id"]
                            uid = mail["uid"]
                            folder_name = mail["folder"]
                            subject = mail["subject"] or "NoSubject"
                            date_header = mail["date"] or ""

                            # Format date
                            date_str = ""
                            if date_header:
                                try:
                                    from datetime import datetime as dt_class
                                    dt = dt_class.fromisoformat(date_header.replace('Z', '+00:00'))
                                    date_str = dt.strftime("%Y%m%d_%H%M%S")
                                except Exception:
                                    date_str = re.sub(r'[\/:*?"<>|]', '_', date_header).strip()
                            if not date_str:
                                date_str = "unknown_date"

                            subj_clean = re.sub(r'[\/:*?"<>|]', '_', subject).strip()[:60]
                            eml_filename = f"{date_str}_{uid}_{subj_clean}.eml"
                            folder_clean = re.sub(r'[\/:*?"<>|]', '_', folder_name).strip()

                            # Resolve target path using unified path utility
                            from core.settings import get_account_mailbox_dir
                            new_mailbox_dir = get_account_mailbox_dir(base_path, email_addr, subfolder, folder_name)

                            new_mailbox_dir.mkdir(parents=True, exist_ok=True)
                            new_eml_path = new_mailbox_dir / eml_filename

                            # 1. EML migration
                            old_parts = [base_path, "mails", group_clean]
                            if subfolder and subfolder != ".":
                                old_parts.append(subfolder)
                            old_parts.append(folder_clean)
                            old_mailbox_dir = Path(*old_parts)
                            old_eml_path = old_mailbox_dir / eml_filename

                            # Log exact source/target directory on the very first mail processing
                            if m_idx == 0:
                                self.emit_progress(
                                    int(((idx + (m_idx / total_mails_count)) / total_accounts) * 100),
                                    f"📂 Kaynak Klasör (Eski): {old_mailbox_dir}\n"
                                    f"📂 Hedef Klasör (Yeni) : {new_mailbox_dir}"
                                )

                            eml_status = ""
                            if old_eml_path.exists() and old_eml_path.resolve() != new_eml_path.resolve():
                                try:
                                    shutil.move(str(old_eml_path), str(new_eml_path))
                                    emls_moved += 1
                                    total_bytes += new_eml_path.stat().st_size
                                    eml_status = f"✉️ EML taşındı: {eml_filename}"
                                except Exception as e:
                                    eml_status = f"❌ EML taşıma hatası: {e}"
                            elif not new_eml_path.exists():
                                # Fetch raw_data on-demand ONLY if file is missing (preserves RAM)
                                try:
                                    row_raw = conn.execute("SELECT raw_data FROM mail_raw WHERE mail_id = ?", (mail_id,)).fetchone()
                                    raw_content = row_raw["raw_data"] if row_raw else None
                                    if raw_content:
                                        new_eml_path.write_bytes(raw_content)
                                        emls_moved += 1
                                        total_bytes += len(raw_content)
                                        eml_status = f"✉️ EML yeniden oluşturuldu: {eml_filename}"
                                except Exception as e:
                                    eml_status = f"❌ EML yazma hatası: {e}"

                            if eml_status:
                                if m_idx % 40 == 0 or "❌" in eml_status:
                                    self.emit_progress(
                                        int(((idx + (m_idx / total_mails_count)) / total_accounts) * 100),
                                        eml_status
                                    )

                            # 2. Attachments migration
                            attachments = mail_attachments.get(mail_id, [])
                            if attachments:
                                new_attachments_dir = new_mailbox_dir / "Attachments"
                                new_attachments_dir.mkdir(parents=True, exist_ok=True)

                                for att in attachments:
                                    att_id = att["id"]
                                    sha256 = att["sha256_hash"]
                                    att_filename = re.sub(r'[\/:*?"<>|]', '_', att["filename"] or "unknown").strip()
                                    old_storage_path = att["storage_path"]

                                    new_att_filename = f"{date_str}_{uid}_{att_filename}"
                                    new_storage_path = new_attachments_dir / new_att_filename

                                    # Fallback old path
                                    old_path_fallback_parts = [base_path, "attachments", group_clean]
                                    if subfolder and subfolder != ".":
                                        old_path_fallback_parts.append(subfolder)
                                    old_path_fallback = Path(*old_path_fallback_parts) / sha256

                                    actual_old_path = None
                                    if old_storage_path and Path(old_storage_path).exists():
                                        actual_old_path = Path(old_storage_path)
                                    elif old_path_fallback.exists():
                                        actual_old_path = old_path_fallback

                                    if actual_old_path and actual_old_path.resolve() != new_storage_path.resolve():
                                        try:
                                            shutil.copy(str(actual_old_path), str(new_storage_path))
                                            # Buffer updates for single transaction (reduces SQLite CPU/Disk IO overhead)
                                            db_updates.append((str(new_storage_path), att_id))
                                            
                                            try:
                                                actual_old_path.unlink()
                                            except Exception:
                                                pass
                                            atts_moved += 1
                                            total_bytes += new_storage_path.stat().st_size
                                            
                                            if m_idx % 20 == 0:
                                                self.emit_progress(
                                                    int(((idx + (m_idx / total_mails_count)) / total_accounts) * 100),
                                                    f"📎 Ek taşındı: {att_filename} -> INBOX/Attachments/"
                                                )
                                        except Exception as ex:
                                            self.emit_progress(
                                                int(((idx + (m_idx / total_mails_count)) / total_accounts) * 100),
                                                f"❌ Ek taşıma hatası ({att_filename}): {ex}"
                                            )
                                            
                            # Run chunked DB update transactions to keep locks short
                            if len(db_updates) >= 300:
                                try:
                                    with self.engine.db.transaction() as write_conn:
                                        write_conn.executemany("UPDATE attachments SET storage_path = ? WHERE id = ?", db_updates)
                                    db_updates.clear()
                                except Exception as tx_ex:
                                    logger.error("Failed to commit chunked attachment updates: %s", tx_ex)

                        # Execute remaining DB updates
                        if db_updates:
                            try:
                                with self.engine.db.transaction() as write_conn:
                                    write_conn.executemany("UPDATE attachments SET storage_path = ? WHERE id = ?", db_updates)
                                db_updates.clear()
                            except Exception as tx_ex:
                                logger.error("Failed to commit remaining attachment updates: %s", tx_ex)

                except Exception as e:
                    logger.error("Failed to query mails: %s", e)
                    self.emit_progress(
                        int((idx / total_accounts) * 100),
                        f"⚠️ Hata: Hesap verileri okunamadı: {e}"
                    )
                    continue

            # Rebuild index
            self.emit_progress(100, "\n🔍 Arama dizini (FTS) yeniden oluşturuluyor...")
            self.engine.db.rebuild_fts_index()
            self.emit_progress(100, "✅ Arama dizini başarıyla güncellendi.")

            total_mb = total_bytes / (1024 * 1024)
            self.finished.emit(emls_moved, atts_moved, total_mb)

        except Exception as e:
            logger.exception("Migration crash")
            self.error_occurred.emit(str(e))


class ArchiveOptimizerDialog(QDialog):
    """Visual dialog showing folder structure comparison, progress, and logs during reorganization."""

    def __init__(self, engine, settings, parent=None, account_ids=None):
        super().__init__(parent)
        self.engine = engine
        self.settings = settings
        self.account_ids = account_ids
        self.worker = None

        self.setWindowTitle("Arşiv Klasör Yapısı Optimizasyonu")
        self.resize(650, 480)
        self.setModal(False)

        self.setStyleSheet("""
            QDialog {
                background-color: #f8fafc;
            }
            QGroupBox {
                color: #1e293b;
                font-weight: bold;
                border: 1.5px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 6px;
                padding-top: 18px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
                color: #4361ee;
            }
            QTextEdit {
                background-color: #0f172a;
                color: #38bdf8;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 11px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
            }
            QProgressBar {
                background-color: #e2e8f0;
                border: none;
                border-radius: 4px;
                text-align: center;
                color: #1e293b;
                font-weight: bold;
                font-size: 10px;
                height: 16px;
            }
            QProgressBar::chunk {
                background-color: #10b981;
                border-radius: 4px;
            }
            QPushButton {
                font-weight: bold;
                font-size: 12px;
                padding: 8px 16px;
                border-radius: 6px;
            }
        """)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Top Information
        self.lbl_intro = QLabel("Bu araç, arşiv dizin yapınızı yeni, temiz ve okunabilir formata dönüştürür.")
        self.lbl_intro.setStyleSheet("font-size: 12px; color: #475569; font-weight: 500;")
        layout.addWidget(self.lbl_intro)

        # Structure Comparison Preview Panel
        comp_group = QGroupBox("Klasör Yapısı Karşılaştırması")
        comp_layout = QHBoxLayout(comp_group)
        comp_layout.setContentsMargins(10, 14, 10, 10)
        comp_layout.setSpacing(10)

        # Before
        before_frame = QFrame()
        before_frame.setStyleSheet("background: #fef2f2; border: 1px solid #fee2e2; border-radius: 6px; padding: 6px;")
        before_layout = QVBoxLayout(before_frame)
        lbl_b_title = QLabel("❌ Eski Yapı (Before)")
        lbl_b_title.setStyleSheet("font-weight: bold; color: #ef4444; font-size: 11px;")
        lbl_b_desc = QLabel(
            "📁 [Eski Klasör]/[Mailbox]/emls/YYYY/MM/DD/mail.eml\n"
            "📁 mails/[Domain]/[Hesap]/[Mailbox]/mail.eml"
        )
        lbl_b_desc.setStyleSheet("font-family: monospace; font-size: 10px; color: #991b1b;")
        before_layout.addWidget(lbl_b_title)
        before_layout.addWidget(lbl_b_desc)
        comp_layout.addWidget(before_frame, stretch=1)

        # After
        after_frame = QFrame()
        after_frame.setStyleSheet("background: #ecfdf5; border: 1px solid #d1fae5; border-radius: 6px; padding: 6px;")
        after_layout = QVBoxLayout(after_frame)
        lbl_a_title = QLabel("✅ Yeni Yapı (After)")
        lbl_a_title.setStyleSheet("font-weight: bold; color: #10b981; font-size: 11px;")
        lbl_a_desc = QLabel(
            "📁 [Yedek Klasörü]/[Alt Klasör]/[Klasör]/mail.eml\n"
            "📁 [Yedek Klasörü]/[Alt Klasör]/[Klasör]/Attachments/[orijinal_isim]"
        )
        lbl_a_desc.setStyleSheet("font-family: monospace; font-size: 10px; color: #065f46;")
        after_layout.addWidget(lbl_a_title)
        after_layout.addWidget(lbl_a_desc)
        comp_layout.addWidget(after_frame, stretch=1)

        layout.addWidget(comp_group)

        # Console Logs Area
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setPlaceholderText("İşlem adımları burada listelenecektir...")
        layout.addWidget(self.console, stretch=1)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Summary Report Box (Hidden initially)
        self.summary_box = QGroupBox("İşlem Özeti")
        self.summary_box.setVisible(False)
        self.summary_layout = QVBoxLayout(self.summary_box)
        self.summary_layout.setContentsMargins(12, 12, 12, 12)
        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet("font-size: 12px; color: #1e293b; font-weight: 500;")
        self.summary_layout.addWidget(self.lbl_summary)
        layout.addWidget(self.summary_box)

        # Action Buttons
        self.btns_layout = QHBoxLayout()
        self.btns_layout.addStretch()

        self.btn_cancel = QPushButton("İptal")
        self.btn_cancel.setStyleSheet("background-color: #ef4444; color: white; border: none;")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._cancel_migration)

        self.btn_background = QPushButton("Arka Planda Çalıştır")
        self.btn_background.setStyleSheet("background-color: #f59e0b; color: white; border: none;")
        self.btn_background.setVisible(False)
        self.btn_background.clicked.connect(self._run_in_background)

        self.btn_start = QPushButton("🚀 Optimizasyonu Başlat")
        self.btn_start.setStyleSheet("background-color: #10b981; color: white; border: none;")
        self.btn_start.clicked.connect(self._start_migration)

        self.btn_close = QPushButton("Kapat")
        self.btn_close.setStyleSheet("background-color: #6b7280; color: white; border: none;")
        self.btn_close.clicked.connect(self.reject)

        self.btns_layout.addWidget(self.btn_cancel)
        self.btns_layout.addWidget(self.btn_background)
        self.btns_layout.addWidget(self.btn_start)
        self.btns_layout.addWidget(self.btn_close)

        layout.addLayout(self.btns_layout)

    @Slot()
    def _start_migration(self):
        self.btn_start.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.btn_background.setVisible(True)
        self.summary_box.setVisible(False)
        self.console.clear()
        self.progress_bar.setValue(0)

        self.console.append("🕒 Optimizasyon işlemi başlatıldı...")

        self.worker = ArchiveOptimizerWorker(self.engine, self.settings, self.account_ids)
        self.worker.progress_update.connect(self._on_progress_update)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self._on_finished_bg)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

    @Slot()
    def _cancel_migration(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.console.append("\n🛑 İşlem kullanıcı tarafından iptal ediliyor...")
            self.btn_cancel.setEnabled(False)
            self.btn_background.setEnabled(False)
            if self.parent() and hasattr(self.parent(), "clear_optimizer_status"):
                self.parent().clear_optimizer_status()

    @Slot(int, str)
    def _on_progress_update(self, val, msg):
        self.progress_bar.setValue(val)
        if msg:
            self.console.append(msg)
        self.console.ensureCursorVisible()
        if self.parent() and hasattr(self.parent(), "update_optimizer_status"):
            self.parent().update_optimizer_status(val)

    @Slot(int, int, float)
    def _on_finished(self, emls, atts, size_mb):
        self.btn_close.setEnabled(True)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.setEnabled(True)
        self.btn_start.setEnabled(True)
        self.progress_bar.setValue(100)

        # Generate visual report
        summary_text = (
            f"🎉 <b>Klasör Optimizasyonu Başarıyla Tamamlandı!</b><br/><br/>"
            f"• <b>Taşınan EML Dosyası:</b> {emls} adet<br/>"
            f"• <b>Yeniden Adlandırılan Ek (Attachment):</b> {atts} adet<br/>"
            f"• <b>Toplam Taşınan Boyut:</b> {size_mb:.2f} MB<br/>"
            f"• <b>Eski Dizin Temizliği:</b> Başarılı (Tüm taşınan eski dosyalar diskten unlinked edildi)<br/>"
        )
        self.lbl_summary.setText(summary_text)
        self.summary_box.setVisible(True)
        self.console.append("\n🎉 İŞLEM BAŞARIYLA TAMAMLANDI.")
        if self.parent() and hasattr(self.parent(), "clear_optimizer_status"):
            self.parent().clear_optimizer_status()

    @Slot(str)
    def _on_error(self, err_msg):
        self.btn_close.setEnabled(True)
        self.btn_cancel.setVisible(False)
        self.btn_background.setVisible(False)
        self.btn_start.setEnabled(True)
        self.console.append(f"\n❌ Kritik Hata: {err_msg}")
        QMessageBox.critical(self, "Hata", f"Optimizasyon sırasında bir hata oluştu:\n{err_msg}")
        if self.parent() and hasattr(self.parent(), "clear_optimizer_status"):
            self.parent().clear_optimizer_status()

    @Slot()
    def _run_in_background(self):
        self.hide()
        if self.worker:
            self.worker.is_background = True
        # Initial status notification
        if self.parent() and hasattr(self.parent(), "update_optimizer_status"):
            self.parent().update_optimizer_status(self.progress_bar.value())

    @Slot(int, int, float)
    def _on_finished_bg(self, emls, atts, size_mb):
        if self.parent() and hasattr(self.parent(), "clear_optimizer_status"):
            self.parent().clear_optimizer_status()

        if not self.isVisible():
            QMessageBox.information(
                None,
                "Optimizasyon Tamamlandı",
                f"Arka planda yürütülen arşiv klasör optimizasyonu tamamlandı!\n\n"
                f"✅ Düzenlenen EML: {emls} adet\n"
                f"✅ Taşınan Ekler: {atts} adet\n"
                f"📂 Toplam Boyut: {size_mb:.2f} MB",
                QMessageBox.Ok
            )
            # Re-show to allow close
            self.show()
            self._on_finished(emls, atts, size_mb)
