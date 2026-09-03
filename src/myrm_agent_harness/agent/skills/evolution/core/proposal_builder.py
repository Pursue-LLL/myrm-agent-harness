"""Proposal Builder for Skill Evolution.

Generates the standardized EvolutionProposal data structure, decoupling the
framework from direct file-system modifications.

[INPUT]
- utils.json_parsing::parse_llm_json_object (POS: robust JSON object extraction from LLM output — fences, prose, bare control chars, trailing commas)

[OUTPUT]
- ProposalBuilder: Builds an EvolutionProposal for review by Server/Frontend.

[POS]
Proposal Builder for Skill Evolution.
"""

import difflib
import logging
from datetime import UTC, datetime
from typing import Any

from myrm_agent_harness.agent.skills.evolution.core.eval_regression import (
    evaluate_content_assertions,
)
from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionProposal,
    EvolutionType,
    SkillRecord,
)
from myrm_agent_harness.eval.leakage_guard import (
    evaluate_pareto_generalization,
    is_test_case_spec,
)
from myrm_agent_harness.eval.manifest_prediction import (
    ChangePredictionManifest,
    MetricPrediction,
    PredictionDirection,
)
from myrm_agent_harness.utils.json_parsing import parse_llm_json_object

logger = logging.getLogger(__name__)


def build_change_manifest(
    *,
    eval_cases: list[dict[str, Any]] | None,
    skill_name: str,
    skill_id: str,
    evolution_type: str,
    reasoning: str,
    original_content: str,
    proposed_content: str,
) -> dict[str, Any] | None:
    """Build a falsifiable change prediction manifest for an evolution proposal.

    Baseline and target pass rates are computed deterministically by the
    zero-LLM static-assertion engine against the skill's bound eval_cases
    (proposal-updated cases take precedence). Returns None when the skill has
    no usable eval_cases or the evolution type carries no code content
    (e.g. OPTIMIZE_DESCRIPTION) so static code assertions would be meaningless.
    """
    if evolution_type == EvolutionType.OPTIMIZE_DESCRIPTION.value:
        return None
    if not eval_cases:
        return None

    baseline_pass_rate = evaluate_content_assertions(eval_cases, original_content)
    target_pass_rate = evaluate_content_assertions(eval_cases, proposed_content)

    search_cases = [c for c in eval_cases if not is_test_case_spec(c)]
    test_cases = [c for c in eval_cases if is_test_case_spec(c)]

    predictions = [
        MetricPrediction(
            metric_name="pass_rate",
            direction=PredictionDirection.INCREASE,
            baseline_value=baseline_pass_rate,
            target_value=max(target_pass_rate, baseline_pass_rate),
            tolerance=0.05,
        ),
    ]

    base_search_rate = evaluate_content_assertions(search_cases, original_content) if search_cases else baseline_pass_rate
    target_search_rate = evaluate_content_assertions(search_cases, proposed_content) if search_cases else target_pass_rate

    base_test_rate = evaluate_content_assertions(test_cases, original_content) if test_cases else None
    target_test_rate = evaluate_content_assertions(test_cases, proposed_content) if test_cases else None

    if test_cases and base_test_rate is not None and target_test_rate is not None:
        predictions.append(
            MetricPrediction(
                metric_name="test_pass_rate",
                direction=PredictionDirection.INCREASE,
                baseline_value=base_test_rate,
                target_value=max(target_test_rate, base_test_rate),
                tolerance=0.05,
            )
        )

    pareto_verdict = evaluate_pareto_generalization(
        baseline_search_rate=base_search_rate,
        target_search_rate=target_search_rate,
        baseline_test_rate=base_test_rate,
        target_test_rate=target_test_rate,
    )

    manifest = ChangePredictionManifest(
        manifest_id=f"manifest-{skill_id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        target_component=f"skills/{skill_name}",
        rationale=reasoning or "Self-evolution enhancement",
        predictions=predictions,
        created_at=datetime.now(UTC).isoformat(),
    )
    manifest_dict = manifest.to_dict()
    manifest_dict["pareto_generalization_verdict"] = pareto_verdict.value
    manifest_dict["search_pass_rate"] = target_search_rate
    manifest_dict["test_pass_rate"] = target_test_rate
    return manifest_dict


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

        updated_eval_cases = None
        if edit_summary and isinstance(edit_summary.get("updated_eval_cases"), list):
            updated_eval_cases = edit_summary["updated_eval_cases"]

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
            updated_eval_cases=updated_eval_cases,
            created_at=datetime.now(),
            change_manifest=build_change_manifest(
                eval_cases=(
                    updated_eval_cases
                    if updated_eval_cases is not None
                    else skill.eval_cases
                ),
                skill_name=skill.name,
                skill_id=skill.skill_id,
                evolution_type=evolution_type.value,
                reasoning=reasoning,
                original_content=original,
                proposed_content=content,
            ),
        )

        logger.info(
            "Built EvolutionProposal for skill %s (Score: %.2f)", skill.name, score
        )
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

        summary = parse_llm_json_object(summary_raw)
        if summary is not None:
            return skill_content, summary

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
