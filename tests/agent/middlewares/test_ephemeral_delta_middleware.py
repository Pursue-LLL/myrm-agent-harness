"""Live-path wiring tests for EphemeralDeltaMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.middlewares.memory_context.ephemeral_delta_middleware import (
    ephemeral_delta_middleware,
)
from myrm_agent_harness.core.context_vars import chat_id_var
from myrm_agent_harness.toolkits.memory.ephemeral_delta import (
    get_shared_ephemeral_delta_store,
    record_ephemeral_memory_delta,
)


@pytest.fixture(autouse=True)
def _reset_shared_store() -> None:
    store = get_shared_ephemeral_delta_store()
    store.clear("chat-ephemeral-mw-1")
    store.clear("default")
    yield
    store.clear("chat-ephemeral-mw-1")


@pytest.mark.asyncio
async def test_middleware_injects_delta_on_last_human_when_chat_id_set() -> None:
    session_id = "chat-ephemeral-mw-1"
    token = chat_id_var.set(session_id)
    try:
        record_ephemeral_memory_delta(key="nickname", value="Old Zhang")
        request = ModelRequest(
            messages=[
                SystemMessage(content="frozen prefix"),
                HumanMessage(content="Call me something else."),
            ],
            model=MagicMock(),
        )
        captured: list[ModelRequest] = []

        async def handler(req: ModelRequest) -> ModelResponse:
            captured.append(req)
            return ModelResponse(result=[])

        await ephemeral_delta_middleware.awrap_model_call(request, handler)
    finally:
        chat_id_var.reset(token)

    assert len(captured) == 1
    last_human = captured[0].messages[-1]
    assert isinstance(last_human, HumanMessage)
    assert "<ephemeral_session_deltas>" in str(last_human.content)
    assert "Old Zhang" in str(last_human.content)


@pytest.mark.asyncio
async def test_middleware_noop_without_chat_id() -> None:
    request = ModelRequest(
        messages=[HumanMessage(content="hello")],
        model=MagicMock(),
    )
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await ephemeral_delta_middleware.awrap_model_call(request, handler)
    handler.assert_awaited_once_with(request)
