"""Skill analysis tool for quality evaluation and forgetting suggestions.

Factory function to create skill_analyze LangChain tool.

[INPUT]
- backends.skills.forgetting_strategy::DefaultForgettingStrategy, (POS: Skill forgetting strategies to prevent skill accumulation.)
- backends.skills.types::SkillMetadata (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)

[OUTPUT]
- create_skill_analyze_tool: Create skill_analyze LangChain tool.

[POS]
Skill analysis tool for quality evaluation and forgetting suggestions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal

from langchain.tools import tool
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from myrm_agent_harness.backends.skills.forgetting_strategy import (
    DefaultForgettingStrategy,
    ForgettingConfig,
    ForgettingReason,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)

TOOL_NAME = "skill_analyze_tool"
TOOL_DESCRIPTION = """Analyze skills to identify low-quality or stale skills for potential removal.

Actions:
- list_low_quality: List skills that meet forgetting criteria (stale, low success rate, LRU candidates).
- suggest_cleanup: Get cleanup suggestions with detailed reasoning.

Use this tool to maintain skill quality and prevent skill accumulation ("snowball effect").
IMPORTANT: Always confirm with user before actually deleting skills.
"""


def create_skill_analyze_tool(
    get_all_skills_fn: Callable[[], list[SkillMetadata]], forgetting_config: ForgettingConfig | None = None
) -> BaseTool:
    """Create skill_analyze LangChain tool.

    Args:
        get_all_skills_fn: Function to get all loaded skills
        forgetting_config: Optional custom forgetting configuration

    Returns:
        LangChain tool for skill analysis
    """
    strategy = DefaultForgettingStrategy(config=forgetting_config)

    class SkillAnalyzeInput(BaseModel):
        action: Literal["list_low_quality", "suggest_cleanup"] = Field(
            description="Action: list_low_quality (show candidates) or suggest_cleanup (detailed suggestions)."
        )

    @tool(TOOL_NAME, args_schema=SkillAnalyzeInput, description=TOOL_DESCRIPTION)
    def skill_analyze_impl(action: str) -> str:
        """Analyze skills for quality and forgetting opportunities."""
        try:
            all_skills = get_all_skills_fn()

            if not all_skills:
                return "No skills loaded."

            # Collect forgetting candidates
            stale_or_low_quality: list[ForgettingReason] = []
            for skill in all_skills:
                reason = strategy.should_forget(skill)
                if reason:
                    stale_or_low_quality.append(reason)

            # LRU candidates
            lru_candidates = strategy.select_lru_candidates(all_skills)

            all_candidates = stale_or_low_quality + lru_candidates

            if not all_candidates:
                return f"All {len(all_skills)} skills are healthy. No cleanup needed."

            if action == "list_low_quality":
                return _format_candidate_list(all_candidates)
            else:  # action == "suggest_cleanup", validated by Pydantic
                return _format_detailed_suggestions(all_candidates, all_skills)

        except Exception as e:
            logger.error("skill_analyze failed: %s", e, exc_info=True)
            return f"ERROR: Failed to analyze skills: {e}"

    return skill_analyze_impl


def _format_candidate_list(candidates: list[ForgettingReason]) -> str:
    """Format candidate list in concise format."""
    lines = [f"Found {len(candidates)} skills that may need cleanup:\n"]

    for idx, reason in enumerate(candidates, 1):
        stats = reason.stats
        lines.append(
            f"{idx}. {reason.skill_name} ({reason.reason_type})\n"
            f"   - Calls: {stats.call_count}, Success rate: {stats.success_rate:.1%}\n"
            f"   - Last used: {stats.last_used_at.strftime('%Y-%m-%d') if stats.last_used_at else 'Never'}\n"
            f"   - Reason: {reason.reason_message}"
        )

    return "\n".join(lines)


def _format_detailed_suggestions(candidates: list[ForgettingReason], all_skills: list[SkillMetadata]) -> str:
    """Format detailed cleanup suggestions."""
    lines = [
        f"Skill cleanup suggestions ({len(candidates)}/{len(all_skills)} skills):\n",
        "=" * 60,
        "",
    ]

    # Group by reason type
    by_type: dict[str, list[ForgettingReason]] = {}
    for reason in candidates:
        by_type.setdefault(reason.reason_type, []).append(reason)

    for reason_type, reasons in by_type.items():
        lines.append(f"{reason_type.upper().replace('_', ' ')} ({len(reasons)} skills):")
        lines.append("")

        for reason in reasons:
            stats = reason.stats
            lines.append(f"  • {reason.skill_name}")
            lines.append(
                f"    Calls: {stats.call_count} | Success: {stats.success_rate:.1%} | Last: {stats.last_used_at.strftime('%Y-%m-%d') if stats.last_used_at else 'Never'}"
            )
            lines.append(f"    → {reason.reason_message}")
            lines.append("")

    lines.append("=" * 60)
    lines.append("Recommendation: Review and delete unnecessary skills using skill_manage.delete().")
    lines.append("IMPORTANT: Confirm with user before deleting!")

    return "\n".join(lines)
