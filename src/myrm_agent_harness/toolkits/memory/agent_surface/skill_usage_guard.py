"""Deterministic guard: block memory_search_tool misuse for skill-usage lookups.

When an MCP/storage skill is loaded (``get_loaded_skills``), weak models may
reach for ``memory_search_tool`` to "look up how to use" the skill. Skill usage
is authoritative in the skill SOP and its ``/mcp/*.md`` function docs — never in
memory. This guard deterministically intercepts such queries (skill core term +
usage-intent marker co-occurrence) and redirects the agent to the
SOP/docs path via ``file_read_tool`` or direct skill execution via bash PTC.

[INPUT]
- agent.skill_agent.context::get_loaded_skills (POS: loaded skill runtime state)
- backends.skills.types_metadata::SkillMetadata (POS: skill runtime metadata)

[OUTPUT]
- SkillUsageHit: dataclass identifying a matched skill-usage query
- detect_skill_usage_lookup: ContextVar-backed detection entry point
- detect_against_loaded: pure detection for tests/injection
- build_skill_usage_guide: LLM-facing redirect message

[POS]
Framework-level memory tool guard. Defines the exact boundary of
``memory_search_tool``: it only recalls stored memories and must never be used
to discover tool/skill usage instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.types_metadata import SkillMetadata

# ---------------------------------------------------------------------------
# Usage-intent markers (co-occurring with a loaded-skill core term).
# Keep markers strong (explicit usage wording) so legitimate memory recall
# queries (preferences, history, facts) are never intercepted.
# ---------------------------------------------------------------------------

_USAGE_INTENT_MARKERS: tuple[str, ...] = (
    # zh — explicit usage wording
    "怎么",
    "如何",
    "用法",
    "使用方法",
    "使用说明",
    "怎么用",
    "如何用",
    "怎么操作",
    "如何操作",
    "怎么调用",
    "如何调用",
    "查询方法",
    "调用方法",
    "操作步骤",
    "使用教程",
    "函数文档",
    "接口文档",
    "说明书",
    "查询",
    "调用",
    "操作",
    # en — explicit usage wording
    "how to",
    "how do",
    "how is",
    "how does",
    "usage",
    "use the",
    "use skill",
    "invoke",
    "call the",
    "api",
    "sop",
    "manual",
    "tutorial",
    "workflow",
)

_SKILL_PREFIXES: tuple[str, ...] = ("mcp_", "tool_")
_SKILL_SUFFIXES: tuple[str, ...] = ("_skill",)


@dataclass(frozen=True)
class SkillUsageHit:
    """A memory_search query that targets skill-usage instructions."""

    skill_name: str
    matched_term: str


def extract_skill_core_terms(skill_name: str) -> tuple[str, ...]:
    """Derive candidate core terms for a skill name.

    ``mcp_12306_skill`` → ``mcp_12306_skill``, ``12306_skill``, ``12306``
    (each with a space-normalized variant).
    """
    name = skill_name.lower()
    candidates: set[str] = {name}
    core = name
    for prefix in _SKILL_PREFIXES:
        if core.startswith(prefix):
            core = core[len(prefix) :]
            candidates.add(core)
            break
    for suffix in _SKILL_SUFFIXES:
        if core.endswith(suffix):
            core = core[: -len(suffix)]
            break
    if core and core != name:
        candidates.add(core)
    spaced = {
        " ".join(term.replace("_", " ").replace("-", " ").split())
        for term in candidates
    }
    candidates |= spaced
    return tuple(sorted(candidates, key=len))


def detect_against_loaded(
    query: str,
    loaded_skills: list["SkillMetadata"] | tuple["SkillMetadata", ...],
) -> SkillUsageHit | None:
    """Pure detection: query targets skill usage for any loaded skill.

    A hit requires a loaded-skill core term AND an explicit usage-intent marker
    to co-occur in the query — this keeps legitimate memory recall (preferences,
    history, facts about the skill domain) flowing untouched.
    """
    lowered = query.lower()
    if not lowered:
        return None
    for skill in loaded_skills:
        skill_name = skill.name
        for term in extract_skill_core_terms(skill_name):
            if term not in lowered:
                continue
            for marker in _USAGE_INTENT_MARKERS:
                if marker in lowered:
                    return SkillUsageHit(skill_name=skill_name, matched_term=term)
    return None


def detect_skill_usage_lookup(query: str) -> SkillUsageHit | None:
    """Detect skill-usage lookup using the currently loaded skills (ContextVar)."""
    from myrm_agent_harness.agent.skill_agent.context import get_loaded_skills

    loaded = get_loaded_skills()
    if not loaded:
        return None
    return detect_against_loaded(query, loaded)


def build_skill_usage_guide(hit: SkillUsageHit) -> str:
    """Build the redirect message returned to the agent when the guard fires."""
    return (
        f"memory_search_tool only recalls stored memories — it is NOT a lookup "
        f"for skill usage instructions. The loaded skill '{hit.skill_name}' "
        f"carries all usage instructions in its SOP and /mcp/*.md function docs. "
        f"Read them with file_read_tool, then call the skill's tools directly "
        f"via bash PTC. Do not search memory for skill usage."
    )


def usage_intent_markers() -> tuple[str, ...]:
    """Expose the marker table for parity tests."""
    return _USAGE_INTENT_MARKERS


__all__ = [
    "SkillUsageHit",
    "build_skill_usage_guide",
    "detect_against_loaded",
    "detect_skill_usage_lookup",
    "extract_skill_core_terms",
    "usage_intent_markers",
]
