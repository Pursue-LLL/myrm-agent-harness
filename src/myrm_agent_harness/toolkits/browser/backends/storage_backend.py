"""Cloud-native storage backend for SessionVault.


[INPUT]
- myrm_agent_harness.toolkits.storage.base::StorageProvider (POS: storage provider protocol)
- ..session_vault_exceptions::InvalidDomainError (POS: Exception type definitions for SessionVault. Provides fine-grained error classification for targeted error handling by callers.)
- .file_backend::is_valid_domain_name (POS: domain name validation utility)

[OUTPUT]
- StorageVaultBackend: Cloud-native storage backend using StorageProvider

[POS]
Cloud-native storage backend for SessionVault. Uses StorageProvider abstraction to support multiple cloud storage
(S3/R2/GCS). Suitable for multi-instance deployments and cloud-native environments. URL encoding ensures bijective mapping from domains to storage keys.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

from ..session_vault_exceptions import InvalidDomainError
from .file_backend import is_valid_domain_name

logger = logging.getLogger(__name__)


class StorageVaultBackend:
    """Cloud-native storage backend using StorageProvider.

    Supports multi-instance deployments via cloud storage (S3/R2/GCS).
    Uses StorageProvider abstraction for storage operations.

    Domain encoding: URL-encodes domain names to prevent collisions.
    Path structure: {prefix}/{encoded_domain}.enc

    Args:
        storage_provider: Storage provider instance (e.g., S3Backend, R2Backend, LocalStorageBackend)
        prefix: Storage key prefix (default: "browser/sessions")

    Example:
        >>> from myrm_agent_harness.toolkits.storage import LocalStorageBackend
        >>> storage = LocalStorageBackend("./workspace")
        >>> backend = StorageVaultBackend(storage, prefix="sessions")
        >>> await backend.write("example.com", encrypted_data)
    """

    def __init__(self, storage_provider: StorageProvider, prefix: str = "browser/sessions") -> None:
        self._storage = storage_provider
        self._prefix = prefix.rstrip("/")

    def _storage_key(self, domain: str) -> str:
        """Get storage key for domain.

        Args:
            domain: Domain name (e.g., "example.com", "localhost:8080")

        Returns:
            Storage key path

        Raises:
            InvalidDomainError: If domain is invalid
        """
        if not is_valid_domain_name(domain):
            raise InvalidDomainError(
                f"Invalid domain name: {domain!r}. Only [a-zA-Z0-9._-:] allowed, no path traversal (.., /, \\)"
            )

        safe = quote(domain, safe="")
        return f"{self._prefix}/{safe}.enc"

    async def read(self, domain: str) -> bytes | None:
        """Read encrypted session for domain."""
        key = self._storage_key(domain)
        try:
            return await self._storage.read(key)
        except FileNotFoundError:
            return None

    async def write(self, domain: str, data: bytes) -> None:
        """Write encrypted session for domain."""
        key = self._storage_key(domain)
        await self._storage.write(key, data)

    async def delete(self, domain: str) -> bool:
        """Delete session for domain."""
        key = self._storage_key(domain)
        try:
            await self._storage.delete(key)
            return True
        except FileNotFoundError:
            return False

    async def list_all(self) -> list[str]:
        """List all saved domains using URL decoding."""
        try:
            keys = await self._storage.list(self._prefix)
            domains = []
            for key in keys:
                # Extract domain from key: {prefix}/{encoded}.enc -> {encoded}
                if key.startswith(f"{self._prefix}/") and key.endswith(".enc"):
                    encoded = key[len(self._prefix) + 1 : -4]
                    try:
                        domains.append(unquote(encoded))
                    except Exception:
                        continue
            return domains
        except Exception:
            logger.warning(f"Failed to list sessions from storage: {self._prefix}", exc_info=True)
            return []

    async def backup_corrupted(self, domain: str, data: bytes) -> None:
        """Backup corrupted session data to .corrupted file."""
        try:
            key = self._storage_key(domain).replace(".enc", ".corrupted")
            await self._storage.write(key, data)
            logger.info("Backed up corrupted session to %s", key)
        except Exception as exc:
            logger.warning("Failed to backup corrupted session: %s", exc)
