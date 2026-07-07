"""Tests for invoke_deferred_tool."""

from __future__ import annotations

import pytest
from langchain.tools import tool

from myrm_agent_harness.agent.meta_tools.defer.invoke_deferred_tool import (
    INVOKE_DEFERRED_TOOL_NAME,
    create_invoke_deferred_tool,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.agent.tool_management.types import ToolBindMode, ToolSource


@tool("target_defer_tool", description="A deferred target")
def _target_defer_tool(value: str = "ok") -> str:
    return f"ran:{value}"


@pytest.mark.asyncio
async def test_invoke_resolves_and_runs_discoverable_tool() -> None:
    registry = ToolRegistry()
    registry.register(_target_defer_tool, source=ToolSource.META, bind_mode=ToolBindMode.DISCOVERABLE)
    invoke = create_invoke_deferred_tool(registry)

    result = await invoke.ainvoke({"name": "target_defer_tool", "arguments": {"value": "x"}})
    assert result == "ran:x"


@pytest.mark.asyncio
async def test_invoke_unknown_deferred_name_returns_error() -> None:
    registry = ToolRegistry()
    invoke = create_invoke_deferred_tool(registry)

    result = await invoke.ainvoke({"name": "missing_defer_tool", "arguments": {}})
    assert "Error:" in result
    assert "missing_defer_tool" in result


def test_invoke_tool_name_constant() -> None:
    registry = ToolRegistry()
    invoke = create_invoke_deferred_tool(registry)
    assert invoke.name == INVOKE_DEFERRED_TOOL_NAME


@pytest.mark.asyncio
async def test_invoke_resolves_name_with_tool_suffix() -> None:
    registry = ToolRegistry()
    registry.register(_target_defer_tool, source=ToolSource.META, bind_mode=ToolBindMode.DISCOVERABLE)
    invoke = create_invoke_deferred_tool(registry)

    result = await invoke.ainvoke({"name": "target_defer", "arguments": {"value": "y"}})
    assert result == "ran:y"


@pytest.mark.asyncio
async def test_invoke_returns_json_for_non_string_result() -> None:
    from langchain.tools import tool

    @tool("dict_defer_tool", description="returns dict")
    def _dict_tool() -> dict[str, str]:
        return {"status": "ok"}

    registry = ToolRegistry()
    registry.register(_dict_tool, source=ToolSource.META, bind_mode=ToolBindMode.DISCOVERABLE)
    invoke = create_invoke_deferred_tool(registry)

    result = await invoke.ainvoke({"name": "dict_defer_tool", "arguments": {}})
    assert '"status"' in result


@pytest.mark.asyncio
async def test_invoke_surfaces_target_errors() -> None:
    from langchain.tools import tool

    @tool("broken_defer_tool", description="raises")
    def _broken_tool() -> str:
        raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(_broken_tool, source=ToolSource.META, bind_mode=ToolBindMode.DISCOVERABLE)
    invoke = create_invoke_deferred_tool(registry)

    result = await invoke.ainvoke({"name": "broken_defer_tool", "arguments": {}})
    assert "Error invoking" in result
    assert "boom" in result
