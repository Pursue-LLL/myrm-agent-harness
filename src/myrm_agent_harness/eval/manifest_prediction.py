"""Harness Change Manifest & Falsifiable Prediction Attribution Engine.

[INPUT]
- protocols::EvalResult, EvalTurnResult (POS: evaluation benchmark metrics)

[OUTPUT]
- PredictionDirection: expected metric trend (INCREASE, DECREASE, NEUTRAL, PRESERVE_MIN)
- MetricPrediction: falsifiable hypothesis per target metric
- ChangePredictionManifest: structured prediction contract attached to code/skill evolutions
- AttributionVerdict: outcome verdict (CONFIRMED, REFUTED, INCONCLUSIVE, REGRESSION)
- ManifestAttributionResult: evaluation attribution record comparing prediction vs reality
- evaluate_manifest_attribution(): deterministic verification and attribution engine

[POS]
Provides formal causal reasoning and regression foresight for autonomous agent evolutions.
Eliminates ungrounded code modifications by establishing a falsifiable hypothesis before evaluation.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class PredictionDirection(enum.StrEnum):
    """Direction of predicted metric movement."""

    INCREASE = "increase"  # Metric expected to rise (e.g. pass rate, speed)
    DECREASE = "decrease"  # Metric expected to drop (e.g. latency, token cost, error count)
    NEUTRAL = "neutral"  # Metric expected to remain roughly unchanged
    PRESERVE_MIN = "preserve_min"  # Baseline threshold that must not regress below


class AttributionVerdict(enum.StrEnum):
    """Attribution outcome after comparing predicted vs evaluated metrics."""

    CONFIRMED = "confirmed"  # Actual metric satisfied the falsifiable hypothesis
    REFUTED = "refuted"  # Metric failed to satisfy the prediction
    REGRESSION = "regression"  # Severe unexpected degradation observed
    INCONCLUSIVE = "inconclusive"  # Metric difference within statistical noise margin


@dataclass(frozen=True, slots=True)
class MetricPrediction:
    """A single falsifiable prediction for an evaluation metric."""

    metric_name: str  # e.g., "pass_rate", "total_cost", "avg_latency_ms"
    direction: PredictionDirection
    baseline_value: float
    target_value: float
    tolerance: float = 0.02  # Epsilon margin for statistical significance

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "direction": self.direction.value,
            "baseline_value": round(self.baseline_value, 4),
            "target_value": round(self.target_value, 4),
            "tolerance": round(self.tolerance, 4),
        }


@dataclass(slots=True)
class ChangePredictionManifest:
    """Formal change manifest accompanying an evolution or harness edit."""

    manifest_id: str
    target_component: str  # e.g., "harness/eval/runner.py", "skills/web_search"
    rationale: str
    predictions: list[MetricPrediction] = field(default_factory=list)
    rollback_patch: str | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "target_component": self.target_component,
            "rationale": self.rationale,
            "predictions": [p.to_dict() for p in self.predictions],
            "rollback_patch": self.rollback_patch,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class MetricAttributionDetail:
    """Attribution breakdown for an individual predicted metric."""

    metric_name: str
    predicted_target: float
    actual_value: float
    delta: float
    verdict: AttributionVerdict
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "predicted_target": round(self.predicted_target, 4),
            "actual_value": round(self.actual_value, 4),
            "delta": round(self.delta, 4),
            "verdict": self.verdict.value,
            "explanation": self.explanation,
        }


@dataclass(slots=True)
class ManifestAttributionResult:
    """Comprehensive attribution evaluation report for a ChangePredictionManifest."""

    manifest_id: str
    overall_verdict: AttributionVerdict
    metric_attributions: list[MetricAttributionDetail] = field(default_factory=list)
    confidence_score: float = 1.0  # 0.0 to 1.0
    recommended_action: str = "keep"  # "keep", "rollback", "re_evaluate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "overall_verdict": self.overall_verdict.value,
            "metric_attributions": [m.to_dict() for m in self.metric_attributions],
            "confidence_score": round(self.confidence_score, 4),
            "recommended_action": self.recommended_action,
        }


def evaluate_manifest_attribution(
    manifest: ChangePredictionManifest,
    actual_metrics: dict[str, float],
) -> ManifestAttributionResult:
    """Deterministically attribute evaluation metrics back to the change manifest's predictions."""
    details: list[MetricAttributionDetail] = []
    has_refutation = False
    has_regression = False
    all_confirmed = True

    for p in manifest.predictions:
        actual = actual_metrics.get(p.metric_name, p.baseline_value)
        delta = actual - p.baseline_value
        verdict = AttributionVerdict.INCONCLUSIVE
        explanation = ""

        if p.direction == PredictionDirection.INCREASE:
            if actual >= (p.target_value - p.tolerance):
                verdict = AttributionVerdict.CONFIRMED
                explanation = f"Met or exceeded target (+{delta:.2f})"
            elif actual < (p.baseline_value - p.tolerance):
                verdict = AttributionVerdict.REGRESSION
                explanation = f"Regressed below baseline ({delta:.2f})"
                has_regression = True
                all_confirmed = False
            else:
                verdict = AttributionVerdict.REFUTED
                explanation = f"Did not reach target (+{delta:.2f} vs expected target {p.target_value:.2f})"
                has_refutation = True
                all_confirmed = False

        elif p.direction == PredictionDirection.DECREASE:
            if actual <= (p.target_value + p.tolerance):
                verdict = AttributionVerdict.CONFIRMED
                explanation = f"Decreased as predicted ({delta:.2f})"
            elif actual > (p.baseline_value + p.tolerance):
                verdict = AttributionVerdict.REGRESSION
                explanation = f"Increased worse than baseline (+{delta:.2f})"
                has_regression = True
                all_confirmed = False
            else:
                verdict = AttributionVerdict.REFUTED
                explanation = f"Did not decrease sufficiently ({delta:.2f})"
                has_refutation = True
                all_confirmed = False

        elif p.direction == PredictionDirection.PRESERVE_MIN:
            if actual >= (p.target_value - p.tolerance):
                verdict = AttributionVerdict.CONFIRMED
                explanation = f"Preserved baseline threshold ({actual:.2f} >= {p.target_value:.2f})"
            else:
                verdict = AttributionVerdict.REGRESSION
                explanation = f"Violated baseline threshold ({actual:.2f} < {p.target_value:.2f})"
                has_regression = True
                all_confirmed = False

        else:  # NEUTRAL
            if abs(delta) <= p.tolerance:
                verdict = AttributionVerdict.CONFIRMED
                explanation = f"Remained within stable noise bounds (|Δ|={abs(delta):.2f})"
            else:
                verdict = AttributionVerdict.INCONCLUSIVE
                explanation = f"Observed minor drift (|Δ|={abs(delta):.2f})"
                all_confirmed = False

        details.append(
            MetricAttributionDetail(
                metric_name=p.metric_name,
                predicted_target=p.target_value,
                actual_value=actual,
                delta=delta,
                verdict=verdict,
                explanation=explanation,
            )
        )

    if has_regression:
        overall_verdict = AttributionVerdict.REGRESSION
        recommended_action = "rollback"
    elif has_refutation:
        overall_verdict = AttributionVerdict.REFUTED
        recommended_action = "re_evaluate"
    elif all_confirmed:
        overall_verdict = AttributionVerdict.CONFIRMED
        recommended_action = "keep"
    else:
        overall_verdict = AttributionVerdict.INCONCLUSIVE
        recommended_action = "keep"

    return ManifestAttributionResult(
        manifest_id=manifest.manifest_id,
        overall_verdict=overall_verdict,
        metric_attributions=details,
        confidence_score=0.95 if all_confirmed or has_regression else 0.75,
        recommended_action=recommended_action,
    )
