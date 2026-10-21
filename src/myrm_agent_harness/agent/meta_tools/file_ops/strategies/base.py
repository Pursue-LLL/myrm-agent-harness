"""文件系统策略基类

定义统一的文件操作接口，由具体策略实现。

活跃策略：
- MCPFileSystemStrategy: 读取 MCP 技能文档
- StorageBackendStrategy: 访问 StorageProvider（本地/Docker/S3等）

[INPUT]
- (none)

[OUTPUT]
- FileSystemStrategy: class — File System Strategy

[POS]
Provides FileSystemStrategy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.operation_context import ViewRange


class FileSystemStrategy(ABC):
    """文件系统策略抽象基类

    定义统一的文件操作接口（策略模式）。

    实现类：
    - MCPFileSystemStrategy: 读取 MCP 虚拟文档（/mcp/ 路径）
    - StorageBackendStrategy: 通过 StorageProvider 访问实际文件
    """

    @abstractmethod
    async def read_file(self, path: str, view_range: ViewRange | None = None) -> list[str]:
        """读取文件内容

        Args:
            path: 文件路径
            view_range: 视图范围（可选）

        Returns:
            文件行列表

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式错误或过大
        """
        pass

    @abstractmethod
    async def write_file(self, path: str, content: str) -> None:
        """写入文件

        Args:
            path: 文件路径
            content: 文件内容

        Raises:
            FileExistsError: 文件已存在（仅用于创建操作）
            PermissionError: 权限不足
        """
        pass

    @abstractmethod
    async def delete_file(self, path: str) -> None:
        """删除文件

        Args:
            path: 文件路径

        Raises:
            FileNotFoundError: 文件不存在
            PermissionError: 权限不足
        """
        pass

    @abstractmethod
    async def replace_text(self, path: str, old_str: str, new_str: str) -> None:
        """替换文件中的文本

        Args:
            path: 文件路径
            old_str: 要替换的文本
            new_str: 替换后的文本

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文本未找到或有多个匹配
        """
        pass

    @abstractmethod
    async def is_directory(self, path: str) -> bool:
        """检查路径是否为目录

        Args:
            path: 文件路径

        Returns:
            是否为目录
        """
        pass

    @abstractmethod
    async def list_directory(self, path: str) -> list[tuple[str, bool, int]]:
        """列出目录内容

        Args:
            path: 目录路径

        Returns:
            (name, is_dir, size) 元组列表

        Raises:
            FileNotFoundError: 目录不存在
            NotADirectoryError: 路径不是目录
        """
        pass

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """检查路径是否存在

        Args:
            path: 文件路径

        Returns:
            是否存在
        """
        pass

    @abstractmethod
    async def get_file_size(self, path: str) -> int:
        """获取文件大小

        Args:
            path: 文件路径

        Returns:
            文件大小（字节）

        Raises:
            FileNotFoundError: 文件不存在
        """
        pass

    @abstractmethod
    def get_actual_path(self, path: str) -> str:
        """获取实际文件路径

        Args:
            path: 相对路径

        Returns:
            绝对路径
        """
        pass
