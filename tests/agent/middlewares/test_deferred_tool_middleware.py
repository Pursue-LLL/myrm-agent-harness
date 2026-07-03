"""Tests for DeferredToolMiddleware.

Covers: parsing of `<AutoMountTools>` XML tags, injection of tools into the request.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.meta_tools.bash.background_deferred_activation import (
    activate_session_deferred_tool,
    reset_deferred_activation_for_tests,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_process_tools import (
    BASH_PROCESS_TOOL_NAME,
    create_bash_process_tool,
)
from myrm_agent_harness.agent.middlewares.deferred_tool_middleware import (
    DeferredToolMiddleware,
    _messages_from_agent_state,
    collect_activated_native_tool_names,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.agent.tool_management.types import ToolBindMode, ToolSource


class DummyTool(BaseTool):
    name: str = "dummy_tool"
    description: str = "A dummy tool"

    def _run(self, *args: object, **kwargs: object) -> str:
        return "dummy"


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(DummyTool(), source=ToolSource.META, bind_mode=ToolBindMode.DISCOVERABLE)
    return reg


@pytest.mark.asyncio
async def test_deferred_tool_middleware_session_spawn_automount() -> None:
    """Background spawn activates bash_process_tool via session-scoped deferred registry."""
    reset_deferred_activation_for_tests()
    reg = ToolRegistry()
    reg.register(
        create_bash_process_tool(),
        source=ToolSource.META,
        bind_mode=ToolBindMode.DISCOVERABLE,
    )
    middleware = DeferredToolMiddleware(reg)
    request = MagicMock()
    request.messages = []
    request.tools = []

    activate_session_deferred_tool("chat-spawn", BASH_PROCESS_TOOL_NAME)

    async def next_call(req: object) -> str:
        return "response"

    with patch(
        "myrm_agent_harness.agent.middlewares._session_context.get_approval_session",
        return_value="chat-spawn",
    ):
        response = await middleware.awrap_model_call(request, next_call)

    assert response == "response"
    assert len(request.tools) == 1
    assert request.tools[0].name == BASH_PROCESS_TOOL_NAME


@pytest.mark.asyncio
async def test_deferred_tool_middleware_no_discover_capability(
    registry: ToolRegistry,
) -> None:
    middleware = DeferredToolMiddleware(registry)
    request = MagicMock()
    request.messages = []
    request.tools = []

    async def next_call(req: object) -> str:
        return "response"

    # To test a method decorated with @wrap_model_call, we need to extract the original function
    # LangChain's decorator creates a class with an `awrap_model_call` method which is itself a method,
    # but the original function might be stored differently. Let's just bypass the middleware entirely
    # and extract the logic to a separate function if we can't call it, or we can just test it by
    # instantiating the middleware and calling its `awrap_model_call` method properly if it's the class method.
    # Wait, the decorator returns a class. So `DeferredToolMiddleware` is actually a class returned by the decorator!
    # No, `DeferredToolMiddleware` inherits from `AgentMiddleware`. The method `awrap_model_call` is decorated.
    # Actually, let's look at the source code of `wrap_model_call` decorator.
    # It returns a new class. But here we used it as a method decorator.
    # This is incorrect usage of `@wrap_model_call`. It's meant to decorate a function, not a method!
    # Let's fix the middleware implementation instead!
    response = await middleware.awrap_model_call(request, next_call)
    assert response == "response"
    assert len(request.tools) == 0


@pytest.mark.asyncio
async def test_deferred_tool_middleware_with_discover_capability(
    registry: ToolRegistry,
) -> None:
    middleware = DeferredToolMiddleware(registry)
    request = MagicMock()

    # Create a ToolMessage simulating discover_capability output
    json_data = json.dumps([{"name": "dummy_tool"}])
    content = (
        f"### Found Native Tools\n<AutoMountTools>\n{json_data}\n</AutoMountTools>"
    )

    msg = ToolMessage(content=content, name="discover_capability_tool", tool_call_id="123")
    request.messages = [msg]
    request.tools = []

    async def next_call(req: object) -> str:
        return "response"

    # To test a method decorated with @wrap_model_call, we need to extract the original function
    # LangChain's decorator creates a class with an `awrap_model_call` method which is itself a method,
    # but the original function might be stored differently. Let's just bypass the middleware entirely
    # and extract the logic to a separate function if we can't call it, or we can just test it by
    # instantiating the middleware and calling its `awrap_model_call` method properly if it's the class method.
    # Wait, the decorator returns a class. So `DeferredToolMiddleware` is actually a class returned by the decorator!
    # No, `DeferredToolMiddleware` inherits from `AgentMiddleware`. The method `awrap_model_call` is decorated.
    # Actually, let's look at the source code of `wrap_model_call` decorator.
    # It returns a new class. But here we used it as a method decorator.
    # This is incorrect usage of `@wrap_model_call`. It's meant to decorate a function, not a method!
    # Let's fix the middleware implementation instead!
    response = await middleware.awrap_model_call(request, next_call)
    assert response == "response"
    assert len(request.tools) == 1
    assert request.tools[0].name == "dummy_tool"


@pytest.mark.asyncio
async def test_deferred_tool_middleware_with_discover_capability_tool_suffix(
    registry: ToolRegistry,
) -> None:
    """ToolMessage.name is discover_capability_tool after normalize_tool_names()."""
    middleware = DeferredToolMiddleware(registry)
    request = MagicMock()

    json_data = json.dumps([{"name": "dummy_tool"}])
    content = (
        f"### Found Native Tools\n<AutoMountTools>\n{json_data}\n</AutoMountTools>"
    )

    msg = ToolMessage(content=content, name="discover_capability_tool", tool_call_id="124")
    request.messages = [msg]
    request.tools = []

    async def next_call(req: object) -> str:
        return "response"

    response = await middleware.awrap_model_call(request, next_call)
    assert response == "response"
    assert len(request.tools) == 1
    assert request.tools[0].name == "dummy_tool"


@pytest.mark.asyncio
async def test_deferred_tool_middleware_with_invalid_json(
    registry: ToolRegistry,
) -> None:
    middleware = DeferredToolMiddleware(registry)
    request = MagicMock()

    # Invalid JSON inside XML tags
    content = (
        "### Found Native Tools\n<AutoMountTools>\n[invalid json\n</AutoMountTools>"
    )

    msg = ToolMessage(content=content, name="discover_capability_tool", tool_call_id="123")
    request.messages = [msg]
    request.tools = []

    async def next_call(req: object) -> str:
        return "response"

    # To test a method decorated with @wrap_model_call, we need to extract the original function
    # LangChain's decorator creates a class with an `awrap_model_call` method which is itself a method,
    # but the original function might be stored differently. Let's just bypass the middleware entirely
    # and extract the logic to a separate function if we can't call it, or we can just test it by
    # instantiating the middleware and calling its `awrap_model_call` method properly if it's the class method.
    # Wait, the decorator returns a class. So `DeferredToolMiddleware` is actually a class returned by the decorator!
    # No, `DeferredToolMiddleware` inherits from `AgentMiddleware`. The method `awrap_model_call` is decorated.
    # Actually, let's look at the source code of `wrap_model_call` decorator.
    # It returns a new class. But here we used it as a method decorator.
    # This is incorrect usage of `@wrap_model_call`. It's meant to decorate a function, not a method!
    # Let's fix the middleware implementation instead!
    response = await middleware.awrap_model_call(request, next_call)
    assert response == "response"
    assert len(request.tools) == 0


@pytest.mark.asyncio
async def test_deferred_tool_middleware_already_in_tools(
    registry: ToolRegistry,
) -> None:
    middleware = DeferredToolMiddleware(registry)
    request = MagicMock()

    json_data = json.dumps([{"name": "dummy_tool"}])
    content = (
        f"### Found Native Tools\n<AutoMountTools>\n{json_data}\n</AutoMountTools>"
    )

    msg = ToolMessage(content=content, name="discover_capability_tool", tool_call_id="123")
    request.messages = [msg]
    # Tool is already in request.tools
    request.tools = [DummyTool()]

    async def next_call(req: object) -> str:
        return "response"

    # To test a method decorated with @wrap_model_call, we need to extract the original function
    # LangChain's decorator creates a class with an `awrap_model_call` method which is itself a method,
    # but the original function might be stored differently. Let's just bypass the middleware entirely
    # and extract the logic to a separate function if we can't call it, or we can just test it by
    # instantiating the middleware and calling its `awrap_model_call` method properly if it's the class method.
    # Wait, the decorator returns a class. So `DeferredToolMiddleware` is actually a class returned by the decorator!
    # No, `DeferredToolMiddleware` inherits from `AgentMiddleware`. The method `awrap_model_call` is decorated.
    # Actually, let's look at the source code of `wrap_model_call` decorator.
    # It returns a new class. But here we used it as a method decorator.
    # This is incorrect usage of `@wrap_model_call`. It's meant to decorate a function, not a method!
    # Let's fix the middleware implementation instead!
    response = await middleware.awrap_model_call(request, next_call)
    assert response == "response"
    # Should not duplicate the tool
    assert len(request.tools) == 1


def test_collect_activated_native_tool_names_parses_discover_output() -> None:
    json_data = json.dumps([{"name": "dummy_tool"}, {"name": "other_tool"}])
    content = f"<AutoMountTools>\n{json_data}\n</AutoMountTools>"
    msg = ToolMessage(content=content, name="discover_capability_tool", tool_call_id="1")
    activated = collect_activated_native_tool_names([msg])
    assert activated == {"dummy_tool", "other_tool"}


def test_collect_activated_native_tool_names_swallows_parse_errors() -> None:
    content = "<AutoMountTools>\n{broken json\n</AutoMountTools>"
    msg = ToolMessage(content=content, name="discover_capability", tool_call_id="5")
    assert collect_activated_native_tool_names([msg]) == set()


def test_wrap_model_call_sync_raises() -> None:
    middleware = DeferredToolMiddleware(ToolRegistry())
    with pytest.raises(NotImplementedError):
        middleware.wrap_model_call(MagicMock(), MagicMock())


def test_wrap_tool_call_sync_raises() -> None:
    middleware = DeferredToolMiddleware(ToolRegistry())
    with pytest.raises(NotImplementedError):
        middleware.wrap_tool_call(MagicMock(), MagicMock())


def test_collect_activated_native_tool_names_ignores_non_discover_messages() -> None:
    msg = ToolMessage(content="plain", name="bash_tool", tool_call_id="2")
    assert collect_activated_native_tool_names([msg]) == set()


def test_messages_from_agent_state_dict_and_object() -> None:
    msg = ToolMessage(content="x", name="discover_capability_tool", tool_call_id="3")
    assert _messages_from_agent_state({"messages": [msg]}) == [msg]

    state = MagicMock()
    state.messages = [msg]
    assert _messages_from_agent_state(state) == [msg]

    assert _messages_from_agent_state({}) == []
    assert _messages_from_agent_state(MagicMock(messages=None)) == []


@pytest.mark.asyncio
async def test_awrap_tool_call_passes_through_when_tool_already_set(
    registry: ToolRegistry,
) -> None:
    middleware = DeferredToolMiddleware(registry)
    request = MagicMock()
    request.tool = DummyTool()
    handler = AsyncMock(return_value="handled")

    result = await middleware.awrap_tool_call(request, handler)

    assert result == "handled"
    handler.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_awrap_tool_call_supplies_deferred_tool_when_activated(
    registry: ToolRegistry,
) -> None:
    middleware = DeferredToolMiddleware(registry)
    json_data = json.dumps([{"name": "dummy_tool"}])
    content = f"<AutoMountTools>\n{json_data}\n</AutoMountTools>"
    discover_msg = ToolMessage(
        content=content, name="discover_capability_tool", tool_call_id="4"
    )

    request = MagicMock()
    request.tool = None
    request.tool_call = {"name": "dummy_tool"}
    request.state = {"messages": [discover_msg]}
    request.override = MagicMock(side_effect=lambda **kwargs: MagicMock(tool=kwargs.get("tool")))

    captured: list[object] = []

    async def handler(req: object) -> str:
        captured.append(req)
        return "ok"

    result = await middleware.awrap_tool_call(request, handler)

    assert result == "ok"
    assert len(captured) == 1
    assert getattr(captured[0], "tool", None) is not None
    assert captured[0].tool.name == "dummy_tool"


@pytest.mark.asyncio
async def test_awrap_tool_call_resolves_from_registry_when_not_activated(
    registry: ToolRegistry,
) -> None:
    registry.register(DummyTool(), source=ToolSource.META, bind_mode=ToolBindMode.TURN1)
    middleware = DeferredToolMiddleware(registry)

    request = MagicMock()
    request.tool = None
    request.tool_call = {"name": "dummy"}
    request.state = {"messages": []}
    request.override = MagicMock(side_effect=lambda **kwargs: MagicMock(tool=kwargs.get("tool")))

    captured: list[object] = []

    async def handler(req: object) -> str:
        captured.append(req)
        return "resolved"

    with patch(
        "myrm_agent_harness.agent.middlewares._session_context.get_active_resolved_tools",
        return_value=[],
    ), patch(
        "myrm_agent_harness.agent.middlewares._session_context.get_active_tool_registry",
        return_value=None,
    ):
        result = await middleware.awrap_tool_call(request, handler)

    assert result == "resolved"
    assert captured[0].tool.name == "dummy_tool"


@pytest.mark.asyncio
async def test_awrap_tool_call_falls_through_when_tool_missing(
    registry: ToolRegistry,
) -> None:
    middleware = DeferredToolMiddleware(registry)
    request = MagicMock()
    request.tool = None
    request.tool_call = {"name": "missing_tool"}
    request.state = {"messages": []}
    handler = AsyncMock(return_value="fallback")

    with patch(
        "myrm_agent_harness.agent.middlewares._session_context.get_active_resolved_tools",
        return_value=[],
    ), patch(
        "myrm_agent_harness.agent.middlewares._session_context.get_active_tool_registry",
        return_value=None,
    ):
        result = await middleware.awrap_tool_call(request, handler)

    assert result == "fallback"
    handler.assert_awaited_once_with(request)
