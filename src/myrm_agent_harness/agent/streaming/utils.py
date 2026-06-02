"""Agent 内部工具函数

1. 本文件的 INPUT/OUTPUT/POS 注释
2. agent/context_management/PROMPT_CACHE_PRACTICE.md §2.2 时间戳注入 & Agent 行为规则

[INPUT]
- langchain_core.tools::BaseTool (POS: LangChain 工具基类)
- streaming.model_discipline::AGENT_CORE_RULES (POS: 反叙述 + 工具诚实规则，re-exported as AGENT_BEHAVIOR_RULES)

[OUTPUT]
- DATETIME_TAG, DATETIME_TAG_END, DATETIME_SYSTEM_RULES: 标记常量与系统规则
- AGENT_BEHAVIOR_RULES: 反叙述 + 工具诚实系统规则 (re-export from model_discipline.AGENT_CORE_RULES)
- user_timezone_var, datetime_injection_enabled_var: 上下文变量
- set_user_timezone(): 设置用户时区
- set_datetime_injection_enabled(): 设置是否启用时间戳注入
- get_datetime_prompt(): 生成时间基准提示词
- validate_context(): 验证运行时上下文
- normalize_tool_names(): 规范化工具名称，确保以 _tool 结尾

[POS]
Agent internal utility functions. Provides context validation, timestamp injection,
agent behavior rules (anti-narration + tool honesty), and tool name normalization.

"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.streaming.model_discipline import (
    AGENT_CORE_RULES as AGENT_BEHAVIOR_RULES,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

__all__ = [
    "AGENT_BEHAVIOR_RULES",
    "DATETIME_FORMAT",
    "DATETIME_SYSTEM_RULES",
    "DATETIME_TAG",
    "DATETIME_TAG_END",
]

logger = get_agent_logger(__name__)

# ============================================================================
# 时间戳注入
# ============================================================================

DATETIME_TAG = "<current_datetime>"
DATETIME_TAG_END = "</current_datetime>"
DATETIME_FORMAT = "%Y-%m-%d %H:%M %A"

DATETIME_SYSTEM_RULES = (
    "\n<datetime_rules>"
    "Messages may contain timestamp tags: "
    "`[Sent at: YYYY-MM-DD HH:MM Weekday (UTC±X)]` for historical messages (immutable, preserves Prompt Cache), "
    "or `<current_datetime>YYYY-MM-DD HH:MM:SS Weekday (UTC±X)</current_datetime>` for the current message. "
    'Always use the latest `<current_datetime>` as your only "now" reference for all time-related reasoning.'
    "</datetime_rules>"
)

# ============================================================================
# Agent 行为规则 — canonical source is model_discipline.AGENT_CORE_RULES
# Re-exported here for backward-compatible imports.
# ============================================================================


user_timezone_var: ContextVar[str | None] = ContextVar("user_timezone", default=None)
datetime_injection_enabled_var: ContextVar[bool] = ContextVar(
    "datetime_injection_enabled", default=True
)


def set_user_timezone(timezone: str | None) -> None:
    user_timezone_var.set(timezone)


def set_datetime_injection_enabled(enabled: bool) -> None:
    datetime_injection_enabled_var.set(enabled)


def get_datetime_prompt(timezone: str | None = None, dt: datetime | None = None) -> str:
    """生成时间基准提示词，注入到用户消息中让 LLM 感知当前时间。

    仅包含时间和 UTC offset，说明文案由 System Prompt 中的 datetime_rules 统一声明，
    避免每条消息重复 ~15 tokens。

    Args:
        timezone: IANA 时区标识符（如 "Asia/Shanghai"），None 时使用服务器本地时间。
        dt: 指定时间点。None 时使用 datetime.now()。用于历史消息确定性时间戳注入。

    Example output::

        <current_datetime>2026-03-06 22:30 (UTC+8)</current_datetime>
    """
    now: datetime
    tz_label = ""
    if timezone:
        try:
            tz = ZoneInfo(timezone)
            now = (dt or datetime.now()).astimezone(tz)
            utc_offset = now.utcoffset()
            if utc_offset is not None:
                total_seconds = int(utc_offset.total_seconds())
                sign = "+" if total_seconds >= 0 else "-"
                hours, remainder = divmod(abs(total_seconds), 3600)
                mins = remainder // 60
                offset_str = f"{sign}{hours}:{mins:02d}" if mins else f"{sign}{hours}"
                tz_label = f" (UTC{offset_str})"
            else:
                tz_label = ""
        except Exception:
            logger.warning("Invalid timezone: %s, using server time", timezone)
            now = dt or datetime.now()
    else:
        now = dt or datetime.now()

    current_time_str = now.strftime(DATETIME_FORMAT)

    return f"{DATETIME_TAG}{current_time_str}{tz_label}{DATETIME_TAG_END}"


# ============================================================================
# 上下文验证
# ============================================================================


def validate_context(
    context: dict[str, object] | None, context_schema: type | None
) -> dict[str, object]:
    """验证并处理 context

    Raises:
        ValueError: 当 context 验证失败时
    """
    if context_schema:
        import dataclasses

        if not context:
            raise ValueError(
                f"context is required when context_schema is defined. Expected schema: {context_schema.__name__}"
            )
        try:
            if dataclasses.is_dataclass(context_schema):
                instance = context_schema(**context)
                return dataclasses.asdict(instance)
            validated = context_schema(**context)
            return vars(validated) if hasattr(validated, "__dict__") else context
        except TypeError as e:
            expected_fields = (
                list(dataclasses.fields(context_schema))
                if dataclasses.is_dataclass(context_schema)
                else getattr(context_schema, "__annotations__", {}).keys()
            )
            raise ValueError(
                f"Context validation failed: {e}. "
                f"Expected fields: {[f.name if hasattr(f, 'name') else f for f in expected_fields]}. "
                f"Provided keys: {list(context.keys())}"
            ) from e
        except Exception as e:
            raise ValueError(
                f"Context validation failed for schema {context_schema.__name__}: {e}"
            ) from e
    return context or {}


# ============================================================================
# 工具名称规范化
# ============================================================================


# Meta tools intentionally use stable names without the _tool suffix (LLM-facing contract).
_META_TOOL_NAME_EXEMPT = frozenset({"discover_capability_tool"})


def normalize_tool_names(tools: list[BaseTool]) -> list[BaseTool]:
    """规范化工具名称，确保以 _tool 结尾。过滤非 BaseTool 对象。"""
    result: list[BaseTool] = []
    for tool in tools:
        if not isinstance(tool, BaseTool):
            cls_name = type(tool).__name__
            logger.warning(" Skipping non-BaseTool object in user_tools: %s", cls_name)
            continue
        if tool.name not in _META_TOOL_NAME_EXEMPT and not tool.name.endswith("_tool"):
            original_name = tool.name
            tool.name = f"{tool.name}_tool"
            logger.info(" Tool name normalized: %s -> %s", original_name, tool.name)
        result.append(tool)
    return result
