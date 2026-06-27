#!/usr/bin/env python3
"""
main.py — CLI entry point for the Mail Archive System.

Clean Architecture — CLI Interface (outermost layer).
Uses the `rich` library for a polished terminal experience.

Usage:
    python main.py

Commands:
    accounts    — Manage email accounts
    sync        — Synchronize emails
    backup      — Backup to cloud (S3 / GDrive)
    restore     — Restore from cloud backup
    search      — Full-text search archived mails
    dedup       — Deduplicate mails
    audit       — View audit trail
    schedule    — Manage scheduled tasks
    report      — Generate reports
    health      — System health check
    help        — Show this help
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.crypto_utils import CryptoManager
from core.health_check import HealthChecker
from core.mail_engine import MailEngine
from core.reporter import ReportGenerator
from core.scheduler import TaskScheduler

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler("data/app.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("cli")


def print_banner() -> None:
    """Print the application banner using rich."""
    from rich.console import Console
    from rich.panel import Panel
    console = Console()
    banner = """
   __  ___         _       ____            _     _
  /  |/  /__  ___ (_)___  / __ \\___ _   _(_)___(_)_   _____
 / /|_/ / _ \\/ _ \\/ / __ \\/ /_/ / _ \\ | / / / __| \\ \\ / / _ \\
/ /  / /  __/  __/ / /_/ / _, _/  __/ |/ /| \\__ \\ |\\ V /  __/
/_/  /_/\\___/\\___/_/ .__/_/ |_|\\___/|___/_/|___/_| \\_/ \\___|
                   /_/
    """
    console.print(Panel(banner.strip(), title="Mail Archive System v1.0",
                        border_style="blue", subtitle="Clean Architecture"))


def main() -> None:
    """Main CLI loop."""
    from rich.console import Console
    from rich.table import Table
    from rich.prompt import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn

    console = Console()

    # Initialize engine
    engine = MailEngine()
    reporter = ReportGenerator()
    scheduler = TaskScheduler()
    health_checker = HealthChecker(engine.db, engine.crypto, engine.accounts, engine.audit)

    print_banner()
    console.print("[dim]Type 'help' for commands, 'exit' to quit.[/dim]\n")

    while True:
        try:
            cmd = Prompt.ask("[bold blue]mail-archive[/bold blue]").strip().lower()

            if cmd in ("exit", "quit", "q"):
                scheduler.stop()
                engine.shutdown()
                console.print("[green]Goodbye![/green]")
                break

            elif cmd == "help":
                _show_help(console)

            # ---- Accounts ----
            elif cmd == "accounts":
                _accounts_menu(console, engine)

            elif cmd == "account add":
                _account_add(console, engine)

            elif cmd == "account list":
                _account_list(console, engine)

            elif cmd == "account remove":
                _account_remove(console, engine)

            # ---- Sync ----
            elif cmd == "sync":
                _sync_all(console, engine)

            elif cmd.startswith("sync "):
                parts = cmd.split()
                if len(parts) == 2 and parts[1].isdigit():
                    _sync_one(console, engine, int(parts[1]))
                elif len(parts) == 3 and parts[1] == "dry-run" and parts[2].isdigit():
                    _sync_dry_run(console, engine, int(parts[2]))
                else:
                    console.print("[red]Usage: sync [account_id] | sync dry-run [account_id][/red]")

            # ---- Search ----
            elif cmd.startswith("search "):
                query = cmd[7:]
                _search(console, engine, query)

            # ---- Backup ----
            elif cmd == "backup":
                _backup_menu(console, engine)

            elif cmd.startswith("backup s3"):
                _backup_s3(console, engine)

            elif cmd.startswith("backup gdrive"):
                _backup_gdrive(console, engine)

            # ---- Restore ----
            elif cmd == "restore":
                _restore_menu(console, engine)

            # ---- Dedup ----
            elif cmd == "dedup":
                _run_dedup(console, engine)

            # ---- Audit ----
            elif cmd == "audit":
                _show_audit(console, engine)

            elif cmd == "audit verify":
                _audit_verify(console, engine)

            # ---- Report ----
            elif cmd == "report":
                _report_menu(console, engine)

            # ---- Schedule ----
            elif cmd == "schedule":
                _schedule_menu(console, scheduler)

            # ---- Health ----
            elif cmd == "health":
                _health_check(console, health_checker)

            # ---- Stats ----
            elif cmd == "stats":
                _show_stats(console, engine)

            # ---- Export ----
            elif cmd.startswith("export "):
                _export_mbox(console, engine)

            # ---- Config validation ----
            elif cmd.startswith("validate "):
                _validate_account(console, engine, cmd[9:])

            elif cmd == "":
                continue

            else:
                console.print(f"[red]Unknown command: {cmd}[/red]")
                console.print("Type [bold]help[/bold] for available commands.")

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
            break
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/red]")
            logger.exception("CLI error")


# ======================================================================
# Command implementations
# ======================================================================

def _show_help(console) -> None:
    from rich.table import Table
    table = Table(title="Mail Archive System — Commands")
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description", style="white")
    table.add_row("accounts", "Manage accounts (list, add, remove)")
    table.add_row("account add", "Add a new email account")
    table.add_row("account list", "List all accounts")
    table.add_row("account remove", "Remove an account")
    table.add_row("sync", "Sync all accounts")
    table.add_row("sync <id>", "Sync a specific account")
    table.add_row("sync dry-run <id>", "Preview sync for an account")
    table.add_row("backup", "Backup to S3 or Google Drive")
    table.add_row("restore", "Restore from S3 or Google Drive")
    table.add_row("search <query>", "Full-text search archived mails")
    table.add_row("dedup", "Run deduplication")
    table.add_row("audit", "View audit trail")
    table.add_row("audit verify", "Verify audit chain integrity")
    table.add_row("report", "Generate reports")
    table.add_row("schedule", "Manage scheduled tasks")
    table.add_row("health", "System health check")
    table.add_row("stats", "Show database statistics")
    table.add_row("export mbox", "Export mails to MBOX format")
    table.add_row("validate <id>", "Validate account configuration")
    table.add_row("exit", "Exit the application")
    console.print(table)


def _accounts_menu(console, engine: MailEngine) -> None:
    """Interactive accounts sub-menu."""
    from rich.prompt import Prompt
    while True:
        console.print("\n[bold]Account Management[/bold]")
        console.print("  1. List accounts")
        console.print("  2. Add account")
        console.print("  3. Remove account")
        console.print("  4. Back to main menu")
        choice = Prompt.ask("Select", choices=["1", "2", "3", "4"])
        if choice == "1":
            _account_list(console, engine)
        elif choice == "2":
            _account_add(console, engine)
        elif choice == "3":
            _account_remove(console, engine)
        elif choice == "4":
            break


def _account_list(console, engine: MailEngine) -> None:
    accounts = engine.list_accounts()
    if not accounts:
        console.print("[yellow]No accounts configured.[/yellow]")
        return
    from rich.table import Table
    table = Table(title="Email Accounts")
    table.add_column("ID", style="cyan")
    table.add_column("Label", style="green")
    table.add_column("Email", style="blue")
    table.add_column("IMAP Host")
    table.add_column("Port")
    table.add_column("SSL")
    for acc in accounts:
        table.add_row(
            str(acc["id"]),
            acc["label"],
            acc["email"],
            acc["imap_host"],
            str(acc["imap_port"]),
            "Yes" if acc["use_ssl"] else "No",
        )
    console.print(table)


def _account_add(console, engine: MailEngine) -> None:
    from rich.prompt import Prompt, IntPrompt, Confirm
    console.print("[bold]Add New Email Account[/bold]")
    label = Prompt.ask("Label", default="My Account")
    email = Prompt.ask("Email address")
    imap_host = Prompt.ask("IMAP server")
    imap_port = IntPrompt.ask("Port", default=993)
    use_ssl = Confirm.ask("Use SSL/TLS?", default=True)
    username = Prompt.ask("Username", default=email)
    password = Prompt.ask("Password", password=True)

    account_id = engine.add_account(
        label=label, email=email,
        imap_host=imap_host, imap_port=imap_port,
        use_ssl=use_ssl, username=username, password=password,
    )
    console.print(f"[green]Account added with ID: {account_id}[/green]")


def _account_remove(console, engine: MailEngine) -> None:
    from rich.prompt import IntPrompt, Confirm
    accounts = engine.list_accounts()
    if not accounts:
        console.print("[yellow]No accounts to remove.[/yellow]")
        return
    _account_list(console, engine)
    account_id = IntPrompt.ask("Account ID to remove")
    if Confirm.ask(f"Remove account {account_id}? This cannot be undone.", default=False):
        engine.remove_account(account_id)
        console.print(f"[green]Account {account_id} removed.[/green]")


def _sync_all(console, engine: MailEngine) -> None:
    from rich.progress import Progress, SpinnerColumn, TextColumn
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console) as progress:
        progress.add_task("Syncing all accounts...", total=None)
        reports = engine.sync_all()
    for r in reports:
        status = "OK" if r.get("errors", 0) == 0 else "ERROR"
        console.print(f"  {r.get('account_label', '?')}: {r.get('mails_fetched', 0)} fetched, "
                      f"{r.get('duplicates_found', 0)} dupes, "
                      f"{r.get('errors', 0)} errors [{'green' if status == 'OK' else 'red'}]{status}[/]")


def _sync_one(console, engine: MailEngine, account_id: int) -> None:
    from rich.progress import Progress, SpinnerColumn, TextColumn
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console) as progress:
        progress.add_task(f"Syncing account {account_id}...", total=None)
        report = engine.sync_account(account_id)
    console.print(f"[green]Sync complete: {report.get('mails_fetched', 0)} mails fetched, "
                  f"{report.get('duplicates_found', 0)} duplicates[/green]")


def _sync_dry_run(console, engine: MailEngine, account_id: int) -> None:
    result = engine.sync_dry_run(account_id)
    if "error" in result:
        console.print(f"[red]Error: {result['error']}[/red]")
        return
    console.print(f"[bold]Dry Run for: {result.get('account', '?')}[/bold]")
    console.print(f"  Estimated new mails: {result.get('total_estimated', 0)}")
    for folder in result.get("folders", []):
        console.print(f"    {folder['folder']}: {folder['new_mails']} new (since UID {folder['since_uid']})")


def _search(console, engine: MailEngine, query: str) -> None:
    results = engine.search(query, limit=20)
    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return
    from rich.table import Table
    table = Table(title=f"Search Results: {query}")
    table.add_column("ID", style="cyan")
    table.add_column("Date", style="blue")
    table.add_column("From", style="green")
    table.add_column("Subject")
    table.add_column("Folder")
    for r in results:
        table.add_row(
            str(r["id"]),
            r.get("date", "")[:19] if r.get("date") else "",
            r.get("sender", "")[:30],
            (r.get("subject") or "")[:50],
            r.get("folder", ""),
        )
    console.print(table)


def _backup_menu(console, engine: MailEngine) -> None:
    from rich.prompt import Prompt
    while True:
        console.print("\n[bold]Backup[/bold]")
        console.print("  1. Backup to S3")
        console.print("  2. Backup to Google Drive")
        console.print("  3. Back to main menu")
        choice = Prompt.ask("Select", choices=["1", "2", "3"])
        if choice == "1":
            _backup_s3(console, engine)
        elif choice == "2":
            _backup_gdrive(console, engine)
        elif choice == "3":
            break


def _backup_s3(console, engine: MailEngine) -> None:
    from rich.prompt import Prompt, IntPrompt, Confirm
    accounts = engine.list_accounts()
    if not accounts:
        console.print("[yellow]No accounts configured.[/yellow]")
        return
    _account_list(console, engine)
    account_id = IntPrompt.ask("Account ID")
    bucket = Prompt.ask("S3 Bucket name")
    region = Prompt.ask("Region", default="us-east-1")
    dry_run = Confirm.ask("Dry run (preview only)?", default=False)
    result = engine.backup_to_s3(account_id, bucket, region, dry_run=dry_run)
    if dry_run:
        console.print(f"[yellow]Dry Run: Would backup {result.get('mails_backed_up', 0)} mails[/yellow]")
    else:
        status = "OK" if result.get("errors", 0) == 0 else "ERROR"
        console.print(f"[{'green' if status == 'OK' else 'red'}]Backup {status}: "
                      f"{result.get('mails_backed_up', 0)} mails, "
                      f"{result.get('total_bytes', 0)} bytes[/]")


def _backup_gdrive(console, engine: MailEngine) -> None:
    from rich.prompt import Prompt, IntPrompt, Confirm
    accounts = engine.list_accounts()
    if not accounts:
        console.print("[yellow]No accounts configured.[/yellow]")
        return
    _account_list(console, engine)
    account_id = IntPrompt.ask("Account ID")
    dry_run = Confirm.ask("Dry run (preview only)?", default=False)
    result = engine.backup_to_gdrive(account_id, dry_run=dry_run)
    if dry_run:
        console.print(f"[yellow]Dry Run: Would backup {result.get('mails_backed_up', 0)} mails[/yellow]")
    else:
        status = "OK" if result.get("errors", 0) == 0 else "ERROR"
        console.print(f"[{'green' if status == 'OK' else 'red'}]GDrive backup {status}: "
                      f"{result.get('mails_backed_up', 0)} mails[/]")


def _restore_menu(console, engine: MailEngine) -> None:
    from rich.prompt import Prompt, Confirm
    console.print("[bold]Restore from Backup[/bold]")
    source = Prompt.ask("Source", choices=["s3", "gdrive"])
    dry_run = Confirm.ask("Dry run (preview only)?", default=False)
    if source == "s3":
        bucket = Prompt.ask("S3 Bucket")
        key = Prompt.ask("Remote key")
        result = engine.restore_from_s3(key, bucket, dry_run=dry_run)
    else:
        name = Prompt.ask("Remote filename")
        result = engine.restore_from_gdrive(name, dry_run=dry_run)
    if dry_run:
        console.print(f"[yellow]Dry Run: Would restore {result.get('mails_restored', 0)} mails[/yellow]")
    else:
        status = "OK" if result.get("errors", 0) == 0 else "ERROR"
        console.print(f"[{'green' if status == 'OK' else 'red'}]Restore {status}: "
                      f"{result.get('mails_restored', 0)} restored, "
                      f"{result.get('hash_verified', 0)} hashes verified[/]")


def _run_dedup(console, engine: MailEngine) -> None:
    from rich.prompt import IntPrompt
    accounts = engine.list_accounts()
    if not accounts:
        console.print("[yellow]No accounts configured.[/yellow]")
        return
    _account_list(console, engine)
    account_id = IntPrompt.ask("Account ID")
    count = engine.run_deduplication(account_id)
    console.print(f"[green]Deduplication complete: {count} duplicates found[/green]")


def _show_audit(console, engine: MailEngine) -> None:
    from rich.table import Table
    entries = engine.get_audit_log(limit=50)
    if not entries:
        console.print("[yellow]No audit entries.[/yellow]")
        return
    table = Table(title="Audit Trail (last 50 entries)")
    table.add_column("ID", style="cyan")
    table.add_column("Timestamp", style="blue")
    table.add_column("Action", style="green")
    table.add_column("Account")
    table.add_column("Details")
    for e in entries:
        table.add_row(
            str(e["id"]),
            e.get("timestamp", "")[:19],
            e["action"],
            str(e.get("account_id", "")),
            str(e.get("details", ""))[:60],
        )
    console.print(table)


def _audit_verify(console, engine: MailEngine) -> None:
    from rich.prompt import Confirm
    console.print("Verifying audit chain integrity...")
    is_valid = engine.verify_audit_chain()
    if is_valid:
        console.print("[green]Audit chain integrity verified — no tampering detected.[/green]")
    else:
        console.print("[red]Audit chain is BROKEN! Possible tampering detected.[/red]")


def _report_menu(console, engine: MailEngine) -> None:
    from rich.prompt import Prompt, IntPrompt
    console.print("[bold]Generate Reports[/bold]")
    console.print("  1. Sync report for last operation")
    console.print("  2. Database statistics report")
    console.print("  3. Back")
    choice = Prompt.ask("Select", choices=["1", "2", "3"])
    if choice == "1":
        console.print("[yellow]Run a sync first, then check data/reports/ directory.[/yellow]")
    elif choice == "2":
        stats = engine.get_stats()
        from rich.table import Table
        table = Table(title="Database Statistics")
        for k, v in stats.items():
            table.add_row(k, str(v))
        console.print(table)


def _schedule_menu(console, scheduler: TaskScheduler) -> None:
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    while True:
        console.print("\n[bold]Task Scheduler[/bold]")
        console.print("  1. List scheduled tasks")
        console.print("  2. Start scheduler")
        console.print("  3. Stop scheduler")
        console.print("  4. Back to main menu")
        choice = Prompt.ask("Select", choices=["1", "2", "3", "4"])
        if choice == "1":
            tasks = scheduler.list_tasks()
            if not tasks:
                console.print("[yellow]No scheduled tasks.[/yellow]")
            else:
                table = Table(title="Scheduled Tasks")
                table.add_column("ID", style="cyan")
                table.add_column("Type")
                table.add_column("Schedule")
                table.add_column("Function")
                for t in tasks:
                    sched = t.get("cron") or f"Every {t.get('hours', 0)}h {t.get('minutes', 0)}m"
                    table.add_row(t["id"], t["type"], sched, t.get("func_name", ""))
                console.print(table)
        elif choice == "2":
            scheduler.start()
            console.print("[green]Scheduler started.[/green]")
        elif choice == "3":
            scheduler.stop()
            console.print("[yellow]Scheduler stopped.[/yellow]")
        elif choice == "4":
            break


def _health_check(console, checker: HealthChecker) -> None:
    from rich.table import Table
    console.print("[bold]Running system health checks...[/bold]")
    result = checker.check_all()
    table = Table(title=f"System Health: {result['status'].upper()}")
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Message")
    for c in result["checks"]:
        status_style = {"ok": "green", "warning": "yellow", "error": "red"}
        table.add_row(
            c["name"],
            f"[{status_style.get(c['status'], 'white')}]{c['status']}[/]",
            c["message"],
        )
    console.print(table)


def _show_stats(console, engine: MailEngine) -> None:
    from rich.table import Table
    stats = engine.get_stats()
    table = Table(title="Database Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    for k, v in stats.items():
        table.add_row(k.replace("_", " ").title(), str(v))
    console.print(table)


def _export_mbox(console, engine: MailEngine) -> None:
    """Export archived mails to MBOX format.

    TODO: Implement full MBOX export using mailbox module.
    """
    console.print("[yellow]MBOX export is not yet implemented.[/yellow]")
    console.print("See TODO in core/mail_engine.py")


def _validate_account(console, engine: MailEngine, account_id_str: str) -> None:
    try:
        account_id = int(account_id_str.strip())
    except ValueError:
        console.print("[red]Invalid account ID. Usage: validate <id>[/red]")
        return
    acc = engine.accounts.get(account_id)
    if not acc:
        console.print(f"[red]Account {account_id} not found.[/red]")
        return
    # Decrypt credentials for validation
    username = engine.crypto.decrypt(acc["username_enc"])
    password = engine.crypto.decrypt(acc["password_enc"])
    account_config = {
        "imap_host": acc["imap_host"],
        "imap_port": acc["imap_port"],
        "use_ssl": bool(acc["use_ssl"]),
        "username": username,
        "password": password,
    }
    checker = HealthChecker(engine.db, engine.crypto, engine.accounts, engine.audit)
    result = checker.validate_account_config(account_config)
    from rich.table import Table
    table = Table(title=f"Validation Result for Account {account_id}")
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="bold")
    table.add_column("Details")
    for key in ("host_resolution", "imap_connection", "authentication"):
        passed = result.get(key, False)
        table.add_row(
            key.replace("_", " ").title(),
            f"[{'green' if passed else 'red'}]{'PASS' if passed else 'FAIL'}[/]",
            "" if passed else result.get("errors", ["Unknown"])[0] if result.get("errors") else "",
        )
    console.print(table)


if __name__ == "__main__":
    main()
