"""验证器基类

定义验证器的统一接口。

[INPUT]
- (none)

[OUTPUT]
- Validator: class — Validator

[POS]
Provides Validator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.operation_context import OperationContext


class Validator(ABC):
    """验证器抽象基类

    实现责任链模式，每个验证器负责特定的验证逻辑。
    """

    def __init__(self) -> None:
        """初始化验证器"""
        self._next_validator: Validator | None = None

    def set_next(self, validator: Validator) -> Validator:
        """设置下一个验证器

        Args:
            validator: 下一个验证器

        Returns:
            下一个验证器（用于链式调用）
        """
        self._next_validator = validator
        return validator

    async def validate(self, context: OperationContext, path: str) -> None:
        """执行验证

        Args:
            context: 操作上下文
            path: 文件路径

        Raises:
            ValueError: 验证失败
            PermissionError: 权限不足
        """
        # 执行当前验证器的验证逻辑
        await self._do_validate(context, path)

        # 调用下一个验证器
        if self._next_validator:
            await self._next_validator.validate(context, path)

    @abstractmethod
    async def _do_validate(self, context: OperationContext, path: str) -> None:
        """执行具体的验证逻辑

        Args:
            context: 操作上下文
            path: 文件路径

        Raises:
            ValueError: 验证失败
            PermissionError: 权限不足
        """
        pass
