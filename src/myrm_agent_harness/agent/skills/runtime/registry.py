"""Skill Registry

1. INPUT/OUTPUT/POS annotations

[INPUT]
- backends.skills.types::SkillMetadata (POS: skill metadata type definition)

[OUTPUT]
- SkillRegistry: Skill registry class (manages registration, lookup, updates)
- skill_registry: Global skill registry singleton
- get_metadata_summary(): XML-format skill summary (embedded in first HumanMessage ``<bound_skills>``, not tool schema; optional hidden_skill_count for search-first routing_rules)

[POS]
Skill registry. Manages runtime caches and lookups, primarily for MCP-based skills.

"""

from __future__ import annotations

import logging
from xml.sax.saxutils import escape, quoteattr

from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)

MAX_SKILLS_IN_PROMPT = 20
MAX_SKILL_FILE_BYTES = 128 * 1024  # 128 KB per skill file
_CONTRACT_TEXT_LIMIT = 160


def _truncate_summary_text(text: str, limit: int = _CONTRACT_TEXT_LIMIT) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _append_contract_summary(lines: list[str], skill: SkillMetadata) -> None:
    contract = skill.contract
    if contract is None:
        return

    attrs = [
        f"steps={quoteattr(str(len(contract.steps)))}",
        f"judgments={quoteattr(str(len(contract.key_judgments)))}",
        f"traps={quoteattr(str(len(contract.potential_traps)))}",
        f"verifications={quoteattr(str(len(contract.verification_steps)))}",
    ]
    if contract.estimated_duration_seconds is not None:
        attrs.append(f"duration_seconds={quoteattr(f'{contract.estimated_duration_seconds:g}')}")

    lines.append(f" <contract {' '.join(attrs)}>")

    if contract.success_criteria:
        lines.append(f" <success>{escape(_truncate_summary_text(contract.success_criteria))}</success>")

    if contract.dependencies:
        dependency_text = ", ".join(contract.dependencies[:5])
        lines.append(f" <dependencies>{escape(_truncate_summary_text(dependency_text))}</dependencies>")

    for verification in contract.verification_steps[:2]:
        verification_hint = verification.description
        if verification.expected_output:
            verification_hint = f"{verification.description} -> {verification.expected_output}"
        lines.append(f" <verify>{escape(_truncate_summary_text(verification_hint))}</verify>")

    for trap in contract.potential_traps[:2]:
        trap_hint = f"{trap.description}; mitigate: {trap.mitigation}"
        lines.append(f" <trap severity={quoteattr(trap.severity)}>{escape(_truncate_summary_text(trap_hint))}</trap>")

    lines.append(" </contract>")


class SkillRegistry:
    """Runtime skill cache and lookup registry.

    Handles dynamic MCP skill registration and runtime skill lookup.
    Storage-backed skills are loaded via SkillBackendProtocol, not registered here.
    """

    def __init__(self):
        self._skills: dict[str, SkillMetadata] = {}

    def register(self, skill: SkillMetadata) -> None:
        self._skills[skill.name] = skill
        if skill.is_mcp_skill:
            source = f"mcp:{skill.mcp.server}" if skill.mcp else "mcp"
        elif skill.is_storage_skill:
            source = "storage"
        else:
            source = "unknown"
        logger.info("Registered skill: %s (source=%s)", skill.name, source)

    def get_skill(self, name: str) -> SkillMetadata | None:
        return self._skills.get(name)

    def list_skills(self) -> list[SkillMetadata]:
        return list(self._skills.values())

    def list_mcp_skills(self) -> list[SkillMetadata]:
        return [skill for skill in self._skills.values() if skill.is_mcp_skill]

    def list_storage_skills(self) -> list[SkillMetadata]:
        return [skill for skill in self._skills.values() if skill.is_storage_skill]

    def clear_mcp_skills(self) -> None:
        """Remove MCP-routed skills before a fresh routing pass.

        Storage-backed skills registered here are preserved.
        """
        removed = [name for name, skill in self._skills.items() if skill.is_mcp_skill]
        for name in removed:
            del self._skills[name]
        if removed:
            logger.info("Cleared %d MCP skill(s) from registry: %s", len(removed), removed)

    def clear(self) -> None:
        self._skills.clear()


skill_registry = SkillRegistry()


def get_metadata_summary(
    skills: list[SkillMetadata],
    max_skills: int = MAX_SKILLS_IN_PROMPT,
    *,
    hidden_skill_count: int = 0,
) -> str:
    """Generate structured XML skill summary for HumanMessage catalog blocks.

    Rendered inside ``<bound_skills>`` on the first HumanMessage (see
    ``skill_catalog_delivery.py``), **not** in tool schema or SystemMessage.

    XML format is more parseable by LLMs than Markdown lists, and supports
    structured attributes (availability, trust, routing hints).

    Skills with always=True are guaranteed inclusion in the XML. Remaining slots
    are filled by available skills first, then unavailable ones, up to max_skills.

    Cache impact: stable skill list in messages[] keeps tool schema bytes stable;
    catalog size still counts toward cached conversation prefix when present.
    """
    if not skills:
        if hidden_skill_count > 0:
            return "\n".join(
                [
                    "<skills>",
                    " <routing_rules>",
                    " If exactly one skill clearly applies to the user's request: use skill_select_tool to read its SKILL.md.",
                    " If multiple skills may apply: ask the user which to use.",
                    " If no skill applies: proceed without skills.",
                    " If the needed skill is not listed below: use skill_search_tool before skill_select_tool.",
                    " </routing_rules>",
                    "</skills>",
                ]
            )
        return "<skills>No skills available.</skills>"

    always_skills = [s for s in skills if s.always]
    other_skills = [s for s in skills if not s.always]
    other_skills.sort(key=lambda s: (not s.available, s.name))
    remaining = max(0, max_skills - len(always_skills))
    included = always_skills + other_skills[:remaining]

    if len(skills) > len(included):
        logger.warning(
            "Skill prompt limit: %d/%d skills included (max_skills_in_prompt=%d)",
            len(included),
            len(skills),
            max_skills,
        )

    lines = [
        "<skills>",
        " <routing_rules>",
        " If exactly one skill clearly applies to the user's request: use skill_select_tool to read its SKILL.md.",
        " If multiple skills may apply: ask the user which to use.",
        " If no skill applies: proceed without skills.",
    ]
    if hidden_skill_count > 0:
        lines.append(" If the needed skill is not listed below: use skill_search_tool before skill_select_tool.")
    lines.append(" </routing_rules>")
    for s in included:
        attrs = f"name={quoteattr(s.name)} available={quoteattr(str(s.available).lower())} trust={quoteattr(s.trust.name.lower())}"
        if not s.available and s.unavailable_reason:
            attrs += f" reason={quoteattr(s.unavailable_reason)}"
        if s.always:
            attrs += ' always="true"'
        if s.usage_stats.is_stale:
            attrs += ' stale="true"'

        lines.append(f" <skill {attrs}>")
        lines.append(f" <description>{escape(s.description)}</description>")

        _append_contract_summary(lines, s)

        lines.append(" </skill>")

    lines.append("</skills>")
    return "\n".join(lines)


__all__ = [
    "MAX_SKILLS_IN_PROMPT",
    "MAX_SKILL_FILE_BYTES",
    "SkillRegistry",
    "get_metadata_summary",
    "skill_registry",
]
