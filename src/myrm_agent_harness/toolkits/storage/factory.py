"""Storage factory.


[INPUT]
- base::StorageProvider (POS: storage provider abstract base class)
- config::StorageConfig, StorageMode, storage_config (POS: storage configuration and global config singleton)
- local::LocalStorageBackend (POS: local storage backend implementation)

[OUTPUT]
- create_storage_provider(): factory function to create a storage provider instance
- get_storage_provider(): global storage provider singleton accessor

[POS]
Storage factory layer. Creates storage provider instances based on configuration and provides
global singleton access. Supports lazy initialization for simplified storage management.
"""

import logging

from .base import StorageProvider
from .config import StorageConfig, StorageMode, storage_config

logger = logging.getLogger(__name__)


def create_storage_provider(config: StorageConfig | None = None) -> StorageProvider:
    """CreateStorageprovides者Instance

    Args:
        config: StorageConfigure，If is  None then using GlobalConfigure

    Returns:
        Storageprovides者Instance
    """
    if config is None:
        config = storage_config

    if config.mode == StorageMode.LOCAL:
        from .local import LocalStorageBackend

        base_path = config.get_local_base_path()
        logger.info(f"Using local storage: {base_path}")
        return LocalStorageBackend(base_path)

    elif config.mode == StorageMode.PERSISTENT:
        from .persistent import PersistentStorageBackend

        logger.info(
            f"Using persistent storage: "
            f"persistent={config.persistent.persistent_path}, "
            f"workspace={config.persistent.workspace_path}"
        )
        return PersistentStorageBackend(
            persistent_path=config.persistent.persistent_path,
            workspace_path=config.persistent.workspace_path,
        )

    raise ValueError(f"Unsupported storage mode: {config.mode}")


# latencyInitialize GlobalStorageprovides者Instance
_storage_provider: StorageProvider | None = None


def get_storage_provider() -> StorageProvider:
    """GetGlobalStorageprovides者Instance（latencyInitialize）"""
    global _storage_provider
    if _storage_provider is None:
        _storage_provider = create_storage_provider()
    return _storage_provider


def set_storage_provider(provider: StorageProvider) -> None:
    """SetGlobalStorageprovides者（business layerdepends oninject）

    Args:
        provider: business layerprovides Storageimplements（e.g.CloudStorage or customLocalPathStrategy）
    """
    global _storage_provider
    _storage_provider = provider
