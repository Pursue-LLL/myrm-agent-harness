"""Tests for DeferredToolMiddleware.

Covers: parsing of `<AutoMountTools>` XML tags, injection of tools into the request.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.middlewares.deferred_tool_middleware import (
    DeferredToolMiddleware,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.agent.tool_management.types import ToolSource


class DummyTool(BaseTool):
    name: str = "dummy_tool"
    description: str = "A dummy tool"

    def _run(self, *args: object, **kwargs: object) -> str:
        return "dummy"


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(DummyTool(), source=ToolSource.META, deferred=True)
    return reg


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
