"""Tests for sync hook parity adapter (R142 signoff clarify warm)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from myrm_agent_harness.agent.middlewares.sync_hook_parity import (
    SyncHookParityAdapter,
    apply_sync_hook_parity,
)


class _AsyncOnlyMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    name = "async_only"

    async def awrap_model_call(
        self,
        request: ModelRequest[object],
        handler: Callable[[ModelRequest[object]], Awaitable[ModelResponse[object]]],
    ) -> ModelResponse[object]:
        return await handler(request)


def test_sync_hook_parity_wrap_tool_call_passthrough() -> None:
    inner = _AsyncOnlyMiddleware()
    adapter = SyncHookParityAdapter(inner)
    seen: list[str] = []
    request = MagicMock()

    def handler(_request: Any) -> str:
        seen.append("ok")
        return "tool-result"

    result = adapter.wrap_tool_call(request, handler)  # type: ignore[arg-type]
    assert result == "tool-result"
    assert seen == ["ok"]


def test_apply_sync_hook_parity_wraps_async_only_middleware() -> None:
    inner = _AsyncOnlyMiddleware()
    adapted = apply_sync_hook_parity([inner])
    assert len(adapted) == 1
    assert isinstance(adapted[0], SyncHookParityAdapter)


@pytest.mark.asyncio
async def test_sync_hook_parity_delegates_async_model_hook() -> None:
    inner = _AsyncOnlyMiddleware()
    adapter = SyncHookParityAdapter(inner)
    called = False
    request = ModelRequest(model=MagicMock(), messages=[])

    async def handler(_request: ModelRequest[object]) -> ModelResponse[object]:
        nonlocal called
        called = True
        return ModelResponse(result=[])

    await adapter.awrap_model_call(request, handler)
    assert called is True
