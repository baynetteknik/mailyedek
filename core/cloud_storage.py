"""
cloud_storage.py — Cloud storage manager (S3 + Google Drive).

Clean Architecture — Core Service Layer.
Provides a unified interface for cloud operations, delegating to
infrastructure adapters. Implements retry with exponential backoff.
"""

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.event_bus import EventBus, Event, Events
from domain.interfaces import CloudStorageProvider
from infrastructure.s3_client import S3Client
from infrastructure.gdrive_client import GoogleDriveClient
from plugins.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)

RETRY_DELAYS = [5, 15, 30, 60]


def with_retry(operation: Callable, *args, max_retries: int = 4,
               retry_delays: Optional[List[int]] = None, **kwargs) -> Any:
    """Execute *operation* with exponential backoff retry.

    Args:
        operation: Callable to execute
        max_retries: Maximum number of retries (default 4)
        retry_delays: List of delays in seconds (default [5, 15, 30, 60])

    Returns:
        The operation's return value, or None if all retries failed.
    """
    import time
    delays = retry_delays or RETRY_DELAYS
    last_exc = None

    for attempt in range(max_retries + 1):
        try:
            return operation(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = delays[min(attempt, len(delays) - 1)]
                logger.warning(
                    "Operation %s failed (attempt %d/%d): %s. Retrying in %ds...",
                    operation.__name__, attempt + 1, max_retries + 1, exc, delay
                )
                time.sleep(delay)
            else:
                logger.error(
                    "Operation %s failed after %d attempts: %s",
                    operation.__name__, max_retries + 1, exc
                )

    return None


class CloudStorageManager:
    """Unified cloud storage operations across providers.

    Delegates to S3Client and GoogleDriveClient based on provider type.
    """

    def __init__(self, event_bus: Optional[EventBus] = None,
                 provider_registry: Optional[ProviderRegistry] = None):
        self._event_bus = event_bus
        self._provider_registry = provider_registry or ProviderRegistry()
        self._providers: Dict[str, CloudStorageProvider] = {}

    def get_provider(self, provider_type: str, **config) -> CloudStorageProvider:
        """Get or create a cloud storage provider instance."""
        key = f"{provider_type}:{hash(frozenset(config.items()))}"

        if key in self._providers:
            return self._providers[key]

        provider: Optional[CloudStorageProvider] = None

        if provider_type == "s3":
            provider = S3Client(
                bucket_name=config.get("bucket_name", ""),
                region=config.get("region", "us-east-1"),
                access_key_id=config.get("access_key_id"),
                secret_access_key=config.get("secret_access_key"),
            )
        elif provider_type == "gdrive":
            provider = GoogleDriveClient(
                credentials_path=config.get("credentials_path"),
            )
        else:
            # Try plugin registry
            provider = self._provider_registry.get_cloud_provider(provider_type)

        if provider is None:
            raise ValueError(f"Unknown cloud provider: {provider_type}")

        self._providers[key] = provider
        return provider

    def upload_with_retry(self, provider: CloudStorageProvider,
                          local_path: Path, remote_key: str) -> bool:
        """Upload a file with exponential backoff."""
        result = with_retry(provider.upload, local_path, remote_key)
        if result and self._event_bus:
            self._event_bus.publish(Event(Events.BACKUP_COMPLETED, {
                "remote_key": remote_key,
                "local_path": str(local_path),
            }))
        return bool(result)

    def download_with_retry(self, provider: CloudStorageProvider,
                            remote_key: str, local_path: Path) -> bool:
        """Download a file with exponential backoff."""
        result = with_retry(provider.download, remote_key, local_path)
        return bool(result)

    def upload_stream_with_retry(
        self, provider: CloudStorageProvider,
        stream, remote_key: str, content_length: int) -> bool:
        """Stream-upload with exponential backoff."""
        # TODO: Implement streaming multipart upload with retry
        raise NotImplementedError("Streaming upload with retry is not yet implemented.")
