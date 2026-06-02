"""错误处理工具模块

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- langchain_core.messages::BaseMessage (POS: LangChain 消息类型)

[OUTPUT]
- ToolError: Agent 工具执行错误（诊断信息 + 修复建议 + format_for_llm 协议）
- format_error_message(): 格式化异常信息
- log_and_format_error(): 记录日志并格式化异常信息
- ModelOutputValidator: 模型输出验证器

[POS]
Framework-level error handling. Defines ToolError (implementing format_for_llm protocol) and ModelOutputValidator for structured error reporting.

"""

from __future__ import annotations

import logging
import traceback

from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

# ============================================================================
# Agent 工具异常类
# ============================================================================


class ToolError(Exception):
    """Agent 工具执行错误（诊断信息 + 修复建议 + format_for_llm 协议）。

    tool_interceptor_middleware 通过 ``format_for_llm()`` 方法获取结构化错误信息
    传递给 LLM，使其能基于诊断上下文做出恢复决策。

    Attributes:
        message: 错误消息（技术细节）
        user_hint: 给 LLM 的提示（如何修复或重试）
        diagnostic_info: 诊断信息（错误分类、上下文、根因分析）
        recovery_suggestions: 修复建议列表（按优先级排序）
        error_code: 错误代码（用于分类和统计）

    Example:
        >>> raise ToolError(
        ...     message="Container exited with code 255",
        ...     user_hint="You may have used a return value with an unclear structure.",
        ...     diagnostic_info={
        ...         "error_category": "execution_failure",
        ...         "exit_code": 255,
        ...         "last_output": "...",
        ...     },
        ...     recovery_suggestions=[
        ...         "Check if the return value is JSON serializable",
        ...         "Verify the command syntax is correct",
        ...         "Try running the command with simpler arguments",
        ...     ],
        ...     error_code="SANDBOX_EXIT_255",
        ... )
    """

    def __init__(
        self,
        message: str,
        user_hint: str = "",
        *,
        diagnostic_info: dict[str, object] | None = None,
        recovery_suggestions: list[str] | None = None,
        error_code: str | None = None,
    ):
        super().__init__(message)
        self.user_hint = user_hint
        self.diagnostic_info = diagnostic_info or {}
        self.recovery_suggestions = recovery_suggestions or []
        self.error_code = error_code

    def format_for_llm(self) -> str:
        """Format error for LLM consumption with full diagnostic context."""
        parts = [f"Error: {self.args[0]}"]

        if self.error_code:
            parts.append(f"Error Code: {self.error_code}")

        if self.user_hint:
            parts.append(f"\nHint: {self.user_hint}")

        if self.diagnostic_info:
            parts.append("\nDiagnostic Info:")
            for key, value in self.diagnostic_info.items():
                parts.append(f" - {key}: {value}")

        if self.recovery_suggestions:
            parts.append("\nRecovery Suggestions:")
            for i, suggestion in enumerate(self.recovery_suggestions, 1):
                parts.append(f" {i}. {suggestion}")

        return "\n".join(parts)


# ============================================================================
# 错误格式化工具
# ============================================================================


def format_error_message(exception: Exception, context: str = "", include_traceback: bool = False) -> str:
    """格式化异常信息

    Args:
        exception: 异常对象
        context: 错误上下文描述
        include_traceback: 是否包含堆栈跟踪信息

    Returns:
        格式化后的错误信息字符串
    """
    error_type = type(exception).__name__
    error_msg = str(exception)

    if not error_msg or error_msg.strip() == "":
        error_msg = repr(exception)

    if not error_msg or error_msg.strip() == "":
        error_msg = f"{error_type} occurred"

    if context:
        formatted_error = f"{context} - {error_type}: {error_msg}"
    else:
        formatted_error = f"{error_type}: {error_msg}"

    if include_traceback:
        tb = traceback.format_exc()
        formatted_error += f"\nStack trace:\n{tb}"

    return formatted_error


def log_and_format_error(
    exception: Exception,
    context: str = "",
    include_traceback: bool = False,
) -> str:
    """记录日志并格式化异常信息

    Args:
        exception: 异常对象
        context: 错误上下文描述
        include_traceback: 是否包含堆栈跟踪信息

    Returns:
        格式化后的错误信息字符串
    """
    formatted_error = format_error_message(exception, context, include_traceback)
    logger.warning(formatted_error)

    return formatted_error


# ============================================================================
# 模型输出验证
# ============================================================================


class ModelOutputValidator:
    """模型输出验证器 - 统一检测和处理模型输出异常"""

    @staticmethod
    def validate_model_output(output_data: object) -> dict[str, object]:
        """验证模型输出，返回验证结果

        Args:
            output_data: 模型输出数据

        Returns:
            Dict包含: has_content, has_tool_calls, extracted_text, is_valid, error_msg
        """
        has_content = False
        has_tool_calls = False
        extracted_text = ""
        error_msg = None

        try:
            if isinstance(output_data, BaseMessage):
                content_payload = output_data.content
                if isinstance(content_payload, str):
                    extracted_text = content_payload
                elif isinstance(content_payload, list):
                    extracted_text = " ".join(map(str, content_payload))
                else:
                    extracted_text = str(content_payload)

                has_tool_calls = bool(getattr(output_data, "tool_calls", None))

            elif isinstance(output_data, str):
                extracted_text = output_data

            else:
                extracted_text = str(output_data)
                if hasattr(output_data, "tool_calls"):
                    has_tool_calls = bool(getattr(output_data, "tool_calls", None))

            has_content = bool(extracted_text and extracted_text.strip())
            is_valid = has_content or has_tool_calls

            if not is_valid:
                error_msg = "This model may have limited support for tool invocation capabilities"

        except Exception as e:
            error_msg = f"Model output validation failed: {e!s}"
            is_valid = False

        return {
            "has_content": has_content,
            "has_tool_calls": has_tool_calls,
            "extracted_text": extracted_text,
            "is_valid": is_valid,
            "error_msg": error_msg,
        }

    @staticmethod
    def create_model_capability_error() -> RuntimeError:
        """创建模型能力不足的标准错误"""
        return RuntimeError("This model may have limited support for tool invocation capabilities")
