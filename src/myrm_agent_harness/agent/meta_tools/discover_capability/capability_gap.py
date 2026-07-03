"""Capability gap detection for discover_capability_tool.

[INPUT]
- core.security.tool_registry::TOOL_GROUP_MAP (POS: harness tool group SSOT)

[OUTPUT]
- detect_capability_gap / detect_skill_gap: entitlement gap hits
- format_capability_gap_block / format_skill_gap_block: XML blocks for tool messages
- CAPABILITY_GAP_REGISTRY: SSOT for GUI-togglable builtin tool_id → group + triggers (baseline excluded)
- BUILTIN_TOOL_ID_TO_GROUP: derived view for server catalog parity tests

[POS]
Detects when a user query needs a **GUI-togglable** builtin tool group or skill that is not
enabled on the current Agent profile, so discover can surface structured gap hints instead of
bare misses. ``AGENT_BASELINE_BUILTIN_TOOLS`` (file_ops, code_execute) are forced at runtime
and omitted from ``CAPABILITY_GAP_REGISTRY`` — they must never emit entitlement gaps.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class CapabilityGapEntry:
    """Single builtin entitlement gap spec: server tool_id, harness group, match triggers."""

    tool_id: str
    tool_group: str
    triggers: tuple[str, ...]


# Ordered registry: earlier entries win when multiple triggers could match.
# Maps GUI-togglable server tool IDs to harness TOOL_GROUP_MAP keys + gap triggers.
# Agent baseline (file_ops, code_execute) is forced at runtime — not listed here.
CAPABILITY_GAP_REGISTRY: tuple[CapabilityGapEntry, ...] = (
    CapabilityGapEntry(
        "web_search",
        "web",
        (
            "web search",
            "search the web",
            "internet search",
            "google search",
            "联网搜索",
            "网上搜",
            "搜索网页",
            "上网查",
        ),
    ),
    CapabilityGapEntry(
        "memory",
        "memory",
        (
            "remember this",
            "recall from memory",
            "save to memory",
            "记住",
            "回忆",
            "记忆",
            "想起来",
        ),
    ),
    CapabilityGapEntry(
        "browser",
        "browser",
        (
            "browser",
            "browse",
            "webpage",
            "website",
            "selenium",
            "网页",
            "浏览",
            "打开网站",
        ),
    ),
    CapabilityGapEntry(
        "computer_use",
        "computer_use",
        (
            "desktop",
            "screenshot",
            "screen capture",
            "gui click",
            "桌面",
            "截屏",
            "截图",
            "屏幕",
        ),
    ),
    CapabilityGapEntry("wiki", "wiki", ("wiki", "知识库", "personal wiki")),
    CapabilityGapEntry("kanban", "kanban", ("kanban", "看板", "task board")),
    CapabilityGapEntry("canvas", "canvas", ("canvas", "画布", "whiteboard")),
    CapabilityGapEntry(
        "render_ui",
        "render_ui",
        ("render ui", "interactive ui", "ui artifact", "渲染界面"),
    ),
    CapabilityGapEntry(
        "answer_tool",
        "answer_tool",
        (
            "ask the user",
            "confirm with user",
            "request answer",
            "向用户确认",
            "问问用户",
            "让用户选择",
        ),
    ),
    CapabilityGapEntry(
        "planning",
        "planning",
        ("multi-step plan", "task plan", "规划步骤", "任务规划"),
    ),
    CapabilityGapEntry(
        "image_generation",
        "image_generation",
        (
            "generate image",
            "draw picture",
            "dall-e",
            "文生图",
            "生成图片",
            "画图",
        ),
    ),
    CapabilityGapEntry(
        "video_generation",
        "video_generation",
        ("generate video", "text to video", "生成视频", "文生视频"),
    ),
    CapabilityGapEntry("tts", "tts", ("text to speech", "tts", "语音合成", "朗读")),
)

BUILTIN_TOOL_ID_TO_GROUP: dict[str, str] = {
    entry.tool_id: entry.tool_group for entry in CAPABILITY_GAP_REGISTRY
}


@dataclass(frozen=True, slots=True)
class CapabilityGapHit:
    tool_id: str
    tool_group: str


@dataclass(frozen=True, slots=True)
class SkillGapHit:
    skill_id: str


def _normalized_query(query: str) -> str:
    return query.strip().lower()


def detect_capability_gap(
    query: str,
    active_tool_groups: frozenset[str],
) -> CapabilityGapHit | None:
    """Return the first disabled builtin tool group matching *query*."""
    normalized = _normalized_query(query)
    if not normalized:
        return None

    for entry in CAPABILITY_GAP_REGISTRY:
        if entry.tool_group in active_tool_groups:
            continue
        if any(term in normalized for term in entry.triggers):
            return CapabilityGapHit(tool_id=entry.tool_id, tool_group=entry.tool_group)
    return None


def detect_skill_gap(
    query: str,
    bound_skill_names: frozenset[str],
    library_skill_names: frozenset[str],
) -> SkillGapHit | None:
    """Detect when the user names a skill that is not bound to this Agent."""
    for match in re.finditer(r"([a-zA-Z0-9][\w-]*_skill)", query):
        skill_id = match.group(1)
        if skill_id in bound_skill_names:
            continue
        if library_skill_names and skill_id not in library_skill_names:
            continue
        return SkillGapHit(skill_id=skill_id)
    return None


def format_capability_gap_block(hit: CapabilityGapHit) -> str:
    payload = json.dumps(
        {"tool_id": hit.tool_id, "tool_group": hit.tool_group},
        ensure_ascii=False,
    )
    return (
        f"### Capability Gap (enable required builtin tool):\n"
        f"<CapabilityGap>\n{payload}\n</CapabilityGap>"
    )


def format_skill_gap_block(hit: SkillGapHit) -> str:
    payload = json.dumps({"skill_id": hit.skill_id}, ensure_ascii=False)
    return (
        f"### Skill Gap (bind skill to this Agent):\n"
        f"<SkillGap>\n{payload}\n</SkillGap>"
    )
