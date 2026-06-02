"""Tests for goals/steering_prompts.py."""

from myrm_agent_harness.agent.goals.steering_prompts import (
    build_objective_updated_steering_message,
)
from myrm_agent_harness.agent.goals.types import Goal, GoalBudget, GoalStatus


def _make_goal(
    objective: str = "Test objective",
    tokens_used: int = 5000,
    budget: GoalBudget | None = None,
    constraints: list[str] | None = None,
) -> Goal:
    return Goal(
        goal_id="g1",
        session_id="s1",
        objective=objective,
        status=GoalStatus.ACTIVE,
        tokens_used=tokens_used,
        budget=budget,
        constraints=constraints or [],
    )


def test_basic_structure():
    msg = build_objective_updated_steering_message(_make_goal())
    assert "The active goal objective was edited by the user" in msg
    assert "<untrusted_objective>" in msg
    assert "Test objective" in msg
    assert "</untrusted_objective>" in msg
    assert "Tokens used: 5000" in msg


def test_budget_info_with_max_tokens():
    goal = _make_goal(budget=GoalBudget(max_tokens=10000), tokens_used=3000)
    msg = build_objective_updated_steering_message(goal)
    assert "Token budget: 10000" in msg
    assert "Tokens remaining: 7000" in msg


def test_budget_info_without_budget():
    goal = _make_goal(budget=None)
    msg = build_objective_updated_steering_message(goal)
    assert "Token budget: none" in msg
    assert "Tokens remaining: unknown" in msg


def test_constraints_reminder():
    goal = _make_goal(constraints=["No SQL injection", "Keep under 100ms"])
    msg = build_objective_updated_steering_message(goal)
    assert "Active constraints still apply" in msg
    assert "No SQL injection" in msg
    assert "Keep under 100ms" in msg


def test_no_constraints_no_reminder():
    goal = _make_goal(constraints=[])
    msg = build_objective_updated_steering_message(goal)
    assert "Active constraints still apply" not in msg


def test_xml_escape():
    goal = _make_goal(objective="Use <script>alert('xss')</script> & more")
    msg = build_objective_updated_steering_message(goal)
    assert "&lt;script&gt;" in msg
    assert "&amp; more" in msg
    assert "<script>" not in msg


def test_plan_update_reminder():
    msg = build_objective_updated_steering_message(_make_goal())
    assert "update it to reflect the new objective" in msg


def test_direction_adjustment_instruction():
    msg = build_objective_updated_steering_message(_make_goal())
    assert "Adjust the current turn to pursue the updated objective" in msg
    assert "Avoid continuing work that only served the previous objective" in msg


def test_unicode_objective():
    goal = _make_goal(objective="构建用户管理 REST API，支持中文 🎯")
    msg = build_objective_updated_steering_message(goal)
    assert "构建用户管理 REST API" in msg
    assert "<untrusted_objective>" in msg


def test_tokens_exceeded_budget():
    """When tokens_used exceeds max_tokens, remaining should be 0."""
    goal = _make_goal(budget=GoalBudget(max_tokens=5000), tokens_used=8000)
    msg = build_objective_updated_steering_message(goal)
    assert "Tokens used: 8000" in msg
    assert "Tokens remaining: 0" in msg


def test_multiline_objective():
    goal = _make_goal(objective="Line 1\nLine 2\nLine 3")
    msg = build_objective_updated_steering_message(goal)
    assert "Line 1\nLine 2\nLine 3" in msg


def test_multiple_constraints():
    goal = _make_goal(constraints=["C1", "C2", "C3", "C4"])
    msg = build_objective_updated_steering_message(goal)
    for c in ["C1", "C2", "C3", "C4"]:
        assert f"- {c}" in msg
