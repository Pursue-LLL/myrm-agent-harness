"""External evidence gate helpers for CompletionGuard.

Detects freshness-sensitive user requests and verifies that the session
CallRecord window contains successful web/browser/MCP PTC bash evidence
before allowing completion.

[INPUT]
- langchain_core.messages::HumanMessage (POS: human turn content extraction)
- agent.security.guards.loop_guard::CallRecord (POS: loop guard types)

[OUTPUT]
- build_external_evidence_reason(): block reason when evidence is required but missing
- has_external_evidence(): True when web/browser or MCP PTC bash evidence exists
- extract_latest_human_text(): latest non-empty human message text

[POS]
CompletionGuard external-evidence policy module. Mirrors deliverable_write_verifier
separation — keeps completion_guard.py focused on orchestration and mixed-message guard.
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage

_MCP_PTC_BASH_MARKER = "skills.mcp_"

_EXTERNAL_EVIDENCE_TOOLS: frozenset[str] = frozenset(
    {
        "web_search_tool",
        "web_fetch_tool",
        "browser_navigate_tool",
        "browser_extract_tool",
        "browser_snapshot_tool",
        "browser_inspect_tool",
    }
)

_EXTERNAL_FRESHNESS_KEYWORDS: tuple[str, ...] = (
    "latest",
    "today",
    "current",
    "real-time",
    "realtime",
    "live",
    "news",
    "price",
    "stock",
    "最新",
    "今天",
    "当前",
    "实时",
    "新闻",
    "价格",
    "行情",
    "刚刚",
)

_EXTERNAL_CITATION_KEYWORDS: tuple[str, ...] = (
    "source",
    "sources",
    "citation",
    "citations",
    "reference",
    "references",
    "来源",
    "出处",
    "链接",
    "官网",
)

_EXTERNAL_WEB_HINT_KEYWORDS: tuple[str, ...] = (
    "web",
    "internet",
    "online",
    "search",
    "website",
    "网址",
    "网页",
    "网站",
    "搜索",
    "联网",
)


def extract_latest_human_text(messages: list[object]) -> str | None:
    for message in reversed(messages):
        if not isinstance(message, HumanMessage):
            continue
        if isinstance(message.content, str):
            text = message.content.strip()
            if text:
                return text
            continue
        if isinstance(message.content, list):
            parts: list[str] = []
            for item in message.content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            if parts:
                return " ".join(parts)
    return None


def _requires_external_evidence(user_text: str) -> bool:
    lowered = user_text.lower()
    if _contains_keyword(lowered, _EXTERNAL_FRESHNESS_KEYWORDS):
        return True
    has_citation = _contains_keyword(lowered, _EXTERNAL_CITATION_KEYWORDS)
    has_web_hint = _contains_keyword(lowered, _EXTERNAL_WEB_HINT_KEYWORDS)
    return has_citation and has_web_hint


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    for keyword in keywords:
        normalized = keyword.lower()
        if _is_ascii_word(normalized):
            if re.search(rf"\b{re.escape(normalized)}\b", text):
                return True
            continue
        if normalized in text:
            return True
    return False


def _is_ascii_word(keyword: str) -> bool:
    return keyword.isascii() and keyword.isalpha()


def _bash_command_text(args: object) -> str:
    if not isinstance(args, dict):
        return ""
    command = args.get("command")
    if isinstance(command, str):
        return command
    code = args.get("code")
    if isinstance(code, str):
        return code
    return ""


def _bash_mcp_ptc_evidence_succeeded(record: object) -> bool:
    """True when bash executed a successful MCP PTC import path (skills.mcp_*)."""
    tool_name = getattr(record, "tool_name", "")
    if tool_name != "bash_code_execute_tool":
        return False
    success_level = getattr(record, "success_level", None)
    if getattr(success_level, "name", "") == "FAILURE":
        return False
    args = getattr(record, "args", None)
    return _MCP_PTC_BASH_MARKER in _bash_command_text(args)


def has_external_evidence(records: list[object]) -> bool:
    for record in records:
        if _bash_mcp_ptc_evidence_succeeded(record):
            return True
        tool_name = getattr(record, "tool_name", "")
        if tool_name not in _EXTERNAL_EVIDENCE_TOOLS:
            continue
        success_level = getattr(record, "success_level", None)
        if getattr(success_level, "name", "") == "FAILURE":
            continue
        return True
    return False


def build_external_evidence_reason(
    *,
    messages: list[object],
    records: list[object],
) -> str | None:
    latest_human = extract_latest_human_text(messages)
    if not latest_human or not _requires_external_evidence(latest_human):
        return None
    if has_external_evidence(records):
        return None
    excerpt = latest_human.replace("\n", " ").strip()
    if len(excerpt) > 200:
        excerpt = f"{excerpt[:200]}..."
    return f"latest user request hints external/freshness need: '{excerpt}'"


__all__ = [
    "build_external_evidence_reason",
    "extract_latest_human_text",
    "has_external_evidence",
]
