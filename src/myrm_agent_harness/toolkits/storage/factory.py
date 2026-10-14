"""Storage factory.


[INPUT]
- base::StorageProvider (POS: storage provider abstract base class)
- config::StorageConfig, storage_config (POS: storage configuration and global config singleton)
- local::LocalStorageBackend (POS: local storage backend implementation)

[OUTPUT]
- create_storage_provider(): factory function to create a storage provider instance
- get_storage_provider(): global storage provider singleton accessor
- set_storage_provider(): inject a business-layer provider as the global singleton

[POS]
Storage factory layer. Creates the local storage provider for a configuration and provides
global singleton access. Supports lazy initialization for simplified storage management.
"""

import logging

from .base import StorageProvider
from .config import StorageConfig, storage_config
from .local import LocalStorageBackend

logger = logging.getLogger(__name__)


def create_storage_provider(config: StorageConfig | None = None) -> StorageProvider:
    """Create a storage provider rooted at the configured storage directory.

    Args:
        config: Storage configuration; the global configuration is used when omitted.

    Returns:
        A LocalStorageBackend writing under ``config.get_base_path()``.
    """
    if config is None:
        config = storage_config

    base_path = config.get_base_path()
    logger.info("Using local storage: %s", base_path)
    return LocalStorageBackend(base_path)


# Lazily initialized global storage provider
_storage_provider: StorageProvider | None = None


def get_storage_provider() -> StorageProvider:
    """Get the global storage provider instance (lazily initialized)."""
    global _storage_provider
    if _storage_provider is None:
        _storage_provider = create_storage_provider()
    return _storage_provider


def set_storage_provider(provider: StorageProvider) -> None:
    """Set the global storage provider (injected by the business layer).

    Args:
        provider: Business-layer storage implementation (e.g. cloud storage or a custom path strategy).
    """
    global _storage_provider
    _storage_provider = provider
