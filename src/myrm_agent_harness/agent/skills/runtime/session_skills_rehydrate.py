"""Rehydrate loaded skills from chat history at run() start.

[INPUT]
- langchain_core.messages::AIMessage, BaseMessage, ToolMessage (POS: LangChain message types)
- backends.skills.types::SkillMetadata (POS: Skill metadata)
- utils.chat_utils::ChatHistoryReq (POS: Raw chat history entries)

[OUTPUT]
- rehydrate_loaded_skills_from_history(): Restore ContextVar loaded_skills from prior turns

[POS]
Session skill contract persistence without a separate checkpoint store.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.types import SkillMetadata
    from myrm_agent_harness.utils.chat_utils import ChatHistoryReq

logger = logging.getLogger(__name__)

SESSION_LOADED_SKILL_NAMES_CONTEXT_KEY = "session_loaded_skill_names"

_SKILL_SELECT_TOOL_NAMES = frozenset({"skill_select_tool", "skill_select"})
_NEXT_SKILL_ENTRY = re.compile(r"\n[^\n]+_skill：")
_GENERIC_SUCCESS_MARKERS = (
    "Skill executed successfully.",
    "MCP skills executed:",
)


def _try_parse_agent_history(content: str) -> dict[str, object] | None:
    if not content.startswith('{"__agent_history"'):
        return None
    try:
        data = json.loads(content)
        if isinstance(data, dict) and data.get("__agent_history") is True:
            return data
    except (json.JSONDecodeError, TypeError):
        return None
    return None


def _extract_entry_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return " ".join(parts).strip()
    return str(content)


def _normalize_history_messages(
    chat_history: ChatHistoryReq | list[BaseMessage] | None,
) -> list[BaseMessage]:
    if not chat_history:
        return []

    if isinstance(chat_history, list) and chat_history and isinstance(chat_history[0], BaseMessage):
        return list(chat_history)

    messages: list[BaseMessage] = []
    for item in chat_history:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        role, content = item[0], item[1]
        if role != "assistant":
            continue

        text_content = _extract_entry_text(content)
        agent_data = _try_parse_agent_history(text_content)
        if agent_data is None:
            continue

        tool_calls_data = agent_data.get("tool_calls", [])
        if not isinstance(tool_calls_data, list) or not tool_calls_data:
            continue

        lc_tool_calls: list[dict[str, object]] = []
        for idx, tc in enumerate(tool_calls_data):
            if not isinstance(tc, dict):
                continue
            tc_name = str(tc.get("name", ""))
            tc_args = tc.get("args", {})
            if not isinstance(tc_args, dict):
                tc_args = {}
            lc_tool_calls.append(
                {
                    "name": tc_name,
                    "args": tc_args,
                    "id": f"hist_rehydrate_{idx}",
                    "type": "tool_call",
                }
            )

        if lc_tool_calls:
            messages.append(AIMessage(content="", tool_calls=lc_tool_calls))
            for tc in lc_tool_calls:
                messages.append(
                    ToolMessage(
                        content="Skill executed successfully.",
                        tool_call_id=str(tc["id"]),
                        name=str(tc["name"]),
                    )
                )

    return messages


def _tool_call_name(tool_call: object) -> str | None:
    if isinstance(tool_call, dict):
        name = tool_call.get("name")
        return str(name) if name else None
    name_attr = getattr(tool_call, "name", None)
    return str(name_attr) if name_attr else None


def _tool_call_id(tool_call: object) -> str | None:
    if isinstance(tool_call, dict):
        tc_id = tool_call.get("id")
        return str(tc_id) if tc_id else None
    id_attr = getattr(tool_call, "id", None)
    return str(id_attr) if id_attr else None


def _tool_call_args(tool_call: object) -> dict[str, object]:
    if isinstance(tool_call, dict):
        args = tool_call.get("args", {})
        return args if isinstance(args, dict) else {}
    args_attr = getattr(tool_call, "args", None)
    return args_attr if isinstance(args_attr, dict) else {}


def _skill_names_from_args(args: dict[str, object]) -> list[str]:
    raw = args.get("skill_names")
    if isinstance(raw, list):
        return [str(name) for name in raw if name]
    single = args.get("skill_name")
    if isinstance(single, str) and single:
        return [single]
    return []


def _skill_entry_section(tool_content: str, skill_name: str) -> str | None:
    marker = f"{skill_name}："
    start = tool_content.find(marker)
    if start < 0:
        return None
    section_start = start + len(marker)
    rest = tool_content[section_start:]
    next_match = _NEXT_SKILL_ENTRY.search(rest)
    if next_match:
        return rest[: next_match.start()]
    return rest.split("</skills_sop>", 1)[0]


def _skill_entry_succeeded(tool_content: str, skill_name: str) -> bool:
    if "<skills_sop>" not in tool_content:
        return any(marker in tool_content for marker in _GENERIC_SUCCESS_MARKERS)

    section = _skill_entry_section(tool_content, skill_name)
    if section is None:
        return False

    stripped = section.lstrip()
    if stripped.startswith("Error:"):
        return False
    return "Error:" not in stripped


def _is_skill_select_tool_message(name: str | None) -> bool:
    return bool(name) and name in _SKILL_SELECT_TOOL_NAMES


def collect_loaded_skill_names_from_messages(messages: list[BaseMessage]) -> list[str]:
    """Collect successfully loaded skill names in chronological order (deduped)."""
    pending: dict[str, list[str]] = {}
    loaded_order: list[str] = []
    seen: set[str] = set()

    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in msg.tool_calls or []:
                tc_name = _tool_call_name(tc)
                if not _is_skill_select_tool_message(tc_name):
                    continue
                tc_id = _tool_call_id(tc)
                if not tc_id:
                    continue
                skill_names = _skill_names_from_args(_tool_call_args(tc))
                if skill_names:
                    pending[tc_id] = skill_names
            continue

        if not isinstance(msg, ToolMessage) or not _is_skill_select_tool_message(msg.name):
            continue
        if getattr(msg, "status", None) == "error":
            pending.pop(str(msg.tool_call_id), None)
            continue

        skill_names = pending.pop(str(msg.tool_call_id), [])
        content = str(msg.content)
        for skill_name in skill_names:
            if skill_name in seen:
                continue
            if _skill_entry_succeeded(content, skill_name):
                loaded_order.append(skill_name)
                seen.add(skill_name)

    return loaded_order


def merge_loaded_skill_name_sources(
    history_names: list[str],
    session_loaded_skill_names: list[str] | None,
) -> list[str]:
    """Union history-derived and chat-level SSOT skill names (history order first)."""
    merged: list[str] = []
    seen: set[str] = set()
    for name in [*history_names, *(session_loaded_skill_names or [])]:
        if name and name not in seen:
            merged.append(name)
            seen.add(name)
    return merged


def rehydrate_loaded_skills_from_history(
    chat_history: ChatHistoryReq | list[BaseMessage] | None,
    available_skills: list[SkillMetadata],
    session_loaded_skill_names: list[str] | None = None,
) -> list[SkillMetadata]:
    """Rebuild loaded skill metadata from history and optional chat-level SSOT names."""
    messages = _normalize_history_messages(chat_history)
    history_names = collect_loaded_skill_names_from_messages(messages) if messages else []
    merged_names = merge_loaded_skill_name_sources(history_names, session_loaded_skill_names)
    if not merged_names:
        return []

    by_name = {s.name: s for s in available_skills}
    rehydrated: list[SkillMetadata] = []
    for skill_name in merged_names:
        skill_meta = by_name.get(skill_name)
        if skill_meta is not None:
            rehydrated.append(skill_meta)
        else:
            logger.debug("Skipping rehydrate for unknown skill '%s'", skill_name)

    if rehydrated:
        logger.info(
            "Rehydrated %d loaded skill(s) (history=%d, ssot=%d): %s",
            len(rehydrated),
            len(history_names),
            len(session_loaded_skill_names or []),
            [s.name for s in rehydrated],
        )
    return rehydrated
