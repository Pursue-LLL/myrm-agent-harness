"""权限验证器

验证文件操作权限。

[INPUT]
- (none)

[OUTPUT]
- PermissionValidator: class — Permission Validator

[POS]
Provides PermissionValidator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.operation_context import OperationType
from .base import Validator

if TYPE_CHECKING:
    from ..core.operation_context import OperationContext
    from ..strategies.base import FileSystemStrategy


class PermissionValidator(Validator):
    """权限验证器

    验证文件操作权限。
    """

    def __init__(self, strategy: FileSystemStrategy) -> None:
        """初始化验证器

        Args:
            strategy: 文件系统策略
        """
        super().__init__()
        self.strategy = strategy

    async def _do_validate(self, context: OperationContext, path: str) -> None:
        """验证操作权限"""
        # CREATE 操作：检查文件是否已存在
        if context.operation == OperationType.CREATE:
            if await self.strategy.exists(path):
                raise FileExistsError(f"File already exists: {path}. Use str_replace to modify existing files.")

        # STR_REPLACE 操作：检查文件是否存在
        elif context.operation == OperationType.STR_REPLACE:
            if not await self.strategy.exists(path):
                raise FileNotFoundError(f"File not found: {path}")

            if await self.strategy.is_directory(path):
                raise IsADirectoryError(f"Cannot replace text in directory: {path}")

        # VIEW 操作：检查路径是否存在
        elif context.operation == OperationType.VIEW and not await self.strategy.exists(path):
            raise FileNotFoundError(f"Path not found: {path}")
