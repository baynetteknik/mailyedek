"""
scheduler.py — Task scheduler and retention policy manager.

Clean Architecture — Core Service Layer.
Uses APScheduler for periodic sync/backup tasks and
supports configurable retention policies (e.g., "7 years, then delete").
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.event_bus import EventBus, Event, Events

logger = logging.getLogger(__name__)

SCHEDULER_CONFIG_PATH = Path("data/scheduler_config.json")


class RetentionPolicy:
    """Defines data retention rules.

    Example configurations:
      - Retain all mails for 7 years, then delete.
      - Move mails older than 3 years to S3 Glacier.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @property
    def retain_years(self) -> int:
        return self.config.get("retain_years", 7)

    @property
    def glacier_years(self) -> Optional[int]:
        return self.config.get("glacier_years")  # None = no glacier transition

    @property
    def delete_after_years(self) -> Optional[int]:
        return self.config.get("delete_after_years")  # None = never delete

    def get_cutoff_date(self, years: int) -> str:
        """Return ISO date string for *years* ago."""
        return (datetime.utcnow() - timedelta(days=years * 365)).isoformat()

    def to_dict(self) -> Dict:
        return self.config

    @classmethod
    def from_dict(cls, data: Dict) -> "RetentionPolicy":
        return cls(data)


class TaskScheduler:
    """APScheduler-based task scheduler for periodic operations.

    Supports:
      - Periodic sync (cron or interval)
      - Periodic backup to S3/Google Drive
      - Retention policy enforcement
      - Configurable schedules persisted to JSON
    """

    def __init__(self, event_bus: Optional[EventBus] = None,
                 config_path: Optional[Path] = None):
        self._event_bus = event_bus
        self._config_path = config_path or SCHEDULER_CONFIG_PATH
        self._scheduler: Any = None
        self._tasks: Dict[str, Dict] = {}
        self._load_config()

    # ------------------------------------------------------------------
    # Scheduler lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the APScheduler background scheduler."""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
            from apscheduler.triggers.interval import IntervalTrigger

            self._scheduler = BackgroundScheduler({
                "apscheduler.job_defaults.coalesce": True,
                "apscheduler.job_defaults.max_instances": 1,
            })

            # Register stored tasks
            for task_id, task_cfg in self._tasks.items():
                self._add_task_to_scheduler(task_id, task_cfg)

            self._scheduler.start()
            logger.info("Task scheduler started with %d tasks", len(self._tasks))

        except ImportError:
            logger.warning(
                "APScheduler is not installed. Install with: pip install apscheduler"
            )
        except Exception as exc:
            logger.error("Failed to start scheduler: %s", exc)

    def stop(self) -> None:
        """Shut down the scheduler gracefully."""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("Task scheduler stopped")

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    def add_cron_task(self, task_id: str, func: Callable,
                      cron_expression: str,
                      args: Optional[List] = None,
                      kwargs: Optional[Dict] = None) -> None:
        """Add a cron-triggered task.

        Args:
            task_id: Unique identifier
            func: Callable to execute
            cron_expression: Standard cron format ("0 2 * * *" = daily at 2 AM)
            args: Positional arguments for func
            kwargs: Keyword arguments for func
        """
        self._tasks[task_id] = {
            "type": "cron",
            "cron": cron_expression,
            "func_name": func.__name__,
            "args": args or [],
            "kwargs": kwargs or {},
        }
        self._save_config()

        if self._scheduler:
            self._add_task_to_scheduler(task_id, self._tasks[task_id], func)

        logger.info("Added cron task '%s': %s", task_id, cron_expression)

    def add_interval_task(self, task_id: str, func: Callable,
                          hours: int = 0, minutes: int = 0, seconds: int = 0,
                          args: Optional[List] = None,
                          kwargs: Optional[Dict] = None) -> None:
        """Add an interval-triggered task."""
        self._tasks[task_id] = {
            "type": "interval",
            "hours": hours,
            "minutes": minutes,
            "seconds": seconds,
            "func_name": func.__name__,
            "args": args or [],
            "kwargs": kwargs or {},
        }
        self._save_config()

        if self._scheduler:
            self._add_task_to_scheduler(task_id, self._tasks[task_id], func)

        logger.info("Added interval task '%s': every %dh %dm",
                    task_id, hours, minutes)

    def remove_task(self, task_id: str) -> None:
        """Remove a scheduled task."""
        self._tasks.pop(task_id, None)
        self._save_config()
        if self._scheduler:
            try:
                self._scheduler.remove_job(task_id)
            except Exception:
                pass
        logger.info("Removed task '%s'", task_id)

    def list_tasks(self) -> List[Dict]:
        """Return all configured tasks."""
        return [{"id": tid, **cfg} for tid, cfg in self._tasks.items()]

    # ------------------------------------------------------------------
    # Retention policy enforcement
    # ------------------------------------------------------------------

    def enforce_retention(self, policy: RetentionPolicy,
                          mail_cleanup_func: Callable) -> Dict[str, Any]:
        """Enforce a retention policy, deleting or archiving old mails.

        Args:
            policy: RetentionPolicy instance
            mail_cleanup_func: Callable that accepts (before_date, action)
                               and returns a dict with deletion stats.

        Returns:
            Dict with cleanup results (deleted, archived, errors).
        """
        result: Dict[str, Any] = {
            "deleted": 0,
            "archived_to_glacier": 0,
            "errors": 0,
        }

        # Delete mails older than retain_years
        if policy.delete_after_years:
            cutoff = policy.get_cutoff_date(policy.delete_after_years)
            try:
                cleanup_result = mail_cleanup_func(before_date=cutoff, action="delete")
                result["deleted"] = cleanup_result.get("affected", 0)
                logger.info("Retention: Deleted %d mails older than %d years",
                            result["deleted"], policy.delete_after_years)
            except Exception as exc:
                logger.error("Retention deletion failed: %s", exc)
                result["errors"] += 1

        # TODO: Archive to S3 Glacier
        if policy.glacier_years:
            logger.info("S3 Glacier transition policy configured (%d years) but not implemented",
                        policy.glacier_years)
            result["archived_to_glacier"] = 0

        if self._event_bus:
            self._event_bus.publish(Event(Events.SYNC_COMPLETED, {
                "action": "retention_enforcement",
                "result": result,
            }))

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _add_task_to_scheduler(self, task_id: str, task_cfg: Dict,
                                func: Optional[Callable] = None) -> None:
        """Register a task with APScheduler."""
        if not self._scheduler:
            return

        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        actual_func = func  # If func is provided, use it directly
        if actual_func is None:
            # TODO: Resolve function by name using a registry
            logger.warning("Cannot resolve function for task '%s'", task_id)
            return

        try:
            if task_cfg["type"] == "cron":
                trigger = CronTrigger.from_crontab(task_cfg["cron"])
            else:
                trigger = IntervalTrigger(
                    hours=task_cfg.get("hours", 0),
                    minutes=task_cfg.get("minutes", 0),
                    seconds=task_cfg.get("seconds", 0),
                )

            self._scheduler.add_job(
                actual_func,
                trigger=trigger,
                id=task_id,
                args=task_cfg.get("args", []),
                kwargs=task_cfg.get("kwargs", {}),
                replace_existing=True,
            )
        except Exception as exc:
            logger.error("Failed to add task '%s' to scheduler: %s", task_id, exc)

    def _save_config(self) -> None:
        """Persist task configuration to JSON."""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, "w") as f:
                json.dump(self._tasks, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save scheduler config: %s", exc)

    def _load_config(self) -> None:
        """Load task configuration from JSON."""
        if self._config_path.exists():
            try:
                with open(self._config_path) as f:
                    self._tasks = json.load(f)
            except Exception as exc:
                logger.error("Failed to load scheduler config: %s", exc)
