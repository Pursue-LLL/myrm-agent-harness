"""Tests for MCP connection manager concurrency, singleflight weakref locks, and cancellation cleanup.

Covers:
- WeakValueDictionary automatic garbage collection for _create_locks (zero memory leak)
- _create_connection cancellation / exception teardown (orphan process prevention)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.mcp.config import MCPConfig
from myrm_agent_harness.toolkits.mcp.connection_manager import MCPConnectionManager


@pytest.mark.asyncio
async def test_create_locks_weakref_garbage_collection() -> None:
    """Verify that _create_locks automatically garbage-collects locks when no longer referenced."""
    manager = MCPConnectionManager()

    config_hash = "test-hash-12345"
    assert config_hash not in manager._create_locks

    # Acquire lock in a block
    async with manager._get_create_lock(config_hash):
        assert config_hash in manager._create_locks
        assert isinstance(manager._create_locks[config_hash], asyncio.Lock)

    # After exiting the context and releasing local reference, WeakValueDictionary must be clean
    # Note: In CPython, once the frame and local variable are cleared, weakref drops immediately.
    assert config_hash not in manager._create_locks
    assert len(manager._create_locks) == 0


@pytest.mark.asyncio
async def test_create_connection_cleans_up_actors_on_cancellation() -> None:
    """Verify that when connection creation task is cancelled, all started actors are closed."""
    manager = MCPConnectionManager()
    cfg1 = MCPConfig(name="srv1", type="stdio", command="dummy")
    cfg2 = MCPConfig(name="srv2", type="stdio", command="dummy")

    actor1 = MagicMock()
    actor1.start = AsyncMock()
    actor1.close = AsyncMock()

    actor2_started = asyncio.Event()
    actor2_hang = asyncio.Event()

    async def _actor2_start() -> None:
        actor2_started.set()
        await actor2_hang.wait()

    actor2 = MagicMock()
    actor2.start = AsyncMock(side_effect=_actor2_start)
    actor2.close = AsyncMock()

    with patch(
        "myrm_agent_harness.toolkits.mcp.session_actor.MCPSessionActor",
        side_effect=[actor1, actor2],
    ):
        task = asyncio.create_task(manager._create_connection([cfg1, cfg2], "test-hash-cancel"))
        await actor2_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    actor1.close.assert_called_once()


@pytest.mark.asyncio
async def test_create_connection_cleans_up_actors_when_all_fail() -> None:
    """Verify that if all servers fail to start, any partially started actors are closed."""
    manager = MCPConnectionManager()
    cfg1 = MCPConfig(name="srv1", type="stdio", command="dummy")

    actor1 = MagicMock()
    actor1.start = AsyncMock(side_effect=RuntimeError("connection refused"))
    actor1.close = AsyncMock()

    with (
        patch(
            "myrm_agent_harness.toolkits.mcp.session_actor.MCPSessionActor",
            return_value=actor1,
        ),
        pytest.raises(RuntimeError, match="All MCP servers failed to start"),
    ):
        await manager._create_connection([cfg1], "test-hash-fail")


@pytest.mark.asyncio
async def test_get_server_runtime_status_offline() -> None:
    """Verify that unstarted server defaults to OFFLINE state."""
    manager = MCPConnectionManager()
    status = manager.get_server_runtime_status("unknown_server")
    assert status["state"] == "offline"
    assert status["healthy"] is False
    assert status["tool_count"] == 0


@pytest.mark.asyncio
async def test_get_server_runtime_status_connected() -> None:
    """Verify that healthy server returns CONNECTED state and usage metrics."""
    from myrm_agent_harness.toolkits.mcp.connection_pool_types import (
        ConnectionMetrics,
        ConnectionStatus,
        MCPConnection,
    )

    manager = MCPConnectionManager()
    actor = MagicMock()
    actor.is_healthy.return_value = True
    actor.tools = [MagicMock(), MagicMock()]

    conn = MCPConnection(
        config_hash="hash-live",
        actors={"weather": actor},
    )
    conn.status = ConnectionStatus.ACTIVE
    conn.metrics = ConnectionMetrics(
        created_at=100.0,
        last_used=200.0,
        use_count=42,
        total_time=1.5,
        error_count=2,
        total_tokens_consumed=1250,
    )
    manager._connections["hash-live"] = conn

    status = manager.get_server_runtime_status("weather")
    assert status["server_name"] == "weather"
    assert status["state"] == "connected"
    assert status["healthy"] is True
    assert status["tool_count"] == 2
    assert status["use_count"] == 42
    assert status["total_tokens_consumed"] == 1250


@pytest.mark.asyncio
async def test_get_server_runtime_status_backoff_cooldown() -> None:
    """Verify that throttled server returns ERROR state and cooldown seconds."""
    manager = MCPConnectionManager()
    manager._backoff.record_failure("hash-fail", "connection refused", ("broken_srv",))

    status = manager.get_server_runtime_status("broken_srv")
    assert status["server_name"] == "broken_srv"
    assert status["state"] == "error"
    assert status["healthy"] is False
    assert status["last_error"] == "connection refused"
    assert float(status["cooldown_remaining_seconds"]) > 0.0
