# Mail Archive System — Development Guide

## Getting Started

### Prerequisites
- Python 3.9+ (3.11 recommended)
- Git

### Installation

```bash
# Clone / navigate to project
cd mail_archive_system

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\Activate.ps1

# Activate (Linux/macOS)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### First Run

```bash
python main.py
```

The system will:
1. Create `data/` directory with SQLite database and encryption key
2. Show the interactive CLI menu
3. Prompt you to add an email account

## Project Structure

```
mail_archive_system/
├── main.py                    # CLI entry point
├── requirements.txt           # Python dependencies
├── core/                      # Application business rules
│   ├── __init__.py
│   ├── mail_engine.py         # Facade for all operations
│   ├── cloud_storage.py       # Cloud upload/download manager
│   ├── crypto_utils.py        # Encryption, hashing, masking
│   ├── database.py            # SQLite schema, repositories
│   ├── event_bus.py           # Pub/sub event system
│   ├── scheduler.py           # Task scheduler + retention
│   ├── reporter.py            # JSON/HTML report generation
│   └── health_check.py        # System diagnostics
├── domain/                    # Enterprise business rules
│   ├── __init__.py
│   ├── entities.py            # Data classes
│   ├── interfaces.py          # Abstract interfaces
│   └── repositories.py        # Repository contracts
├── infrastructure/            # Framework adapters
│   ├── __init__.py
│   ├── imap_client.py         # IMAP protocol
│   ├── s3_client.py           # Amazon S3
│   ├── gdrive_client.py       # Google Drive
│   └── sqlite_repository.py   # SQLite implementations
├── usecases/                  # Application use cases
│   ├── __init__.py
│   ├── sync_usecase.py        # Email sync
│   ├── backup_usecase.py      # Cloud backup
│   └── restore_usecase.py     # Cloud restore
├── plugins/                   # Plugin system
│   ├── __init__.py
│   └── provider_registry.py   # Provider registry
├── docs/                      # Documentation
│   ├── ARCHITECTURE.md        # Architecture guide
│   ├── TODO.md                # Task list
│   └── DEVELOPMENT.md         # This file
└── data/                      # Runtime data (gitignored)
    ├── mail_archive.db        # SQLite database
    ├── key.key                # Encryption key
    ├── app.log                # Application log
    └── reports/               # Generated reports
```

## Development Workflow

### Adding a New Feature

1. **Start with the Domain** — Define entities and interfaces in `domain/`
2. **Implement Core Logic** — Add business rules in `core/`
3. **Write Use Case** — Orchestrate the flow in `usecases/`
4. **Add Infrastructure** — Implement adapters in `infrastructure/`
5. **Register Plugin** — If external provider, register in `plugins/provider_registry.py`
6. **Expose via Facade** — Add method to `core/mail_engine.py`
7. **Add CLI Command** — Wire up in `main.py`

### Running Tests

```bash
# Run all tests (when implemented)
pytest tests/ -v

# Run specific test
pytest tests/test_sync_usecase.py -v

# With coverage
pytest --cov=core --cov=usecases --cov=infrastructure tests/
```

### Code Quality

```bash
# Linting
ruff check .

# Type checking
mypy core/ usecases/ infrastructure/ plugins/

# Formatting
ruff format .
```

## Common Tasks

### Adding a New Mail Provider (e.g., Gmail API)

```python
# infrastructure/gmail_api_client.py
from domain.interfaces import MailProvider

class GmailApiClient(MailProvider):
    def connect(self, ...): ...
    def fetch_uids(self, ...): ...

# plugins/provider_registry.py — in register_defaults():
registry.register_mail_provider("gmail_api", GmailApiClient)
```

### Adding a New Cloud Provider (e.g., Dropbox)

```python
# infrastructure/dropbox_client.py
from domain.interfaces import CloudStorageProvider

class DropboxClient(CloudStorageProvider):
    def connect(self, ...): ...
    def upload(self, ...): ...

# plugins/provider_registry.py
registry.register_cloud_provider("dropbox", DropboxClient)
```

### Creating a Custom Plugin

```python
from domain.interfaces import PluginProvider
from core.event_bus import Event, Events

class CustomPlugin(PluginProvider):
    def name(self) -> str:
        return "custom_plugin"

    def initialize(self) -> None:
        # Subscribe to events
        engine.on(Events.MAIL_FETCHED, self.on_mail_fetched)

    def on_mail_fetched(self, event: Event):
        print(f"Mail fetched: {event.data}")

    def shutdown(self) -> None:
        pass
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MAIL_ARCHIVE_DB` | Database path | `data/mail_archive.db` |
| `MAIL_ARCHIVE_KEY` | Encryption key path | `data/key.key` |
| `MAIL_ARCHIVE_LOG` | Log file path | `data/app.log` |
| `MAIL_ARCHIVE_LOG_LEVEL` | Log level | `INFO` |
| `AWS_ACCESS_KEY_ID` | AWS access key (fallback) | — |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key (fallback) | — |
| `AWS_DEFAULT_REGION` | AWS default region | `us-east-1` |

## Database Migrations

The system uses automatic schema creation on first run. For schema changes:

1. Add new `CREATE TABLE IF NOT EXISTS` statements to `DatabaseManager._init_schema()`
2. Add migration helper for non-destructive ALTER TABLE operations
3. Test with existing database

Future: Alembic-based migrations for production deployments.

## Security Guidelines

1. **Never log email content or passwords** — use `CryptoManager.mask_email()` and `mask_password()`
2. **Encrypt all stored credentials** — Fernet AES-128-CBC with PBKDF2
3. **Verify hash chains** — Audit trail is append-only with SHA-256 chaining
4. **Validate configuration** — Before connecting to any external service
5. **Stream large files** — Never load >25 MB into memory at once
