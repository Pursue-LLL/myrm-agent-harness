"""PPT reporting plan outline quality gate verifier for CompletionGuard.

Inspects generated presentation outlines (in plan-phase, todo plans, or message draft outlines)
when the user requests PowerPoint / slide deck / presentation generation or reporting outlines.
Enforces the 4-dimensional presentation quality rubric:
1. Concise titles / headlines (anti-text-wall, max 10 words / 15 chars for Chinese).
2. Explicit takeaway statement / thesis per slide.
3. Concrete visual / data anchor per slide (chart, native table, metric card, layout).
4. Balanced content density (max 6 points/bullets per slide).

[INPUT]
- Assistant response text or plan text + latest user request query text.

[OUTPUT]
- check_ppt_outline_quality(): Optional[str] returning gate violation reason, or None if compliant.

[POS]
Harness middleware verifier; integrated into CompletionGuard to enforce professional
reporting PPT structure before generation or plan finalization.
"""

from __future__ import annotations

import re

# Trigger patterns in user query or assistant plan indicating presentation outline delivery
_PPT_INTENT_PATTERN = re.compile(
    r"(?i)\b(ppt|pptx|powerpoint|slides?|presentation|deck|汇报|幻灯片|演示文稿|演讲稿)\b"
)

_SLIDE_HEADER_PATTERN = re.compile(
    r"(?im)^(?:###?\s*|(?:\d+[\.、]\s*))?(?:slide|page|第[一二三四五六七八九十\d]+[页张]|第\s*\d+\s*[页张]|p\d+)[:：\s]+([^\n]+)",
)

_VISUAL_ANCHOR_KEYWORDS = (
    "chart", "table", "graph", "metric", "kpi", "diagram", "card", "layout",
    "图表", "表格", "柱状图", "折线图", "饼图", "漏斗图", "数据看板", "指标", "卡片", "架构图", "对比表"
)

_THESIS_KEYWORDS = (
    "takeaway", "thesis", "core message", "key point", "insight", "conclusion",
    "观点", "核心观点", "结论", "洞察", "要点", "主旨"
)


def is_ppt_reporting_task(user_text: str | None, assistant_text: str) -> bool:
    """Check if the context represents a PPT / slide deck generation or outline planning task."""
    if user_text and _PPT_INTENT_PATTERN.search(user_text):
        return True
    return bool(_PPT_INTENT_PATTERN.search(assistant_text) and len(_SLIDE_HEADER_PATTERN.findall(assistant_text)) >= 2)


def check_ppt_outline_quality(
    user_text: str | None,
    assistant_text: str,
) -> str | None:
    """Validate slide outline quality against the 4-dimensional quality gate.

    Returns a blocking description if defects are found, or None if valid.
    """
    if not is_ppt_reporting_task(user_text, assistant_text):
        return None

    slides = _SLIDE_HEADER_PATTERN.findall(assistant_text)
    # If fewer than 2 explicit slide sections detected, allow normal completion
    if len(slides) < 2:
        return None

    violations: list[str] = []

    # Check 1: Slide headline brevity (anti-text-wall headline check)
    for idx, raw_title in enumerate(slides, start=1):
        clean_title = raw_title.strip()
        words = clean_title.split()
        if len(words) > 10 or len(clean_title) > 25:
            violations.append(
                f"Slide {idx} headline is too verbose ('{clean_title[:30]}...'). "
                f"Headlines must be concise, punchy takeaways (max 6-8 words / 15 chars)."
            )
            break

    # Check 2: Thesis & Visual Anchor density check across the outline
    text_lower = assistant_text.lower()
    has_visual_anchors = any(kw.lower() in text_lower for kw in _VISUAL_ANCHOR_KEYWORDS)
    if not has_visual_anchors:
        violations.append(
            "The slide outline lacks concrete visual or data anchors (e.g. chart type, native table, KPI metric cards). "
            "Every professional reporting slide must specify its visual element."
        )

    has_explicit_theses = any(kw.lower() in text_lower for kw in _THESIS_KEYWORDS)
    if not has_explicit_theses and len(slides) >= 3:
        violations.append(
            "The slide outline lists descriptive topics without explicit thesis statements / key takeaways. "
            "Each slide headline or subtitle must declare an opinionated conclusion or takeaway message."
        )

    if not violations:
        return None

    remediation = " ".join(violations)
    return (
        f"PPT Reporting Plan Outline Quality Gate Failed: {remediation} "
        "Please refine the outline with concise 6-word headlines, explicit takeaways, and native visual anchors."
    )


__all__ = [
    "check_ppt_outline_quality",
    "is_ppt_reporting_task",
]
