"""Builtin tool capability gap detection for discover_capability_tool.

When a user request needs a tool group that is not enabled on the current Agent,
return structured gap hints instead of a bare "not found" message.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

# Maps server ``enabled_builtin_tools`` IDs to harness TOOL_GROUP_MAP keys.
BUILTIN_TOOL_ID_TO_GROUP: dict[str, str] = {
    "web_search": "web",
    "memory": "memory",
    "file_ops": "file_ops",
    "code_execute": "shell",
    "browser": "browser",
    "computer_use": "computer_use",
    "wiki": "wiki",
    "kanban": "kanban",
    "canvas": "canvas",
    "answer_tool": "answer_tool",
    "render_ui": "render_ui",
    "planning": "planning",
    "image_generation": "image_generation",
    "video_generation": "video_generation",
    "tts": "tts",
}


@dataclass(frozen=True, slots=True)
class CapabilityGapHit:
    tool_id: str
    tool_group: str


@dataclass(frozen=True, slots=True)
class SkillGapHit:
    skill_id: str


# (tool_id, trigger terms — lowercase substrings)
_GAP_TRIGGERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("browser", ("browser", "browse", "webpage", "website", "selenium", "网页", "浏览", "打开网站")),
    ("computer_use", ("desktop", "screenshot", "screen capture", "gui click", "桌面", "截屏", "截图", "屏幕")),
    ("wiki", ("wiki", "知识库", "personal wiki")),
    ("kanban", ("kanban", "看板", "task board")),
    ("canvas", ("canvas", "画布", "whiteboard")),
    ("render_ui", ("render ui", "interactive ui", "ui artifact", "渲染界面")),
    ("planning", ("multi-step plan", "task plan", "规划步骤", "任务规划")),
    ("image_generation", ("generate image", "draw picture", "dall-e", "文生图", "生成图片", "画图")),
    ("video_generation", ("generate video", "text to video", "生成视频", "文生视频")),
    ("tts", ("text to speech", "tts", "语音合成", "朗读")),
    ("file_ops", ("read file", "write file", "edit file", "glob", "grep", "读文件", "写文件", "改文件")),
    ("code_execute", ("run shell", "bash", "terminal", "execute script", "命令行", "运行脚本", "执行命令")),
)


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

    for tool_id, triggers in _GAP_TRIGGERS:
        group = BUILTIN_TOOL_ID_TO_GROUP.get(tool_id)
        if group is None or group in active_tool_groups:
            continue
        if any(term in normalized for term in triggers):
            return CapabilityGapHit(tool_id=tool_id, tool_group=group)
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
