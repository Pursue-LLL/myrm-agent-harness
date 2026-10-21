"""Storage backends for SessionVault.

[INPUT]
- (none — standalone module)

[OUTPUT]
- SessionVaultBackend: Storage backend protocol
- FileVaultBackend: Local filesystem backend implementation
- StorageVaultBackend: Cloud-native storage backend implementation

[POS]
Storage backend abstraction layer for SessionVault. Defines interfaces via Protocol,
supporting local file, cloud storage (S3/R2), and other backend implementations.
"""

from .file_backend import FileVaultBackend
from .protocols import SessionVaultBackend
from .storage_backend import StorageVaultBackend

__all__ = ["FileVaultBackend", "SessionVaultBackend", "StorageVaultBackend"]
