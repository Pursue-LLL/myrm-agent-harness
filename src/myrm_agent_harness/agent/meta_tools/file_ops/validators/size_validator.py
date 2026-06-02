"""文件大小验证器

验证文件大小是否在允许范围内。

[INPUT]
- (none)

[OUTPUT]
- SizeValidator: class — Size Validator

[POS]
Provides SizeValidator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..constants import MAX_FILE_READ_SIZE_BYTES as MAX_FILE_SIZE_BYTES
from ..constants import MAX_FILE_SIZE_MB
from ..core.operation_context import OperationType
from .base import Validator

if TYPE_CHECKING:
    from ..core.operation_context import OperationContext
    from ..strategies.base import FileSystemStrategy


class SizeValidator(Validator):
    """文件大小验证器

    验证文件大小是否超过限制。
    """

    def __init__(self, strategy: FileSystemStrategy) -> None:
        """初始化验证器

        Args:
            strategy: 文件系统策略
        """
        super().__init__()
        self.strategy = strategy

    async def _do_validate(self, context: OperationContext, path: str) -> None:
        """验证文件大小"""
        # 只对读取和替换操作验证大小
        if context.operation not in (OperationType.VIEW, OperationType.STR_REPLACE):
            return

        # MCP 虚拟路径跳过验证
        if path.startswith("/mcp/"):
            return

        # 检查文件是否存在
        if not await self.strategy.exists(path):
            return  # 文件不存在，由其他验证器处理

        # 检查是否是目录
        if await self.strategy.is_directory(path):
            return  # 目录不需要验证大小

        # 获取文件大小
        try:
            file_size = await self.strategy.get_file_size(path)

            if file_size > MAX_FILE_SIZE_BYTES:
                size_mb = file_size / (1024 * 1024)
                raise ValueError(
                    f"File too large: {path} ({size_mb:.1f}MB > {MAX_FILE_SIZE_MB:.0f}MB). "
                    "Use line range syntax to read specific lines."
                )
        except FileNotFoundError:
            # 文件不存在，由其他验证器处理
            pass
