"""
provider_registry.py — Plugin registry for external providers.

Clean Architecture — Plugin Layer.
Allows registering custom mail providers (e.g., Gmail API, Exchange EWS)
and cloud storage providers (e.g., Dropbox, OneDrive) without modifying
the core system.

New providers implement the interfaces from domain/interfaces.py and
register themselves here.
"""

import logging
from typing import Any, Dict, Optional

from domain.interfaces import CloudStorageProvider, MailProvider, PluginProvider

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Central registry for pluggable providers.

    Both mail and cloud providers can be registered at runtime.
    The system looks here before falling back to built-in implementations.
    """

    def __init__(self):
        self._mail_providers: Dict[str, type] = {}
        self._cloud_providers: Dict[str, type] = {}
        self._plugins: Dict[str, PluginProvider] = {}

    # ------------------------------------------------------------------
    # Mail provider registration
    # ------------------------------------------------------------------

    def register_mail_provider(self, name: str, provider_class: type) -> None:
        """Register a mail provider class.

        The class must implement MailProvider interface.

        Args:
            name: Unique provider name (e.g., "gmail_api", "exchange_ews")
            provider_class: Class that implements MailProvider
        """
        if not issubclass(provider_class, MailProvider):
            raise TypeError(f"{provider_class.__name__} must implement MailProvider")
        self._mail_providers[name] = provider_class
        logger.info("Registered mail provider: %s → %s", name, provider_class.__name__)

    def get_mail_provider(self, name: str) -> Optional[MailProvider]:
        """Instantiate a registered mail provider by name."""
        cls = self._mail_providers.get(name)
        if cls:
            try:
                return cls()
            except Exception as exc:
                logger.error("Failed to instantiate mail provider '%s': %s", name, exc)
        return None

    def list_mail_providers(self) -> Dict[str, type]:
        return dict(self._mail_providers)

    # ------------------------------------------------------------------
    # Cloud storage provider registration
    # ------------------------------------------------------------------

    def register_cloud_provider(self, name: str, provider_class: type) -> None:
        """Register a cloud storage provider class.

        The class must implement CloudStorageProvider interface.

        Args:
            name: Unique provider name (e.g., "dropbox", "onedrive")
            provider_class: Class that implements CloudStorageProvider
        """
        if not issubclass(provider_class, CloudStorageProvider):
            raise TypeError(f"{provider_class.__name__} must implement CloudStorageProvider")
        self._cloud_providers[name] = provider_class
        logger.info("Registered cloud provider: %s → %s", name, provider_class.__name__)

    def get_cloud_provider(self, name: str) -> Optional[CloudStorageProvider]:
        """Instantiate a registered cloud provider by name."""
        cls = self._cloud_providers.get(name)
        if cls:
            try:
                return cls()
            except Exception as exc:
                logger.error("Failed to instantiate cloud provider '%s': %s", name, exc)
        return None

    def list_cloud_providers(self) -> Dict[str, type]:
        return dict(self._cloud_providers)

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def register_plugin(self, plugin: PluginProvider) -> None:
        """Register and initialize a plugin."""
        name = plugin.name()
        self._plugins[name] = plugin
        try:
            plugin.initialize()
            logger.info("Plugin initialized: %s", name)
        except Exception as exc:
            logger.error("Failed to initialize plugin '%s': %s", name, exc)

    def unregister_plugin(self, name: str) -> None:
        """Shutdown and unregister a plugin."""
        plugin = self._plugins.pop(name, None)
        if plugin:
            try:
                plugin.shutdown()
                logger.info("Plugin shut down: %s", name)
            except Exception as exc:
                logger.error("Error shutting down plugin '%s': %s", name, exc)

    def get_plugin(self, name: str) -> Optional[PluginProvider]:
        return self._plugins.get(name)

    def list_plugins(self) -> Dict[str, PluginProvider]:
        return dict(self._plugins)

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def shutdown_all(self) -> None:
        """Gracefully shut down all registered plugins."""
        for name in list(self._plugins.keys()):
            self.unregister_plugin(name)
        logger.info("All plugins shut down")
