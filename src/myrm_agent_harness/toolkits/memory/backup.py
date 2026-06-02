"""[INPUT]
- (none)

[OUTPUT]
- BackupMetadata: Metadata for a memory backup.
- BackupResult: Result of backup operation.
- RestoreResult: Result of restore operation.
- MemoryBackupStrategy: Protocol for memory backup and restore strategies.

[POS]
Provides BackupMetadata, BackupResult, RestoreResult.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from myrm_agent_harness.toolkits.memory.protocols import RelationalStoreProtocol, VectorStoreProtocol

"""Memory backup and restore protocols for data safety.

Defines abstract interfaces for memory system backup/restore strategies.
Business layer implements concrete strategies (e.g., VolumeBackupStrategy for
sandbox environments, S3BackupStrategy for cloud deployments).

Harness framework layer provides protocol and manager integration,
business layer provides implementation and UI.
"""


@dataclass(frozen=True, slots=True)
class BackupMetadata:
    """Metadata for a memory backup.

    Attributes:
        backup_id: Unique backup identifier
        created_at: Backup creation timestamp
        memory_count: Total memory count in backup
        size_bytes: Backup size in bytes
        collections: List of backed up collections
        description: Optional human-readable description
    """

    backup_id: str
    created_at: datetime
    memory_count: int
    size_bytes: int
    collections: list[str]
    description: str | None = None


@dataclass(frozen=True, slots=True)
class BackupResult:
    """Result of backup operation.

    Attributes:
        success: Operation success status
        metadata: Backup metadata
        duration_ms: Operation duration in milliseconds
        error: Optional error message
    """

    success: bool
    metadata: BackupMetadata | None
    duration_ms: float
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RestoreResult:
    """Result of restore operation.

    Attributes:
        success: Operation success status
        restored_count: Number of memories restored
        duration_ms: Operation duration in milliseconds
        error: Optional error message
    """

    success: bool
    restored_count: int
    duration_ms: float
    error: str | None = None


class MemoryBackupStrategy(Protocol):
    """Protocol for memory backup and restore strategies.

    Business layer implements concrete strategies:
    - VolumeBackupStrategy: Backup to sandbox persistent volume
    - S3BackupStrategy: Backup to cloud storage
    - LocalBackupStrategy: Backup to local filesystem

    Framework provides protocol and manager integration,
    business layer provides implementation and UI.
    """

    async def create_backup(
        self,
        vector: VectorStoreProtocol,
        relational: RelationalStoreProtocol | None = None,
        description: str | None = None,
    ) -> BackupResult:
        """Create a complete memory backup.

        Args:
            vector: Vector store protocol
            relational: Optional relational store protocol
            description: Optional backup description

        Returns:
            Backup operation result
        """
        ...

    async def list_backups(self) -> list[BackupMetadata]:
        """List available backups for a user.

        Returns:
            List of backup metadata sorted by created_at (descending)
        """
        ...

    async def restore_backup(
        self,
        backup_id: str,
        vector: VectorStoreProtocol,
        relational: RelationalStoreProtocol | None = None,
        *,
        overwrite: bool = False,
    ) -> RestoreResult:
        """Restore memories from a backup.

        Args:
            backup_id: Backup identifier
            vector: Vector store protocol
            relational: Optional relational store protocol
            overwrite: If True, clear existing memories before restore

        Returns:
            Restore operation result
        """
        ...

    async def delete_backup(self, backup_id: str) -> bool:
        """Delete a backup.

        Args:
            backup_id: Backup identifier

        Returns:
            True if backup deleted successfully
        """
        ...
