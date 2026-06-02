"""StorageBackendStrategy - 存储提供者策略

通过 StorageProvider 接口访问文件，支持多种底层存储。

支持的存储类型：
- ExecutorStorageAdapter: 将 CodeExecutor 适配为 StorageProvider
- LocalStorageBackend: 本地存储（用于用户文件）
- 业务层可实现自定义云存储后端

[INPUT]
- toolkits.storage.base::StorageProvider (POS: Storage provider abstract base class. Defines the unified storage interface contract for all storage backends. Supports file read/write, delete, list, info query, and namespace isolation. Method names use read/write (not get/put), fully compatible with the StorageBackend Protocol.)

[OUTPUT]
- StorageBackendStrategy: class — Storage Backend Strategy

[POS]
Provides StorageBackendStrategy.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import FileSystemStrategy

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

    from ..core.operation_context import ViewRange


class StorageBackendStrategy(FileSystemStrategy):
    """存储提供者策略

    通过 StorageProvider 接口访问文件，支持多种底层存储实现。

    StorageProvider 可以是：
    - ExecutorStorageAdapter（将 CodeExecutor 适配为 StorageProvider）
    - LocalStorageBackend（用户文件存储）
    - 业务层实现的云存储后端
    """

    def __init__(self, storage_backend: StorageProvider) -> None:
        """初始化策略

        Args:
            storage_backend: StorageProvider 实例
                           自动支持 namespace 隔离
        """
        self.storage = storage_backend

    async def read_file(
        self, path: str, view_range: ViewRange | None = None
    ) -> list[str]:
        """读取文件内容"""
        if not await self.storage.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        try:
            content = await self.storage.get_text(path)
            lines = content.split("\n")

            # 应用视图范围（如果指定）
            if view_range:
                start = max(0, view_range.start - 1)
                end = view_range.end if view_range.end != -1 else len(lines)
                lines = lines[start:end]

            return lines
        except UnicodeDecodeError as e:
            raise ValueError(f"File is not text format: {path}") from e

    async def write_file(self, path: str, content: str) -> None:
        """写入文件"""
        await self.storage.put_text(path, content)

    async def delete_file(self, path: str) -> None:
        """删除文件"""
        if not await self.storage.exists(path):
            raise FileNotFoundError(f"File not found: {path}")
        await self.storage.delete(path)

    async def replace_text(self, path: str, old_str: str, new_str: str) -> None:
        """Replace text in a file with progressive fuzzy matching fallback.

        Tries exact match first (zero overhead). On failure, falls back to
        fuzzy_replace which applies 8-strategy progressive chain.
        Preserves original line endings (CRLF/LF) across edits.
        """
        if not await self.storage.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        content = await self.storage.get_text(path)

        from ..utils.line_endings import detect_line_ending, normalize_line_endings

        original_eol = detect_line_ending(content)

        if old_str in content:
            count = content.count(old_str)
            if count > 1:
                raise ValueError(
                    f"Found {count} matches. Please provide more context to make the match unique."
                )
            new_content = content.replace(old_str, new_str, 1)
            if original_eol:
                new_content = normalize_line_endings(new_content, original_eol)
            await self.storage.put_text(path, new_content)
            return

        from myrm_agent_harness.utils.fuzzy_match import find_closest_lines, fuzzy_replace

        result = fuzzy_replace(content, old_str, new_str)
        if result.success:
            logger.info(
                "Fuzzy match succeeded: strategy=%s confidence=%.2f path=%s",
                result.strategy,
                result.confidence,
                path,
            )
            final = result.content
            if original_eol:
                final = normalize_line_endings(final, original_eol)
            await self.storage.put_text(path, final)
            return

        err_msg = f"Text not found in file: {path}\nSearched for:\n{old_str}"
        hint = find_closest_lines(old_str, content)
        if hint:
            err_msg += hint
        raise ValueError(err_msg)

    async def is_directory(self, path: str) -> bool:
        """检查路径是否为目录"""
        if hasattr(self.storage, "is_dir"):
            return await self.storage.is_dir(path)
        # 回退：以 / 结尾视为目录
        return path.endswith("/")

    async def list_directory(self, path: str) -> list[tuple[str, bool, int]]:
        """列出目录内容"""
        # 确保路径以 / 结尾
        prefix = path if path.endswith("/") else f"{path}/"

        try:
            files = await self.storage.list(prefix=prefix, recursive=False)

            result: list[tuple[str, bool, int]] = []
            for file_path in files:
                # 移除前缀，只保留文件名
                name = file_path[len(prefix) :].split("/")[0]
                is_dir = file_path.endswith("/")

                # 获取文件大小
                size = 0
                if not is_dir:
                    try:
                        info = await self.storage.info(file_path)
                        size = info.size
                    except Exception:
                        pass

                result.append((name, is_dir, size))

            return result
        except Exception as e:
            raise FileNotFoundError(f"Failed to list directory: {path}") from e

    async def exists(self, path: str) -> bool:
        """检查路径是否存在"""
        return await self.storage.exists(path)

    async def get_file_size(self, path: str) -> int:
        """获取文件大小"""
        if not await self.storage.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        try:
            info = await self.storage.info(path)
            return info.size
        except Exception:
            # 回退：读取内容计算大小
            content = await self.storage.get_text(path)
            return len(content.encode("utf-8"))

    def get_actual_path(self, path: str) -> str:
        """获取实际文件路径

        如果 storage_backend 支持路径解析（如 ExecutorStorageAdapter），返回实际路径。
        否则返回相对路径（对于云存储等没有本地路径的存储）。
        """
        if hasattr(self.storage, "_get_full_path") and callable(
            self.storage._get_full_path
        ):
            return self.storage._get_full_path(path)  # type: ignore[attr-defined]

        # 对于其他 StorageProvider，返回路径本身
        # （云存储等没有"实际路径"的概念）
        return path
