"""Trust-based tool filtering (authority attenuation).

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- backends.skills.types::SkillMetadata, SkillTrust (POS: 技能元数据和信任枚举)

[OUTPUT]
- AttenuationResult: 工具衰减结果（过滤后工具 + 最低信任 + 解释 + 移除列表）
- attenuate_tools(): 基于信任级别和 allowed_tools 过滤工具

[POS]
Trust attenuator. Core security defense with three-layer filtering for skill permission management.

"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillTrust

logger = logging.getLogger(__name__)

READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "memory_search",
        "memory_read",
        "memory_tree",
        "time_tool",
        "echo_tool",
        "json_tool",
        "skill_list_tool",
        "discover_capability_tool",
        "skill_select_tool",
        "_completion_check",
    }
)

# Hard upper bound for INSTALLED skills even when scanner-clean.
# Includes READ_ONLY + safe read/write/search tools.
# Excludes bash/shell execution tools (never granted to INSTALLED skills).
INSTALLED_CEILING_TOOLS: frozenset[str] = READ_ONLY_TOOLS | frozenset(
    {
        "file_read_tool",
        "file_write_tool",
        "file_edit_tool",
        "file_delete_tool",
        "file_find_tool",
        "file_search_tool",
        "file_list_tool",
        "web_search_tool",
        "web_fetch_tool",
        "memory_write",
        "memory_delete",
        "skill_manage_tool",
    }
)


@dataclass(frozen=True)
class AttenuationResult:
    """Result of tool attenuation with transparency information."""

    tool_names: list[str]
    """Filtered tool names to expose to the LLM."""

    min_trust: SkillTrust
    """Minimum trust level across all active skills."""

    explanation: str
    """Human-readable explanation of what was removed and why."""

    removed_tools: list[str] = field(default_factory=list)
    """Names of tools that were removed."""


def attenuate_tools(tool_names: list[str], active_skills: list[SkillMetadata]) -> AttenuationResult:
    """Filter tool names based on trust level and allowed_tools of active skills.

    Three-layer security gate:
    1. Trust attenuation: min(trust) determines the baseline ceiling
    2. Scanner-gated widening: clean INSTALLED skills with allowed_tools
       get (allowed_tools ∩ CEILING) ∪ READ_ONLY instead of just READ_ONLY
    3. allowed_tools restriction: union of declared allowed_tools narrows scope

    Args:
        tool_names: All available tool names
        active_skills: Currently active skills (loaded into context)

    Returns:
        AttenuationResult with filtered tools and explanation
    """
    if not active_skills:
        return AttenuationResult(
            tool_names=list(tool_names),
            min_trust=SkillTrust.TRUSTED,
            explanation="No skills active, all tools available",
        )

    min_trust = min(s.trust for s in active_skills)

    trust_allowed = _apply_trust_filter(tool_names, min_trust, active_skills)

    final_tools, allowed_removed = _apply_allowed_tools_filter(trust_allowed, active_skills)

    removed = [n for n in tool_names if n not in frozenset(final_tools)]

    explanation = _build_explanation(min_trust, tool_names, trust_allowed, allowed_removed, removed)

    if removed:
        logger.warning(f" Trust attenuation: {explanation}")

    return AttenuationResult(
        tool_names=final_tools, min_trust=min_trust, explanation=explanation, removed_tools=removed
    )


def _apply_trust_filter(tool_names: list[str], min_trust: SkillTrust, active_skills: list[SkillMetadata]) -> list[str]:
    """Filter tools by trust level ceiling with scanner-gated widening.

    For INSTALLED skills that pass scanner AND declare allowed_tools,
    grant (allowed_tools ∩ INSTALLED_CEILING) ∪ READ_ONLY instead of
    just READ_ONLY. This ensures INSTALLED skills are usable while
    maintaining a hard security ceiling.
    """
    if min_trust >= SkillTrust.TRUSTED:
        return list(tool_names)

    installed_skills = [s for s in active_skills if s.trust == SkillTrust.INSTALLED]

    all_clean_with_allowed = all(s.scanner_clean and s.allowed_tools for s in installed_skills)

    if not all_clean_with_allowed:
        return [n for n in tool_names if n in READ_ONLY_TOOLS]

    # Scanner-gated widening: grant declared tools within CEILING
    widened_union: set[str] = set(READ_ONLY_TOOLS)
    for skill in installed_skills:
        if skill.allowed_tools:
            for tool in skill.allowed_tools:
                if tool in INSTALLED_CEILING_TOOLS:
                    widened_union.add(tool)

    return [n for n in tool_names if n in widened_union]


def _apply_allowed_tools_filter(tools: list[str], active_skills: list[SkillMetadata]) -> tuple[list[str], list[str]]:
    """Further restrict tools by the union of skills' allowed_tools declarations.

    Only applies when ALL active skills declare allowed_tools. If any skill
    has no declaration (None or empty), it may need any tool, so the filter
    is skipped entirely.

    Returns:
        (kept_tools, removed_by_allowed_tools)
    """
    allowed_union: set[str] = set()

    for skill in active_skills:
        if not skill.allowed_tools:
            return tools, []
        allowed_union.update(skill.allowed_tools)

    kept: list[str] = []
    removed: list[str] = []
    for name in tools:
        if name in allowed_union:
            kept.append(name)
        else:
            removed.append(name)

    return kept, removed


def _build_explanation(
    min_trust: SkillTrust,
    original: list[str],
    trust_allowed: list[str],
    allowed_removed: list[str],
    total_removed: list[str],
) -> str:
    """Build a human-readable explanation of what was filtered and why."""
    parts: list[str] = []

    trust_removed_count = len(original) - len(trust_allowed)
    if trust_removed_count > 0:
        parts.append(f"trust({min_trust.name}): removed {trust_removed_count} tool(s)")

    if allowed_removed:
        parts.append(f"allowed_tools: removed {len(allowed_removed)} tool(s): {', '.join(allowed_removed)}")

    if not parts:
        return "All active skills are trusted, all tools available"

    return "; ".join(parts)
