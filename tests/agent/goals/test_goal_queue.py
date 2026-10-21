from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.goals.manager import GoalManager
from myrm_agent_harness.agent.goals.types import GoalBudget, GoalStatus


@pytest.fixture
def mock_storage_provider():
    store: dict[str, str] = {}
    provider = AsyncMock()

    async def write(key: str, content: str) -> None:
        store[key] = content

    async def read(key: str) -> str | None:
        return store.get(key)

    async def delete(key: str) -> None:
        store.pop(key, None)

    provider.write.side_effect = write
    provider.read.side_effect = read
    provider.delete.side_effect = delete
    return provider


@pytest.mark.asyncio
async def test_create_goal_queues_when_active_exists(mock_storage_provider) -> None:
    manager = GoalManager(mock_storage_provider)
    session_id = "test-session-queue"

    goal1 = await manager.create_goal(
        session_id=session_id,
        objective="First goal",
        budget=GoalBudget(max_tokens=5000),
    )
    assert goal1.status == GoalStatus.ACTIVE

    goal2 = await manager.create_goal(
        session_id=session_id,
        objective="Second goal (should be queued)",
    )
    assert goal2.status == GoalStatus.QUEUED
    assert goal2.auto_approve is True

    goal3 = await manager.create_goal(
        session_id=session_id,
        objective="Third goal (also queued)",
    )
    assert goal3.status == GoalStatus.QUEUED


@pytest.mark.asyncio
async def test_get_queued_goals(mock_storage_provider) -> None:
    manager = GoalManager(mock_storage_provider)
    session_id = "test-session-queue-list"

    await manager.create_goal(session_id=session_id, objective="Active")
    await manager.create_goal(session_id=session_id, objective="Queued 1")
    await manager.create_goal(session_id=session_id, objective="Queued 2")

    queued = await manager.get_queued_goals(session_id)
    assert len(queued) == 2
    assert queued[0].objective == "Queued 1"
    assert queued[1].objective == "Queued 2"


@pytest.mark.asyncio
async def test_dequeue_next(mock_storage_provider) -> None:
    manager = GoalManager(mock_storage_provider)
    session_id = "test-session-dequeue"

    goal1 = await manager.create_goal(session_id=session_id, objective="Active")
    await manager.create_goal(session_id=session_id, objective="Queued A")
    await manager.create_goal(session_id=session_id, objective="Queued B")

    # Terminate the active goal
    await manager.update_status(goal1.goal_id, GoalStatus.COMPLETE)

    # Dequeue next
    next_goal = await manager.dequeue_next(session_id)
    assert next_goal is not None
    assert next_goal.objective == "Queued A"
    assert next_goal.status == GoalStatus.ACTIVE
    assert next_goal.auto_approve is True

    # Queue should now have only one
    remaining = await manager.get_queued_goals(session_id)
    assert len(remaining) == 1
    assert remaining[0].objective == "Queued B"


@pytest.mark.asyncio
async def test_dequeue_returns_none_when_empty(mock_storage_provider) -> None:
    manager = GoalManager(mock_storage_provider)
    session_id = "test-session-dequeue-empty"

    goal1 = await manager.create_goal(session_id=session_id, objective="Only goal")
    await manager.update_status(goal1.goal_id, GoalStatus.COMPLETE)

    next_goal = await manager.dequeue_next(session_id)
    assert next_goal is None


@pytest.mark.asyncio
async def test_queue_priority_ordering(mock_storage_provider) -> None:
    manager = GoalManager(mock_storage_provider)
    session_id = "test-session-priority"

    await manager.create_goal(session_id=session_id, objective="Active")
    g2 = await manager.create_goal(session_id=session_id, objective="Low priority")
    g3 = await manager.create_goal(session_id=session_id, objective="High priority")

    # Reorder: put g3 (high priority) first
    await manager.reorder_queue(session_id, [g3.goal_id, g2.goal_id])

    queued = await manager.get_queued_goals(session_id)
    assert queued[0].objective == "High priority"
    assert queued[1].objective == "Low priority"
