"""文件系统策略工厂

根据路径自动选择合适的访问策略。

策略选择：
- /mcp/ 路径 → MCPFileSystemStrategy（读取技能文档）
- 普通路径 → StorageBackendStrategy（通过 Executor 适配器访问文件）

[INPUT]
- backends.skills.types::SkillMetadata (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)
- toolkits.storage.base::StorageProvider (POS: Storage provider abstract base class. Defines the unified storage interface contract for all storage backends. Supports file read/write, delete, list, info query, and namespace isolation. Method names use read/write (not get/put), fully compatible with the StorageBackend Protocol.)
- agent.meta_tools.file_ops.executor_storage_adapter::ExecutorStorageAdapter (POS: CodeExecutor to StorageProvider adapter.)

[OUTPUT]
- FileSystemStrategyFactory: class — File System Strategy Factory

[POS]
Provides FileSystemStrategyFactory.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import FileSystemStrategy
from .mcp_strategy import MCPFileSystemStrategy
from .storage_strategy import StorageBackendStrategy

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.types import SkillMetadata
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor
    from myrm_agent_harness.toolkits.storage.base import StorageProvider


class FileSystemStrategyFactory:
    """文件系统策略工厂"""

    @staticmethod
    def create_strategy(
        path: str,
        skills: list[SkillMetadata],
        executor: CodeExecutor | None = None,
        storage_backend: StorageProvider | None = None,
    ) -> FileSystemStrategy:
        """根据路径自动选择策略

        优先使用 executor，回退到 storage_backend。
        """
        if path.startswith("/mcp/"):
            return MCPFileSystemStrategy(skills)

        backend = storage_backend
        if executor is not None and backend is None:
            from myrm_agent_harness.agent.meta_tools.file_ops.executor_storage_adapter import ExecutorStorageAdapter

            backend = ExecutorStorageAdapter(executor)

        if backend is None:
            raise ValueError("executor or storage_backend is required for non-MCP paths.")
        return StorageBackendStrategy(backend)
