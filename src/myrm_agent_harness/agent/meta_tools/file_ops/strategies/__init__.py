"""File system strategy module.

提供统一的文件操作接口，根据路径自动选择访问策略。

活跃策略：
- MCPFileSystemStrategy: 读取 MCP 虚拟文档（/mcp/路径）
- StorageBackendStrategy: 统一存储访问（通过 StorageProvider）
"""

from .base import FileSystemStrategy
from .mcp_strategy import MCPFileSystemStrategy
from .storage_strategy import StorageBackendStrategy
from .strategy_factory import FileSystemStrategyFactory

__all__ = [
    "FileSystemStrategy",
    "FileSystemStrategyFactory",
    "MCPFileSystemStrategy",
    "StorageBackendStrategy",
]
