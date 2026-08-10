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


@pytest.mark.asyncio
async def test_startup_initializes_and_is_idempotent() -> None:
    """startup() creates the pool once; a second call is a no-op."""
    MCPConnectionManager._instance = None
    lifecycle = MCPLifecycleManager()
    try:
        await lifecycle.startup()
        assert lifecycle._started is True
        assert MCPConnectionManager._instance is not None

        manager = MCPConnectionManager._instance
        await lifecycle.startup()
        # Same singleton, no duplicate re-initialisation.
        assert MCPConnectionManager._instance is manager
    finally:
        await lifecycle.shutdown()


@pytest.mark.asyncio
async def test_lifespan_context_runs_startup_and_shutdown() -> None:
    """The lifespan context manager pairs startup with shutdown even on error."""
    MCPConnectionManager._instance = None
    lifecycle = MCPLifecycleManager()
    entered = False
    try:
        async with lifecycle.lifespan():
            entered = True
            assert lifecycle._started is True
            assert MCPConnectionManager._instance is not None
        assert entered is True
        assert lifecycle._started is False
        assert MCPConnectionManager._instance is None
    finally:
        MCPConnectionManager._instance = None


@pytest.mark.asyncio
async def test_mcp_lifecycle_context_convenience() -> None:
    """The module-level convenience context wraps the singleton lifespan."""
    MCPConnectionManager._instance = None
    from myrm_agent_harness.toolkits.mcp.lifecycle import mcp_lifecycle_context

    try:
        async with mcp_lifecycle_context():
            assert MCPConnectionManager._instance is not None
    finally:
        MCPConnectionManager._instance = None
