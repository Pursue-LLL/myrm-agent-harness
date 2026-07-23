"""文件编辑工具（Claude Code 兼容）

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- core::FileOperationService, OperationContext, OperationType (POS: 文件操作服务和上下文)
- toolkits.code_execution.executors.base::require_executor (POS: 从 ContextVar 获取 executor)
- langchain.tools::tool (POS: LangChain 工具装饰器)
- pydantic::BaseModel, Field (POS: 参数验证)

[OUTPUT]
- StrReplaceEditInput, FileEditInput: 文件编辑输入参数模型
- create_file_edit_tool: 创建 file_edit_tool 工厂函数

[POS]
File edit tool. Batch atomic search-and-replace via edits[] with File ID resolution, fuzzy fallback, integrity gates, and verify rollback.

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, model_validator

from myrm_agent_harness.toolkits.code_execution.executors.base import require_executor
from myrm_agent_harness.utils.errors import ToolError

from .core import FileOperationService, OperationContext, OperationType, StrReplaceEdit
from .file_edit_normalizer import normalize_edits_payload

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)


class StrReplaceEditInput(BaseModel):
    """Single search-and-replace edit."""

    old_str: str = Field(
        description="Text to replace (must be unique in file; include indentation)"
    )
    new_str: str = Field(
        default="", description="Replacement text (empty string deletes old_str)"
    )


class FileEditInput(BaseModel):
    """文件编辑工具输入参数"""

    path: str = Field(description="File path (supports File ID such as @file_001)")
    edits: list[StrReplaceEditInput] = Field(
        description=(
            "Ordered list of search-and-replace edits applied atomically in one transaction. "
            "Each edit uses exact match (fuzzy fallback). Max 20 edits; disjoint regions recommended."
        )
    )
    verify_command: str | None = Field(
        default=None,
        description=(
            "Optional post-edit verify command (e.g. 'python -m py_compile file.py'). "
            "On failure, all edits roll back."
        ),
    )
    reason: str | None = Field(default=None, description="Optional reason for logs")

    @model_validator(mode="before")
    @classmethod
    def normalize_llm_payload(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        if (
            payload.get("edits") is not None
            or "old_str" in payload
            or "old_string" in payload
        ):
            payload["edits"] = normalize_edits_payload(payload)
        return payload


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
        description="""精确编辑文件内容（有序字符串替换）。当需要修改文件时，必须使用本工具而非 bash sed/awk/perl。

参数：
- path: 文件路径 (支持普通路径或 "@file_id")
- edits: JSON 数组 [{old_str, new_str}]，单次调用原子写入（最多 20 条）。每条 old_str 必须唯一且精确匹配（含缩进）；建议区域不重叠。
- verify_command: 编辑后自动执行的语法/类型校验命令（强烈建议，如 'python -m py_compile file.py'）。校验失败会回滚全部 edits。
- reason: 操作原因（可选）
""",
        args_schema=FileEditInput,
    )
    async def file_edit_func(
        path: str,
        edits: list[StrReplaceEditInput],
        verify_command: str | None = None,
        reason: str | None = None,
        *,  # 强制后续参数为关键字参数
        config: RunnableConfig,  # LangChain 注入的配置
    ) -> str:
        """精确编辑文件（批量原子替换）"""
        try:
            executor = require_executor()

            edit_tuple = tuple(
                StrReplaceEdit(old_str=item.old_str, new_str=item.new_str)
                for item in edits
            )

            context = OperationContext(
                operation=OperationType.STR_REPLACE,
                executor=executor,
                skills=skills or [],
                path=path,
                edits=edit_tuple,
                verify_command=verify_command,
                reason=reason,
            )

            service = FileOperationService(context)
            result = await service.execute()
            return result

        except ToolError:
            raise
        except FileNotFoundError as e:
            raise ToolError(
                message=str(e),
                user_hint="The file does not exist. Use file_write_tool to create it first.",
            ) from e
        except PermissionError as e:
            raise ToolError(
                message=str(e),
                user_hint="Permission denied. You cannot edit this file.",
            ) from e
        except ValueError as e:
            error_str = str(e).lower()
            if "not found" in error_str:
                hint = (
                    "An old_str was not found. Check exact text (whitespace/indentation) "
                    "or combine overlapping edits."
                )
            elif "appears" in error_str and "times" in error_str:
                hint = "An old_str matches multiple times. Add surrounding context to make it unique."
            elif "overlap" in error_str:
                hint = "Edits overlap in the file. Merge into one edit or reorder so regions are disjoint."
            else:
                hint = "Invalid edit parameters. Check path and edits array."

            raise ToolError(message=str(e), user_hint=hint) from e
        except Exception as e:
            logger.exception(f"Unexpected error in file_edit_tool: {e}")
            raise ToolError(
                message=f"Unexpected error during file edit: {e}",
                user_hint="An unexpected error occurred. Please check the file path and parameters.",
            ) from e

    return file_edit_func
