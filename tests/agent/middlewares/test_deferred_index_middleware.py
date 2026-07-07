"""Tests for DeferredIndexMiddleware."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.middlewares.deferred_index_middleware import (
    DeferredIndexMiddleware,
)
from myrm_agent_harness.agent.tool_management.defer.stable_index import (
    DEFERRED_TOOLS_MARKER,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.agent.tool_management.types import ToolBindMode, ToolSource


@tool("defer_a_tool", description="defer a")
def _defer_a() -> str:
    return "a"


@tool("defer_b_tool", description="defer b")
def _defer_b() -> str:
    return "b"


@pytest.mark.asyncio
async def test_injects_deferred_index_once() -> None:
    registry = ToolRegistry()
    registry.register(_defer_b, source=ToolSource.META, bind_mode=ToolBindMode.DISCOVERABLE)
    registry.register(_defer_a, source=ToolSource.META, bind_mode=ToolBindMode.DISCOVERABLE)

    middleware = DeferredIndexMiddleware(registry)
    request = MagicMock()
    request.messages = [SystemMessage(content="base"), HumanMessage(content="hi")]
    request.state = {}
    request.override = MagicMock(
        side_effect=lambda **kwargs: MagicMock(messages=kwargs.get("messages"), state=request.state)
    )

    captured: list[object] = []

    async def handler(req: object) -> str:
        captured.append(req)
        return "ok"

    await middleware.awrap_model_call(request, handler)
    assert len(captured) == 1
    messages = captured[0].messages
    assert len(messages) == 3
    injected = messages[1]
    assert isinstance(injected, SystemMessage)
    assert DEFERRED_TOOLS_MARKER in str(injected.content)
    assert "defer_a_tool\ndefer_b_tool" in str(injected.content)

    request2 = MagicMock()
    request2.messages = list(messages)
    request2.state = {}
    request2.override = MagicMock(
        side_effect=lambda **kwargs: MagicMock(messages=kwargs.get("messages"), state=request2.state)
    )
    captured.clear()
    await middleware.awrap_model_call(request2, handler)
    assert len(captured[0].messages) == 3


@pytest.mark.asyncio
async def test_skips_injection_when_no_discoverable_tools() -> None:
    registry = ToolRegistry()
    middleware = DeferredIndexMiddleware(registry)
    request = MagicMock()
    request.messages = [HumanMessage(content="hi")]
    request.state = {}

    async def handler(req: object) -> str:
        return "ok"

    await middleware.awrap_model_call(request, handler)
    assert len(request.messages) == 1


@pytest.mark.asyncio
async def test_skips_injection_when_state_already_has_index() -> None:
    registry = ToolRegistry()
    registry.register(_defer_a, source=ToolSource.META, bind_mode=ToolBindMode.DISCOVERABLE)
    middleware = DeferredIndexMiddleware(registry)
    request = MagicMock()
    request.messages = [HumanMessage(content="hi")]
    request.state = {
        "messages": [
            SystemMessage(
                content=f"base\n{DEFERRED_TOOLS_MARKER}\ndefer_a_tool\n</available-deferred-tools>"
            )
        ]
    }
    request.override = MagicMock(
        side_effect=lambda **kwargs: MagicMock(messages=kwargs.get("messages"), state=request.state)
    )

    captured: list[object] = []

    async def handler(req: object) -> str:
        captured.append(req)
        return "ok"

    await middleware.awrap_model_call(request, handler)
    assert len(captured[0].messages) == 1


def test_sync_wrap_raises() -> None:
    middleware = DeferredIndexMiddleware(ToolRegistry())
    with pytest.raises(NotImplementedError):
        middleware.wrap_model_call(MagicMock(), MagicMock())
