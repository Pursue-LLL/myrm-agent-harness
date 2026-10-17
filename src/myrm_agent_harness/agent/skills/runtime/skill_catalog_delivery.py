"""Bound skill catalog delivery — a frozen baseline in the conversation plus tail updates.

[INPUT]
- agent.skills.runtime.registry::get_metadata_summary (POS: XML catalog body)
- agent.skills.runtime.catalog_display::resolve_catalog_display_skills (POS: inline SSOT)
- langchain_core.messages::HumanMessage (POS: injection target)

[OUTPUT]
- RenderedCatalog / render_bound_skills_catalog(): the catalog the current bind list resolves to
- strip_catalog_blocks() / strip_catalog_blocks_from_message(): remove catalog blocks from message text
- build_bound_skills_block(): ``<bound_skills hash="…" hidden_count="N">`` baseline wrapper
- build_bound_skills_update_block(): ``<bound_skills_update hash="…">`` tail wrapper carrying the full list
- ensure_skill_catalog_in_messages(): strip + baseline on the first HumanMessage of a rebuilt history
- first_human_index(): where a baseline or an update is written
- last_delivered_catalog_key() / plan_catalog_update() / prepend_catalog_update(): tail delivery for a continued thread

[POS]
Prompt-cache-safe skill catalog delivery. The baseline is written once, into the first
HumanMessage of a conversation that is (re)built, and is never rewritten: any changed byte in
the prefix invalidates the provider cache of everything after it. When the bind list drifts,
the new full list is prepended to the new HumanMessage as an update the model reads as superseding
earlier lists. What the thread last delivered is read from the thread's own messages, so a
compaction that drops the blocks makes the next turn deliver the list again. Dynamic bind
list lives in messages[], never in tool schema (see meta_tools/skills/select/_ARCH.md).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage

from myrm_agent_harness.agent.skills.runtime.catalog_display import (
    resolve_catalog_display_skills,
)
from myrm_agent_harness.agent.skills.runtime.registry import get_metadata_summary
from myrm_agent_harness.backends.skills.types import SkillMetadata

if TYPE_CHECKING:
    from collections.abc import Sequence

EMPTY_CATALOG_KEY = "empty"

_BOUND_SKILLS_RE = re.compile(
    r"<bound_skills(?:\s+[^>]*)?>.*?</bound_skills>\s*",
    re.DOTALL | re.IGNORECASE,
)
_BOUND_SKILLS_UPDATE_RE = re.compile(
    r"<bound_skills_update(?:\s+[^>]*)?>.*?</bound_skills_update>\s*",
    re.DOTALL | re.IGNORECASE,
)
_DELIVERED_KEY_RE = re.compile(r'<bound_skills(?:_update)?\s+hash="([0-9a-f]{16}|' + EMPTY_CATALOG_KEY + r')"')

_UPDATE_NOTICE = (
    "Your bound skills changed. The list below is the current bound skills list. "
    "It replaces every earlier skills list in this conversation."
)
_NO_SKILLS_XML = "<skills>No skills available.</skills>"

# Shape of a HumanMessage's content: plain text, or a list of text and multimodal parts.
type _ContentPart = str | dict[str, object]
type _ContentParts = list[_ContentPart]
type _Content = str | _ContentParts


def compute_catalog_hash(catalog_body: str) -> str:
    """Stable short hash for a rendered catalog XML body."""
    digest = hashlib.sha256(catalog_body.encode("utf-8")).hexdigest()
    return digest[:16]


@dataclass(frozen=True, slots=True)
class RenderedCatalog:
    """The catalog a bind list resolves to: XML body, its hash and the count of skills left out of it."""

    xml: str
    hash: str
    hidden_skill_count: int

    @classmethod
    def from_display(cls, display_skills: list[SkillMetadata], *, hidden_skill_count: int = 0) -> RenderedCatalog:
        xml = get_metadata_summary(display_skills, hidden_skill_count=hidden_skill_count)
        return cls(xml=xml, hash=compute_catalog_hash(xml), hidden_skill_count=hidden_skill_count)


def render_bound_skills_catalog(
    skills: list[SkillMetadata],
    *,
    skill_configs: dict[str, dict[str, object]] | None = None,
    available_tool_names: frozenset[str] | None = None,
    available_tool_groups: frozenset[str] | None = None,
) -> RenderedCatalog | None:
    """Resolve ``skills`` to the catalog shown to the model, or ``None`` when nothing is to be shown."""
    if not skills:
        return None
    resolution = resolve_catalog_display_skills(
        skills,
        skill_configs=skill_configs,
        available_tool_names=available_tool_names,
        available_tool_groups=available_tool_groups,
    )
    if not resolution.display_skills and resolution.hidden_skill_count <= 0:
        return None
    return RenderedCatalog.from_display(
        resolution.display_skills,
        hidden_skill_count=resolution.hidden_skill_count,
    )


def strip_catalog_blocks(text: str) -> str:
    """Remove injected catalog blocks (including user-spoofed copies)."""
    cleaned = _BOUND_SKILLS_UPDATE_RE.sub("", text)
    cleaned = _BOUND_SKILLS_RE.sub("", cleaned)
    return cleaned.lstrip()


def _hidden_attr(hidden_skill_count: int) -> str:
    return f' hidden_count="{hidden_skill_count}"' if hidden_skill_count > 0 else ""


def _baseline_block(rendered: RenderedCatalog) -> str:
    return (
        f'<bound_skills hash="{rendered.hash}"{_hidden_attr(rendered.hidden_skill_count)}>\n'
        f"{rendered.xml}\n</bound_skills>"
    )


def build_bound_skills_block(
    display_skills: list[SkillMetadata],
    *,
    hidden_skill_count: int = 0,
) -> str:
    """Render the full ``<bound_skills>`` block for HumanMessage prepend."""
    return _baseline_block(RenderedCatalog.from_display(display_skills, hidden_skill_count=hidden_skill_count))


def build_bound_skills_update_block(rendered: RenderedCatalog | None) -> str:
    """Render the ``<bound_skills_update>`` block; ``None`` announces that no skill is available any more."""
    if rendered is None:
        key, hidden, xml = EMPTY_CATALOG_KEY, "", _NO_SKILLS_XML
    else:
        key, hidden, xml = rendered.hash, _hidden_attr(rendered.hidden_skill_count), rendered.xml
    return f'<bound_skills_update hash="{key}"{hidden}>\n{_UPDATE_NOTICE}\n{xml}\n</bound_skills_update>'


def _strip_message_content(content: _Content) -> _Content:
    if isinstance(content, str):
        return strip_catalog_blocks(content)

    updated: _ContentParts = []
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


def _prepend_block_to_content(content: _Content, block: str) -> _Content:
    prefix = f"{block}\n\n"
    if isinstance(content, str):
        body = content.strip()
        return f"{prefix}{body}" if body else block

    updated: _ContentParts = list(content)
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


def first_human_index(messages: Sequence[BaseMessage]) -> int | None:
    """Index of the first HumanMessage, or ``None`` when there is none."""
    for idx, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            return idx
    return None


def strip_catalog_blocks_from_message(message: HumanMessage) -> HumanMessage:
    """Copy of ``message`` without catalog blocks (a user can type one; only the harness may write one)."""
    content = message.content
    if not isinstance(content, (str, list)):
        return message
    return HumanMessage(content=_strip_message_content(content), additional_kwargs=dict(message.additional_kwargs))


def ensure_skill_catalog_in_messages(
    messages: list[BaseMessage],
    skills: list[SkillMetadata],
    *,
    skill_configs: dict[str, dict[str, object]] | None = None,
    available_tool_names: frozenset[str] | None = None,
    available_tool_groups: frozenset[str] | None = None,
) -> None:
    """Strip catalog blocks from every HumanMessage and write the baseline on the first one.

    For a conversation that is being (re)built from a history record; a continued thread is
    never passed here, its baseline stays as it was.
    """
    if not messages:
        return

    for idx, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            messages[idx] = strip_catalog_blocks_from_message(message)

    rendered = render_bound_skills_catalog(
        skills,
        skill_configs=skill_configs,
        available_tool_names=available_tool_names,
        available_tool_groups=available_tool_groups,
    )
    first_idx = first_human_index(messages)
    if rendered is None or first_idx is None:
        return

    first = messages[first_idx]
    assert isinstance(first, HumanMessage)
    first_content = first.content
    if isinstance(first_content, (str, list)):
        messages[first_idx] = HumanMessage(
            content=_prepend_block_to_content(first_content, _baseline_block(rendered)),
            additional_kwargs=dict(first.additional_kwargs),
        )


def _message_text(content: _Content) -> str:
    if isinstance(content, str):
        return content
    texts: list[str] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            text_val = part.get("text")
            if isinstance(text_val, str):
                texts.append(text_val)
    return "\n".join(texts)


def last_delivered_catalog_key(thread_messages: Sequence[BaseMessage]) -> str:
    """Hash of the catalog the thread last delivered; ``empty`` when the thread carries no catalog block."""
    for message in reversed(thread_messages):
        if not isinstance(message, HumanMessage) or not isinstance(message.content, (str, list)):
            continue
        keys = _DELIVERED_KEY_RE.findall(_message_text(message.content))
        if keys:
            return str(keys[-1])
    return EMPTY_CATALOG_KEY


def plan_catalog_update(
    thread_messages: Sequence[BaseMessage],
    rendered: RenderedCatalog | None,
) -> str | None:
    """The update block to deliver on a continued thread, or ``None`` when the thread already carries the catalog."""
    current_key = EMPTY_CATALOG_KEY if rendered is None else rendered.hash
    if last_delivered_catalog_key(thread_messages) == current_key:
        return None
    return build_bound_skills_update_block(rendered)


def prepend_catalog_update(message: HumanMessage, update_block: str) -> HumanMessage:
    """Copy of the new-turn ``message`` with ``update_block`` in front of the user's text."""
    stripped = strip_catalog_blocks_from_message(message)
    content = stripped.content
    if not isinstance(content, (str, list)):
        return stripped
    return HumanMessage(
        content=_prepend_block_to_content(content, update_block),
        additional_kwargs=dict(stripped.additional_kwargs),
    )


__all__ = [
    "EMPTY_CATALOG_KEY",
    "RenderedCatalog",
    "build_bound_skills_block",
    "build_bound_skills_update_block",
    "compute_catalog_hash",
    "ensure_skill_catalog_in_messages",
    "first_human_index",
    "last_delivered_catalog_key",
    "plan_catalog_update",
    "prepend_catalog_update",
    "render_bound_skills_catalog",
    "strip_catalog_blocks",
    "strip_catalog_blocks_from_message",
]
