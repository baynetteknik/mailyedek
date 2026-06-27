"""
event_bus.py — Event-driven architecture with pub/sub mechanism.

Clean Architecture — Core Layer.
Allows loose coupling between modules:
  mail_engine  ──fire("mail.fetched")──>  cloud_storage (listens)
                                         database (listens)
                                         deduplication (listens)
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Event definitions
# ------------------------------------------------------------------

class EventPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2


@dataclass
class Event:
    """Immutable event payload."""
    name: str
    data: Dict[str, Any] = field(default_factory=dict)
    priority: EventPriority = EventPriority.NORMAL
    source: Optional[str] = None

    def __repr__(self) -> str:
        return f"Event({self.name}, pri={self.priority.name})"


# ------------------------------------------------------------------
# Standard event names (constants)
# ------------------------------------------------------------------

class Events:
    ACCOUNT_ADDED = "account.added"
    ACCOUNT_REMOVED = "account.removed"
    SYNC_STARTED = "sync.started"
    SYNC_COMPLETED = "sync.completed"
    SYNC_FAILED = "sync.failed"
    MAIL_FETCHED = "mail.fetched"
    MAIL_DELETED = "mail.deleted"
    MAIL_MOVED = "mail.moved"
    MAIL_DUPLICATE_DETECTED = "mail.duplicate_detected"
    BACKUP_STARTED = "backup.started"
    BACKUP_COMPLETED = "backup.completed"
    BACKUP_FAILED = "backup.failed"
    RESTORE_STARTED = "restore.started"
    RESTORE_COMPLETED = "restore.completed"
    DEDUP_RUN = "dedup.run"
    ERROR_OCCURRED = "error.occurred"


# ------------------------------------------------------------------
# Listener interface
# ------------------------------------------------------------------

class EventListener(ABC):
    """Abstract listener that can subscribe to events."""

    @abstractmethod
    def handle_event(self, event: Event) -> None:
        """Process an event synchronously."""


# ------------------------------------------------------------------
# Event bus (pub/sub)
# ------------------------------------------------------------------

class EventBus:
    """Simple synchronous pub/sub event bus.

    Thread-safe for parallel dispatch via ThreadPoolExecutor if needed.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[EventListener]] = {}
        self._async_handlers: Dict[str, List[Callable[[Event], Any]]] = {}

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def subscribe(self, event_name: str, listener: EventListener) -> None:
        """Register a listener for a specific event name."""
        self._subscribers.setdefault(event_name, []).append(listener)
        logger.debug("Listener %s subscribed to '%s'", type(listener).__name__, event_name)

    def subscribe_fn(self, event_name: str, callback: Callable[[Event], Any]) -> None:
        """Register a plain callable as an async event handler."""
        self._async_handlers.setdefault(event_name, []).append(callback)
        logger.debug("Function %s subscribed to '%s'", callback.__name__, event_name)

    def unsubscribe(self, event_name: str, listener: EventListener) -> None:
        """Remove a specific listener from an event."""
        if event_name in self._subscribers:
            self._subscribers[event_name] = [
                l for l in self._subscribers[event_name] if l is not listener
            ]

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, event: Event) -> None:
        """Synchronously dispatch *event* to all registered listeners."""
        logger.debug("Publishing event: %s", event)

        # Dispatch to EventListener instances
        for listener in self._subscribers.get(event.name, []):
            try:
                listener.handle_event(event)
            except Exception:
                logger.exception("Listener %s failed handling %s", type(listener).__name__, event)

        # Dispatch to plain callable handlers
        for handler in self._async_handlers.get(event.name, []):
            try:
                handler(event)
            except Exception:
                logger.exception("Handler %s failed handling %s", handler.__name__, event)

    def publish_async(self, event: Event) -> None:
        """TODO: Dispatch event in a background thread / asyncio task."""
        raise NotImplementedError("Async event dispatch is not yet implemented.")


# ------------------------------------------------------------------
# Singleton convenience (optional)
# ------------------------------------------------------------------

_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
