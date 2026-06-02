"""操作上下文

定义文件操作的上下文信息，包含操作类型、参数、元数据等。

[INPUT]
- backends.skills.types::SkillMetadata (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)

[OUTPUT]
- OperationType: class — Operation Type
- ViewRange: class — View Range
- OperationContext: class — Operation Context

[POS]
Provides OperationType, ViewRange, OperationContext.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.types import SkillMetadata
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor


class OperationType(StrEnum):
    """操作类型枚举"""

    VIEW = "view"
    CREATE = "create"
    STR_REPLACE = "str_replace"


@dataclass
class ViewRange:
    """视图行号范围"""

    start: int  # 起始行号（1-indexed）
    end: int  # 结束行号（-1 表示到文件末尾）

    def to_slice(self, total_lines: int) -> tuple[int, int]:
        """转换为切片索引（0-indexed）

        Args:
            total_lines: 文件总行数

        Returns:
            (start_idx, end_idx) 元组
        """
        start_idx = max(0, self.start - 1)
        end_idx = total_lines if self.end == -1 else min(total_lines, self.end)
        return start_idx, end_idx


@dataclass
class OperationContext:
    """文件操作上下文

    存储选择：
    - /mcp/ 路径：使用 skills（不需要 executor）
    - 普通路径：使用 executor 的文件操作方法
    """

    operation: OperationType

    executor: CodeExecutor | None
    skills: list[SkillMetadata] = field(default_factory=list)

    # VIEW 操作参数
    paths: list[str] = field(default_factory=list)

    # CREATE 操作参数
    path: str | None = None
    file_text: str | None = None

    # STR_REPLACE 操作参数
    old_str: str | None = None
    new_str: str | None = None

    # 验证命令（用于文件写入/编辑后的自动校验）
    verify_command: str | None = None

    # 元数据
    reason: str | None = None  # 操作原因（用于日志）

    def validate(self) -> None:
        """验证上下文参数的完整性

        Raises:
            ValueError: 参数不完整或不合法
        """
        if self.operation == OperationType.VIEW:
            if not self.paths:
                raise ValueError("VIEW operation requires 'paths' parameter")

        elif self.operation == OperationType.CREATE:
            if not self.path:
                raise ValueError("CREATE operation requires 'path' parameter")
            if self.file_text is None:
                raise ValueError("CREATE operation requires 'file_text' parameter")

        elif self.operation == OperationType.STR_REPLACE:
            if not self.path:
                raise ValueError("STR_REPLACE operation requires 'path' parameter")
            if self.old_str is None:
                raise ValueError("STR_REPLACE operation requires 'old_str' parameter")
            if self.new_str is None:
                raise ValueError("STR_REPLACE operation requires 'new_str' parameter")
