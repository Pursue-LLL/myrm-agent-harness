"""Falsifiable change prediction manifest for skill evolution proposals.

[INPUT]
- agent.skills.evolution.core.eval_regression::evaluate_content_assertions
- agent.skills.evolution.core.types::EvolutionType
- eval.leakage_guard::{evaluate_pareto_generalization, is_test_case_spec}
- eval.manifest_prediction::{ChangePredictionManifest, MetricPrediction, PredictionDirection}

[OUTPUT]
- build_change_manifest: baseline/target pass rates and a held-out generalization verdict for UI review

[POS]
Framework-owned, deterministic (no LLM, no disk writes). Consumed by ProposalBuilder so the
approval card can show what a proposal is predicted to change before the user applies it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from myrm_agent_harness.agent.skills.evolution.core.eval_regression import (
    evaluate_content_assertions,
)
from myrm_agent_harness.agent.skills.evolution.core.types import EvolutionType
from myrm_agent_harness.eval.leakage_guard import (
    evaluate_pareto_generalization,
    is_test_case_spec,
)
from myrm_agent_harness.eval.manifest_prediction import (
    ChangePredictionManifest,
    MetricPrediction,
    PredictionDirection,
)

_PASS_RATE_TOLERANCE = 0.05


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
            tolerance=_PASS_RATE_TOLERANCE,
        ),
    ]

    base_search_rate = (
        evaluate_content_assertions(search_cases, original_content) if search_cases else baseline_pass_rate
    )
    target_search_rate = (
        evaluate_content_assertions(search_cases, proposed_content) if search_cases else target_pass_rate
    )

    base_test_rate = evaluate_content_assertions(test_cases, original_content) if test_cases else None
    target_test_rate = evaluate_content_assertions(test_cases, proposed_content) if test_cases else None

    if test_cases and base_test_rate is not None and target_test_rate is not None:
        predictions.append(
            MetricPrediction(
                metric_name="test_pass_rate",
                direction=PredictionDirection.INCREASE,
                baseline_value=base_test_rate,
                target_value=max(target_test_rate, base_test_rate),
                tolerance=_PASS_RATE_TOLERANCE,
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
