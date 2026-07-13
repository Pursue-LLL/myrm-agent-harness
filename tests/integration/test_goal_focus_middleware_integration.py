"""Integration: GoalManager → ContextVar → goal_focus_middleware injection chain.

Uses a real GoalManager (in-memory storage backend) and the production
goal_focus_middleware wrapper. Only the downstream LLM handler is stubbed
to capture the overridden ModelRequest.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.goals.manager import GoalManager
from myrm_agent_harness.agent.goals.types import GoalBudget, GoalStatus
from myrm_agent_harness.agent.middlewares._session_context import (
    set_goal_provider,
)
from myrm_agent_harness.agent.middlewares.goal_focus_middleware import (
    goal_focus_middleware,
)


@pytest.fixture
def memory_storage_provider():
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
async def test_goal_focus_full_chain_with_real_goal_manager(
    memory_storage_provider,
) -> None:
    session_id = "integration-goal-focus"
    manager = GoalManager(memory_storage_provider)
    await manager.create_goal(
        session_id=session_id,
        objective="Ship weekly analytics report",
        budget=GoalBudget(max_tokens=10_000, max_turns=20),
    )

    set_goal_provider(manager)
    middleware = goal_focus_middleware()

    captured: dict[str, object] = {}

    async def handler(request: ModelRequest):
        captured["messages"] = list(request.messages)
        return AsyncMock()

    runtime = AsyncMock()
    runtime.context = {"chat_id": session_id}
    request = ModelRequest(
        model=AsyncMock(),
        messages=[
            SystemMessage(content="frozen system prefix"),
            HumanMessage(content="also add Slack notifications", id="user-1"),
        ],
        runtime=runtime,
    )

    await middleware.awrap_model_call(request, handler)

    messages = captured["messages"]
    assert isinstance(messages, list)
    human = messages[1]
    assert isinstance(human, HumanMessage)
    assert "also add Slack notifications" in str(human.content)
    assert "Active goal: Ship weekly analytics report" in str(human.content)
    assert "tokens 0/10000" in str(human.content)
    assert human.id == "user-1"

    active = await manager.get_active_goal(session_id)
    assert active is not None
    assert active.status == GoalStatus.ACTIVE


@pytest.mark.asyncio
async def test_goal_focus_skips_continuation_prompt_in_full_chain(
    memory_storage_provider,
) -> None:
    session_id = "integration-goal-continue-skip"
    manager = GoalManager(memory_storage_provider)
    await manager.create_goal(session_id=session_id, objective="Long running task")

    set_goal_provider(manager)
    middleware = goal_focus_middleware()
    passed_through = False

    async def handler(request: ModelRequest):
        nonlocal passed_through
        passed_through = True
        return AsyncMock()

    runtime = AsyncMock()
    runtime.context = {"session_id": session_id}
    request = ModelRequest(
        model=AsyncMock(),
        messages=[
            HumanMessage(
                content="[Continuing toward your standing goal]\n\n<objective>Long running task</objective>"
            ),
        ],
        runtime=runtime,
    )

    await middleware.awrap_model_call(request, handler)

    assert passed_through is True
