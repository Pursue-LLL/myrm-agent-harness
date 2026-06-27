"""文件编辑工具（Claude Code 兼容）

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- core::FileOperationService, OperationContext, OperationType (POS: 文件操作服务和上下文)
- toolkits.code_execution.executors.base::require_executor (POS: 从 ContextVar 获取 executor)
- langchain.tools::tool (POS: LangChain 工具装饰器)
- pydantic::BaseModel, Field (POS: 参数验证)

[OUTPUT]
- FileEditInput: 文件编辑输入参数模型
- create_file_edit_tool: 创建文件编辑工具的工厂函数

[POS]
File edit tool (Claude Code compatible). Supports precise search-and-replace text editing with auto File ID resolution, artifact updates, multi-match detection, and integrity checks.

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.code_execution.executors.base import require_executor
from myrm_agent_harness.utils.errors import ToolError

from .core import FileOperationService, OperationContext, OperationType

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)


class FileEditInput(BaseModel):
    """文件编辑工具输入参数"""

    path: str = Field(description="文件路径（支持 File ID，如 @file_001）")
    old_str: str = Field(description="要替换的文本（必须精确匹配）")
    new_str: str = Field(description="替换后的文本")
    verify_command: str | None = Field(
        default=None,
        description="编辑后自动执行的校验命令（如 'python -m py_compile file.py' 或 'node --check file.js'）。如果校验失败，将回滚编辑并返回错误。",
    )
    reason: str | None = Field(default=None, description="执行命令的原因（可选，用于日志）")


def create_file_edit_tool(skills: list[SkillMetadata] | None = None) -> BaseTool:
    """创建文件编辑工具

    内部使用 FileOperationService，自动处理：
    - File ID 解析（@file_001 → 实际路径）
    - Artifact 自动更新
    - ArtifactTracker 记录
    - 多重匹配检测（防止误替换）
    - 路径安全验证
    - 策略自动选择（StorageBackendStrategy）

    Args:
        skills: MCP 技能列表（保留仅供工具创建时使用）

    Returns:
        file_edit_tool 工具函数

    Note:
        StorageProvider 通过 context 注入，不再通过参数传递
    """

    @tool(
        "file_edit_tool",
        description="""精确编辑文件内容（字符串替换）。当需要修改文件时，必须使用本工具而非 bash sed/awk/perl。

参数：
- path: 文件路径 (支持普通路径或 "@file_id")
- old_str: 要替换的文本 (必须唯一且精确匹配，含缩进)
- new_str: 替换后的文本
- verify_command: 编辑后自动执行的语法/类型校验命令（强烈建议提供，如 'python -m py_compile file.py'）。校验失败会自动回滚，避免破坏代码。
- reason: 操作原因（可选）
""",
        args_schema=FileEditInput,
    )
    async def file_edit_func(
        path: str,
        old_str: str,
        new_str: str,
        verify_command: str | None = None,
        reason: str | None = None,
        *,  # 强制后续参数为关键字参数
        config: RunnableConfig,  # LangChain 注入的配置
    ) -> str:
        """精确编辑文件

        Args:
            path: 文件路径（支持 File ID）
            old_str: 要替换的文本
            new_str: 替换后的文本
            verify_command: 编辑后自动执行的校验命令
            reason: 操作原因（可选，用于日志）
            config: LangChain 运行时配置，包含 context

        Returns:
            操作成功消息

        Raises:
            ValueError: old_str 不存在或出现多次
            FileNotFoundError: 文件不存在
            PermissionError: 权限不足
        """
        try:
            executor = require_executor()

            context = OperationContext(
                operation=OperationType.STR_REPLACE,
                executor=executor,
                skills=skills or [],
                path=path,  # 支持 @file_001 格式
                old_str=old_str,
                new_str=new_str,
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
        except FileNotFoundError as e:
            # 文件不存在
            raise ToolError(
                message=str(e), user_hint="The file does not exist. Use file_write_tool to create it first."
            ) from e
        except PermissionError as e:
            # 权限不足（如 MCP 虚拟路径、只读文件）
            raise ToolError(message=str(e), user_hint="Permission denied. You cannot edit this file.") from e
        except ValueError as e:
            # 参数错误（如 old_str 不存在、出现多次）
            # FileOperationService 会抛出 ValueError("String not found" 或 "String appears N times")
            error_str = str(e).lower()
            if "not found" in error_str:
                hint = "The old_str was not found in the file. Please check the exact text (including whitespace and indentation)."
            elif "appears" in error_str and "times" in error_str:
                hint = "The old_str appears multiple times in the file. Please provide a more specific string with more context."
            else:
                hint = "Invalid parameter. Please check the file path and text to replace."

            raise ToolError(message=str(e), user_hint=hint) from e
        except Exception as e:
            # 未预期的错误
            logger.exception(f"Unexpected error in file_edit_tool: {e}")
            raise ToolError(
                message=f"Unexpected error during file edit: {e}",
                user_hint="An unexpected error occurred. Please check the file path and parameters.",
            ) from e

    return file_edit_func
