"""Bound skill catalog display resolution — SSOT for inline vs hidden skills.

[INPUT]
- backends.skills.types::SkillMetadata (POS: skill metadata)
- backends.skills.types::skill_visible_for_tools (POS: tool-capability skill filter)
- agent.meta_tools::SKILL_* threshold constants (POS: inline catalog limits)

[OUTPUT]
- CatalogDisplayResolution: display_skills + hidden_skill_count for catalog delivery
- resolve_catalog_display_skills(): shared inline/hidden logic for meta-tools and runtime inject
- should_mount_skill_search_tool(): gate for conditional skill_search_tool mount

[POS]
Runtime catalog display SSOT. Keeps skill_select_tool schema static while preserving
Per-Agent cognitive-load inline rules from get_meta_tools.
"""

from __future__ import annotations

from dataclasses import dataclass

from myrm_agent_harness.backends.skills.types import SkillMetadata, skill_visible_for_tools

SKILL_INLINE_THRESHOLD = 20
SKILL_CORE_MAX = 10
SKILL_SELECT_INLINE_MAX = 20


@dataclass(frozen=True, slots=True)
class CatalogDisplayResolution:
    """Resolved catalog slice shown in ``<bound_skills>`` HumanMessage blocks."""

    filtered_skills: list[SkillMetadata]
    display_skills: list[SkillMetadata]
    hidden_skill_count: int


def _sorted_inline(skills_to_inline: list[SkillMetadata]) -> list[SkillMetadata]:
    return sorted(skills_to_inline, key=lambda skill: skill.name)[:SKILL_SELECT_INLINE_MAX]


def _filter_skills_for_agent_tools(
    skills: list[SkillMetadata],
    *,
    available_tool_names: frozenset[str] | None,
    available_tool_groups: frozenset[str] | None,
) -> list[SkillMetadata]:
    if not skills or (
        available_tool_names is None and available_tool_groups is None
    ):
        return list(skills)

    tool_names = available_tool_names or frozenset()
    tool_groups = available_tool_groups or frozenset()
    return [
        skill
        for skill in skills
        if skill_visible_for_tools(skill, tool_names, tool_groups)
    ]


def resolve_catalog_display_skills(
    skills: list[SkillMetadata],
    *,
    skill_configs: dict[str, dict[str, object]] | None = None,
    available_tool_names: frozenset[str] | None = None,
    available_tool_groups: frozenset[str] | None = None,
) -> CatalogDisplayResolution:
    """Resolve which bound skills appear in the HumanMessage catalog block."""
    filtered = _filter_skills_for_agent_tools(
        skills,
        available_tool_names=available_tool_names,
        available_tool_groups=available_tool_groups,
    )
    available_skills = [skill for skill in filtered if skill.available]
    model_visible = [skill for skill in available_skills if skill.model_invocable]

    if skill_configs is not None:
        core_candidates = [
            skill
            for skill in model_visible
            if skill_configs.get(skill.id, {}).get("is_core", False)
        ]
        display_skills = _sorted_inline(core_candidates)
    elif len(model_visible) > SKILL_INLINE_THRESHOLD:
        always_skills = sorted(
            [skill for skill in model_visible if skill.always],
            key=lambda skill: skill.name,
        )
        non_always = sorted(
            [skill for skill in model_visible if not skill.always],
            key=lambda skill: skill.name,
        )
        remaining = max(SKILL_SELECT_INLINE_MAX - len(always_skills), 0)
        core_non_always = non_always[: min(SKILL_CORE_MAX, remaining)]
        display_skills = _sorted_inline(always_skills + core_non_always)
    else:
        display_skills = _sorted_inline(model_visible)

    hidden = len(model_visible) - len(display_skills)
    return CatalogDisplayResolution(
        filtered_skills=filtered,
        display_skills=display_skills,
        hidden_skill_count=max(hidden, 0),
    )


def should_mount_skill_search_tool(
    skills: list[SkillMetadata],
    *,
    skill_configs: dict[str, dict[str, object]] | None = None,
    available_tool_names: frozenset[str] | None = None,
    available_tool_groups: frozenset[str] | None = None,
) -> bool:
    """Return True when bound skills exceed inline catalog capacity (hidden_count > 0)."""
    if not skills:
        return False
    resolution = resolve_catalog_display_skills(
        skills,
        skill_configs=skill_configs,
        available_tool_names=available_tool_names,
        available_tool_groups=available_tool_groups,
    )
    discoverable = [s for s in resolution.filtered_skills if s.model_invocable]
    return resolution.hidden_skill_count > 0 and bool(discoverable)


__all__ = [
    "SKILL_CORE_MAX",
    "SKILL_INLINE_THRESHOLD",
    "SKILL_SELECT_INLINE_MAX",
    "CatalogDisplayResolution",
    "resolve_catalog_display_skills",
    "should_mount_skill_search_tool",
]
