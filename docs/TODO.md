# Mail Archive System — TODO & Implementation Status

## Overview of Completed vs. Remaining Work

| # | Feature | Status | Priority |
|---|---------|--------|----------|
| 1 | Multi-Account (SQLite + Fernet encryption) | ✅ Done | High |
| 2 | Delta Sync (UID-based, UIDVALIDITY) | ✅ Done | High |
| 3 | Data Integrity (SHA-256 hashing) | ✅ Done | High |
| 4 | Deduplication (hash-based, content-addressable) | ✅ Done | High |
| 5 | MBOX/EML Export/Import | 🔴 TODO | High |
| 6 | Push to IMAP with Filtering | ⚠️ Partial | High |
| 7 | Cloud Backup (S3 + Google Drive) | ✅ Done | High |
| 8 | Restore from Cloud | ✅ Done | High |
| 9 | Retry & Error Handling | ✅ Done | High |
| 10 | Parallel Processing (ThreadPoolExecutor) | ✅ Done | High |
| 11 | FTS5 Full-Text Search | ✅ Done | High |
| 12 | Dry Run Mode | ✅ Done | High |
| 13 | Task Scheduler (APScheduler) | ⚠️ Partial | Medium |
| 14 | Plugin/Event-Driven Architecture | ⚠️ Partial | Medium |
| 15 | Report Generation (JSON + HTML) | ✅ Done | Medium |
| 16 | Audit Trail (Hash-Chained) | ✅ Done | High |
| 17 | Health Check / Monitoring | ✅ Done | Medium |
| 18 | Config Validation | ✅ Done | Medium |
| 19 | Memory Management (Streaming) | 🔴 TODO | High |
| 20 | Conflict Resolution | 🔴 TODO | Low |

## Detailed TODOs

### 🔴 Critical / High Priority

#### 1. MBOX/EML Export/Import (`core/mail_engine.py`)
- Implement `export_mbox()` using Python's `mailbox` module
- Implement `import_mbox()` for Thunderbird/Outlook/Apple Mail archives
- Implement `export_eml()` for single-file export
- Support MailStore import format

#### 2. Streaming Fetch for Large Mails (`infrastructure/imap_client.py`)
- `fetch_message_stream()` — chunked FETCH for messages > 25 MB
- Uses `IMAP4.fetch()` with partial fetch (`<start>-<end>` byte ranges)
- Writes directly to disk / content-addressable store without full RAM load

#### 3. Streaming Upload (`infrastructure/s3_client.py`, `gdrive_client.py`)
- `upload_stream()` implementation for both S3 and Google Drive
- Multipart upload with configurable chunk size
- Progress callback integration with `rich` progress bars

#### 4. Key Rotation (`core/crypto_utils.py`)
- `CryptoManager.rotate_key()` — re-encrypt all stored secrets with new key
- Must read all encrypted fields from DB, decrypt with old key, re-encrypt with new key

#### 5. OS Keyring Integration (`core/crypto_utils.py`)
- Replace file-based key storage with `keyring` library
- `keyring.set_password("mail_archive", "fernet_key", key)`
- Fall back to file if keyring unavailable

### ⚠️ Medium Priority

#### 6. Retention Policy Enforcement (`core/scheduler.py`)
- Implement S3 Glacier transition logic
- Implement "delete after N years" with confirmation
- Add `retention check` CLI command

#### 7. Plugin Auto-Discovery (`plugins/provider_registry.py`)
- Load plugins from `plugins/` directory using Python entry points
- Plugin configuration via `data/plugins_config.json`

#### 8. Async Event Dispatch (`core/event_bus.py`)
- `publish_async()` — dispatch events in background thread pool
- Event queue with persistence (survive crashes)

#### 9. Conflict Resolution (`usecases/sync_usecase.py`)
- When UIDVALIDITY changes AND same UID exists with different hash:
  - Option A: Timestamp-based (keep newest)
  - Option B: Hash-based (keep if hash differs, flag for review)
  - Option C: Ask user (interactive)

### 🔵 Low Priority

#### 10. REST API (FastAPI)
- Create `api/` directory with FastAPI app
- Endpoints: `/sync`, `/backup`, `/restore`, `/search`, `/health`
- Async support with `asyncio.to_thread()` for blocking operations

#### 11. PyQt Desktop GUI
- Create `gui/` directory with PyQt6 application
- Tab-based interface: Accounts | Sync | Backup | Restore | Search | Reports
- System tray integration for background sync

#### 12. Docker / Kubernetes
- Dockerfile with multi-stage build
- docker-compose.yml with volume mounts
- Kubernetes CronJob manifest for scheduled syncs

#### 13. MBOX/EML Import from Thunderbird/Outlook/Apple Mail
- Profile directory scanner for Thunderbird
- PST file parser for Outlook (requires `libpst` or `pypff`)
- .mbox import from Apple Mail

#### 14. Google Drive Export Format Options
- Export as `.zip` (default)
- Export as `.mbox` (single file)
- Export as individual `.eml` files in a folder structure

## Code Quality

- [ ] Unit tests (pytest) for all use cases
- [ ] Integration tests with mock IMAP server
- [ ] Type hints coverage (mypy strict mode)
- [ ] Docstrings for all public methods
- [ ] Pre-commit hooks (ruff, mypy, pytest)
- [ ] CI pipeline (GitHub Actions)
