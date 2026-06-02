"""Tests for MCP lifecycle — graceful teardown of the lazily-started pool."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.mcp.connection_manager import MCPConnectionManager
from myrm_agent_harness.toolkits.mcp.lifecycle import MCPLifecycleManager


@pytest.mark.asyncio
async def test_shutdown_without_instance_is_noop() -> None:
    """Shutdown must be safe even when the pool was never created."""
    MCPConnectionManager._instance = None
    await MCPLifecycleManager().shutdown()
    assert MCPConnectionManager._instance is None


@pytest.mark.asyncio
async def test_shutdown_stops_lazily_started_manager() -> None:
    """A manager started lazily (no explicit lifecycle.startup) must still be
    stopped and the singleton cleared so a later run starts fresh."""
    MCPConnectionManager._instance = None
    manager = MCPConnectionManager()
    await manager.start()
    MCPConnectionManager._instance = manager
    assert manager._started is True

    await MCPLifecycleManager().shutdown()

    assert manager._started is False
    assert MCPConnectionManager._instance is None
