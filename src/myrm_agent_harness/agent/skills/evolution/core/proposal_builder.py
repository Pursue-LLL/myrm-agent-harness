"""Proposal Builder for Skill Evolution.

Generates the standardized EvolutionProposal data structure, decoupling the
framework from direct file-system modifications.

[INPUT]
- (none)

[OUTPUT]
- ProposalBuilder: Builds an EvolutionProposal for review by Server/Frontend.

[POS]
Proposal Builder for Skill Evolution.
"""

import difflib
import json
import logging
from datetime import datetime
from typing import Any

from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionProposal,
    EvolutionType,
    SkillRecord,
)

logger = logging.getLogger(__name__)


class ProposalBuilder:
    """Builds an EvolutionProposal for review by Server/Frontend."""

    def build_proposal(
        self,
        skill: SkillRecord,
        evolution_type: EvolutionType,
        best_variant: str,
        score: float,
        reasoning: str,
        task_context: str = "",
        trajectory: str = "",
        is_general: bool = False,
    ) -> EvolutionProposal:
        """Create the proposal structure.

        Args:
            skill: Original skill record.
            evolution_type: The type of evolution triggered.
            best_variant: The proposed new content (or new description for OPTIMIZE_DESCRIPTION).
            score: The evaluator's score for the variant.
            reasoning: Why this variant is best.
            task_context: Associated intent context.
            trajectory: The detailed trace analysis report.
            is_general: Whether the skill is globally reusable.

        Returns:
            A constructed EvolutionProposal object.
        """
        content, edit_summary = self._split_edit_summary(best_variant)

        if evolution_type == EvolutionType.OPTIMIZE_DESCRIPTION:
            original = skill.description
            diff = self._generate_diff(original, content)
        else:
            original = skill.content
            diff = self._generate_diff(original, content)

        proposal = EvolutionProposal(
            skill_id=skill.skill_id,
            evolution_type=evolution_type,
            original_content=original,
            proposed_content=content,
            diff=diff,
            score=score,
            reasoning=reasoning,
            task_context=task_context,
            trajectory=trajectory,
            is_general=is_general,
            edit_summary=edit_summary,
            created_at=datetime.now(),
        )

        logger.info("Built EvolutionProposal for skill %s (Score: %.2f)", skill.name, score)
        return proposal

    @staticmethod
    def _split_edit_summary(content: str) -> tuple[str, dict[str, Any] | None]:
        """Extract edit_summary JSON block from LLM output if present.

        The variant_generator prompt asks LLM to append a block starting with
        `---EDIT_SUMMARY---` followed by JSON. This method separates it from
        the skill content.
        """
        separator = "---EDIT_SUMMARY---"
        if separator not in content:
            return content, None

        parts = content.split(separator, 1)
        skill_content = parts[0].rstrip()
        summary_raw = parts[1].strip()

        try:
            summary = json.loads(summary_raw)
            if isinstance(summary, dict):
                return skill_content, summary
        except (json.JSONDecodeError, ValueError):
            pass

        return skill_content, None

    def _generate_diff(self, original: str, new: str) -> str:
        """Generate a unified diff between the original and new content."""
        if not isinstance(original, str):
            original = str(original)
        if not isinstance(new, str):
            new = str(new)

        orig_lines = original.splitlines()
        new_lines = new.splitlines()

        diff_lines = list(
            difflib.unified_diff(
                orig_lines,
                new_lines,
                fromfile="Original SKILL",
                tofile="Proposed SKILL",
                lineterm="",
            )
        )
        return "\n".join(diff_lines)
