"""Bound skill catalog delivery — inject stable catalog into HumanMessage prefix.

[INPUT]
- agent.skills.runtime.registry::get_metadata_summary (POS: XML catalog body)
- agent.skills.runtime.catalog_display::resolve_catalog_display_skills (POS: inline SSOT)
- langchain_core.messages::HumanMessage (POS: injection target)

[OUTPUT]
- strip_catalog_blocks(): remove bound_skills blocks from message text
- build_bound_skills_block(): ``<bound_skills hash="…" hidden_count="N">`` wrapper
- ensure_skill_catalog_in_messages(): strip + reinject on first HumanMessage

[POS]
Prompt-cache-safe skill catalog delivery. Dynamic bind list lives in messages[], never
in tool schema (see meta_tools/skills/select/_ARCH.md).
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage

from myrm_agent_harness.agent.skills.runtime.catalog_display import (
    resolve_catalog_display_skills,
)
from myrm_agent_harness.agent.skills.runtime.registry import get_metadata_summary
from myrm_agent_harness.backends.skills.types import SkillMetadata

if TYPE_CHECKING:
    from collections.abc import Sequence

_BOUND_SKILLS_RE = re.compile(
    r"<bound_skills(?:\s+[^>]*)?>.*?</bound_skills>\s*",
    re.DOTALL | re.IGNORECASE,
)
_BOUND_SKILLS_UPDATE_RE = re.compile(
    r"<bound_skills_update(?:\s+hash=\"[^\"]*\")?\s*>.*?</bound_skills_update>\s*",
    re.DOTALL | re.IGNORECASE,
)


def compute_catalog_hash(catalog_body: str) -> str:
    """Stable short hash for a rendered catalog XML body."""
    digest = hashlib.sha256(catalog_body.encode("utf-8")).hexdigest()
    return digest[:16]


def strip_catalog_blocks(text: str) -> str:
    """Remove injected catalog blocks (including user-spoofed copies)."""
    cleaned = _BOUND_SKILLS_UPDATE_RE.sub("", text)
    cleaned = _BOUND_SKILLS_RE.sub("", cleaned)
    return cleaned.lstrip()


def build_bound_skills_block(
    display_skills: list[SkillMetadata],
    *,
    hidden_skill_count: int = 0,
) -> str:
    """Render the full ``<bound_skills>`` block for HumanMessage prepend."""
    catalog_xml = get_metadata_summary(display_skills)
    catalog_hash = compute_catalog_hash(catalog_xml)
    hidden_attr = (
        f' hidden_count="{hidden_skill_count}"' if hidden_skill_count > 0 else ""
    )
    return (
        f'<bound_skills hash="{catalog_hash}"{hidden_attr}>\n{catalog_xml}\n</bound_skills>'
    )


def _strip_message_content(content: str | list[object]) -> str | list[object]:
    if isinstance(content, str):
        return strip_catalog_blocks(content)
    if not isinstance(content, list):
        return content

    updated: list[object] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            text_val = part.get("text")
            if isinstance(text_val, str):
                copied = dict(part)
                copied["text"] = strip_catalog_blocks(text_val)
                updated.append(copied)
                continue
        updated.append(part)
    return updated


def _prepend_block_to_content(
    content: str | list[object], block: str
) -> str | list[object]:
    prefix = f"{block}\n\n"
    if isinstance(content, str):
        body = content.strip()
        return f"{prefix}{body}" if body else block

    if not isinstance(content, list):
        return f"{prefix}{content}"

    updated: list[object] = list(content)
    for idx, part in enumerate(updated):
        if isinstance(part, dict) and part.get("type") == "text":
            text_val = part.get("text")
            if isinstance(text_val, str):
                copied = dict(part)
                body = text_val.strip()
                copied["text"] = f"{prefix}{body}" if body else block
                updated[idx] = copied
                return updated

    updated.insert(0, {"type": "text", "text": block})
    return updated


def _first_human_index(messages: Sequence[BaseMessage]) -> int | None:
    for idx, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            return idx
    return None


def ensure_skill_catalog_in_messages(
    messages: list[BaseMessage],
    skills: list[SkillMetadata],
    *,
    skill_configs: dict[str, dict[str, object]] | None = None,
    available_tool_names: frozenset[str] | None = None,
    available_tool_groups: frozenset[str] | None = None,
) -> None:
    """Strip stale catalog blocks and reinject current bind list on first HumanMessage."""
    if not messages:
        return

    for idx, message in enumerate(messages):
        if not isinstance(message, HumanMessage):
            continue
        content = message.content
        if isinstance(content, (str, list)):
            messages[idx] = HumanMessage(
                content=_strip_message_content(content),
                additional_kwargs=dict(message.additional_kwargs),
            )

    if not skills:
        return

    resolution = resolve_catalog_display_skills(
        skills,
        skill_configs=skill_configs,
        available_tool_names=available_tool_names,
        available_tool_groups=available_tool_groups,
    )
    if not resolution.display_skills and resolution.hidden_skill_count <= 0:
        return

    first_idx = _first_human_index(messages)
    if first_idx is None:
        return

    block = build_bound_skills_block(
        resolution.display_skills,
        hidden_skill_count=resolution.hidden_skill_count,
    )
    first = messages[first_idx]
    assert isinstance(first, HumanMessage)
    first_content = first.content
    if isinstance(first_content, (str, list)):
        messages[first_idx] = HumanMessage(
            content=_prepend_block_to_content(first_content, block),
            additional_kwargs=dict(first.additional_kwargs),
        )


__all__ = [
    "build_bound_skills_block",
    "compute_catalog_hash",
    "ensure_skill_catalog_in_messages",
    "strip_catalog_blocks",
]
