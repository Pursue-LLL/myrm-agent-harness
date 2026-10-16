"""Storage abstraction layer.

Provides a unified storage CRUD interface decoupled from business logic.
The framework ships LocalStorageBackend (rooted at MYRM_DATA_DIR/storage); any other
backend is injected by the business layer through StorageProvider.
"""

from .base import FileInfo, StorageError, StorageProvider
from .config import StorageConfig, storage_config
from .factory import (
    create_storage_provider,
    get_storage_provider,
    set_storage_provider,
)
from .local import LocalStorageBackend

__all__ = [
    "FileInfo",
    "LocalStorageBackend",
    "StorageConfig",
    "StorageError",
    "StorageProvider",
    "create_storage_provider",
    "get_storage_provider",
    "set_storage_provider",
    "storage_config",
]
