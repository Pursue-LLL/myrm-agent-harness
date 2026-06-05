"""观察者管理器

管理和通知所有观察者。

[INPUT]
- (none)

[OUTPUT]
- ObserverManager: class — Observer Manager

[POS]
Provides ObserverManager.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import FileOperationObserver

if TYPE_CHECKING:
    from ..core.operation_context import OperationType


class ObserverManager:
    """观察者管理器

    管理观察者列表并分发事件通知。
    """

    def __init__(self) -> None:
        """初始化观察者管理器"""
        self.observers: list[FileOperationObserver] = []

    def register(self, observer: FileOperationObserver) -> None:
        """注册观察者

        Args:
            observer: 观察者实例
        """
        self.observers.append(observer)

    def unregister(self, observer: FileOperationObserver) -> None:
        """注销观察者

        Args:
            observer: 观察者实例
        """
        self.observers.remove(observer)

    async def notify_file_created(self, path: str, content: str) -> None:
        """通知文件创建事件

        Args:
            path: 文件路径
            content: 文件内容
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            "notify_file_created called for %s, observers count: %d",
            path,
            len(self.observers),
        )
        for observer in self.observers:
            logger.info("Calling on_file_created on observer: %s", type(observer).__name__)
            try:
                await observer.on_file_created(path, content)
            except Exception as e:
                logger.error(
                    "Error in observer %s: %s",
                    type(observer).__name__,
                    e,
                    exc_info=True,
                )

    async def notify_file_modified(self, path: str, old_content: str, new_content: str) -> None:
        """通知文件修改事件

        Args:
            path: 文件路径
            old_content: 修改前的内容
            new_content: 修改后的内容
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            "notify_file_modified called for %s, observers count: %d",
            path,
            len(self.observers),
        )
        for observer in self.observers:
            logger.info("Calling on_file_modified on observer: %s", type(observer).__name__)
            try:
                await observer.on_file_modified(path, old_content, new_content)
            except Exception as e:
                logger.error(
                    "Error in observer %s: %s",
                    type(observer).__name__,
                    e,
                    exc_info=True,
                )

    async def notify_file_viewed(self, path: str) -> None:
        """通知文件查看事件

        Args:
            path: 文件路径
        """
        for observer in self.observers:
            await observer.on_file_viewed(path)

    async def notify_operation_complete(self, operation: OperationType, path: str) -> None:
        """通知操作完成事件

        Args:
            operation: 操作类型
            path: 文件路径
        """
        for observer in self.observers:
            await observer.on_operation_complete(operation, path)
