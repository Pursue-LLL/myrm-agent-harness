"""Explicit skill invocation: the ``[use a,b] text`` tag grammar and what its references point at.

[INPUT]
- backends.skills.types::SkillMetadata (POS: skill metadata)

[OUTPUT]
- parse_use_tag(): the leading ``[use ...]`` tag of a user text, or None
- UseTag: the tag's skill references, its literal text and the user text behind it
- resolve_skill_reference(): the skill a reference points at, or None

[POS]
SSOT of the explicit-invocation wire format shared by the agent and by hosts that decorate user text.
The tag only counts at the very start of the text, so a host that prefixes anything (a delivery banner,
a timestamp) must put it behind the tag (``UseTag.tag``, ``UseTag.text``) or the invocation goes unnoticed.

Users type the catalog name (``my-skill``) while a backend may expose the same skill under a
runtime name (``my_skill_skill``). Matching tolerates that spelling difference but never guesses
between two skills.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from myrm_agent_harness.backends.skills.types import SkillMetadata

_USE_TAG = re.compile(r"^\[use\s+([\w,\s-]+)\]\s*(.*)", re.DOTALL)
_SKILL_SUFFIX = "_skill"
_SEPARATORS = re.compile(r"[-\s]+")


@dataclass(frozen=True, slots=True)
class UseTag:
    """A leading ``[use a,b] text`` invocation, split into its parts."""

    references: tuple[str, ...]
    """Skill references as typed, in order."""
    tag: str
    """The literal ``[use ...]`` text; re-emit it unchanged to keep the invocation intact."""
    text: str
    """What the user wrote behind the tag, stripped."""


def parse_use_tag(text: str) -> UseTag | None:
    """The explicit-invocation tag ``text`` starts with, or None (a tag elsewhere in the text does not count)."""
    match = _USE_TAG.match(text)
    if match is None:
        return None
    references = tuple(name.strip() for name in match.group(1).split(",") if name.strip())
    if not references:
        return None
    return UseTag(references=references, tag=text[: match.start(2)].rstrip(), text=match.group(2).strip())


def _canonical(name: str) -> str:
    """Spelling-independent key: case, ``-`` vs ``_`` and the ``_skill`` suffix are ignored."""
    return _SEPARATORS.sub("_", name.strip().lower()).removesuffix(_SKILL_SUFFIX)


def resolve_skill_reference(reference: str, skills: Sequence[SkillMetadata]) -> SkillMetadata | None:
    """Find the skill ``reference`` names: exact name, then storage id, then canonical spelling.

    The canonical match is accepted only when exactly one skill answers to it.
    """
    for skill in skills:
        if skill.name == reference:
            return skill
    for skill in skills:
        if skill.storage_skill_id == reference:
            return skill
    key = _canonical(reference)
    if not key:
        return None
    matches = [skill for skill in skills if _canonical(skill.name) == key]
    return matches[0] if len(matches) == 1 else None
