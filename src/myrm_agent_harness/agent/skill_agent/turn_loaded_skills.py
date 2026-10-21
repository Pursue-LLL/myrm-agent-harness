"""Serialize skills loaded during the current agent run for message metadata.

[INPUT]
- agent.skill_agent.context::get_loaded_skills (POS: per-run loaded skill list)

[OUTPUT]
- build_turn_loaded_skills_payload: list of UI-safe skill receipt dicts

[POS]
Turn-end metadata bridge. Does not touch prompts or system messages.
"""

from __future__ import annotations

from myrm_agent_harness.agent.skill_agent.context import get_bound_skills_receipt, get_loaded_skills
from myrm_agent_harness.backends.skills.types import SkillMetadata


def build_turn_loaded_skills_payload() -> list[dict[str, object]]:
    """Build receipt rows for bound∪loaded skills (name, id, content hash, load state)."""
    loaded = get_loaded_skills()
    loaded_names = {s.name for s in loaded}
    items: list[dict[str, object]] = []
    for skill in loaded:
        items.append(_skill_receipt_row(skill, bound_only=False))
    for skill in get_bound_skills_receipt():
        if skill.name in loaded_names:
            continue
        items.append(_skill_receipt_row(skill, bound_only=True))
    return items


def _skill_receipt_row(skill: SkillMetadata, *, bound_only: bool) -> dict[str, object]:
    skill_id = skill.storage_skill_id or skill.name
    row: dict[str, object] = {
        "name": skill.name,
        "id": skill_id,
        "partial": bound_only,
    }
    if skill.content_hash:
        row["content_hash"] = skill.content_hash
    if skill.version:
        row["version"] = skill.version
    return row
