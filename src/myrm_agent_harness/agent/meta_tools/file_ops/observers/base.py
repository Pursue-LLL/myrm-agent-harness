"""观察者基类

定义文件操作观察者的统一接口。

[INPUT]
- (none)

[OUTPUT]
- FileOperationObserver: class — File Operation Observer

[POS]
Provides FileOperationObserver.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.operation_context import OperationType


class FileOperationObserver(ABC):
    """文件操作观察者抽象基类

    监听文件操作事件并执行相应的处理。
    """

    @abstractmethod
    async def on_file_created(self, path: str, content: str) -> None:
        """文件创建事件

        Args:
            path: 文件路径
            content: 文件内容
        """
        pass

    @abstractmethod
    async def on_file_modified(self, path: str, old_content: str, new_content: str) -> None:
        """文件修改事件

        Args:
            path: 文件路径
            old_content: 修改前的内容
            new_content: 修改后的内容
        """
        pass

    @abstractmethod
    async def on_file_viewed(self, path: str) -> None:
        """文件查看事件

        Args:
            path: 文件路径
        """
        pass

    async def on_operation_complete(self, operation: OperationType, path: str) -> None:  # noqa: B027
        """操作完成事件（可选实现）

        Args:
            operation: 操作类型
            path: 文件路径
        """
        pass
