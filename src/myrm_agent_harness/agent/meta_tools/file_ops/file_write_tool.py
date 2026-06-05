"""文件写入工具（Claude Code 兼容）

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- core::FileOperationService, OperationContext, OperationType (POS: 文件操作服务和上下文)
- toolkits.code_execution.executors.base::require_executor (POS: 从 ContextVar 获取 executor)
- langchain.tools::tool (POS: LangChain 工具装饰器)
- pydantic::BaseModel, Field (POS: 参数验证)

[OUTPUT]
- FileWriteInput: 文件写入输入参数模型
- create_file_write_tool: 创建文件写入工具的工厂函数

[POS]
File write tool (Claude Code compatible). Creates new files with auto File ID resolution (@file_001), automatic artifact registration, and real-time frontend push.

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.code_execution.executors.base import require_executor
from myrm_agent_harness.utils.errors import ToolError

from .constants import MAX_FILE_WRITE_SIZE_BYTES
from .core import FileOperationService, OperationContext, OperationType

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)


class FileWriteInput(BaseModel):
    """文件写入工具输入参数"""

    path: str = Field(description="文件路径（支持 File ID，如 @file_001）")
    content: str = Field(description="文件内容")
    verify_command: str | None = Field(
        default=None,
        description="写入后自动执行的校验命令（如 'python -m py_compile file.py' 或 'node --check file.js'）。如果校验失败，将拒绝写入并返回错误。",
    )
    reason: str | None = Field(default=None, description="执行命令的原因（可选，用于日志）")


def create_file_write_tool(skills: list[SkillMetadata] | None = None) -> BaseTool:
    """创建文件写入工具

    内部使用 FileOperationService，自动处理：
    - File ID 解析（@file_001 → 实际路径）
    - Artifact 自动注册和实时推送
    - ArtifactTracker 记录
    - 路径安全验证
    - 策略自动选择（StorageBackendStrategy）

    Args:
        skills: MCP 技能列表（保留仅供工具创建时使用）

    Returns:
        file_write_tool 工具函数

    Note:
        StorageProvider 通过 context 注入，不再通过参数传递
    """

    @tool(
        "file_write_tool",
        description="""创建新文件（不能覆盖已有文件，修改已有文件请用 file_edit_tool）。

参数：
- path: 文件路径 (支持普通路径或 "@file_id")
- content: 写入的完整内容
- verify_command: 写入后自动执行的语法/类型校验命令（强烈建议提供，如 'python -m py_compile file.py'）。校验失败会拒绝写入，避免死循环。
- reason: 操作原因（可选）
""",
        args_schema=FileWriteInput,
    )
    async def file_write_func(
        path: str,
        content: str,
        verify_command: str | None = None,
        reason: str | None = None,
        *,  # 强制后续参数为关键字参数
        config: RunnableConfig,  # LangChain 注入的配置
    ) -> str:
        """创建或覆盖文件

        Args:
            path: 文件路径（支持 File ID）
            content: 文件内容
            verify_command: 写入后自动执行的校验命令
            reason: 操作原因（可选，用于日志）
            config: LangChain 运行时配置，包含 context

        Returns:
            操作成功消息

        Raises:
            ValueError: 参数错误
            PermissionError: 权限不足
        """
        logger.info("file_write_func called for path: %s", path)
        try:
            # 检查文件大小（5MB 限制）
            content_bytes = content.encode("utf-8")
            content_size = len(content_bytes)
            if content_size > MAX_FILE_WRITE_SIZE_BYTES:
                size_mb = content_size / 1024 / 1024
                raise ToolError(
                    message=f"File content too large: {size_mb:.2f}MB exceeds 5MB limit",
                    user_hint=(
                        f"The file you're trying to create is {size_mb:.2f}MB, which exceeds the 5MB limit. "
                        "Please reduce the content size or split it into multiple smaller files."
                    ),
                )

            executor = require_executor()

            context = OperationContext(
                operation=OperationType.CREATE,
                executor=executor,
                skills=skills or [],
                path=path,  # 支持 @file_001 格式
                file_text=content,
                verify_command=verify_command,
                reason=reason,  # 操作原因（日志）
            )

            # 创建服务并执行
            service = FileOperationService(context)
            result = await service.execute()
            return result

        except ToolError:
            # ToolError 已经包含友好提示，直接传播
            raise
        except PermissionError as e:
            # 权限不足（如 MCP 虚拟路径、只读文件）
            raise ToolError(
                message=str(e),
                user_hint="Permission denied. You cannot write to this path.",
            ) from e
        except ValueError as e:
            # 参数错误（如路径格式错误）
            raise ToolError(
                message=str(e),
                user_hint="Invalid parameter. Please check the file path and content.",
            ) from e
        except Exception as e:
            # 未预期的错误
            logger.exception(f"Unexpected error in file_write_tool: {e}")
            raise ToolError(
                message=f"Unexpected error during file write: {e}",
                user_hint="An unexpected error occurred. Please check the file path and try again.",
            ) from e

    return file_write_func
