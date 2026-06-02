"""Container persistent storage backend


[INPUT]
- myrm_agent_harness.agent.security.path_security::safe_join_path (POS: Path security checks)
- _fs_backend::BaseFileSystemBackend (POS: file system storage backend base class)
- base::StorageError (POS: storage exception types)
- pathlib::Path (POS: Python path library)
- aiofiles.os (POS: true async file I/O)
- asyncio, os (POS: Python standard library)

[OUTPUT]
- PersistentStorageBackend: container persistent storage backend (implements StorageProvider protocol)
- PERSISTENT_PREFIXES: default persistent path prefix set

[POS]
Container persistent storage backend. Intelligently routes to /persistent or /workspace by path prefix:
- artifacts/, .memories/, .checkpoints/, skills/ → /persistent (survives restarts)
- other → /workspace (temporary, lost on restart)
Inherits BaseFileSystemBackend; common I/O operations and errno error handling provided by base class.
This class only handles path routing (_route_path/_resolve_key_to_path) and specific logic (idempotent delete, dual-volume list).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path

import aiofiles.os

from ._fs_backend import BaseFileSystemBackend
from .base import StorageError

logger = logging.getLogger(__name__)

PERSISTENT_PREFIXES = frozenset(
    {
        "artifacts/",
        ".memories/",
        ".checkpoints/",
        "skills/",
        "users/",
    }
)


class PersistentStorageBackend(BaseFileSystemBackend):
    """容器持久化Storage后端

     based on PathPrefix智能路由File to 持久化Storage or temporary工作区：
    - 持久化Path (artifacts/, .memories/  etc.) → /persistent
    - temporaryPath → /workspace

    Args:
        persistent_path: 持久化卷Path（Default: /persistent）
        workspace_path: 工作区卷Path（Default: /workspace）
        namespace: Namespace（optional）， for Path隔离
        persistent_prefixes: custom持久化Prefix（None =  using default value）
    """

    def __init__(
        self,
        persistent_path: str = "/persistent",
        workspace_path: str = "/workspace",
        namespace: str | None = None,
        persistent_prefixes: frozenset[str] | None = None,
    ):
        super().__init__(namespace)
        self.persistent_path = Path(persistent_path)
        self.workspace_path = Path(workspace_path)
        self.persistent_prefixes = persistent_prefixes or PERSISTENT_PREFIXES

        self.persistent_path.mkdir(parents=True, exist_ok=True)
        self.workspace_path.mkdir(parents=True, exist_ok=True)

        namespace_info = f" (namespace: {self.namespace})" if self.namespace else ""
        logger.info(
            f"PersistentStorageBackend Initialize: "
            f"persistent={self.persistent_path}, workspace={self.workspace_path}{namespace_info}"
        )

    # ── Path路由 ────────────────────────────────────────

    def _route_path(self, key: str) -> tuple[Path, bool]:
        """路由File to 持久化Storage or 工作区

         使用 safe_join_path 确保路径安全，防止路径遍历、空字节和符号链接攻击。

        Args:
            key: FileKey（如 "artifacts/report.pdf"）

        Returns:
            (resolved_path, is_persistent) 元组

        Raises:
            StorageError: Path越界
        """
        from myrm_agent_harness.core.security.path_security import safe_join_path

        key_normalized = os.path.normpath(key).lstrip("/")

        if self.namespace:
            key_normalized = os.path.normpath(f"{self.namespace}/{key_normalized}")

        is_persistent = any(key_normalized.startswith(prefix) for prefix in self.persistent_prefixes)
        base = self.persistent_path if is_persistent else self.workspace_path

        try:
            full_path = safe_join_path(base, key_normalized)
        except ValueError as e:
            raise StorageError(str(e)) from e

        return (full_path, is_persistent)

    def _resolve_key_to_path(self, key: str) -> Path:
        """Base class模板Methodimplements，委托给 _route_path"""
        path, _ = self._route_path(key)
        return path

    # ── 覆写：幂 etc.Delete ─────────────────────────────────

    async def delete(self, key: str) -> None:
        """DeleteFile（幂 etc.：File not Exists时OnlyRecordWarning）"""
        path = self._resolve_key_to_path(key)

        if not await aiofiles.os.path.exists(str(path)):
            logger.warning(f"File not found for deletion: {key}")
            return

        if await aiofiles.os.path.isfile(str(path)):
            await aiofiles.os.remove(str(path))
        elif await aiofiles.os.path.isdir(str(path)):
            await asyncio.to_thread(shutil.rmtree, path)

        logger.debug(f"DeleteFile: {key}")

    # ── 覆写：双卷List ─────────────────────────────────

    async def _list_in_volume(self, prefix: str, base_path: Path, recursive: bool) -> list[str]:
        """ in single卷 in 列出File"""
        if prefix:
            key_normalized = os.path.normpath(prefix).lstrip("/")
            if self.namespace:
                key_normalized = os.path.normpath(f"{self.namespace}/{key_normalized}")
            start_path = Path(os.path.normpath(base_path / key_normalized))
        elif self.namespace:
            start_path = Path(os.path.normpath(base_path / self.namespace))
        else:
            start_path = base_path

        if not await aiofiles.os.path.exists(str(start_path)):
            return []

        def _scan(dir_path: Path) -> list[str]:
            if not dir_path.is_dir():
                return []
            pattern = dir_path.rglob("*") if recursive else dir_path.iterdir()
            return [str(item.relative_to(base_path)) for item in pattern if item.is_file()]

        return await asyncio.to_thread(_scan, start_path)

    async def list(self, prefix: str = "", recursive: bool = True) -> list[str]:
        """列出File（Merge persistent  and  workspace 两个Storage）

        Args:
            prefix: PathPrefix
            recursive: Whetherrecursive列出子Directory

        Returns:
            去重Sorted相对PathList
        """
        persistent_files, workspace_files = await asyncio.gather(
            self._list_in_volume(prefix, self.persistent_path, recursive),
            self._list_in_volume(prefix, self.workspace_path, recursive),
        )
        return sorted(set(persistent_files + workspace_files))
