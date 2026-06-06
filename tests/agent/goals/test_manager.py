import pytest

from myrm_agent_harness.agent.goals.manager import GoalManager
from myrm_agent_harness.agent.goals.types import GoalBudget, GoalStatus
from myrm_agent_harness.toolkits.storage.local import LocalStorageBackend


@pytest.fixture
async def goal_manager(tmp_path):
    backend = LocalStorageBackend(base_path=str(tmp_path))
    manager = GoalManager(backend)
    yield manager


@pytest.mark.asyncio
async def test_create_and_get_active_goal(goal_manager):
    session_id = "session-1"

    # Create goal
    goal = await goal_manager.create_goal(
        session_id=session_id,
        objective="Do something great",
        budget=GoalBudget(max_tokens=100),
    )

    assert goal is not None
    assert goal.session_id == session_id
    assert goal.objective == "Do something great"
    assert goal.status == GoalStatus.ACTIVE
    assert goal.budget.max_tokens == 100

    # Get active goal
    active_goal = await goal_manager.get_active_goal(session_id)
    assert active_goal is not None
    assert active_goal.goal_id == goal.goal_id


@pytest.mark.asyncio
async def test_create_goal_queues_when_active_exists(goal_manager):
    session_id = "session-2"

    first = await goal_manager.create_goal(session_id, "First goal")
    assert first.status == GoalStatus.ACTIVE

    second = await goal_manager.create_goal(session_id, "Second goal")
    assert second.status == GoalStatus.QUEUED
    assert second.auto_approve is True

    active = await goal_manager.get_active_goal(session_id)
    assert active.goal_id == first.goal_id


@pytest.mark.asyncio
async def test_update_status(goal_manager):
    session_id = "session-3"
    goal = await goal_manager.create_goal(session_id, "Test status")

    # Update to paused
    updated = await goal_manager.update_status(goal.goal_id, GoalStatus.PAUSED)
    assert updated.status == GoalStatus.PAUSED

    # Active goal should now be None
    active = await goal_manager.get_active_goal(session_id)
    assert active is None

    # Update back to active
    updated = await goal_manager.update_status(goal.goal_id, GoalStatus.ACTIVE)
    assert updated.status == GoalStatus.ACTIVE

    # Active goal should be back
    active = await goal_manager.get_active_goal(session_id)
    assert active is not None
    assert active.goal_id == goal.goal_id


@pytest.mark.asyncio
async def test_account_usage_updates_stats(goal_manager):
    session_id = "session-4"
    goal = await goal_manager.create_goal(session_id, "Test usage")

    outcome = await goal_manager.account_usage(
        goal_id=goal.goal_id, token_delta=50, cost_delta=0.01, time_delta_seconds=5, turn_delta=1,
    )

    assert outcome.goal.tokens_used == 50
    assert outcome.goal.cost_usd == 0.01
    assert outcome.goal.time_used_seconds == 5
    assert outcome.goal.turns_used == 1
    assert not outcome.status_changed
    assert not outcome.budget_exhausted


@pytest.mark.asyncio
async def test_account_usage_exhausts_budget(goal_manager):
    session_id = "session-5"
    goal = await goal_manager.create_goal(
        session_id, "Test budget", budget=GoalBudget(max_tokens=100)
    )

    outcome1 = await goal_manager.account_usage(goal.goal_id, 60, 0, 0)
    assert outcome1.goal.tokens_used == 60
    assert outcome1.goal.status == GoalStatus.ACTIVE

    outcome2 = await goal_manager.account_usage(goal.goal_id, 50, 0, 0)
    assert outcome2.goal.tokens_used == 110
    assert outcome2.goal.status == GoalStatus.BUDGET_LIMITED
    assert outcome2.status_changed
    assert outcome2.budget_exhausted

    active = await goal_manager.get_active_goal(session_id)
    assert active is None


@pytest.mark.asyncio
async def test_account_usage_exhausts_turns_budget(goal_manager):
    session_id = "session-turns"
    goal = await goal_manager.create_goal(
        session_id, "Test turn budget", budget=GoalBudget(max_turns=3)
    )

    outcome1 = await goal_manager.account_usage(goal.goal_id, 0, 0, 0, turn_delta=1)
    assert outcome1.goal.turns_used == 1
    assert not outcome1.budget_exhausted

    outcome2 = await goal_manager.account_usage(goal.goal_id, 0, 0, 0, turn_delta=1)
    assert outcome2.goal.turns_used == 2
    assert not outcome2.budget_exhausted

    outcome3 = await goal_manager.account_usage(goal.goal_id, 0, 0, 0, turn_delta=1)
    assert outcome3.goal.turns_used == 3
    assert outcome3.budget_exhausted
    assert outcome3.goal.status == GoalStatus.BUDGET_LIMITED


@pytest.mark.asyncio
async def test_update_budget(goal_manager):
    session_id = "session-budget-test"
    goal = await goal_manager.create_goal(
        session_id, "Test budget update", budget=GoalBudget(max_tokens=100)
    )

    # Update budget
    updated = await goal_manager.update_budget(goal.goal_id, 50)
    assert updated.budget.max_tokens == 150

    # Create goal without budget
    goal_no_budget = await goal_manager.create_goal(
        "session-no-budget", "Test no budget update"
    )

    # Update budget for goal without budget
    updated_no_budget = await goal_manager.update_budget(goal_no_budget.goal_id, 200)
    assert updated_no_budget.budget is not None
    assert updated_no_budget.budget.max_tokens == 200


@pytest.mark.asyncio
async def test_suppression_logic():
    from unittest.mock import MagicMock

    from myrm_agent_harness.agent.goals.manager import GoalManager

    manager = GoalManager(MagicMock())
    session_id = "session-6"

    assert not await manager.is_continuation_suppressed(session_id)

    await manager.suppress_continuation(session_id)
    assert await manager.is_continuation_suppressed(session_id)

    await manager.reset_suppression(session_id)
    assert not await manager.is_continuation_suppressed(session_id)


@pytest.mark.asyncio
async def test_manager_to_dict(goal_manager):
    await goal_manager.suppress_continuation("s1")
    d = goal_manager.to_dict()
    assert d["type"] == "GoalManager"
    assert "s1" in d["suppressed_sessions"]


@pytest.mark.asyncio
async def test_get_latest_goal(goal_manager):
    session_id = "session-latest"
    assert await goal_manager.get_latest_goal(session_id) is None
    goal = await goal_manager.create_goal(session_id, "First")
    latest = await goal_manager.get_latest_goal(session_id)
    assert latest is not None
    assert latest.goal_id == goal.goal_id


@pytest.mark.asyncio
async def test_update_budget_not_found(goal_manager):
    with pytest.raises(ValueError, match="not found"):
        await goal_manager.update_budget("nonexistent", 100)


@pytest.mark.asyncio
async def test_set_budget(goal_manager):
    session_id = "session-set-budget"
    goal = await goal_manager.create_goal(session_id, "Test set budget")
    with pytest.raises(ValueError, match="not found"):
        await goal_manager.set_budget("nonexistent", GoalBudget())

    new_budget = GoalBudget(max_usd=10.0)
    updated = await goal_manager.set_budget(goal.goal_id, new_budget)
    assert updated.budget.max_usd == 10.0


@pytest.mark.asyncio
async def test_update_status_errors(goal_manager):
    session_id = "session-status-errors"
    with pytest.raises(ValueError, match="not found"):
        await goal_manager.update_status("nonexistent", GoalStatus.PAUSED)

    goal = await goal_manager.create_goal(session_id, "Test terminal")
    await goal_manager.update_status(goal.goal_id, GoalStatus.COMPLETE)

    with pytest.raises(ValueError, match="terminal"):
        await goal_manager.update_status(goal.goal_id, GoalStatus.PAUSED)


@pytest.mark.asyncio
async def test_verification_retries(goal_manager):
    session_id = "session-retries"
    goal = await goal_manager.create_goal(session_id, "Test retries")

    with pytest.raises(ValueError, match="not found"):
        await goal_manager.increment_verification_retries("nonexistent")
    with pytest.raises(ValueError, match="not found"):
        await goal_manager.reset_verification_retries("nonexistent")

    updated = await goal_manager.increment_verification_retries(goal.goal_id)
    assert updated.verification_retries == 1

    reset = await goal_manager.reset_verification_retries(goal.goal_id)
    assert reset.verification_retries == 0


@pytest.mark.asyncio
async def test_resume_goal(goal_manager):
    session_id = "session-resume"
    goal = await goal_manager.create_goal(
        session_id, "Test resume", budget=GoalBudget(max_turns=10)
    )

    await goal_manager.account_usage(goal.goal_id, 100, 0, 0, turn_delta=5)
    await goal_manager.update_status(goal.goal_id, GoalStatus.PAUSED)

    resumed = await goal_manager.resume_goal(goal.goal_id, reset_turns=True)
    assert resumed.status == GoalStatus.ACTIVE
    assert resumed.turns_used == 0

    await goal_manager.account_usage(goal.goal_id, 0, 0, 0, turn_delta=3)
    await goal_manager.update_status(goal.goal_id, GoalStatus.PAUSED)

    resumed2 = await goal_manager.resume_goal(goal.goal_id, reset_turns=False)
    assert resumed2.status == GoalStatus.ACTIVE
    assert resumed2.turns_used == 3


@pytest.mark.asyncio
async def test_resume_goal_resets_convergence_counters(goal_manager):
    """resume_goal must reset no_progress_streak and loop_restarts to prevent
    immediate re-convergence after manual resume."""
    session_id = "session-resume-conv"
    goal = await goal_manager.create_goal(
        session_id,
        "Test convergence reset on resume",
        budget=GoalBudget(max_turns=20, convergence_window=3, loop_on_pause=True, max_loop_restarts=5),
    )

    # Simulate convergence state
    await goal_manager.record_progress(goal.goal_id, made_progress=False)
    await goal_manager.record_progress(goal.goal_id, made_progress=False)
    await goal_manager.record_progress(goal.goal_id, made_progress=False)
    await goal_manager.record_loop_restart(goal.goal_id)
    await goal_manager.record_loop_restart(goal.goal_id)

    pre = await goal_manager.get_goal(goal.goal_id)
    assert pre.no_progress_streak == 3
    assert pre.loop_restarts == 2

    await goal_manager.update_status(goal.goal_id, GoalStatus.PAUSED)
    resumed = await goal_manager.resume_goal(goal.goal_id)

    assert resumed.status == GoalStatus.ACTIVE
    assert resumed.no_progress_streak == 0
    assert resumed.loop_restarts == 0


@pytest.mark.asyncio
async def test_resume_goal_errors(goal_manager):
    with pytest.raises(ValueError, match="not found"):
        await goal_manager.resume_goal("nonexistent")

    session_id = "session-resume-err"
    goal = await goal_manager.create_goal(session_id, "Test resume error")
    await goal_manager.update_status(goal.goal_id, GoalStatus.COMPLETE)

    with pytest.raises(ValueError, match="terminal"):
        await goal_manager.resume_goal(goal.goal_id)


@pytest.mark.asyncio
async def test_evaluate_semantic(goal_manager):
    with pytest.raises(NotImplementedError):
        await goal_manager.evaluate_semantic("crit", "content")


@pytest.mark.asyncio
async def test_account_usage_errors_and_inactive(goal_manager):
    with pytest.raises(ValueError, match="not found"):
        await goal_manager.account_usage("nonexistent", 10, 0.1, 1)

    session_id = "session-usage"
    goal = await goal_manager.create_goal(session_id, "Test usage")
    await goal_manager.update_status(goal.goal_id, GoalStatus.PAUSED)

    outcome = await goal_manager.account_usage(goal.goal_id, 10, 0.1, 1)
    assert outcome.goal.tokens_used == 0
    assert not outcome.status_changed


@pytest.mark.asyncio
async def test_subgoal_management(goal_manager):
    session_id = "session-subgoals"
    goal = await goal_manager.create_goal(session_id, "Test subgoals")

    # Add subgoals
    sg1 = await goal_manager.add_subgoal(goal.goal_id, "Subgoal 1")
    assert sg1["text"] == "Subgoal 1"

    sg2 = await goal_manager.add_subgoal(goal.goal_id, "Subgoal 2")
    assert sg2["text"] == "Subgoal 2"

    # Verify they were added
    updated_goal = await goal_manager.get_active_goal(session_id)
    assert len(updated_goal.subgoals) == 2
    assert updated_goal.subgoals[0]["text"] == "Subgoal 1"
    assert updated_goal.subgoals[1]["text"] == "Subgoal 2"

    # Remove subgoal
    removed = await goal_manager.remove_subgoal(goal.goal_id, 0)
    assert removed["text"] == "Subgoal 1"

    # Verify removal
    updated_goal = await goal_manager.get_active_goal(session_id)
    assert len(updated_goal.subgoals) == 1
    assert updated_goal.subgoals[0]["text"] == "Subgoal 2"

    # Invalid removal
    with pytest.raises(IndexError):
        await goal_manager.remove_subgoal(goal.goal_id, 5)

    # Clear subgoals
    count = await goal_manager.clear_subgoals(goal.goal_id)
    assert count == 1

    # Verify clear
    updated_goal = await goal_manager.get_active_goal(session_id)
    assert len(updated_goal.subgoals) == 0


@pytest.mark.asyncio
async def test_create_goal_with_constraints(goal_manager):
    goal = await goal_manager.create_goal(
        session_id="session-c1",
        objective="Deploy to production",
        constraints=["Do not modify config files", "Only use Python 3.13"],
    )

    assert goal.constraints == ["Do not modify config files", "Only use Python 3.13"]

    retrieved = await goal_manager.get_goal(goal.goal_id)
    assert retrieved.constraints == ["Do not modify config files", "Only use Python 3.13"]


@pytest.mark.asyncio
async def test_create_goal_without_constraints(goal_manager):
    goal = await goal_manager.create_goal(
        session_id="session-c2",
        objective="Simple task",
    )

    assert goal.constraints == []


@pytest.mark.asyncio
async def test_update_constraints(goal_manager):
    goal = await goal_manager.create_goal(
        session_id="session-c3",
        objective="Build API",
        constraints=["No database changes"],
    )

    updated = await goal_manager.update_constraints(
        goal.goal_id,
        ["No database changes", "Must use REST conventions"],
    )

    assert updated.constraints == ["No database changes", "Must use REST conventions"]

    retrieved = await goal_manager.get_goal(goal.goal_id)
    assert retrieved.constraints == ["No database changes", "Must use REST conventions"]


@pytest.mark.asyncio
async def test_update_constraints_to_empty(goal_manager):
    goal = await goal_manager.create_goal(
        session_id="session-c4",
        objective="Task with constraints",
        constraints=["Something"],
    )

    updated = await goal_manager.update_constraints(goal.goal_id, [])
    assert updated.constraints == []


@pytest.mark.asyncio
async def test_update_constraints_nonexistent_goal(goal_manager):
    with pytest.raises(ValueError, match="not found"):
        await goal_manager.update_constraints("nonexistent-id", ["test"])


@pytest.mark.asyncio
async def test_dequeue_next_returns_goal(goal_manager):
    """Queued goals are returned by dequeue_next in order."""
    sid = "session-dq1"
    g1 = await goal_manager.create_goal(session_id=sid, objective="First")
    g2 = await goal_manager.create_goal(session_id=sid, objective="Second")
    assert g2.status == GoalStatus.QUEUED

    await goal_manager.update_status(g1.goal_id, GoalStatus.COMPLETE)
    dequeued = await goal_manager.dequeue_next(sid)
    assert dequeued is not None
    assert dequeued.goal_id == g2.goal_id
    assert dequeued.status == GoalStatus.ACTIVE
    assert dequeued.auto_approve is True


@pytest.mark.asyncio
async def test_dequeue_next_returns_none_when_empty(goal_manager):
    result = await goal_manager.dequeue_next("empty-session")
    assert result is None


@pytest.mark.asyncio
async def test_get_queued_goals(goal_manager):
    sid = "session-gq1"
    await goal_manager.create_goal(session_id=sid, objective="Active")
    g2 = await goal_manager.create_goal(session_id=sid, objective="Queued1")
    g3 = await goal_manager.create_goal(session_id=sid, objective="Queued2")

    queued = await goal_manager.get_queued_goals(sid)
    assert len(queued) == 2
    assert queued[0].goal_id == g2.goal_id
    assert queued[1].goal_id == g3.goal_id


@pytest.mark.asyncio
async def test_cancel_queued_goal(goal_manager):
    sid = "session-cq1"
    await goal_manager.create_goal(session_id=sid, objective="Active")
    g2 = await goal_manager.create_goal(session_id=sid, objective="ToCancel")
    assert g2.status == GoalStatus.QUEUED

    cancelled = await goal_manager.cancel_queued_goal(sid, g2.goal_id)
    assert cancelled.status == GoalStatus.CANCELLED

    queued = await goal_manager.get_queued_goals(sid)
    assert len(queued) == 0


@pytest.mark.asyncio
async def test_cancel_queued_goal_not_queued(goal_manager):
    sid = "session-cq2"
    g1 = await goal_manager.create_goal(session_id=sid, objective="Active")
    with pytest.raises(ValueError, match="not in QUEUED status"):
        await goal_manager.cancel_queued_goal(sid, g1.goal_id)


@pytest.mark.asyncio
async def test_reorder_queue(goal_manager):
    sid = "session-rq1"
    await goal_manager.create_goal(session_id=sid, objective="Active")
    g2 = await goal_manager.create_goal(session_id=sid, objective="Q1")
    g3 = await goal_manager.create_goal(session_id=sid, objective="Q2")

    await goal_manager.reorder_queue(sid, [g3.goal_id, g2.goal_id])


@pytest.mark.asyncio
async def test_update_status_same_status_noop(goal_manager):
    """Updating to the same status returns the goal without changes."""
    g = await goal_manager.create_goal(session_id="session-ss", objective="Test")
    result = await goal_manager.update_status(g.goal_id, GoalStatus.ACTIVE)
    assert result.goal_id == g.goal_id


# ---------------------------------------------------------------------------
# update_objective tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_objective(goal_manager):
    goal = await goal_manager.create_goal(session_id="session-uo1", objective="Original task")
    updated = await goal_manager.update_objective(goal.goal_id, "Revised task with new direction")

    assert updated.objective == "Revised task with new direction"
    assert updated.updated_at > goal.updated_at

    retrieved = await goal_manager.get_goal(goal.goal_id)
    assert retrieved.objective == "Revised task with new direction"


@pytest.mark.asyncio
async def test_update_objective_nonexistent_goal(goal_manager):
    with pytest.raises(ValueError, match="not found"):
        await goal_manager.update_objective("nonexistent-id", "New objective")


@pytest.mark.asyncio
async def test_update_objective_terminal_goal_rejected(goal_manager):
    goal = await goal_manager.create_goal(session_id="session-uo2", objective="Will complete")
    await goal_manager.update_status(goal.goal_id, GoalStatus.COMPLETE)

    with pytest.raises(ValueError, match="terminal"):
        await goal_manager.update_objective(goal.goal_id, "Should fail")


@pytest.mark.asyncio
async def test_update_objective_paused_goal_ok(goal_manager):
    """Paused goals can have their objective updated."""
    goal = await goal_manager.create_goal(session_id="session-uo3", objective="Will pause")
    await goal_manager.update_status(goal.goal_id, GoalStatus.PAUSED)

    updated = await goal_manager.update_objective(goal.goal_id, "New direction after pause")
    assert updated.objective == "New direction after pause"


@pytest.mark.asyncio
async def test_update_objective_cancelled_goal_rejected(goal_manager):
    """Cancelled (terminal) goals cannot have their objective updated."""
    goal = await goal_manager.create_goal(session_id="session-uo4", objective="Will cancel")
    await goal_manager.update_status(goal.goal_id, GoalStatus.CANCELLED)

    with pytest.raises(ValueError, match="terminal"):
        await goal_manager.update_objective(goal.goal_id, "Should fail")


@pytest.mark.asyncio
async def test_update_objective_budget_limited_ok(goal_manager):
    """Budget-limited (non-terminal) goals can have their objective updated."""
    goal = await goal_manager.create_goal(
        session_id="session-uo5",
        objective="Will hit budget",
        budget=GoalBudget(max_tokens=1000),
    )
    await goal_manager.update_status(goal.goal_id, GoalStatus.BUDGET_LIMITED)

    updated = await goal_manager.update_objective(goal.goal_id, "New direction after budget limit")
    assert updated.objective == "New direction after budget limit"
