"""Tests for sync hook parity adapter (R142 signoff clarify warm)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage

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


def test_sync_hook_parity_name_property_returns_inner_name() -> None:
    adapter = SyncHookParityAdapter(_AsyncOnlyMiddleware())
    assert adapter.name == "async_only"


def test_sync_hook_parity_wrap_model_call_passthrough() -> None:
    inner = _AsyncOnlyMiddleware()
    adapter = SyncHookParityAdapter(inner)
    request = ModelRequest(model=MagicMock(), messages=[])
    sentinel = object()

    def handler(_request: ModelRequest[object]) -> ModelResponse[object]:
        return sentinel  # type: ignore[return-value]

    result = adapter.wrap_model_call(request, handler)
    assert result is sentinel


@pytest.mark.asyncio
async def test_awrap_model_call_inherited_falls_through() -> None:
    """When inner does not override awrap_model_call, adapter calls handler."""
    inner = AgentMiddleware()
    adapter = SyncHookParityAdapter(inner)
    request = ModelRequest(model=MagicMock(), messages=[])
    called = False

    async def handler(_request: ModelRequest[object]) -> ModelResponse[object]:
        nonlocal called
        called = True
        return ModelResponse(result=[])

    await adapter.awrap_model_call(request, handler)
    assert called is True


@pytest.mark.asyncio
async def test_awrap_tool_call_delegates_or_falls_through() -> None:
    request = MagicMock()

    inner_default = AgentMiddleware()
    adapter_default = SyncHookParityAdapter(inner_default)
    default_called = False

    async def default_handler(_request: object) -> ToolMessage:
        nonlocal default_called
        default_called = True
        return ToolMessage(content="ok", tool_call_id="t1")

    result = await adapter_default.awrap_tool_call(request, default_handler)
    assert default_called is True
    assert result.content == "ok"

    class _AsyncToolMiddleware(AgentMiddleware):  # type: ignore[type-arg]
        name = "async_tool"

        async def awrap_tool_call(self, request, handler):
            return await handler(request)

    adapter_custom = SyncHookParityAdapter(_AsyncToolMiddleware())
    custom_called = False

    async def custom_handler(_request: object) -> ToolMessage:
        nonlocal custom_called
        custom_called = True
        return ToolMessage(content="custom", tool_call_id="t2")

    result = await adapter_custom.awrap_tool_call(request, custom_handler)
    assert custom_called is True
    assert result.content == "custom"


@pytest.mark.asyncio
async def test_aafter_model_inherited_returns_none() -> None:
    inner = AgentMiddleware()
    adapter = SyncHookParityAdapter(inner)
    assert await adapter.aafter_model({}, object()) is None


@pytest.mark.asyncio
async def test_aafter_model_delegates_custom() -> None:
    class _AfterModelMiddleware(AgentMiddleware):  # type: ignore[type-arg]
        name = "after_model"

        async def aafter_model(self, state, runtime):
            return {"messages": []}

    adapter = SyncHookParityAdapter(_AfterModelMiddleware())
    assert await adapter.aafter_model({}, object()) == {"messages": []}


def test_getattr_delegates_to_inner() -> None:
    inner = _AsyncOnlyMiddleware()
    inner.custom_attr = 42  # type: ignore[attr-defined]
    adapter = SyncHookParityAdapter(inner)
    assert adapter.custom_attr == 42  # type: ignore[attr-defined]


def test_apply_keeps_non_middleware_objects() -> None:
    plain = object()
    adapted = apply_sync_hook_parity([plain])
    assert adapted == [plain]


def test_apply_keeps_existing_adapter() -> None:
    inner = _AsyncOnlyMiddleware()
    adapter = SyncHookParityAdapter(inner)
    adapted = apply_sync_hook_parity([adapter])
    assert adapted == [adapter]


def test_apply_wraps_when_sync_hook_missing() -> None:
    inner = _AsyncOnlyMiddleware()
    adapted = apply_sync_hook_parity([inner])
    assert isinstance(adapted[0], SyncHookParityAdapter)


def test_apply_keeps_middleware_with_sync_hooks() -> None:
    class _FullMiddleware(AgentMiddleware):  # type: ignore[type-arg]
        name = "full"

        def wrap_model_call(self, request, handler):
            return handler(request)

        def wrap_tool_call(self, request, handler):
            return handler(request)

    adapted = apply_sync_hook_parity([_FullMiddleware()])
    assert not isinstance(adapted[0], SyncHookParityAdapter)
