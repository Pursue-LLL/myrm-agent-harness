"""Unit tests for Trajectory Failure Mode Taxonomy & Analysis Engine."""

from __future__ import annotations

from myrm_agent_harness.eval import (
    WEIGHTS_RUBRIC_7D,
    AgentResponse,
    EvalCase,
    EvalResult,
    EvalTurnResult,
    FailureMode,
    aggregate_failure_modes,
    analyze_turn_failure_mode,
)


def test_weights_rubric_completeness() -> None:
    """Verify 7D weights sum up to 1.0 within floating point precision."""
    total_weight = sum(WEIGHTS_RUBRIC_7D.values())
    assert abs(total_weight - 1.0) < 1e-6
    assert len(WEIGHTS_RUBRIC_7D) == 7


def test_passed_turn_returns_none_analysis() -> None:
    """A passing turn with no errors should produce no failure diagnosis."""
    turn = EvalTurnResult(
        case=EvalCase(message="List files"),
        response=AgentResponse(answer="Done"),
        assertion_passed=True,
    )
    assert analyze_turn_failure_mode(turn) is None


def test_classify_decontam_violation() -> None:
    """Canary failure or cheat detection triggers DECONTAM_VIOLATION."""
    turn = EvalTurnResult(
        case=EvalCase(message="Inspect test"),
        response=AgentResponse(answer="Leaked canary"),
        assertion_passed=False,
        canary_verified=False,
    )
    analysis = analyze_turn_failure_mode(turn)
    assert analysis is not None
    assert analysis.failure_mode == FailureMode.DECONTAM_VIOLATION


def test_classify_context_overflow_or_budget() -> None:
    """Budget limit hit triggers CONTEXT_OVERFLOW_OR_BUDGET."""
    turn = EvalTurnResult(
        case=EvalCase(message="Solve complex issue"),
        response=AgentResponse(answer="Incomplete", limit_reached="max_tool_calls"),
        assertion_passed=False,
    )
    analysis = analyze_turn_failure_mode(turn)
    assert analysis is not None
    assert analysis.failure_mode == FailureMode.CONTEXT_OVERFLOW_OR_BUDGET


def test_classify_execution_timeout() -> None:
    """Command timeout triggers EXECUTION_TIMEOUT."""
    turn = EvalTurnResult(
        case=EvalCase(message="Run slow test"),
        response=AgentResponse(answer=""),
        assertion_passed=False,
        assertion_details="Command timed out after 600 seconds",
    )
    analysis = analyze_turn_failure_mode(turn)
    assert analysis is not None
    assert analysis.failure_mode == FailureMode.EXECUTION_TIMEOUT


def test_classify_hardcoded_tests_cheat() -> None:
    """Claiming passed while failing test assertions triggers HARDCODED_TESTS."""
    turn = EvalTurnResult(
        case=EvalCase(message="Implement feature"),
        response=AgentResponse(answer="Tests return true and passed 100%"),
        assertion_passed=False,
        assertion_details="Test suite failed: 0/5 passed",
    )
    analysis = analyze_turn_failure_mode(turn)
    assert analysis is not None
    assert analysis.failure_mode == FailureMode.HARDCODED_TESTS
    assert analysis.is_hardcoded_cheat is True


def test_classify_tool_argument_malformed() -> None:
    """Malformed tool argument triggers TOOL_ARGUMENT_MALFORMED."""
    turn = EvalTurnResult(
        case=EvalCase(message="Call API"),
        response=AgentResponse(answer=""),
        assertion_passed=False,
        assertion_details="invalid_tool_call_arguments: missing required field",
    )
    analysis = analyze_turn_failure_mode(turn)
    assert analysis is not None
    assert analysis.failure_mode == FailureMode.TOOL_ARGUMENT_MALFORMED


def test_aggregate_failure_modes_and_pareto() -> None:
    """Verify aggregate failure mode distribution and Pareto statistics in EvalResult."""
    turn1 = EvalTurnResult(
        case=EvalCase(message="Task 1"),
        response=AgentResponse(answer="Success"),
        assertion_passed=True,
    )
    turn2 = EvalTurnResult(
        case=EvalCase(message="Task 2"),
        response=AgentResponse(answer="", limit_reached="max_iterations"),
        assertion_passed=False,
    )
    turn3 = EvalTurnResult(
        case=EvalCase(message="Task 3"),
        response=AgentResponse(answer=""),
        assertion_passed=False,
        assertion_details="Command timed out",
    )

    eval_res = EvalResult(turn_results=[turn1, turn2, turn3])
    report_dict = eval_res.to_dict()

    assert "failure_analysis" in report_dict
    fa = report_dict["failure_analysis"]
    assert fa["total_failures"] == 2
    assert fa["failure_distribution"][FailureMode.CONTEXT_OVERFLOW_OR_BUDGET.value] == 1
    assert fa["failure_distribution"][FailureMode.EXECUTION_TIMEOUT.value] == 1
    assert (
        fa["pareto_percentages"][FailureMode.CONTEXT_OVERFLOW_OR_BUDGET.value] == 50.0
    )
    assert fa["pareto_percentages"][FailureMode.EXECUTION_TIMEOUT.value] == 50.0
    assert len(fa["details"]) == 2
