from myrm_agent_harness.agent.goals.audit import (
    build_continuation_prompt,
    build_judge_criteria,
    get_audit_protocol,
)
from myrm_agent_harness.agent.goals.types import Goal, GoalBudget, GoalStatus


def test_get_audit_protocol():
    protocol = get_audit_protocol()
    assert "Completion Audit Protocol" in protocol
    assert "proxy signals" in protocol


def test_build_continuation_prompt_no_budget():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Refactor database queries",
        status=GoalStatus.ACTIVE,
        tokens_used=500,
    )

    prompt = build_continuation_prompt(goal)

    assert "Continuing toward your standing goal" in prompt
    assert "Refactor database queries" in prompt
    assert "Tokens used: 500" in prompt
    assert "Completion Audit Protocol" in prompt
    assert "Take the next concrete step" in prompt
    assert "blocked and need user input" in prompt


def test_build_continuation_prompt_with_budget():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Refactor database queries",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_tokens=10000, max_usd=5.0, max_turns=20),
        tokens_used=5000,
        cost_usd=2.5,
        turns_used=8,
    )

    prompt = build_continuation_prompt(goal)

    assert "Tokens: 5000 / 10000 (remaining: 5000)" in prompt
    assert "Cost: $2.5000 / $5.0000" in prompt
    assert "Turns: 8 / 20" in prompt


def test_build_continuation_prompt_turns_no_max():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Test",
        status=GoalStatus.ACTIVE,
        turns_used=3,
    )

    prompt = build_continuation_prompt(goal)
    assert "Turns used: 3" in prompt


def test_build_judge_criteria():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Build a REST API for user management",
        status=GoalStatus.ACTIVE,
    )

    criteria = build_judge_criteria(goal)

    assert "strict judge" in criteria
    assert "Build a REST API for user management" in criteria
    assert "DONE" in criteria or "PASS" in criteria
    assert '{"done"' in criteria


def test_build_continuation_prompt_with_learnings_first_turn():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Add i18n support",
        status=GoalStatus.ACTIVE,
        turns_used=0,
        metadata={
            "relevant_learnings": [
                "Always sync locale files after modifying components",
                "Use bun run i18n:check to validate translations",
            ]
        },
    )

    prompt = build_continuation_prompt(goal)
    assert "Relevant learnings from previous goals:" in prompt
    assert "Always sync locale files" in prompt
    assert "bun run i18n:check" in prompt


def test_build_continuation_prompt_no_learnings_after_first_turn():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Add i18n support",
        status=GoalStatus.ACTIVE,
        turns_used=3,
        metadata={
            "relevant_learnings": [
                "Always sync locale files after modifying components",
            ]
        },
    )

    prompt = build_continuation_prompt(goal)
    assert "Relevant learnings" not in prompt


def test_build_continuation_prompt_with_constraints():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Deploy to production",
        status=GoalStatus.ACTIVE,
        constraints=["Do not modify production config files", "Must not exceed 100 API calls"],
    )

    prompt = build_continuation_prompt(goal)
    assert "CONSTRAINTS" in prompt
    assert "MUST NOT VIOLATE" in prompt
    assert "Do not modify production config files" in prompt
    assert "Must not exceed 100 API calls" in prompt


def test_build_continuation_prompt_without_constraints():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Simple task",
        status=GoalStatus.ACTIVE,
        constraints=[],
    )

    prompt = build_continuation_prompt(goal)
    assert "CONSTRAINTS" not in prompt


def test_build_judge_criteria_with_constraints():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Build API",
        status=GoalStatus.ACTIVE,
        constraints=["Do not modify database schema"],
    )

    criteria = build_judge_criteria(goal)
    assert "Do not modify database schema" in criteria


def test_build_judge_criteria_without_constraints():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Build API",
        status=GoalStatus.ACTIVE,
        constraints=[],
    )

    criteria = build_judge_criteria(goal)
    assert "Constraints (goal is NOT done" not in criteria


def test_continuation_prompt_contains_fidelity_block():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Optimize checkout latency",
        status=GoalStatus.ACTIVE,
    )
    prompt = build_continuation_prompt(goal)
    assert "Fidelity:" in prompt
    assert "persists across turns" in prompt
    assert "Do not redefine success" in prompt
    assert "Do not substitute a narrower" in prompt
    assert "misaligned" in prompt


def test_continuation_prompt_contains_evidence_block():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Deploy service",
        status=GoalStatus.ACTIVE,
    )
    prompt = build_continuation_prompt(goal)
    assert "Evidence-based work:" in prompt
    assert "file system and external state as authoritative" in prompt
    assert "inspect actual state before relying on it" in prompt


def test_continuation_prompt_contains_progress_visibility():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Run security audit",
        status=GoalStatus.ACTIVE,
    )
    prompt = build_continuation_prompt(goal)
    assert "Progress visibility:" in prompt
    assert "planner_tool" in prompt
    assert "trivial single-step" in prompt


def test_audit_protocol_contains_enhanced_rules():
    protocol = get_audit_protocol()
    assert "must prove completion" in protocol
    assert "narrow check" in protocol
    assert "broad claim" in protocol
    assert "uncertain or indirect evidence" in protocol


def test_continuation_prompt_with_subgoals():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Build feature",
        status=GoalStatus.ACTIVE,
        subgoals=[
            {"text": "Add unit tests", "created_at": "2026-05-28T10:00:00Z"},
            {"text": "Update docs", "created_at": "2026-05-28T10:05:00Z"},
        ],
    )
    prompt = build_continuation_prompt(goal)
    assert "CRITICAL - Newly Added Subgoals" in prompt
    assert "Add unit tests" in prompt
    assert "Update docs" in prompt


def test_judge_criteria_truncates_long_objective():
    long_objective = "x" * 3000
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective=long_objective,
        status=GoalStatus.ACTIVE,
    )
    criteria = build_judge_criteria(goal)
    assert "[truncated]" in criteria
    assert len(criteria) < len(long_objective) + 500


def test_continuation_prompt_ignores_non_list_learnings():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Task",
        status=GoalStatus.ACTIVE,
        turns_used=0,
        metadata={"relevant_learnings": "not a list"},
    )
    prompt = build_continuation_prompt(goal)
    assert "Relevant learnings" not in prompt


def test_continuation_prompt_full_combination():
    """Verify all blocks appear in correct order when all features enabled."""
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Full featured goal",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_tokens=50000, max_usd=10.0, max_turns=30),
        tokens_used=1000,
        cost_usd=0.5,
        turns_used=0,
        metadata={"relevant_learnings": ["Learning A"]},
        subgoals=[{"text": "Sub 1", "created_at": "2026-05-28T00:00:00Z"}],
        constraints=["Constraint X"],
    )
    prompt = build_continuation_prompt(goal)

    objective_pos = prompt.index("Full featured goal")
    learnings_pos = prompt.index("Relevant learnings")
    subgoals_pos = prompt.index("CRITICAL - Newly Added Subgoals")
    constraints_pos = prompt.index("CONSTRAINTS")
    budget_pos = prompt.index("Budget:")
    fidelity_pos = prompt.index("Fidelity:")
    evidence_pos = prompt.index("Evidence-based work:")
    instructions_pos = prompt.index("Instructions:")
    progress_pos = prompt.index("Progress visibility:")
    audit_pos = prompt.index("Completion Audit Protocol")

    assert objective_pos < learnings_pos < subgoals_pos < constraints_pos
    assert constraints_pos < budget_pos < fidelity_pos < evidence_pos
    assert evidence_pos < instructions_pos < progress_pos < audit_pos


def test_build_continuation_prompt_with_judge_reason():
    """Judge reason is injected between budget and fidelity sections."""
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Generate 5 charts",
        status=GoalStatus.ACTIVE,
        turns_used=3,
    )
    prompt = build_continuation_prompt(goal, last_judge_reason="Only 3/5 charts produced")

    assert "Previous evaluation feedback:" in prompt
    assert "Only 3/5 charts produced" in prompt
    assert "Address this specific gap" in prompt

    budget_pos = prompt.index("Budget:")
    feedback_pos = prompt.index("Previous evaluation feedback:")
    fidelity_pos = prompt.index("Fidelity:")
    assert budget_pos < feedback_pos < fidelity_pos


def test_build_continuation_prompt_no_judge_reason():
    """No feedback block when reason is None or empty."""
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Task",
        status=GoalStatus.ACTIVE,
        turns_used=3,
    )
    prompt_none = build_continuation_prompt(goal, last_judge_reason=None)
    prompt_empty = build_continuation_prompt(goal, last_judge_reason="")
    prompt_generic = build_continuation_prompt(goal, last_judge_reason="not complete")

    assert "Previous evaluation feedback:" not in prompt_none
    assert "Previous evaluation feedback:" not in prompt_empty
    assert "Previous evaluation feedback:" not in prompt_generic


def test_build_continuation_prompt_judge_reason_truncation():
    """Long judge reasons are truncated to 200 characters."""
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Task",
        status=GoalStatus.ACTIVE,
        turns_used=3,
    )
    long_reason = "x" * 300
    prompt = build_continuation_prompt(goal, last_judge_reason=long_reason)

    assert "Previous evaluation feedback:" in prompt
    assert "x" * 200 in prompt
    assert "x" * 201 not in prompt
