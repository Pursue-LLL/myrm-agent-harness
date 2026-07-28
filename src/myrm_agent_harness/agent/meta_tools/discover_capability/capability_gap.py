"""Capability gap detection for discover_capability_tool and stream entitlement preflight.

[INPUT]
- core.security.tool_registry::TOOL_GROUP_MAP (POS: harness tool group SSOT)

[OUTPUT]
- detect_capability_gap: entitlement gap intent hits for preflight
- CAPABILITY_GAP_REGISTRY: substring trigger SSOT for 15 GUI-togglable IDs (excludes skill_market/skill_manage; baseline excluded)
- BUILTIN_TOOL_ID_TO_GROUP: derived view for server catalog parity tests

[POS]
Detects when a user query matches **substring triggers** for a GUI-togglable builtin tool group
that is not enabled on the current Agent profile. Primary runtime consumer: server
``entitlement_gap_preflight`` render_ui **surface_unavailable** intent detection (form-fill queries on IM).
Substring enable-and-resend SSE toasts were removed; registry entries remain for intent matching only.
``skill_market`` / ``skill_manage`` are profile toggles but excluded from this registry (install/author via Settings or explicit profile opt-in).
``AGENT_BASELINE_BUILTIN_TOOLS`` (file_ops, code_execute) are forced at runtime and omitted from
``CAPABILITY_GAP_REGISTRY``.
"""

from __future__ import annotations

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
    CapabilityGapEntry(
        "render_ui",
        "render_ui",
        (
            "render ui",
            "interactive ui",
            "ui artifact",
            "渲染界面",
            "interactive form",
            "multi-field form",
            "fill out",
            "fill in",
            "填表",
            "表单",
            "填写",
            "部署配置",
            "配置表单",
        ),
    ),
    CapabilityGapEntry(
        "structured_clarify",
        "structured_clarify",
        (
            "clarify",
            "clarification form",
            "ask me to choose",
            "澄清",
            "结构化澄清",
            "让我选择",
        ),
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
        "cron",
        "cron",
        (
            "schedule task",
            "cron job",
            "scheduled reminder",
            "定时任务",
            "定时提醒",
            "每天",
        ),
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
    CapabilityGapEntry(
        "external_cli",
        "external_cli",
        (
            "claude code",
            "codex cli",
            "gemini cli",
            "external cli",
            "delegate to agent",
            "外部 cli",
            "委派给",
            "claude code 写代码",
        ),
    ),
)

BUILTIN_TOOL_ID_TO_GROUP: dict[str, str] = {
    entry.tool_id: entry.tool_group for entry in CAPABILITY_GAP_REGISTRY
}


@dataclass(frozen=True, slots=True)
class CapabilityGapHit:
    tool_id: str
    tool_group: str


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
