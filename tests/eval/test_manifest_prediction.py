"""Unit tests for Harness Change Manifest & Falsifiable Prediction Attribution Engine."""

from __future__ import annotations

import pytest

from myrm_agent_harness.eval.manifest_prediction import (
    AttributionVerdict,
    ChangePredictionManifest,
    MetricAttributionDetail,
    MetricPrediction,
    ManifestAttributionResult,
    PredictionDirection,
    evaluate_manifest_attribution,
)


def test_metric_prediction_to_dict() -> None:
    pred = MetricPrediction(
        metric_name="pass_rate",
        direction=PredictionDirection.INCREASE,
        baseline_value=0.5,
        target_value=1.0,
        tolerance=0.01,
    )
    d = pred.to_dict()
    assert d["metric_name"] == "pass_rate"
    assert d["direction"] == "increase"
    assert d["baseline_value"] == 0.5
    assert d["target_value"] == 1.0
    assert d["tolerance"] == 0.01


def test_change_prediction_manifest_to_dict() -> None:
    manifest = ChangePredictionManifest(
        manifest_id="pred_123",
        target_component="skills/test_skill",
        rationale="Fix regex pattern",
        predictions=[
            MetricPrediction(
                metric_name="pass_rate",
                direction=PredictionDirection.INCREASE,
                baseline_value=0.0,
                target_value=1.0,
            )
        ],
        rollback_patch="diff ...",
        created_at="2026-09-01T12:00:00Z",
    )
    d = manifest.to_dict()
    assert d["manifest_id"] == "pred_123"
    assert d["target_component"] == "skills/test_skill"
    assert d["rationale"] == "Fix regex pattern"
    assert len(d["predictions"]) == 1
    assert d["predictions"][0]["metric_name"] == "pass_rate"
    assert d["rollback_patch"] == "diff ..."
    assert d["created_at"] == "2026-09-01T12:00:00Z"


def test_manifest_attribution_result_to_dict() -> None:
    detail = MetricAttributionDetail(
        metric_name="pass_rate",
        predicted_target=1.0,
        actual_value=1.0,
        delta=0.0,
        verdict=AttributionVerdict.CONFIRMED,
        explanation="Target reached",
    )
    res = ManifestAttributionResult(
        manifest_id="pred_123",
        overall_verdict=AttributionVerdict.CONFIRMED,
        metric_attributions=[detail],
        confidence_score=1.0,
        recommended_action="keep",
    )
    d = res.to_dict()
    assert d["manifest_id"] == "pred_123"
    assert d["overall_verdict"] == "confirmed"
    assert len(d["metric_attributions"]) == 1
    assert d["confidence_score"] == 1.0
    assert d["recommended_action"] == "keep"


def test_evaluate_manifest_attribution_empty_predictions() -> None:
    manifest = ChangePredictionManifest(
        manifest_id="pred_empty",
        target_component="skills/test",
        rationale="No predictions",
        predictions=[],
    )
    res = evaluate_manifest_attribution(manifest, actual_metrics={})
    assert res.overall_verdict == AttributionVerdict.INCONCLUSIVE
    assert res.recommended_action == "re_evaluate"
    assert len(res.metric_attributions) == 0


def test_evaluate_manifest_attribution_increase_confirmed() -> None:
    manifest = ChangePredictionManifest(
        manifest_id="pred_inc",
        target_component="skills/test",
        rationale="Improve pass rate",
        predictions=[
            MetricPrediction(
                metric_name="pass_rate",
                direction=PredictionDirection.INCREASE,
                baseline_value=0.5,
                target_value=0.9,
                tolerance=0.05,
            )
        ],
    )
    res = evaluate_manifest_attribution(manifest, actual_metrics={"pass_rate": 0.95})
    assert res.overall_verdict == AttributionVerdict.CONFIRMED
    assert res.recommended_action == "keep"
    assert res.metric_attributions[0].verdict == AttributionVerdict.CONFIRMED


def test_evaluate_manifest_attribution_increase_regression() -> None:
    manifest = ChangePredictionManifest(
        manifest_id="pred_reg",
        target_component="skills/test",
        rationale="Improve pass rate",
        predictions=[
            MetricPrediction(
                metric_name="pass_rate",
                direction=PredictionDirection.INCREASE,
                baseline_value=0.5,
                target_value=1.0,
                tolerance=0.05,
            )
        ],
    )
    res = evaluate_manifest_attribution(manifest, actual_metrics={"pass_rate": 0.2})
    assert res.overall_verdict == AttributionVerdict.REGRESSION
    assert res.recommended_action == "rollback"
    assert res.metric_attributions[0].verdict == AttributionVerdict.REGRESSION


def test_evaluate_manifest_attribution_decrease_confirmed() -> None:
    manifest = ChangePredictionManifest(
        manifest_id="pred_dec",
        target_component="skills/test",
        rationale="Reduce latency",
        predictions=[
            MetricPrediction(
                metric_name="latency_ms",
                direction=PredictionDirection.DECREASE,
                baseline_value=100.0,
                target_value=50.0,
                tolerance=5.0,
            )
        ],
    )
    res = evaluate_manifest_attribution(manifest, actual_metrics={"latency_ms": 45.0})
    assert res.overall_verdict == AttributionVerdict.CONFIRMED
    assert res.metric_attributions[0].verdict == AttributionVerdict.CONFIRMED


def test_evaluate_manifest_attribution_preserve_min() -> None:
    manifest = ChangePredictionManifest(
        manifest_id="pred_pres",
        target_component="skills/test",
        rationale="Preserve accuracy",
        predictions=[
            MetricPrediction(
                metric_name="accuracy",
                direction=PredictionDirection.PRESERVE_MIN,
                baseline_value=0.9,
                target_value=0.9,
                tolerance=0.02,
            )
        ],
    )
    # Satisfied
    res1 = evaluate_manifest_attribution(manifest, actual_metrics={"accuracy": 0.91})
    assert res1.overall_verdict == AttributionVerdict.CONFIRMED

    # Regressed below threshold
    res2 = evaluate_manifest_attribution(manifest, actual_metrics={"accuracy": 0.85})
    assert res2.overall_verdict == AttributionVerdict.REGRESSION
    assert res2.recommended_action == "rollback"
