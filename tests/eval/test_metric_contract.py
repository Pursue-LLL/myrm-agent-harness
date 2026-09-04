"""Unit tests for Metric Contract SSOT and Proxy Alignment Guard."""

from __future__ import annotations

from myrm_agent_harness.eval.metric_contract import (
    MetricContract,
    MetricIntentSpec,
    MetricProxySpec,
    ProxyAlignmentVerdict,
    evaluate_metric_proxy_alignment,
)


def test_metric_contract_serialization() -> None:
    """Verify serialization of MetricContract and default values."""
    contract = MetricContract(contract_id="contract_test_v1")
    data = contract.to_dict()

    assert data["contract_id"] == "contract_test_v1"
    assert data["min_sample_size"] == 5
    assert len(data["primary_intents"]) >= 2
    assert len(data["proxies"]) >= 2


def test_unconverged_sample_size() -> None:
    """Verify small sample sizes trigger UNCONVERGED to avoid false positive alarms."""
    baseline = {"pass_rate": 0.8, "tokens": 1000.0}
    candidate = {"pass_rate": 0.5, "tokens": 500.0}

    # Default min_sample_size is 5, test with sample_size=3
    analysis = evaluate_metric_proxy_alignment(
        baseline_metrics=baseline,
        candidate_metrics=candidate,
        sample_size=3,
    )

    assert analysis.verdict == ProxyAlignmentVerdict.UNCONVERGED
    assert "below confidence threshold" in analysis.warning_message
    assert analysis.sample_size == 3


def test_aligned_perfect_improvement() -> None:
    """Verify true improvement where core intent improves and proxies optimize."""
    baseline = {"pass_rate": 0.8, "tokens": 1000.0, "duration_ms": 3000.0}
    candidate = {"pass_rate": 0.95, "tokens": 800.0, "duration_ms": 2500.0}

    analysis = evaluate_metric_proxy_alignment(
        baseline_metrics=baseline,
        candidate_metrics=candidate,
        sample_size=10,
    )

    assert analysis.verdict == ProxyAlignmentVerdict.ALIGNED
    assert analysis.intent_delta > 0
    assert analysis.proxy_improvement > 0
    assert "well-aligned" in analysis.warning_message


def test_accepted_tradeoff() -> None:
    """Verify acceptable trade-off: slight fluctuation in core intent within tolerance offset by massive proxy gain."""
    # pass_rate tolerance is 0.03 (3%), dropping from 1.0 to 0.98 (-2%) with 50% token reduction
    baseline = {"pass_rate": 1.0, "tokens": 2000.0}
    candidate = {"pass_rate": 0.98, "tokens": 1000.0}

    contract = MetricContract(
        contract_id="tradeoff_test",
        primary_intents=(MetricIntentSpec(name="pass_rate", tolerance=0.03),),
        proxies=(MetricProxySpec(name="tokens", higher_is_better=False),),
        min_sample_size=5,
    )

    analysis = evaluate_metric_proxy_alignment(
        baseline_metrics=baseline,
        candidate_metrics=candidate,
        contract=contract,
        sample_size=8,
    )

    assert analysis.verdict == ProxyAlignmentVerdict.ACCEPTED_TRADEOFF
    assert analysis.intent_delta < 0
    assert analysis.proxy_improvement >= 0.30
    assert "Accepted Trade-off" in analysis.warning_message


def test_goodhart_drift_corner_cutting() -> None:
    """Verify Goodhart's law drift where proxies improve by cutting corners on core fidelity."""
    # Tokens slashed by 60%, tool calls down 70%, but pass_rate plunged from 90% to 60%
    baseline = {"pass_rate": 0.90, "tokens": 5000.0, "tool_calls": 10.0}
    candidate = {"pass_rate": 0.60, "tokens": 2000.0, "tool_calls": 3.0}

    analysis = evaluate_metric_proxy_alignment(
        baseline_metrics=baseline,
        candidate_metrics=candidate,
        sample_size=12,
    )

    assert analysis.verdict == ProxyAlignmentVerdict.GOODHART_DRIFT
    assert analysis.intent_delta < -0.05
    assert analysis.proxy_improvement > 0.10
    assert "Goodhart's Law Drift detected" in analysis.warning_message
    assert "tokens" in analysis.flagged_proxies or "tool_calls" in analysis.flagged_proxies


def test_missing_intent_metrics_safe_unconverged() -> None:
    """Verify evaluation safely handles payloads lacking primary intent metrics."""
    baseline = {"custom_foo": 10.0}
    candidate = {"custom_foo": 5.0}

    analysis = evaluate_metric_proxy_alignment(
        baseline_metrics=baseline,
        candidate_metrics=candidate,
        sample_size=10,
    )

    assert analysis.verdict == ProxyAlignmentVerdict.UNCONVERGED
    assert "No matching primary intent metrics" in analysis.warning_message
