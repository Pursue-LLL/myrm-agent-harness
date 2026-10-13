"""Live-path wiring tests for TwoLayerContextMiddleware (Layer 1 only)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.middlewares.memory_context.two_layer_context_middleware import (
    _injector,
    two_layer_context_middleware,
)
from myrm_agent_harness.core.context_vars import chat_id_var


@pytest.fixture(autouse=True)
def _reset_injector_session() -> None:
    _injector.reset_session("chat-two-layer-1")
    yield
    _injector.reset_session("chat-two-layer-1")


@pytest.mark.asyncio
async def test_middleware_appends_base_context_without_mutating_system(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYRM_TWO_LAYER_CONTEXT_LIVE", raising=False)
    session_id = "chat-two-layer-1"
    token = chat_id_var.set(session_id)
    try:
        frozen = "frozen system prefix"
        request = ModelRequest(
            messages=[
                SystemMessage(content=frozen),
                HumanMessage(content="Continue the rollout checklist."),
            ],
            model=MagicMock(),
        )
        captured: list[ModelRequest] = []

        async def handler(req: ModelRequest) -> ModelResponse:
            captured.append(req)
            return ModelResponse(result=[])

        await two_layer_context_middleware.awrap_model_call(request, handler)
    finally:
        chat_id_var.reset(token)

    assert len(captured) == 1
    assert captured[0].messages[0].content == frozen
    last_human = captured[0].messages[-1]
    assert isinstance(last_human, HumanMessage)
    tail = str(last_human.content)
    assert "<base_context" in tail
    assert "Continue the rollout checklist." in tail


@pytest.mark.asyncio
async def test_middleware_noop_without_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYRM_TWO_LAYER_CONTEXT_LIVE", raising=False)
    request = ModelRequest(
        messages=[HumanMessage(content="hello")],
        model=MagicMock(),
    )
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await two_layer_context_middleware.awrap_model_call(request, handler)
    handler.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_middleware_respects_disable_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYRM_TWO_LAYER_CONTEXT_LIVE", "0")
    session_id = "chat-two-layer-1"
    token = chat_id_var.set(session_id)
    try:
        request = ModelRequest(
            messages=[HumanMessage(content="hello")],
            model=MagicMock(),
        )
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        await two_layer_context_middleware.awrap_model_call(request, handler)
        handler.assert_awaited_once_with(request)
    finally:
        chat_id_var.reset(token)
