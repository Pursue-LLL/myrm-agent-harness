"""Storage backend protocol for SessionVault.

[INPUT]
- (none — standalone module)

[OUTPUT]
- SessionVaultBackend: Pluggable storage backend protocol

[POS]
Defines the storage backend interface for SessionVault. Implements dependency
inversion via Protocol, supporting local file, database, and other backends.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SessionVaultBackend(Protocol):
    """Pluggable storage backend for encrypted session blobs."""

    async def read(self, domain: str) -> bytes | None:
        """Read encrypted session data for domain.

        Args:
            domain: Domain name

        Returns:
            Encrypted bytes if exists, None otherwise
        """
        ...

    async def write(self, domain: str, data: bytes) -> None:
        """Write encrypted session data for domain.

        Args:
            domain: Domain name
            data: Encrypted session bytes

        Raises:
            OSError: If write operation fails
        """
        ...

    async def delete(self, domain: str) -> bool:
        """Delete session data for domain.

        Args:
            domain: Domain name

        Returns:
            True if deleted, False if not found
        """
        ...

    async def list_all(self) -> list[str]:
        """List all saved domain names.

        Returns:
            List of domain names
        """
        ...

    async def backup_corrupted(self, domain: str, data: bytes) -> None:
        """Backup corrupted session data for forensics.

        Args:
            domain: Domain name
            data: Corrupted encrypted bytes
        """
        ...
