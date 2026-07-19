from myrm_agent_harness.agent.goals.types import (
    ContinuationDecision,
    Goal,
    GoalBudget,
    GoalExecutionSummary,
    GoalStatus,
)


def test_goal_status_enum():
    assert GoalStatus.ACTIVE == "active"
    assert GoalStatus.PAUSED == "paused"
    assert GoalStatus.BUDGET_LIMITED == "budget_limited"
    assert GoalStatus.WAIT == "wait"
    assert GoalStatus.COMPLETE == "complete"
    assert GoalStatus.CANCELLED == "cancelled"


def test_goal_budget_creation():
    budget = GoalBudget(max_tokens=1000, max_usd=1.5, max_time_seconds=3600)
    assert budget.max_tokens == 1000
    assert budget.max_usd == 1.5
    assert budget.max_time_seconds == 3600
    assert budget.max_turns is None


def test_goal_budget_with_max_turns():
    budget = GoalBudget(max_tokens=1000, max_turns=25)
    assert budget.max_turns == 25


def test_goal_creation_and_properties():
    goal = Goal(
        goal_id="test-goal-1",
        session_id="test-session-1",
        objective="Test objective",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_tokens=5000),
        tokens_used=100,
        time_used_seconds=10,
        cost_usd=0.01,
        turns_used=3,
        metadata={"key": "value"},
    )

    assert goal.goal_id == "test-goal-1"
    assert goal.session_id == "test-session-1"
    assert goal.objective == "Test objective"
    assert goal.status == GoalStatus.ACTIVE
    assert goal.budget.max_tokens == 5000
    assert goal.tokens_used == 100
    assert goal.time_used_seconds == 10
    assert goal.cost_usd == 0.01
    assert goal.turns_used == 3
    assert goal.metadata == {"key": "value"}

    assert goal.is_active is True
    assert goal.is_terminal is False


def test_goal_turns_used_default():
    goal = Goal(
        goal_id="g1", session_id="s1", objective="obj", status=GoalStatus.ACTIVE
    )
    assert goal.turns_used == 0


def test_goal_terminal_states():
    goal_complete = Goal(
        goal_id="g1", session_id="s1", objective="obj", status=GoalStatus.COMPLETE
    )
    assert goal_complete.is_active is False
    assert goal_complete.is_terminal is True

    goal_cancelled = Goal(
        goal_id="g2", session_id="s2", objective="obj", status=GoalStatus.CANCELLED
    )
    assert goal_cancelled.is_active is False
    assert goal_cancelled.is_terminal is True


def test_goal_to_dict():
    goal = Goal(
        goal_id="test-goal-1",
        session_id="test-session-1",
        objective="Test objective",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_tokens=5000, max_usd=2.0, max_time_seconds=600, max_turns=20),
        tokens_used=100,
        time_used_seconds=10,
        cost_usd=0.01,
        turns_used=5,
        metadata={"key": "value"},
    )

    d = goal.to_dict()
    assert d["goal_id"] == "test-goal-1"
    assert d["session_id"] == "test-session-1"
    assert d["objective"] == "Test objective"
    assert d["status"] == "active"
    assert d["budget"]["max_tokens"] == 5000
    assert d["budget"]["max_usd"] == 2.0
    assert d["budget"]["max_time_seconds"] == 600
    assert d["budget"]["max_turns"] == 20
    assert d["tokens_used"] == 100
    assert d["time_used_seconds"] == 10
    assert d["cost_usd"] == 0.01
    assert d["turns_used"] == 5
    assert d["metadata"] == {"key": "value"}
    assert "created_at" in d
    assert "updated_at" in d


def test_goal_constraints_default_empty():
    goal = Goal(goal_id="g1", session_id="s1", objective="obj", status=GoalStatus.ACTIVE)
    assert goal.constraints == []


def test_goal_constraints_set_and_to_dict():
    constraints = ["Do not modify production files", "Must not exceed 100 API calls"]
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="obj",
        status=GoalStatus.ACTIVE,
        constraints=constraints,
    )
    assert goal.constraints == constraints
    d = goal.to_dict()
    assert d["constraints"] == constraints


def test_continuation_decision():
    decision = ContinuationDecision(
        should_continue=True,
        verdict="continue",
        reason="All guards passed",
        turns_used=3,
        max_turns=25,
        message="prompt text",
    )
    assert decision.should_continue is True
    assert decision.verdict == "continue"
    assert decision.turns_used == 3
    assert decision.max_turns == 25

    stop = ContinuationDecision(
        should_continue=False,
        verdict="budget",
        reason="Budget exhausted",
    )
    assert stop.should_continue is False
    assert stop.turns_used is None
    assert stop.message == ""


def test_execution_summary_creation_and_to_dict():
    summary = GoalExecutionSummary(
        files_modified=("src/main.py", "tests/test_main.py"),
        verifications=({"cmd": "pytest", "passed": True}, {"cmd": "ruff check", "passed": False}),
        browser_checks=2,
        total_tokens=15000,
        total_cost_usd=0.12,
        execution_duration_s=45.3,
        turns_used=7,
    )

    assert summary.files_modified == ("src/main.py", "tests/test_main.py")
    assert len(summary.verifications) == 2
    assert summary.browser_checks == 2
    assert summary.total_tokens == 15000
    assert summary.total_cost_usd == 0.12
    assert summary.execution_duration_s == 45.3
    assert summary.turns_used == 7

    d = summary.to_dict()
    assert d["files_modified"] == ["src/main.py", "tests/test_main.py"]
    assert d["verifications"] == [{"cmd": "pytest", "passed": True}, {"cmd": "ruff check", "passed": False}]
    assert d["browser_checks"] == 2
    assert d["total_tokens"] == 15000
    assert d["total_cost_usd"] == 0.12
    assert d["execution_duration_s"] == 45.3
    assert d["turns_used"] == 7


def test_execution_summary_immutable():
    summary = GoalExecutionSummary(
        files_modified=(),
        verifications=(),
        browser_checks=0,
        total_tokens=0,
        total_cost_usd=0.0,
        execution_duration_s=0.0,
        turns_used=0,
    )
    import pytest

    with pytest.raises(Exception):
        summary.turns_used = 5  # type: ignore[misc]
