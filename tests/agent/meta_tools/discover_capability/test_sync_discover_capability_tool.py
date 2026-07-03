"""Tests for discover_capability_tool registry sync after deferred mutations."""

from __future__ import annotations

import pytest
from langchain.tools import tool

from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
    create_discover_capability_tool,
    sync_discover_capability_tool,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry, ToolSource
from myrm_agent_harness.agent.tool_management.types import ToolBindMode


@tool("cron_manage_tool", description="Manage scheduled cron jobs and automation tasks")
def _cron_manage_tool(name: str) -> str:
    """Create or update cron jobs."""
    return name


@tool("bash_process_list_tool", description="List background bash processes")
def _bash_process_list_tool() -> str:
    """List processes."""
    return "ok"


@pytest.mark.asyncio
async def test_sync_reindexes_server_deferred_after_meta_deferred() -> None:
    """Server deferred tools registered after initial discover must become searchable."""
    registry = ToolRegistry()
    registry.register(_bash_process_list_tool, source=ToolSource.META, bind_mode=ToolBindMode.DISCOVERABLE)
    registry.register(
        create_discover_capability_tool(registry=registry),
        source=ToolSource.META,
    )

    stale_discover = next(t for t in registry.resolve() if t.name == "discover_capability_tool")
    stale_result = await stale_discover.ainvoke({"query": "cron scheduled automation"})
    assert "cron_manage_tool" not in stale_result

    registry.register(_cron_manage_tool, source=ToolSource.USER, bind_mode=ToolBindMode.DISCOVERABLE)
    sync_discover_capability_tool(registry)

    fresh_discover = next(t for t in registry.resolve() if t.name == "discover_capability_tool")
    fresh_result = await fresh_discover.ainvoke({"query": "cron.*manage", "mode": "regex"})
    assert "cron_manage_tool" in fresh_result
    assert "<AutoMountTools>" in fresh_result


@pytest.mark.asyncio
async def test_sync_removes_discover_when_no_deferred_or_skills() -> None:
    registry = ToolRegistry()
    registry.register(_bash_process_list_tool, source=ToolSource.META, bind_mode=ToolBindMode.DISCOVERABLE)
    sync_discover_capability_tool(registry)
    assert registry.has_tool("discover_capability_tool")

    registry.remove_tool("bash_process_list_tool")
    sync_discover_capability_tool(registry)
    assert not registry.has_tool("discover_capability_tool")
