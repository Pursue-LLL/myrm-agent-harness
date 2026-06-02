"""File system storage backend base class

Provides common aiofiles I/O implementation for LocalStorageBackend and PersistentStorageBackend.
Subclasses only need to implement the `_resolve_key_to_path(key)` template method for path resolution.

[INPUT]
- base::StorageProvider, FileInfo, StorageError (POS: storage protocol and types)
- aiofiles, aiofiles.os (POS: true async file I/O)
- asyncio, errno, shutil, mimetypes (POS: Python standard library)

[OUTPUT]
- BaseFileSystemBackend: file system storage backend base class

[POS]
File system storage backend base class. Centralizes aiofiles file operations and errno error handling,
inherited by LocalStorageBackend and PersistentStorageBackend.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import mimetypes
import shutil
from abc import abstractmethod
from datetime import UTC, datetime
from pathlib import Path

import aiofiles
import aiofiles.os

from .base import FileInfo, StorageError, StorageProvider

logger = logging.getLogger(__name__)


class BaseFileSystemBackend(StorageProvider):
    """File系统Storage后端Base class

    Subclass需implements `_resolve_key_to_path(key)` 以定义PathParseStrategy。
    """

    @abstractmethod
    def _resolve_key_to_path(self, key: str) -> Path:
        """将StorageKeyParse is File系统绝对Path

        Args:
            key: StorageKey（如 "artifacts/report.pdf"）

        Returns:
            Parse后 绝对Path

        Raises:
            StorageError: Path越界
        """
        ...

    # ── read ────────────────────────────────────────────

    async def read(self, key: str) -> bytes:
        path = self._resolve_key_to_path(key)
        try:
            async with aiofiles.open(path, "rb") as f:
                return await f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {key}") from None
        except IsADirectoryError:
            raise StorageError(f"Not a file: {key}") from None

    async def read_text(self, key: str, encoding: str = "utf-8") -> str:
        path = self._resolve_key_to_path(key)
        try:
            async with aiofiles.open(path, encoding=encoding) as f:
                return await f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {key}") from None

    # ── write ───────────────────────────────────────────

    async def write(
        self, key: str, content: bytes, content_type: str | None = None
    ) -> None:
        from myrm_agent_harness.infra.atomic_write import async_atomic_write

        path = self._resolve_key_to_path(key)
        try:
            await async_atomic_write(path, content, mode=None)
        except OSError as e:
            raise self._translate_os_error(e, key) from e

    async def write_text(
        self,
        key: str,
        content: str,
        encoding: str = "utf-8",
        content_type: str | None = None,
    ) -> None:
        from myrm_agent_harness.infra.atomic_write import async_atomic_write

        path = self._resolve_key_to_path(key)
        try:
            await async_atomic_write(path, content.encode(encoding), mode=None)
        except OSError as e:
            raise self._translate_os_error(e, key) from e

    # ── delete ──────────────────────────────────────────

    async def delete(self, key: str) -> None:
        path = self._resolve_key_to_path(key)

        if not await aiofiles.os.path.exists(str(path)):
            raise FileNotFoundError(f"File not found: {key}")

        if await aiofiles.os.path.isfile(str(path)):
            await aiofiles.os.remove(str(path))
        elif await aiofiles.os.path.isdir(str(path)):
            await asyncio.to_thread(shutil.rmtree, path)

    # ── exists ──────────────────────────────────────────

    async def exists(self, key: str) -> bool:
        try:
            path = self._resolve_key_to_path(key)
            return await aiofiles.os.path.exists(str(path))
        except StorageError:
            return False

    async def is_dir(self, key: str) -> bool:
        try:
            path = self._resolve_key_to_path(key)
            return await aiofiles.os.path.isdir(str(path))
        except StorageError:
            return False

    # ── info ────────────────────────────────────────────

    async def info(self, key: str) -> FileInfo:
        path = self._resolve_key_to_path(key)
        try:
            stat_result = await aiofiles.os.stat(str(path))
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {key}") from None

        content_type, _ = mimetypes.guess_type(str(path))
        return FileInfo(
            key=key,
            size=stat_result.st_size,
            last_modified=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC),
            content_type=content_type,
        )

    # ── copy / move ─────────────────────────────────────

    async def copy(self, src_key: str, dst_key: str) -> None:
        src_path = self._resolve_key_to_path(src_key)
        dst_path = self._resolve_key_to_path(dst_key)

        if not await aiofiles.os.path.exists(str(src_path)):
            raise FileNotFoundError(f"Source file not found: {src_key}")

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if await aiofiles.os.path.isfile(str(src_path)):
            await asyncio.to_thread(shutil.copy2, src_path, dst_path)
        elif await aiofiles.os.path.isdir(str(src_path)):
            await asyncio.to_thread(shutil.copytree, src_path, dst_path)

    async def move(self, src_key: str, dst_key: str) -> None:
        src_path = self._resolve_key_to_path(src_key)
        dst_path = self._resolve_key_to_path(dst_key)

        if not await aiofiles.os.path.exists(str(src_path)):
            raise FileNotFoundError(f"Source file not found: {src_key}")

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(shutil.move, str(src_path), str(dst_path))

    # ── get_url ─────────────────────────────────────────

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        path = self._resolve_key_to_path(key)

        if not await aiofiles.os.path.exists(str(path)):
            raise FileNotFoundError(f"File not found: {key}")

        return Path(path).as_uri()

    # ── error helpers ───────────────────────────────────

    @staticmethod
    def _translate_os_error(e: OSError, key: str) -> Exception:
        """将 OSError 翻译 is 更Concrete ExceptionType"""
        if e.errno == errno.ENOSPC:
            return OSError(f"No space left on device: {key}")
        if e.errno == errno.ENAMETOOLONG:
            return ValueError(f"File name too long: {key}")
        if e.errno == errno.EROFS:
            return PermissionError(f"Read-only file system: {key}")
        return StorageError(f"Failed to write {key}: {e}")
