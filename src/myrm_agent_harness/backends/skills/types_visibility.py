"""Tool-conditional skill visibility filter.

[INPUT]
- types_metadata.SkillMetadata (POS: skill metadata with activation fields)

[OUTPUT]
- skill_visible_for_tools(): pure visibility predicate for agent tool sets

[POS]
Deterministic skill visibility given available tools and tool groups; no side effects.
"""

from __future__ import annotations

from myrm_agent_harness.backends.skills.types_metadata import SkillMetadata


def skill_visible_for_tools(
    skill: SkillMetadata,
    available_tool_names: frozenset[str],
    available_tool_groups: frozenset[str],
) -> bool:
    """Determine whether *skill* should be visible given the agent's tool set.

    Pure function, no side effects, trivially testable.

    Rules:
    - ``requires_tools``: ALL listed tools must be present → hide if any absent.
    - ``requires_tool_groups``: ALL listed groups must be enabled → hide if any absent.
    - ``fallback_for_tools``: hide when ANY listed tool IS present (primary available).
    - ``fallback_for_tool_groups``: hide when ANY listed group IS enabled.

    Empty lists (default) impose no constraints → skill is always visible.
    """
    for t in skill.requires_tools:
        if t not in available_tool_names:
            return False
    for g in skill.requires_tool_groups:
        if g not in available_tool_groups:
            return False
    for t in skill.fallback_for_tools:
        if t in available_tool_names:
            return False
    return all(g not in available_tool_groups for g in skill.fallback_for_tool_groups)
