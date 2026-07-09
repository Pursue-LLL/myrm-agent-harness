"""Tests for DeferredToolMiddleware (cache-safe; no bind_tools mutation)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.middlewares.deferred_tool_middleware import (
    DeferredToolMiddleware,
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
async def test_awrap_model_call_does_not_mutate_tools(registry: ToolRegistry) -> None:
    """Prefix-cache safe: middleware must not append deferred tools to request.tools."""
    middleware = DeferredToolMiddleware(registry)
    request = MagicMock()
    request.messages = []
    request.tools = []

    async def next_call(req: object) -> str:
        return "response"

    response = await middleware.awrap_model_call(request, next_call)
    assert response == "response"
    assert request.tools == []


def test_wrap_model_call_sync_raises() -> None:
    middleware = DeferredToolMiddleware(ToolRegistry())
    with pytest.raises(NotImplementedError):
        middleware.wrap_model_call(MagicMock(), MagicMock())


def test_wrap_tool_call_sync_raises() -> None:
    middleware = DeferredToolMiddleware(ToolRegistry())
    with pytest.raises(NotImplementedError):
        middleware.wrap_tool_call(MagicMock(), MagicMock())


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
async def test_awrap_tool_call_resolves_discoverable_tool(registry: ToolRegistry) -> None:
    middleware = DeferredToolMiddleware(registry)
    request = MagicMock()
    request.tool = None
    request.tool_call = {"name": "dummy_tool"}
    request.override = MagicMock(side_effect=lambda **kwargs: MagicMock(tool=kwargs.get("tool")))

    captured: list[object] = []

    async def handler(req: object) -> str:
        captured.append(req)
        return "ok"

    result = await middleware.awrap_tool_call(request, handler)

    assert result == "ok"
    assert len(captured) == 1
    assert captured[0].tool.name == "dummy_tool"


@pytest.mark.asyncio
async def test_awrap_tool_call_resolves_from_registry_when_turn1_bound(
    registry: ToolRegistry,
) -> None:
    registry.register(DummyTool(), source=ToolSource.META, bind_mode=ToolBindMode.TURN1)
    middleware = DeferredToolMiddleware(registry)

    request = MagicMock()
    request.tool = None
    request.tool_call = {"name": "dummy"}
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


@pytest.mark.asyncio
async def test_awrap_tool_call_resolves_from_active_resolved_tools(
    registry: ToolRegistry,
) -> None:
    middleware = DeferredToolMiddleware(registry)
    request = MagicMock()
    request.tool = None
    request.tool_call = {"name": "dummy_tool"}
    request.override = MagicMock(side_effect=lambda **kwargs: MagicMock(tool=kwargs.get("tool")))

    captured: list[object] = []

    async def handler(req: object) -> str:
        captured.append(req)
        return "from_session"

    with patch(
        "myrm_agent_harness.agent.middlewares._session_context.get_active_resolved_tools",
        return_value=[DummyTool()],
    ), patch(
        "myrm_agent_harness.agent.middlewares._session_context.get_active_tool_registry",
        return_value=None,
    ):
        result = await middleware.awrap_tool_call(request, handler)

    assert result == "from_session"
    assert captured[0].tool.name == "dummy_tool"


@pytest.mark.asyncio
async def test_awrap_tool_call_skips_non_string_tool_names(
    registry: ToolRegistry,
) -> None:
    middleware = DeferredToolMiddleware(registry)
    request = MagicMock()
    request.tool = None
    request.tool_call = {"name": "dummy_tool"}
    request.override = MagicMock(side_effect=lambda **kwargs: MagicMock(tool=kwargs.get("tool")))

    class BadNameTool:
        name = 123

    async def handler(req: object) -> str:
        return "ok"

    with patch(
        "myrm_agent_harness.agent.middlewares._session_context.get_active_resolved_tools",
        return_value=[BadNameTool(), DummyTool()],
    ), patch(
        "myrm_agent_harness.agent.middlewares._session_context.get_active_tool_registry",
        return_value=None,
    ):
        result = await middleware.awrap_tool_call(request, handler)

    assert result == "ok"


@pytest.mark.asyncio
async def test_awrap_tool_call_resolves_discoverable_only_pool(registry: ToolRegistry) -> None:
    middleware = DeferredToolMiddleware(registry)
    request = MagicMock()
    request.tool = None
    request.tool_call = {"name": "dummy_tool"}
    request.override = MagicMock(side_effect=lambda **kwargs: MagicMock(tool=kwargs.get("tool")))

    captured: list[object] = []

    async def handler(req: object) -> str:
        captured.append(req)
        return "discoverable"

    with patch.object(registry, "resolve", return_value=[]), patch.object(
        registry, "get_runtime_tools", return_value=[]
    ), patch(
        "myrm_agent_harness.agent.middlewares._session_context.get_active_resolved_tools",
        return_value=[],
    ), patch(
        "myrm_agent_harness.agent.middlewares._session_context.get_active_tool_registry",
        return_value=None,
    ):
        result = await middleware.awrap_tool_call(request, handler)

    assert result == "discoverable"
    assert captured[0].tool.name == "dummy_tool"


@pytest.mark.asyncio
async def test_deferred_tool_middleware_allowed_tools_with_loaded_skills(
    registry: ToolRegistry,
) -> None:
    """Loaded skills restrict via tool_choice.allowed_tools; request.tools stays intact."""
    from langchain.agents.middleware import ModelRequest

    from myrm_agent_harness.agent._skill_agent_context import reset_loaded_skills, set_loaded_skills
    from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillTrust

    class AllowedTool(BaseTool):
        name: str = "file_write_tool"
        description: str = "write files"

        def _run(self, *args: object, **kwargs: object) -> str:
            return "ok"

    class BlockedTool(BaseTool):
        name: str = "bash_code_execute_tool"
        description: str = "run bash"

        def _run(self, *args: object, **kwargs: object) -> str:
            return "ok"

    middleware = DeferredToolMiddleware(registry)
    request = ModelRequest(
        model=MagicMock(),
        messages=[],
        tools=[AllowedTool(), BlockedTool(), DummyTool()],
    )
    original_tool_names = [tool.name for tool in request.tools or []]

    reset_loaded_skills()
    set_loaded_skills(
        [
            SkillMetadata(
                name="demo_skill",
                description="demo",
                trust=SkillTrust.INSTALLED,
                scanner_clean=True,
                allowed_tools=["file_write_tool"],
            )
        ]
    )

    captured_request: ModelRequest | None = None

    try:
        async def next_call(req: ModelRequest) -> str:
            nonlocal captured_request
            captured_request = req
            return "response"

        response = await middleware.awrap_model_call(request, next_call)

        assert response == "response"
        assert [tool.name for tool in request.tools or []] == original_tool_names
        assert captured_request is not None
        tool_choice = captured_request.tool_choice
        assert isinstance(tool_choice, dict)
        assert tool_choice["type"] == "allowed_tools"
        assert tool_choice["mode"] == "auto"
        allowed = {entry["name"] for entry in tool_choice["tools"]}
        assert allowed == {"file_write_tool"}
    finally:
        reset_loaded_skills()
