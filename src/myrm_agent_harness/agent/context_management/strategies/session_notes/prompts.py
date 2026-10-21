"""Session Notes 提示词模板

[INPUT]
- schemas::NoteSection (POS: section 数据结构)

[OUTPUT]
- build_incremental_prompt: 构建增量合并提示词
- build_full_refresh_prompt: 构建全量刷新提示词
- build_section_reminders: 构建超限 section 提醒

[POS]
Session Notes LLM prompt templates. Supports incremental merge (new messages + current notes) and full refresh (complete context + current notes) modes.

"""

from __future__ import annotations

from .schemas import NoteSection, SessionNotes

_SECTION_TEMPLATE = """### {title}
_Description: {description}_
Current content:
{content}"""

_COMMON_RULES = """CRITICAL RULES:
- Output ONLY valid JSON with section keys as keys and updated content as values.
- Write all content in the same language the user was using in the conversation — do not translate or switch languages.
- Preserve all identifiers exactly (file paths, UUIDs, hashes, API endpoints, URLs, error codes, env vars, IP:port). Never simplify or obscure them.
- Write DETAILED, INFO-DENSE content — include specifics like file paths, function names, error messages, exact commands.
- Keep each section within its token limit. If approaching the limit, condense by removing less important details while preserving critical information.
- ALWAYS update "current_state" to reflect the most recent work — this is critical for continuity after compaction.
- Skip sections with no substantial new insights — leave them unchanged rather than adding filler.
- Do NOT reference these instructions in the output."""


def build_incremental_prompt(notes: SessionNotes, new_messages_text: str) -> str:
    """构建增量合并提示词

    只传递新消息 + 当前笔记，让 LLM 增量更新。
    """
    sections_text = _format_sections(notes.sections)
    reminders = _build_section_reminders(notes)

    return f"""Update the session notes by merging new conversation content into the existing notes.

## Current Session Notes
{sections_text}

## New Conversation Content (since last update)
{new_messages_text}

## Instructions
Merge the new content into the existing notes. Update relevant sections with new information.

{_COMMON_RULES}
{reminders}
## Output Format
Return a JSON object where keys are section keys and values are the updated content strings:
{_format_output_schema(notes.sections)}"""


def build_full_refresh_prompt(notes: SessionNotes, full_context_text: str) -> str:
    """构建全量刷新提示词

    传递完整上下文，让 LLM 重建笔记（防止增量合并的信息漂移）。
    """
    sections_text = _format_sections(notes.sections)
    reminders = _build_section_reminders(notes)

    return f"""Rebuild the session notes from the full conversation context. This is a periodic refresh to ensure accuracy.

## Current Session Notes (for reference — may have drifted from actual content)
{sections_text}

## Full Conversation Context
{full_context_text}

## Instructions
Rebuild all sections based on the full conversation. Prioritize accuracy over preserving existing content.

{_COMMON_RULES}
{reminders}
## Output Format
Return a JSON object where keys are section keys and values are the rebuilt content strings:
{_format_output_schema(notes.sections)}"""


def _format_sections(sections: list[NoteSection]) -> str:
    parts: list[str] = []
    for s in sections:
        content = s.content if s.content.strip() else "(empty)"
        parts.append(_SECTION_TEMPLATE.format(title=s.title, description=s.description, content=content))
    return "\n\n".join(parts)


def _format_output_schema(sections: list[NoteSection]) -> str:
    keys = ", ".join(f'"{s.key}": "..."' for s in sections)
    return "```json\n{" + keys + "}\n```"


def _build_section_reminders(notes: SessionNotes) -> str:
    """构建超限 section 提醒"""
    total_tokens = notes.estimate_total_tokens()
    over_budget = total_tokens > notes.config.total_max_tokens

    oversized: list[str] = []
    for s in notes.sections:
        section_tokens = len(s.content) // 4
        if section_tokens > s.max_tokens:
            oversized.append(f'- "{s.title}" is ~{section_tokens} tokens (limit: {s.max_tokens})')

    if not oversized and not over_budget:
        return ""

    parts: list[str] = ["\n## Size Warnings"]
    if over_budget:
        parts.append(
            f"CRITICAL: Total notes are ~{total_tokens} tokens, exceeding the maximum of "
            f"{notes.config.total_max_tokens}. Aggressively condense oversized sections. "
            f'Prioritize keeping "Current State" and "Errors & Corrections" accurate.'
        )
    if oversized:
        label = (
            "Oversized sections to condense"
            if over_budget
            else "The following sections exceed their limit and MUST be condensed"
        )
        parts.append(f"{label}:\n" + "\n".join(oversized))

    return "\n".join(parts)
