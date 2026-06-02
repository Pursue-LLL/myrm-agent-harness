"""验证器链

组装和管理验证器链。

[INPUT]
- agent.config::DEFAULT_FILE_IO_CONFIG, (POS: Configuration and type definitions for the Deep Research system. Pure data structures with no business logic dependencies.)

[OUTPUT]
- ValidatorChain: class — Validator Chain

[POS]
Provides ValidatorChain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.agent.config import DEFAULT_FILE_IO_CONFIG, FileIOConfig

from .binary_validator import BinaryValidator
from .path_validator import PathValidator
from .permission_validator import PermissionValidator
from .sensitive_file_validator import SensitiveFileValidator
from .size_validator import SizeValidator

if TYPE_CHECKING:
    from ..core.operation_context import OperationContext
    from ..strategies.base import FileSystemStrategy


class ValidatorChain:
    """验证器链

    组装和管理验证器链。
    """

    def __init__(
        self,
        strategy: FileSystemStrategy,
        allowed_base_paths: list[str] | None = None,
        io_config: FileIOConfig | None = None,
        block_sensitive_reads: bool = False,
    ) -> None:
        """初始化验证器链

        Args:
            strategy: 文件系统策略
            allowed_base_paths: 允许的基础路径列表（可选）
            io_config: I/O 配置（可选，默认使用全局配置）
            block_sensitive_reads: 是否阻止敏感文件读取（默认 False，仅警告）
        """
        config = io_config or DEFAULT_FILE_IO_CONFIG

        # 构建验证器链：
        # 1. 路径验证（路径遍历、符号链接、危险路径）
        # 2. 敏感文件检测（credentials、keys 等）
        # 3. 二进制数据检测（防止写入乱码）
        # 4. 文件大小验证
        # 5. 权限验证（文件存在性、操作合法性）
        self.chain = PathValidator(allowed_base_paths, config)
        self.chain.set_next(
            SensitiveFileValidator(config, block_sensitive_reads)
        ).set_next(BinaryValidator()).set_next(SizeValidator(strategy)).set_next(
            PermissionValidator(strategy)
        )

    async def validate(self, context: OperationContext, path: str) -> None:
        """执行验证链

        Args:
            context: 操作上下文
            path: 文件路径

        Raises:
            ValueError: 验证失败
            PermissionError: 权限不足
        """
        await self.chain.validate(context, path)
