"""CodeExecutor to StorageProvider adapter.

Adapts CodeExecutor file operations to the StorageProvider interface,
allowing file tool strategies to use an executor as a storage backend.

[INPUT]
- toolkits.storage.base::FileInfo, StorageProvider (POS: Storage provider abstract base class. Defines the unified storage interface contract for all storage backends. Supports file read/write, delete, list, info query, and namespace isolation. Method names use read/write (not get/put), fully compatible with the StorageBackend Protocol.)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)

[OUTPUT]
- ExecutorStorageAdapter: Adapt a CodeExecutor to the StorageProvider interface.

[POS]
CodeExecutor to StorageProvider adapter.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.storage.base import FileInfo, StorageProvider

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor


class ExecutorStorageAdapter(StorageProvider):
    """Adapt a CodeExecutor to the StorageProvider interface."""

    def __init__(self, executor: CodeExecutor) -> None:
        super().__init__(namespace=None)
        self._executor = executor

    @property
    def workspace_path(self) -> str:
        return self._executor.workspace_path

    def _get_full_path(self, path: str) -> str:
        """Synchronous path resolution (compatible with StorageBackendStrategy.get_actual_path)."""
        from pathlib import Path as _Path

        wp = _Path(self._executor.workspace_path).resolve()
        clean = path
        if clean.startswith("/workspace"):
            clean = clean[len("/workspace") :].lstrip("/") or "."
        if _Path(clean).is_absolute():
            return str(_Path(clean).resolve())
        return str((wp / clean).resolve())

    async def read(self, key: str) -> bytes:
        return await self._executor.read_file_bytes(key)

    async def read_text(self, key: str, encoding: str = "utf-8") -> str:
        return await self._executor.read_file(key)

    async def get_text(self, key: str, encoding: str = "utf-8") -> str:
        return await self._executor.read_file(key)

    async def write(self, key: str, content: bytes, content_type: str | None = None) -> None:
        await self._executor.write_file(key, content.decode("utf-8"))

    async def write_text(
        self,
        key: str,
        content: str,
        encoding: str = "utf-8",
        content_type: str | None = None,
    ) -> None:
        await self._executor.write_file(key, content)

    async def put_text(
        self,
        key: str,
        content: str,
        encoding: str = "utf-8",
        content_type: str | None = None,
    ) -> None:
        await self._executor.write_file(key, content)

    async def delete(self, key: str) -> None:
        await self._executor.delete_file(key)

    async def exists(self, key: str) -> bool:
        return await self._executor.file_exists(key)

    async def is_dir(self, key: str) -> bool:
        return await self._executor.is_dir(key)

    async def list(self, prefix: str = "", recursive: bool = False) -> list[str]:
        path = prefix or "."
        return await self._executor.list_files(path)

    async def info(self, key: str) -> FileInfo:
        if not await self._executor.file_exists(key):
            raise FileNotFoundError(f"File not found: {key}")
        content = await self._executor.read_file(key)
        return FileInfo(
            key=key,
            size=len(content.encode("utf-8")),
            last_modified=datetime.now(),
            content_type=None,
        )

    async def copy(self, src_key: str, dst_key: str) -> None:
        content = await self._executor.read_file_bytes(src_key)
        await self._executor.write_file_bytes(dst_key, content)

    async def move(self, src_key: str, dst_key: str) -> None:
        await self.copy(src_key, dst_key)
        await self._executor.delete_file(src_key)

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        raise NotImplementedError("ExecutorStorageAdapter does not support URL generation")
