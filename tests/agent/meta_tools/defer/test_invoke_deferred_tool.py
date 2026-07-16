"""Tests for invoke_deferred_tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
async def test_direct_invoke_refuses_to_bypass_runtime_normalization() -> None:
    registry = ToolRegistry()
    registry.register(_target_defer_tool, source=ToolSource.META, bind_mode=ToolBindMode.DISCOVERABLE)
    invoke = create_invoke_deferred_tool(registry)

    target_invoke = AsyncMock(return_value="ran:x")
    with patch.object(_target_defer_tool, "ainvoke", target_invoke):
        result = await invoke.ainvoke({"name": "target_defer_tool", "arguments": {"value": "x"}})

    assert "runtime safety normalization" in result
    target_invoke.assert_not_awaited()


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
async def test_invoke_requires_canonical_catalog_name() -> None:
    registry = ToolRegistry()
    registry.register(_target_defer_tool, source=ToolSource.META, bind_mode=ToolBindMode.DISCOVERABLE)
    invoke = create_invoke_deferred_tool(registry)

    result = await invoke.ainvoke({"name": "target_defer", "arguments": {"value": "y"}})
    assert "not a deferred native tool" in result
