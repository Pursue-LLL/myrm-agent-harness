"""Local file system storage backend


[INPUT]
- myrm_agent_harness.core.security.path::safe_join_path (POS: Path security checks)
- _fs_backend::BaseFileSystemBackend (POS: file system storage backend base class)
- base::StorageError (POS: storage exception types)
- pathlib::Path (POS: Python path library)
- aiofiles.os (POS: async file system operations)
- asyncio, os (POS: Python standard library)

[OUTPUT]
- LocalStorageBackend: local file system storage backend

[POS]
Local file system storage backend. Stores files under a single root directory; used for local development,
single-machine deployments and cloud sandboxes whose root is the persistent volume. Inherits BaseFileSystemBackend; common I/O operations and errno error handling
provided by base class. This class only handles path resolution (_resolve_key_to_path) and local-specific
logic (chmod, list).

Naming convention:
- Provider: abstract interface defining the contract (e.g. StorageProvider)
- Backend: concrete implementation, directly usable (e.g. LocalStorageBackend)
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import aiofiles.os

from ._fs_backend import BaseFileSystemBackend
from .base import StorageError

logger = logging.getLogger(__name__)


class LocalStorageBackend(BaseFileSystemBackend):
    """Local filesystem storage backend.

    Stores files under a single root directory; suitable for development, single-machine
    deployments and cloud sandboxes whose root points at the persistent volume.

    Args:
        base_path: Storage root directory (created when missing)

    Example:
        >>> storage = LocalStorageBackend("./storage")
        >>> await storage.write("file.txt", b"content")
        >>> # Actual path: ./storage/file.txt
    """

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info("LocalStorageBackend initialized: %s", self.base_path)

    def _resolve_key_to_path(self, key: str) -> Path:
        """Resolve a storage key to a local filesystem path.

        Uses safe_join_path to guard against path traversal, null bytes and symlink escapes.
        """
        from myrm_agent_harness.core.security.path import safe_join_path

        normalized_key = Path(key).as_posix().lstrip("/")
        try:
            return safe_join_path(self.base_path, normalized_key)
        except ValueError as e:
            raise StorageError(str(e)) from e

    async def write(self, key: str, content: bytes, content_type: str | None = None) -> None:
        """Write a file and restrict its permissions to 0o600."""
        await super().write(key, content, content_type)

        path = self._resolve_key_to_path(key)
        try:
            await asyncio.to_thread(os.chmod, str(path), 0o600)
        except OSError as e:
            logger.debug(f"chmod failed for {key}: {e}")

        logger.info("Wrote file: %s (%d bytes)", key, len(content))

    async def list(self, prefix: str = "", recursive: bool = True) -> list[str]:
        """List files under the storage root.

        Args:
            prefix: Relative path prefix to list under (the whole root when empty)
            recursive: Whether to descend into subdirectories

        Returns:
            Paths relative to the storage root
        """
        base = self._resolve_key_to_path(prefix) if prefix else self.base_path

        if not await aiofiles.os.path.exists(str(base)):
            return []

        result: list[str] = []
        normalized_prefix = prefix.rstrip("/") if prefix else ""

        def _list_files(dir_path: Path, rel_prefix: str) -> None:
            for item in dir_path.iterdir():
                rel_path = f"{rel_prefix}/{item.name}" if rel_prefix else item.name
                if item.is_file():
                    result.append(rel_path)
                elif item.is_dir() and recursive:
                    _list_files(item, rel_path)

        await asyncio.to_thread(_list_files, base, normalized_prefix)
        return result

    async def delete(self, key: str) -> None:
        """Delete a file or directory."""
        await super().delete(key)
        logger.info("Deleted: %s", key)

    async def copy(self, src_key: str, dst_key: str) -> None:
        """Copy a file or directory."""
        await super().copy(src_key, dst_key)
        logger.info("Copied: %s -> %s", src_key, dst_key)

    async def move(self, src_key: str, dst_key: str) -> None:
        """Move a file or directory."""
        await super().move(src_key, dst_key)
        logger.info("Moved: %s -> %s", src_key, dst_key)

    def resolve_absolute_path(self, key: str) -> str:
        """Get the absolute filesystem path of a key.

        For callers that need to access the filesystem directly.

        Args:
            key: File path/key

        Returns:
            Absolute path string
        """
        return str(self._resolve_key_to_path(key))
