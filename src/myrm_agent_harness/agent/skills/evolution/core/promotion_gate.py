"""Held-out regression gate for skill version promotion.

[INPUT]
- agent.skills.evolution.core.eval_regression::evaluate_content_assertions
- eval.leakage_guard::{evaluate_pareto_generalization, is_test_case_spec, ParetoGeneralizationVerdict}
- eval.manifest_prediction::{ChangePredictionManifest, MetricPrediction, PredictionDirection}

[OUTPUT]
- PromotionVerdictResult: allow/block decision with optional change manifest
- build_change_manifest: falsifiable manifest for UI (Growth + optimize promote)
- evaluate_promotion_gate: single entry for server optimize/shadow promote paths

[POS]
Framework-owned promotion gate. No LLM, no disk writes. Shared by evolution proposals
and skill-optimization promote / auto-promote (server calls in-process).
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from myrm_agent_harness.agent.skills.evolution.core.eval_regression import (
    evaluate_content_assertions,
)
from myrm_agent_harness.eval.leakage_guard import (
    ParetoGeneralizationVerdict,
    evaluate_pareto_generalization,
    is_test_case_spec,
)
from myrm_agent_harness.eval.manifest_prediction import (
    ChangePredictionManifest,
    MetricPrediction,
    PredictionDirection,
)

logger = logging.getLogger(__name__)

_PASS_RATE_TOLERANCE = 0.05

_BLOCKING_PARETO_VERDICTS = frozenset(
    {
        ParetoGeneralizationVerdict.REGRESSION,
        ParetoGeneralizationVerdict.GENERALIZATION_COLLAPSE,
        ParetoGeneralizationVerdict.OVERFITTING,
    }
)


class PromotionReasonCode(enum.StrEnum):
    """Machine-readable promotion gate outcome."""

    ALLOWED = "allowed"
    NO_EVAL_CASES = "no_eval_cases"
    REGRESSION = "regression"
    PARETO_BLOCK = "pareto_block"
    MISSING_CONTENT = "missing_content"


@dataclass(frozen=True, slots=True)
class PromotionVerdictResult:
    """Result of evaluating a candidate skill version for promotion."""

    allowed: bool
    reason_code: PromotionReasonCode
    baseline_pass_rate: float
    candidate_pass_rate: float
    pareto_verdict: str | None
    manifest: dict[str, Any] | None
    message: str


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
    """Build a falsifiable change prediction manifest (same semantics as Growth proposals)."""
    if evolution_type in {"optimize_description", "OPTIMIZE_DESCRIPTION"}:
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
        rationale=reasoning or "Skill version promotion",
        predictions=predictions,
        created_at=datetime.now(UTC).isoformat(),
    )
    manifest_dict = manifest.to_dict()
    manifest_dict["pareto_generalization_verdict"] = pareto_verdict.value
    manifest_dict["search_pass_rate"] = target_search_rate
    manifest_dict["test_pass_rate"] = target_test_rate
    return manifest_dict


def evaluate_promotion_gate(
    *,
    eval_cases: list[dict[str, Any]] | None,
    baseline_content: str,
    candidate_content: str,
    skill_name: str,
    skill_id: str,
    require_eval_cases: bool = False,
    reasoning: str = "",
) -> PromotionVerdictResult:
    """Decide whether a candidate version may replace the active baseline."""
    if not baseline_content.strip() or not candidate_content.strip():
        return PromotionVerdictResult(
            allowed=False,
            reason_code=PromotionReasonCode.MISSING_CONTENT,
            baseline_pass_rate=0.0,
            candidate_pass_rate=0.0,
            pareto_verdict=None,
            manifest=None,
            message="Baseline or candidate skill content is empty.",
        )

    cases = eval_cases or []
    if require_eval_cases and not cases:
        return PromotionVerdictResult(
            allowed=False,
            reason_code=PromotionReasonCode.NO_EVAL_CASES,
            baseline_pass_rate=0.0,
            candidate_pass_rate=0.0,
            pareto_verdict=None,
            manifest=None,
            message="Eval cases are required before promotion.",
        )

    if not cases:
        return PromotionVerdictResult(
            allowed=True,
            reason_code=PromotionReasonCode.ALLOWED,
            baseline_pass_rate=1.0,
            candidate_pass_rate=1.0,
            pareto_verdict=None,
            manifest=None,
            message="No eval cases bound; regression gate skipped.",
        )

    baseline_pass = evaluate_content_assertions(cases, baseline_content)
    candidate_pass = evaluate_content_assertions(cases, candidate_content)

    manifest = build_change_manifest(
        eval_cases=cases,
        skill_name=skill_name,
        skill_id=skill_id,
        evolution_type="skill_patch",
        reasoning=reasoning,
        original_content=baseline_content,
        proposed_content=candidate_content,
    )
    pareto_value = manifest.get("pareto_generalization_verdict") if manifest else None

    if candidate_pass < baseline_pass - _PASS_RATE_TOLERANCE:
        logger.info(
            "Promotion blocked: pass rate regression for %s (%.2f -> %.2f)",
            skill_id,
            baseline_pass,
            candidate_pass,
        )
        return PromotionVerdictResult(
            allowed=False,
            reason_code=PromotionReasonCode.REGRESSION,
            baseline_pass_rate=baseline_pass,
            candidate_pass_rate=candidate_pass,
            pareto_verdict=pareto_value,
            manifest=manifest,
            message="Candidate fails bound eval cases versus baseline.",
        )

    if pareto_value in {v.value for v in _BLOCKING_PARETO_VERDICTS}:
        return PromotionVerdictResult(
            allowed=False,
            reason_code=PromotionReasonCode.PARETO_BLOCK,
            baseline_pass_rate=baseline_pass,
            candidate_pass_rate=candidate_pass,
            pareto_verdict=pareto_value,
            manifest=manifest,
            message="Held-out eval split indicates overfitting or generalization collapse.",
        )

    return PromotionVerdictResult(
        allowed=True,
        reason_code=PromotionReasonCode.ALLOWED,
        baseline_pass_rate=baseline_pass,
        candidate_pass_rate=candidate_pass,
        pareto_verdict=pareto_value,
        manifest=manifest,
        message="Regression gate passed.",
    )
