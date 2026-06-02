"""Resumable Upload - Checkpoint-based Upload for Large Files

[INPUT]

[OUTPUT]
- Checkpoint storage interface for resumable uploads

[POS]
Resumable upload interface (framework layer). Defines the checkpoint storage protocol for business-layer implementations (Memory/File/Redis).

"""

from __future__ import annotations

from typing import Protocol


class ResumableUploadProtocol(Protocol):
    """Resumable upload checkpoint storage protocol (Framework layer interface)

    Business layer should implement this protocol to provide checkpoint storage.
    Framework layer only defines the interface, does not couple with specific storage implementation.

    Example implementations:
    - MemoryCheckpointStore: In-memory storage (for testing or single-process scenarios)
    - FileCheckpointStore: File-based storage (for multi-process scenarios)
    - RedisCheckpointStore: Redis-based storage (for distributed multi-tenant SaaS scenarios)
    """

    async def save_checkpoint(self, upload_id: str, checkpoint: dict) -> None:
        """Save upload checkpoint

        Args:
            upload_id: Unique upload identifier (e.g., UUID)
            checkpoint: Checkpoint data (format: {"uploaded_bytes": int, "total_bytes": int, "timestamp": float})

        Example:
            await checkpoint_store.save_checkpoint(
                upload_id="upload-123",
                checkpoint={"uploaded_bytes": 5000000, "total_bytes": 10000000, "timestamp": time.time()}
            )
        """
        ...

    async def load_checkpoint(self, upload_id: str) -> dict | None:
        """Load upload checkpoint

        Args:
            upload_id: Unique upload identifier

        Returns:
            Checkpoint data (if exists), or None (if not exists or expired)

        Example:
            checkpoint = await checkpoint_store.load_checkpoint(upload_id="upload-123")
            if checkpoint:
                uploaded_bytes = checkpoint["uploaded_bytes"]
                # Resume upload from uploaded_bytes...
        """
        ...

    async def delete_checkpoint(self, upload_id: str) -> None:
        """Delete upload checkpoint (after successful upload)

        Args:
            upload_id: Unique upload identifier

        Example:
            await checkpoint_store.delete_checkpoint(upload_id="upload-123")
        """
        ...


class MemoryCheckpointStore:
    """In-memory checkpoint storage (business layer example implementation)

    This is a simple example implementation for testing or single-process scenarios.
    For production use, consider:
    - FileCheckpointStore: File-based storage for multi-process scenarios
    - RedisCheckpointStore: Redis-based storage for distributed multi-tenant SaaS scenarios
    """

    def __init__(self):
        self._checkpoints: dict[str, dict] = {}

    async def save_checkpoint(self, upload_id: str, checkpoint: dict) -> None:
        """Save checkpoint to memory"""
        self._checkpoints[upload_id] = checkpoint

    async def load_checkpoint(self, upload_id: str) -> dict | None:
        """Load checkpoint from memory"""
        return self._checkpoints.get(upload_id)

    async def delete_checkpoint(self, upload_id: str) -> None:
        """Delete checkpoint from memory"""
        self._checkpoints.pop(upload_id, None)
