import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from myrm_agent_harness.agent.goals.storage import GoalStorage
from myrm_agent_harness.agent.goals.types import Goal, GoalBudget, GoalStatus
from myrm_agent_harness.toolkits.storage.local import LocalStorageBackend


@pytest.fixture
async def storage_provider(tmp_path: Path) -> AsyncIterator[LocalStorageBackend]:
    backend = LocalStorageBackend(base_path=str(tmp_path))
    yield backend

@pytest.fixture
def goal_storage(storage_provider: LocalStorageBackend) -> GoalStorage:
    return GoalStorage(storage_provider)

@pytest.mark.asyncio
async def test_save_and_get_goal(goal_storage: GoalStorage) -> None:
    goal_id = str(uuid.uuid4())
    session_id = "test-session"
    goal = Goal(
        goal_id=goal_id,
        session_id=session_id,
        objective="Test objective",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_tokens=1000),
    )

    await goal_storage.save_goal(goal)

    retrieved = await goal_storage.get_goal(goal_id)
    assert retrieved is not None
    assert retrieved.goal_id == goal_id
    assert retrieved.session_id == session_id
    assert retrieved.objective == "Test objective"
    assert retrieved.status == GoalStatus.ACTIVE
    assert retrieved.budget is not None
    assert retrieved.budget.max_tokens == 1000

@pytest.mark.asyncio
async def test_get_nonexistent_goal(goal_storage: GoalStorage) -> None:
    retrieved = await goal_storage.get_goal("nonexistent")
    assert retrieved is None

@pytest.mark.asyncio
async def test_active_goal_index(goal_storage: GoalStorage) -> None:
    session_id = "session-with-active"
    goal_id = "active-goal-id"

    active_id = await goal_storage.get_active_goal_id(session_id)
    assert active_id is None

    goal = Goal(
        goal_id=goal_id,
        session_id=session_id,
        objective="Active objective",
        status=GoalStatus.ACTIVE,
    )
    await goal_storage.save_goal(goal)

    active_id = await goal_storage.get_active_goal_id(session_id)
    assert active_id == goal_id

    goal.status = GoalStatus.COMPLETE
    await goal_storage.save_goal(goal)

    active_id = await goal_storage.get_active_goal_id(session_id)
    assert active_id is None

@pytest.mark.asyncio
async def test_update_goal_fields(goal_storage: GoalStorage) -> None:
    goal_id = "update-goal"
    goal = Goal(
        goal_id=goal_id,
        session_id="s1",
        objective="obj",
        status=GoalStatus.ACTIVE,
        tokens_used=10,
    )
    await goal_storage.save_goal(goal)

    goal.tokens_used = 50
    goal.status = GoalStatus.PAUSED
    await goal_storage.save_goal(goal)

    retrieved = await goal_storage.get_goal(goal_id)
    assert retrieved is not None
    assert retrieved.tokens_used == 50
    assert retrieved.status == GoalStatus.PAUSED


@pytest.mark.asyncio
async def test_turns_used_roundtrip(goal_storage: GoalStorage) -> None:
    goal = Goal(
        goal_id="turns-goal",
        session_id="s-turns",
        objective="test turns",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_tokens=1000, max_turns=25),
        turns_used=7,
    )
    await goal_storage.save_goal(goal)

    retrieved = await goal_storage.get_goal("turns-goal")
    assert retrieved is not None
    assert retrieved.turns_used == 7
    assert retrieved.budget is not None
    assert retrieved.budget.max_turns == 25


@pytest.mark.asyncio
async def test_backward_compatible_deserialization(goal_storage: GoalStorage) -> None:
    """Missing turns fields should deserialize with defaults."""
    goal = Goal(
        goal_id="old-goal",
        session_id="s-old",
        objective="old",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_tokens=100),
    )
    await goal_storage.save_goal(goal)

    retrieved = await goal_storage.get_goal("old-goal")
    assert retrieved is not None
    assert retrieved.turns_used == 0
    assert retrieved.budget is not None
    assert retrieved.budget.max_turns is None


@pytest.mark.asyncio
async def test_ui_summary_roundtrip(goal_storage: GoalStorage) -> None:
    """ui_summary should survive serialization/deserialization."""
    goal = Goal(
        goal_id="ui-summary-goal",
        session_id="s-ui",
        objective="A very long objective that would be truncated in UI",
        status=GoalStatus.ACTIVE,
        ui_summary="Short summary for UI",
    )
    await goal_storage.save_goal(goal)

    retrieved = await goal_storage.get_goal("ui-summary-goal")
    assert retrieved is not None
    assert retrieved.ui_summary == "Short summary for UI"


@pytest.mark.asyncio
async def test_ui_summary_empty_default(goal_storage: GoalStorage) -> None:
    """Goals without ui_summary should deserialize with empty string."""
    goal = Goal(
        goal_id="no-ui-summary",
        session_id="s-no-ui",
        objective="test",
        status=GoalStatus.ACTIVE,
    )
    await goal_storage.save_goal(goal)

    retrieved = await goal_storage.get_goal("no-ui-summary")
    assert retrieved is not None
    assert retrieved.ui_summary == ""


@pytest.mark.asyncio
async def test_constraints_roundtrip(goal_storage: GoalStorage) -> None:
    constraints = ["Do not modify production config", "Must not exceed 100 API calls"]
    goal = Goal(
        goal_id="constraints-goal",
        session_id="s-constraints",
        objective="Deploy safely",
        status=GoalStatus.ACTIVE,
        constraints=constraints,
    )
    await goal_storage.save_goal(goal)

    retrieved = await goal_storage.get_goal("constraints-goal")
    assert retrieved is not None
    assert retrieved.constraints == constraints


@pytest.mark.asyncio
async def test_constraints_empty_default(goal_storage: GoalStorage) -> None:
    goal = Goal(
        goal_id="no-constraints",
        session_id="s-no-constraints",
        objective="Simple task",
        status=GoalStatus.ACTIVE,
    )
    await goal_storage.save_goal(goal)

    retrieved = await goal_storage.get_goal("no-constraints")
    assert retrieved is not None
    assert retrieved.constraints == []
