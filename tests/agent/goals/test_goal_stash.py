from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.goals.manager import GoalManager
from myrm_agent_harness.agent.goals.types import GoalBudget, GoalStatus


@pytest.fixture
def mock_storage_provider():
    # Simulate a robust in-memory k-v store using dict
    store = {}
    provider = AsyncMock()

    async def write(key, content):
        store[key] = content

    async def read(key):
        return store.get(key)

    async def delete(key):
        store.pop(key, None)

    provider.write.side_effect = write
    provider.read.side_effect = read
    provider.delete.side_effect = delete
    return provider


@pytest.mark.asyncio
async def test_goal_stash_restore_flow(mock_storage_provider) -> None:
    # 1. Initialize GoalManager
    manager = GoalManager(mock_storage_provider)

    session_id = "test-session-stash"
    branch_name = "feature/agent-mascot"

    # Create an active goal
    goal = await manager.create_goal(
        session_id=session_id,
        objective="Implement Mascot Customization Panel",
        budget=GoalBudget(max_tokens=5000),
    )

    # 2. Stash the goal
    planner_state = {"steps": ["Step 1", "Step 2"], "current_idx": 0}
    chat_history = [{"role": "user", "content": "Help me build it"}]

    stashed = await manager.stash_goal(
        session_id=session_id,
        branch_name=branch_name,
        progress_state=planner_state,
        chat_history=chat_history,
    )
    assert stashed is True

    # After stash, goal should be PAUSED
    goal_after_stash = await manager.get_goal(goal.goal_id)
    assert goal_after_stash.status == GoalStatus.PAUSED

    # Active goal should be None now (because it's PAUSED)
    active_goal = await manager.get_active_goal(session_id)
    assert active_goal is None

    # 3. Restore the goal
    restored = await manager.restore_goal(session_id, branch_name)
    assert restored is not None
    assert restored["goal"].goal_id == goal.goal_id
    assert restored["goal"].status == GoalStatus.ACTIVE
    assert restored["progress_state"] == planner_state
    assert restored["chat_history"] == chat_history

    # Stash should be deleted after restore
    empty_restore = await manager.restore_goal(session_id, branch_name)
    assert empty_restore is None
