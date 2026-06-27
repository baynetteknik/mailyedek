# Mail Archive System — Architecture Guide

## Clean Architecture Layers

```
┌──────────────────────────────────────────────────────┐
│                   CLI (main.py)                       │  Frameworks & Drivers
│              REST API (future)                        │
│              PyQt GUI (future)                        │
├──────────────────────────────────────────────────────┤
│                 Use Cases                             │  Interface Adapters
│   sync_usecase.py   backup_usecase.py                 │
│   restore_usecase.py                                  │
├──────────────────────────────────────────────────────┤
│                   Core                                │  Application Business Rules
│   mail_engine.py   cloud_storage.py  database.py      │
│   crypto_utils.py  event_bus.py      scheduler.py     │
│   reporter.py      health_check.py                    │
├──────────────────────────────────────────────────────┤
│                  Domain                               │  Enterprise Business Rules
│   entities.py     interfaces.py     repositories.py   │
├──────────────────────────────────────────────────────┤
│               Infrastructure                          │  Adapters / Frameworks
│   imap_client.py  s3_client.py      gdrive_client.py  │
│   sqlite_repository.py                                │
├──────────────────────────────────────────────────────┤
│                  Plugins                              │  Extensibility
│   provider_registry.py                                │
└──────────────────────────────────────────────────────┘
```

## Dependency Rule

Dependencies point **inward**. Inner layers never know about outer layers:
- **Domain** — No dependencies on anything outside itself.
- **Core** — Depends only on Domain.
- **Use Cases** — Depends on Domain and Core.
- **Infrastructure** — Implements Domain interfaces, depends on Core.
- **Plugins** — Implements Domain interfaces.
- **CLI/API/GUI** — Depends on Core/MailEngine facade.

## Data Flow (Sync Operation)

```
User Input (CLI)
    │
    ▼
MailEngine.sync_all()          ─── Facade
    │
    ▼
SyncUseCase.sync_all()         ─── Use Case
    │
    ├─► ImapClient.connect()   ─── Infrastructure (IMAP)
    ├─► ImapClient.fetch_uids()
    ├─► ImapClient.fetch_message()
    │
    ├─► CryptoManager.hash()   ─── Core (Hashing)
    ├─► DatabaseManager         ─── Core (SQLite)
    │   ├─► upsert_mail_metadata()
    │   ├─► update_sync_state()
    │   ├─► store_raw_mail()
    │   └─► append_audit_log()
    │
    ├─► EventBus.publish()     ─── Core (Event-Driven)
    │
    └─► ReportGenerator        ─── Core (Reporting)
```

## Key Design Decisions

### 1. Why SQLite + FTS5 instead of Elasticsearch?
For a desktop/CLI-first tool, SQLite with FTS5 provides zero-configuration full-text search. The schema supports future migration to PostgreSQL or Elasticsearch by swapping the repository implementation.

### 2. Why UID-based sync instead of Message-ID?
IMAP UIDs are the authoritative identifier within a folder. UIDVALIDITY changes are detected and handled. Message-IDs are stored for reference but not used for sync logic.

### 3. Why Fernet (AES-128-CBC)?
Fernet provides authenticated encryption (encrypt-then-MAC), preventing tampering. Keys are derived via PBKDF2. Future: OS keyring integration.

### 4. Why Event Bus?
Decouples modules: when `mail.fetched` fires, any number of listeners (dedup, cloud backup, FTS indexing) can react without the sync engine knowing about them.

### 5. Content-Addressable Attachments
Attachments are stored by SHA-256 hash. If the same PDF is attached to 50 different emails, it is stored once on disk with 50 references. This is implemented in the `attachments` and `attachment_links` tables.

## Porting to Other Interfaces

### REST API (FastAPI)
```python
# future: api/main.py
from core.mail_engine import MailEngine

app = FastAPI()
engine = MailEngine()

@app.post("/sync")
async def sync():
    return engine.sync_all()
```

### Desktop GUI (PyQt)
```python
# future: gui/main_window.py
from core.mail_engine import MailEngine

class MainWindow(QMainWindow):
    def __init__(self):
        self.engine = MailEngine()
```

### Docker
```dockerfile
FROM python:3.11-slim
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["python", "main.py"]
```

### Kubernetes
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: mail-archive-sync
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: sync
            image: mail-archive:latest
            command: ["python", "main.py", "--sync-all"]
```
