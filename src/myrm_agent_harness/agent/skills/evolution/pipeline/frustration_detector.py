"""Frustration signal detector for skill evolution.

Detects user style/behavior frustration signals (distinct from factual corrections)
via lightweight regex patterns. Zero LLM cost — pure CPU.

Frustration signals indicate the user is unhappy with HOW the agent performed
(style, verbosity, format), not WHAT it got wrong (factual errors).

[INPUT]
- Conversation messages (Sequence[dict[str, str]])

[OUTPUT]
- FrustrationSignal: Detected frustration type and matched text
- detect_frustration: Entry point for frustration detection

[POS]
Frustration signal detector for skill evolution pipeline.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class FrustrationCategory(StrEnum):
    """Category of detected frustration signal."""

    VERBOSITY = "verbosity"
    STYLE = "style"
    FORMAT = "format"
    WORKFLOW = "workflow"
    GENERAL = "general"


@dataclass(frozen=True, slots=True)
class FrustrationSignal:
    """Detected frustration signal with category and evidence."""

    category: FrustrationCategory
    matched_text: str
    user_message: str


_FRUSTRATION_SCAN_WINDOW = 4

_VERBOSITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bjust give me (?:the )?(?:answer|code|result)\b", re.IGNORECASE),
    re.compile(r"\bstop explain(?:ing)?\b", re.IGNORECASE),
    re.compile(r"\btoo (?:verbose|wordy|long|much (?:text|explanation))\b", re.IGNORECASE),
    re.compile(r"\bdon'?t (?:need|want) (?:the )?explain", re.IGNORECASE),
    re.compile(r"\bskip (?:the )?(?:explanation|preamble|intro)\b", re.IGNORECASE),
    re.compile(r"\bget to the point\b", re.IGNORECASE),
    re.compile(r"\bwhy are you explain", re.IGNORECASE),
    re.compile(r"太啰嗦"),
    re.compile(r"太冗[长余]"),
    re.compile(r"(?:别|不要|不用|少)(?:说|写)?(?:那么多|这么多)(?:废话|解释)?"),
    re.compile(r"直接给(?:我)?(?:答案|代码|结果)"),
    re.compile(r"简[洁短](?:一?点|些)"),
    re.compile(r"废话太多"),
    re.compile(r"多余的(?:解释|说明)"),
)

_STYLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bstop doing (?:that|this|it)\b", re.IGNORECASE),
    re.compile(r"\byou always do (?:this|that)\b", re.IGNORECASE),
    re.compile(r"\bI hate (?:when|that|it when) you\b", re.IGNORECASE),
    re.compile(r"\bdon'?t (?:do|add|write|put) (?:that|this|it)", re.IGNORECASE),
    re.compile(r"\bplease stop\b", re.IGNORECASE),
    re.compile(r"\bI(?:'ve| have) told you (?:before|already|many times)\b", re.IGNORECASE),
    re.compile(r"\bhow many times\b", re.IGNORECASE),
    re.compile(r"(?:别|不要|禁止|停止)(?:再|总是|一直)?(?:这样|那样)(?:做|写|搞)"),
    re.compile(r"以后(?:都)?(?:别|不要|不用)"),
    re.compile(r"说了(?:多少|很多|好几)次"),
    re.compile(r"你总是"),
    re.compile(r"烦死了"),
    re.compile(r"每次都(?:这样|那样)"),
)

_FORMAT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bdon'?t (?:use|format|output|return) .*(?:markdown|table|bullet|list|heading)\b", re.IGNORECASE),
    re.compile(r"\bno (?:markdown|tables?|headers?|bullets?)\b", re.IGNORECASE),
    re.compile(r"\bplain ?text (?:only|please)\b", re.IGNORECASE),
    re.compile(r"\bdon'?t format (?:like|it like) (?:this|that)\b", re.IGNORECASE),
    re.compile(r"\bstop (?:using|adding) (?:emojis?|emoji)\b", re.IGNORECASE),
    re.compile(r"不要(?:用|返回|给我).*(?:表格|markdown|列表|标题)"),
    re.compile(r"(?:别|不要|不用).*(?:格式化|排版)"),
    re.compile(r"纯文本(?:就[行好]|即可)"),
    re.compile(r"不要加(?:emoji|表情)"),
)

_WORKFLOW_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bdon'?t (?:ask|check|confirm) (?:me )?(?:every|each|before)\b", re.IGNORECASE),
    re.compile(r"\bjust do it\b", re.IGNORECASE),
    re.compile(r"\bstop asking\b", re.IGNORECASE),
    re.compile(r"\bdon'?t wait for (?:my |me to )?confirm\b", re.IGNORECASE),
    re.compile(r"(?:别|不要|不用)(?:总是|每次都)?(?:问我|确认|询问)"),
    re.compile(r"直接做(?:就[行好]|吧)"),
    re.compile(r"不用等我确认"),
)

_GENERAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bremember (?:this|that)\b.*\bdon'?t\b", re.IGNORECASE),
    re.compile(r"\bnever (?:do|add|write) (?:that|this|it) again\b", re.IGNORECASE),
    re.compile(r"\bfrom now on\b", re.IGNORECASE),
    re.compile(r"以后(?:注意|记住)"),
)

_CATEGORY_PATTERN_MAP: tuple[tuple[FrustrationCategory, tuple[re.Pattern[str], ...]], ...] = (
    (FrustrationCategory.VERBOSITY, _VERBOSITY_PATTERNS),
    (FrustrationCategory.STYLE, _STYLE_PATTERNS),
    (FrustrationCategory.FORMAT, _FORMAT_PATTERNS),
    (FrustrationCategory.WORKFLOW, _WORKFLOW_PATTERNS),
    (FrustrationCategory.GENERAL, _GENERAL_PATTERNS),
)


def detect_frustration(messages: Sequence[dict[str, str]]) -> FrustrationSignal | None:
    """Detect frustration signals from recent user messages.

    Scans the last few user messages for frustration patterns across
    categories (verbosity, style, format, workflow). Returns the first
    match found (highest priority category first).

    Returns None if no frustration signal is detected.
    """
    recent = messages[-_FRUSTRATION_SCAN_WINDOW:]

    for msg in recent:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "").strip()
        if not content:
            continue

        for category, patterns in _CATEGORY_PATTERN_MAP:
            for pattern in patterns:
                match = pattern.search(content)
                if match:
                    return FrustrationSignal(
                        category=category,
                        matched_text=match.group(0),
                        user_message=content[:500],
                    )

    return None
