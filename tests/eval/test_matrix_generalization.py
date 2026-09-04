"""Unit tests for cross-model generalization gate in matrix.py."""

from __future__ import annotations

import pytest

from myrm_agent_harness.eval.matrix import (
    GeneralizationGateMetrics,
    GeneralizationGateVerdict,
    MatrixResult,
    evaluate_generalization_gate,
)
from myrm_agent_harness.eval.protocols import (
    AgentResponse,
    EvalCase,
    EvalResult,
    EvalTimings,
    EvalTurnResult,
)


def _make_case(idx: int) -> EvalCase:
    return EvalCase(message=f"test case {idx}")


def _make_turn(case: EvalCase, passed: bool) -> EvalTurnResult:
    return EvalTurnResult(
        case=case,
        response=AgentResponse(answer="mock response"),
        assertion_passed=passed,
        timings=EvalTimings(total_ms=15.0),
    )


def test_generalization_gate_insufficient_profiles() -> None:
    cases = [_make_case(0), _make_case(1)]
    single_res = EvalResult(turn_results=[_make_turn(cases[0], True), _make_turn(cases[1], True)])
    mat = MatrixResult(
        profile_ids=["qwen-2.5-7b"],
        cases=cases,
        per_profile_results={"qwen-2.5-7b": single_res},
    )
    metrics = evaluate_generalization_gate(mat, min_required_profiles=2)
    assert metrics.verdict == GeneralizationGateVerdict.INSUFFICIENT_PROFILES
    assert metrics.evaluated_profile_count == 1
    assert metrics.passed_profile_count == 0
    assert "at least 2 profiles" in metrics.recommendation


def test_generalization_gate_passed() -> None:
    cases = [_make_case(i) for i in range(4)]
    # All 4 cases pass on both profiles
    res_a = EvalResult(turn_results=[_make_turn(c, True) for c in cases])
    res_b = EvalResult(turn_results=[_make_turn(c, True) for c in cases])

    mat = MatrixResult(
        profile_ids=["claude-3-5", "deepseek-v3"],
        cases=cases,
        per_profile_results={"claude-3-5": res_a, "deepseek-v3": res_b},
    )
    metrics = evaluate_generalization_gate(mat, min_required_profiles=2, pass_rate_threshold=0.5)
    assert metrics.verdict == GeneralizationGateVerdict.PASSED
    assert metrics.evaluated_profile_count == 2
    assert metrics.passed_profile_count == 2
    assert metrics.regression_case_count == 0
    assert metrics.stable_case_count == 4
    assert metrics.mean_pass_rate == 1.0
    assert metrics.pass_rate_spread == 0.0
    assert "Safe to adopt globally" in metrics.recommendation

    d = metrics.to_dict()
    assert d["verdict"] == "passed"
    assert d["passed_profile_count"] == 2


def test_generalization_gate_partial_overfit() -> None:
    cases = [_make_case(i) for i in range(4)]
    # Profile A (e.g. Qwen): 4/4 pass (100%)
    res_a = EvalResult(turn_results=[_make_turn(c, True) for c in cases])
    # Profile B (e.g. Claude): 1/4 pass (25%) -> severe mismatch regression
    res_b = EvalResult(
        turn_results=[
            _make_turn(cases[0], True),
            _make_turn(cases[1], False),
            _make_turn(cases[2], False),
            _make_turn(cases[3], False),
        ]
    )

    mat = MatrixResult(
        profile_ids=["qwen-2.5-7b", "claude-3-5-sonnet"],
        cases=cases,
        per_profile_results={"qwen-2.5-7b": res_a, "claude-3-5-sonnet": res_b},
    )
    metrics = evaluate_generalization_gate(
        mat, min_required_profiles=2, pass_rate_threshold=0.5, max_regression_rate=0.25
    )
    assert metrics.verdict == GeneralizationGateVerdict.PARTIAL_OVERFIT
    assert metrics.passed_profile_count == 1
    assert metrics.regression_case_count == 3
    assert metrics.pass_rate_spread == 0.75
    assert "Overfitting detected" in metrics.recommendation
    assert "pathology" in metrics.recommendation


def test_generalization_gate_collapse() -> None:
    cases = [_make_case(i) for i in range(4)]
    # Both profiles fail almost completely
    res_a = EvalResult(turn_results=[_make_turn(c, False) for c in cases])
    res_b = EvalResult(turn_results=[_make_turn(c, False) for c in cases])

    mat = MatrixResult(
        profile_ids=["model-a", "model-b"],
        cases=cases,
        per_profile_results={"model-a": res_a, "model-b": res_b},
    )
    metrics = evaluate_generalization_gate(mat, min_required_profiles=2)
    assert metrics.verdict == GeneralizationGateVerdict.GENERALIZATION_COLLAPSE
    assert metrics.passed_profile_count == 0
    assert "Severe capability collapse" in metrics.recommendation


def test_matrix_result_to_dict_includes_gate() -> None:
    cases = [_make_case(0), _make_case(1)]
    res = EvalResult(turn_results=[_make_turn(cases[0], True), _make_turn(cases[1], True)])
    mat = MatrixResult(
        profile_ids=["p1", "p2"],
        cases=cases,
        per_profile_results={"p1": res, "p2": res},
    )
    data = mat.to_dict()
    assert "generalization_gate" in data
    gate = data["generalization_gate"]
    assert isinstance(gate, dict)
    assert gate["verdict"] == "passed"
    assert gate["evaluated_profile_count"] == 2
