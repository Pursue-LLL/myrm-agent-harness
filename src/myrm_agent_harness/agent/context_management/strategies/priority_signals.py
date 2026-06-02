"""Priority signal helpers for compression planning.

聚焦信号匹配与优先级调整逻辑独立于 compactor，避免主编排器继续膨胀。

[INPUT]
- (none)

[OUTPUT]
- adjust_group_priority: Adjust group priority using structured focus and goal hints.

[POS]
Priority signal helpers for compression planning.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from langchain_core.messages import AIMessage, ToolMessage

from ..infra.message_priority import MessagePriority

_ASCII_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{2,}")
_CJK_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,12}")
_STOP_TERMS = frozenset(
    {
        "continue",
        "current",
        "issue",
        "problem",
        "please",
        "start",
        "task",
        "that",
        "the",
        "this",
        "with",
        "修复",
        "处理",
        "问题",
        "继续",
        "开始",
        "当前",
    }
)
_MAX_GOAL_TERMS = 8
_MAX_TEXT_SCAN_CHARS = 64000
_EDGE_SCAN_CHARS = 32000


def adjust_group_priority(
    base_priority: MessagePriority,
    group: object,
    *,
    focus_files: frozenset[str] | None,
    focus_modules: frozenset[str] | None,
    user_goal_hint: str,
) -> MessagePriority:
    """Adjust group priority using structured focus and goal hints."""
    if base_priority <= MessagePriority.HIGH_TOOL_ERROR:
        return base_priority

    if _group_matches_focus_signals(
        group, focus_files=focus_files or frozenset(), focus_modules=focus_modules or frozenset()
    ):
        return MessagePriority.HIGH_TOOL_CALL

    if _group_matches_goal_hint(group, user_goal_hint):
        if base_priority >= MessagePriority.LOW_TOOL_SUCCESS:
            return MessagePriority.MEDIUM_TOOL_SUMMARY
        return MessagePriority.HIGH_TOOL_CALL

    return base_priority


def _group_matches_focus_signals(group: object, *, focus_files: frozenset[str], focus_modules: frozenset[str]) -> bool:
    if not focus_files and not focus_modules:
        return False

    lowered_haystacks = _build_group_haystacks(group)
    return _matches_exact_signals(
        lowered_haystacks, (signal.removeprefix("./").lower() for signal in (*focus_files, *focus_modules))
    )


def _group_matches_goal_hint(group: object, user_goal_hint: str) -> bool:
    goal_terms = _extract_goal_terms(user_goal_hint)
    if not goal_terms:
        return False

    lowered_haystacks = _build_group_haystacks(group)
    matched_count = 0
    for term in goal_terms:
        if any(term in haystack for haystack in lowered_haystacks):
            matched_count += 1
            if matched_count >= 2 or "/" in term or "." in term:
                return True
    return False


def _matches_exact_signals(lowered_haystacks: list[str], signals: Iterable[str]) -> bool:
    return any(signal and any(signal in haystack for haystack in lowered_haystacks) for signal in signals)


def _build_group_haystacks(group: object) -> list[str]:
    ai_message = getattr(group, "ai_message", None)
    tool_message = getattr(group, "tool_message", None)
    tool_call = getattr(group, "tool_call", None)

    haystacks: list[str] = []
    if isinstance(tool_call, dict):
        haystacks.append(json.dumps(tool_call, ensure_ascii=False))
    if isinstance(ai_message, AIMessage):
        if isinstance(ai_message.content, str):
            haystacks.append(ai_message.content)
        elif ai_message.content:
            haystacks.append(json.dumps(ai_message.content, ensure_ascii=False))
    if isinstance(tool_message, ToolMessage):
        content = tool_message.content
        if isinstance(content, str):
            haystacks.append(_build_scan_window(content))
        elif content:
            haystacks.append(_build_scan_window(json.dumps(content, ensure_ascii=False)))

    return [item.lower() for item in haystacks if item]


def _build_scan_window(text: str) -> str:
    if len(text) <= _MAX_TEXT_SCAN_CHARS:
        return text
    return f"{text[:_EDGE_SCAN_CHARS]}\n...\n{text[-_EDGE_SCAN_CHARS:]}"


def _extract_goal_terms(user_goal_hint: str) -> tuple[str, ...]:
    normalized = " ".join(user_goal_hint.split()).strip().lower()
    if not normalized:
        return ()

    raw_terms: list[str] = []
    raw_terms.extend(match.group(0).lower() for match in _ASCII_TOKEN_PATTERN.finditer(normalized))
    raw_terms.extend(match.group(0) for match in _CJK_TOKEN_PATTERN.finditer(normalized))

    deduped: list[str] = []
    seen: set[str] = set()
    for term in raw_terms:
        if term in _STOP_TERMS or term in seen:
            continue
        if len(term) < 2:
            continue
        seen.add(term)
        deduped.append(term)
        if len(deduped) >= _MAX_GOAL_TERMS:
            break
    return tuple(deduped)
