"""External evidence gate helpers for CompletionGuard.

Detects freshness-sensitive user requests and verifies that the session
CallRecord window contains successful web/browser/MCP evidence before
allowing completion. MCP evidence covers both PTC bash imports
(``skills.mcp_*``) and Direct FC tool calls (``mcp__{server}__{tool}``).
Intercepted calls (``success_level is None``) never count as evidence —
an unexecuted tool provides no external data.

Local code-work requests (e.g. "analyze the latest code changes") are
exempted from the freshness gate: their "latest" phrasing refers to the
user's own repository, not external data, so forcing a web search would
be meaningless. An explicit external hint (links/sources/web) suppresses
the exemption.

[INPUT]
- langchain_core.messages::HumanMessage (POS: human turn content extraction)
- agent.security.guards.loop_guard::CallRecord (POS: loop guard types)
- toolkits.mcp.config::is_mcp_tool_name (POS: Direct FC MCP tool-name recognition)

[OUTPUT]
- build_external_evidence_reason(): block reason when evidence is required but missing
- has_external_evidence(): True when web/browser or MCP evidence exists
- extract_latest_human_text(): latest non-empty human message text

[POS]
CompletionGuard external-evidence policy module. Mirrors deliverable_write_verifier
separation — keeps completion_guard.py focused on orchestration and mixed-message guard.
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage

from myrm_agent_harness.toolkits.mcp.config import is_mcp_tool_name

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

# 本地代码工作线索：命中表示用户要的是自己代码库/项目内的"最新"状态，
# 而非外部新鲜数据——此时不应触发外部证据门（否则本地任务会被逼着联网）。
_EXTERNAL_LOCAL_WORK_KEYWORDS: tuple[str, ...] = (
    "代码",
    "项目",
    "文件",
    "仓库",
    "提交",
    "模块",
    "接口",
    "改动",
    "重构",
    "函数",
    "逻辑",
    "分支",
    "测试",
    "脚本",
    "日志",
    "code",
    "project",
    "file",
    "repo",
    "repository",
    "git",
    "commit",
    "module",
    "interface",
    "refactor",
    "function",
    "logic",
    "branch",
    "test",
    "tests",
    "testing",
    "script",
    "scripts",
    "log",
    "logs",
)


def extract_latest_human_text(messages: list[object]) -> str | None:
    from myrm_agent_harness.agent.skills.runtime.skill_catalog_delivery import (
        strip_catalog_blocks,
    )

    for message in reversed(messages):
        if not isinstance(message, HumanMessage):
            continue
        if isinstance(message.content, str):
            text = strip_catalog_blocks(message.content).strip()
            if text:
                return text
            continue
        if isinstance(message.content, list):
            parts: list[str] = []
            for item in message.content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        cleaned = strip_catalog_blocks(text).strip()
                        if cleaned:
                            parts.append(cleaned)
            if parts:
                return " ".join(parts)
    return None


def _has_external_hint(text: str) -> bool:
    """True when the request explicitly asks for external material (links/sources/web)."""
    return _contains_keyword(
        text, _EXTERNAL_CITATION_KEYWORDS + _EXTERNAL_WEB_HINT_KEYWORDS
    )


def _requires_external_evidence(user_text: str) -> bool:
    lowered = user_text.lower()
    if _contains_keyword(lowered, _EXTERNAL_FRESHNESS_KEYWORDS):
        # 本地代码工作上下文豁免：用户问的是自己代码库里的"最新"状态
        # （如"最新改动的代码逻辑"），并非要外部新鲜数据——要求联网只会
        # 让 Agent 执行无意义的搜索。只要用户明确要求外部材料（链接/来源/
        # 搜索/网站），豁免即被抑制，仍强制外部证据。
        if _contains_keyword(lowered, _EXTERNAL_LOCAL_WORK_KEYWORDS) and not (
            _has_external_hint(lowered)
        ):
            return False
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
    return ""


def _bash_mcp_ptc_evidence_succeeded(record: object) -> bool:
    """True when bash executed a successful MCP PTC import path (skills.mcp_*).

    Intercepted calls (``success_level is None``) never count as evidence —
    an unexecuted tool provides no external data.
    """
    tool_name = getattr(record, "tool_name", "")
    if tool_name != "bash_code_execute_tool":
        return False
    success_level = getattr(record, "success_level", None)
    if success_level is None:
        return False
    if getattr(success_level, "name", "") == "FAILURE":
        return False
    args = getattr(record, "args", None)
    return _MCP_PTC_BASH_MARKER in _bash_command_text(args)


def _mcp_direct_evidence_succeeded(record: object) -> bool:
    """True when a Direct FC MCP tool call succeeded (mcp__{server}__{tool}).

    Small MCP servers (schema <= Direct FC threshold) are bound as first-class
    tools rather than routed through bash PTC, so their tool name — not a
    ``skills.mcp_*`` bash import — is the external evidence marker.

    Intercepted calls (``success_level is None``) never count as evidence —
    an unexecuted tool provides no external data.
    """
    tool_name = getattr(record, "tool_name", "")
    if not is_mcp_tool_name(tool_name):
        return False
    success_level = getattr(record, "success_level", None)
    if success_level is None:
        return False
    return getattr(success_level, "name", "") != "FAILURE"


def has_external_evidence(records: list[object]) -> bool:
    for record in records:
        if _bash_mcp_ptc_evidence_succeeded(record):
            return True
        if _mcp_direct_evidence_succeeded(record):
            return True
        tool_name = getattr(record, "tool_name", "")
        if tool_name not in _EXTERNAL_EVIDENCE_TOOLS:
            continue
        success_level = getattr(record, "success_level", None)
        if success_level is None:
            continue
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
