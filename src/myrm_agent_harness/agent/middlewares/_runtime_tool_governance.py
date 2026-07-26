"""Runtime tool governance helpers (prefix-cache safe).

[INPUT]
- langchain_core.messages::HumanMessage (POS: message extraction)
- core.security.tool_registry::resolve_permission_type, resolve_safety_metadata
  (POS: tool capability metadata)

[OUTPUT]
- extract_recent_human_text(): best-effort recent user text extraction
- derive_runtime_allowed_tools(): per-turn allowed-tools restriction decision

[POS]
Lightweight intent-aware tool narrowing that only mutates per-turn
``tool_choice.allowed_tools`` and keeps ``bind_tools`` prefix stable.
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage

from myrm_agent_harness.core.security.tool_registry import (
    resolve_permission_type,
    resolve_safety_metadata,
)

_UI_TOOLS: frozenset[str] = frozenset({"render_ui_tool", "update_ui_data_tool"})

_READ_ONLY_TOOL_ALLOWLIST: frozenset[str] = frozenset(
    {
        "ask_question_tool",
        "request_answer_user_tool",
        "web_search_tool",
        "web_fetch_tool",
        "memory_search_tool",
        "conversation_search_tool",
        "file_read_tool",
        "glob_tool",
        "grep_tool",
        "browser_snapshot_tool",
        "browser_extract_tool",
        "browser_inspect_tool",
        "skill_search_tool",
        "skill_market_tool",
        "skill_select_tool",
    }
)

_READ_ONLY_PERMISSIONS: frozenset[str] = frozenset(
    {
        "file_read",
        "net_fetch",
        "web_fetch",
        "web_search_tool",
        "browser_read",
        "desktop_capture",
        "conversation_search_tool",
        "memory_search_tool",
        "ask_question_tool",
    }
)

_UI_INTENT_KEYWORDS: tuple[str, ...] = (
    "ui",
    "dashboard",
    "chart",
    "table",
    "card",
    "panel",
    "visual",
    "plot",
    "grid",
    "可视化",
    "图表",
    "表格",
    "卡片",
    "面板",
    "仪表盘",
)

_READ_ONLY_INTENT_KEYWORDS: tuple[str, ...] = (
    "explain",
    "analyze",
    "analyse",
    "compare",
    "summary",
    "summarize",
    "review",
    "what",
    "why",
    "how",
    "clarify",
    "解释",
    "分析",
    "对比",
    "比较",
    "总结",
    "评审",
    "是什么",
    "为什么",
    "如何",
)

_ACTION_INTENT_KEYWORDS: tuple[str, ...] = (
    "write",
    "edit",
    "modify",
    "fix",
    "implement",
    "create",
    "delete",
    "remove",
    "run",
    "execute",
    "commit",
    "push",
    "deploy",
    "refactor",
    "build",
    "生成",
    "编写",
    "修复",
    "实现",
    "创建",
    "删除",
    "运行",
    "执行",
    "提交",
    "部署",
    "重构",
    "修改",
    "新增",
)


def extract_recent_human_text(messages: list[object]) -> str | None:
    """Extract the latest human message text from LangChain messages."""
    for message in reversed(messages):
        if not isinstance(message, HumanMessage):
            continue
        text = _content_to_text(message.content)
        if text:
            return text
    return None


def derive_runtime_allowed_tools(
    *,
    tool_names: list[str],
    recent_human_text: str | None,
) -> tuple[frozenset[str] | None, tuple[str, ...]]:
    """Derive a per-turn allowlist for bound tools.

    Returns:
        (allowed_names_or_none, applied_reasons)
    """
    if not tool_names:
        return None, ()

    allowed: set[str] = set(tool_names)
    reasons: list[str] = []
    text = (recent_human_text or "").strip()

    if text and not _has_keyword(text, _UI_INTENT_KEYWORDS):
        removed_ui = allowed & _UI_TOOLS
        if removed_ui:
            allowed -= removed_ui
            reasons.append("ui_intent_gate")

    if text and _is_read_only_intent(text):
        readonly_allowed = {name for name in allowed if _is_read_only_tool(name)}
        if readonly_allowed and readonly_allowed != allowed:
            allowed = readonly_allowed
            reasons.append("readonly_intent_gate")

    if len(allowed) == len(tool_names):
        return None, ()
    if not allowed:
        return None, ()

    return frozenset(allowed), tuple(reasons)


def _is_read_only_intent(text: str) -> bool:
    lowered = text.lower()
    has_readonly_hint = _has_keyword(lowered, _READ_ONLY_INTENT_KEYWORDS) or lowered.endswith(
        ("?", "？")
    )
    has_action_hint = _has_keyword(lowered, _ACTION_INTENT_KEYWORDS)
    return has_readonly_hint and not has_action_hint


def _is_read_only_tool(tool_name: str) -> bool:
    if tool_name in _READ_ONLY_TOOL_ALLOWLIST:
        return True

    permission = resolve_permission_type(tool_name, None)
    if permission in _READ_ONLY_PERMISSIONS:
        return True

    safety = resolve_safety_metadata(tool_name)
    if safety.is_read_only and not safety.is_destructive:
        return True
    return False


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    for keyword in keywords:
        normalized = keyword.lower()
        if _is_ascii_word(normalized):
            if re.search(rf"\b{re.escape(normalized)}\b", lowered):
                return True
            continue
        if normalized in lowered:
            return True
    return False


def _is_ascii_word(keyword: str) -> bool:
    return keyword.isascii() and keyword.isalpha()


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return " ".join(parts)
    return ""

