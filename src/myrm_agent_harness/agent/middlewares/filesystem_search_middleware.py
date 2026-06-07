"""文件系统搜索中间件

兼容 LangChain 的中间件，提供文件搜索功能。
这是 LangChain FilesystemFileSearchMiddleware 的增强版替代品，
具有更强的安全性和性能。

特性：
- Glob 搜索（文件名模式）
- Grep 搜索（文件内容正则搜索）
- 增强的安全性（路径遍历防护、ReDoS 防护）
- 性能优化（ripgrep、mmap、缓存、并发）
- 资源限制（超时、结果限制、文件大小限制）
- 审计日志

兼容 LangChain 中间件系统。

[INPUT]
- langchain.agents.middleware::AgentMiddleware (POS: Base middleware class for LangChain agent lifecycle hooks and tool injection.)
- langchain.agents.middleware.types::ToolCallRequest (POS: Typed request object for wrap_tool_call/awrap_tool_call hooks.)
- agent.config::FileIOConfig (POS: Configuration and type definitions for the Deep Research system. Pure data structures with no business logic dependencies.)
- toolkits.storage.base::StorageProvider (POS: Storage provider abstract base class. Defines the unified storage interface contract for all storage backends. Supports file read/write, delete, list, info query, and namespace isolation. Method names use read/write (not get/put), fully compatible with the StorageBackend Protocol.)

[OUTPUT]
- FilesystemFileSearchMiddleware: Example:
- create_filesystem_search_middleware: Args:

[POS]
Provides FilesystemFileSearchMiddleware, create_filesystem_search_middleware.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command

from myrm_agent_harness.agent.config import FileIOConfig

from ..meta_tools.file_search import create_glob_tool, create_grep_tool

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

logger = logging.getLogger(__name__)


class FilesystemFileSearchMiddleware(AgentMiddleware):
    """文件系统搜索中间件（兼容 LangChain）

    为 Agent 提供两个工具：
    1. glob_tool - 通过路径模式搜索文件
    2. grep_tool - 通过正则表达式搜索文件内容

    这是 LangChain FilesystemFileSearchMiddleware 的增强版替代品，
    具有增强的安全性和性能特性。

    Example:
        ```python
        from myrm_agent_harness.agent.middlewares import FilesystemFileSearchMiddleware

        middleware = FilesystemFileSearchMiddleware(
            root_path="/workspace",
            use_ripgrep=True,
            max_file_size_mb=10)

        agent = SkillAgent(
            llm=llm,
            skills=skills,
            middlewares=[middleware])
        ```
    """

    def __init__(
        self,
        root_path: str,
        use_ripgrep: bool = True,
        max_file_size_mb: int = 10,
        max_search_results: int = 100,
        max_search_files: int = 1000,
        search_timeout_seconds: float = 30.0,
        max_regex_length: int = 500,
        enable_audit_log: bool = True,
        storage_backend: StorageProvider | None = None,
    ) -> None:
        """初始化文件系统搜索中间件

        Args:
            root_path: 文件搜索的根目录（必需）
            use_ripgrep: 是否使用 ripgrep 加速搜索（默认: True）
            max_file_size_mb: 最大扫描文件大小（MB）（默认: 10）
            max_search_results: 最大搜索结果数（默认: 100）
            max_search_files: 最大搜索文件数（默认: 1000）
            search_timeout_seconds: 搜索操作超时时间（秒）（默认: 30.0）
            max_regex_length: 最大正则表达式长度（默认: 500）
            enable_audit_log: 是否启用安全审计日志（默认: True）
            storage_backend: 可选的存储后端
        """
        self.root_path = Path(root_path).absolute()
        self.storage_backend = storage_backend

        # Validate root path
        if not self.root_path.exists():
            raise ValueError(f"Root path does not exist: {root_path}")
        if not self.root_path.is_dir():
            raise ValueError(f"Root path is not a directory: {root_path}")

        self.io_config = FileIOConfig(
            max_file_size_bytes=max_file_size_mb * 1024 * 1024,
            max_search_results=max_search_results,
            max_search_files=max_search_files,
            search_timeout_seconds=search_timeout_seconds,
            max_regex_length=max_regex_length,
            enable_audit_log=enable_audit_log,
        )

        # Store ripgrep preference (will be auto-detected by grep_tool)
        self._use_ripgrep = use_ripgrep

        self._tools: list[BaseTool] = self._build_tools()

        logger.info(
            "FilesystemFileSearchMiddleware initialized: root=%s, "
            "ripgrep=%s, max_size=%sMB",
            self.root_path,
            use_ripgrep,
            max_file_size_mb,
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        return await handler(request)

    def _build_tools(self) -> list[BaseTool]:
        """Build glob and grep tools bound to this middleware's config."""
        glob_tool = create_glob_tool(io_config=self.io_config)
        grep_tool = create_grep_tool(io_config=self.io_config)

        glob_tool.description = (
            f"Search for files by path pattern under {self.root_path}. "
            "Supports wildcards (* and **). "
            f"Maximum {self.io_config.max_search_results} results."
        )
        grep_tool.description = (
            f"Search file contents by regex pattern under {self.root_path}. "
            "Supports Python regex syntax. "
            f"Maximum {self.io_config.max_search_results} results, "
            f"timeout {int(self.io_config.search_timeout_seconds)}s."
        )

        return [glob_tool, grep_tool]

    def get_tools(self) -> list[BaseTool]:
        """Return glob and grep tools for registration by the agent framework."""
        return self._tools


# Convenience function for creating middleware
def create_filesystem_search_middleware(
    root_path: str,
    use_ripgrep: bool = True,
    max_file_size_mb: int = 10,
    max_search_results: int = 100,
    max_search_files: int = 1000,
    search_timeout_seconds: float = 30.0,
    storage_backend: StorageProvider | None = None,
) -> FilesystemFileSearchMiddleware:
    """创建文件系统搜索中间件

    便捷函数，匹配 LangChain 的 API。

    Args:
        root_path: 文件搜索的根目录
        use_ripgrep: 是否使用 ripgrep 加速搜索
        max_file_size_mb: 最大扫描文件大小（MB）
        max_search_results: 最大搜索结果数
        max_search_files: 最大搜索文件数
        search_timeout_seconds: 搜索超时时间（秒）
        storage_backend: 可选的存储后端

    Returns:
        FilesystemFileSearchMiddleware 实例

    Example:
        ```python
        middleware = create_filesystem_search_middleware(
            root_path="/workspace",
            use_ripgrep=True)
        ```
    """
    return FilesystemFileSearchMiddleware(
        root_path=root_path,
        use_ripgrep=use_ripgrep,
        max_file_size_mb=max_file_size_mb,
        max_search_results=max_search_results,
        max_search_files=max_search_files,
        search_timeout_seconds=search_timeout_seconds,
        storage_backend=storage_backend,
    )
