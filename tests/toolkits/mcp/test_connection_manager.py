"""Tests for MCPConnectionManager — warm-session pool, lazy loading, health, TTL."""

from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.mcp.connection_manager import (
    ConnectionMetrics,
    ConnectionStatus,
    MCPConnection,
    MCPConnectionManager,
)


@dataclass
class _FakeConfig:
    """Minimal stub satisfying MCPServerConfigProtocol."""

    name: str = "test-server"
    type: str = "stdio"
    url: str | None = None
    command: str | None = "/usr/bin/echo"
    args: list[str] | None = None
    description: str = "Test MCP server"
    headers: dict[str, str] | None = None
    extra_params: dict[str, object] | None = None
    tool_include: list[str] | None = None
    tool_exclude: list[str] | None = None


class _FakeActor:
    """In-memory stand-in for MCPSessionActor (no real subprocess)."""

    def __init__(
        self,
        name: str = "test-server",
        *,
        tools: list[object] | None = None,
        instructions: str | None = None,
        healthy: bool = True,
    ) -> None:
        self.server_name = name
        self._tools = tools if tools is not None else [MagicMock()]
        self.instructions = instructions
        self._healthy = healthy
        self.last_activity = time.time()
        self.closed = False
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.raise_on_call: Exception | None = None

    @property
    def tools(self) -> list[object]:
        return list(self._tools)

    def is_healthy(self) -> bool:
        return self._healthy and not self.closed

    async def call(self, tool_name: str, params: dict[str, object]) -> object:
        self.calls.append((tool_name, params))
        self.last_activity = time.time()
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return f"result:{tool_name}"

    async def close(self) -> None:
        self.closed = True


# ============================================================================
# MCPConnection unit tests
# ============================================================================


class TestMCPConnection:
    @pytest.fixture
    def actor(self) -> _FakeActor:
        return _FakeActor("server_a", instructions="hello")

    @pytest.fixture
    def connection(self, actor: _FakeActor) -> MCPConnection:
        return MCPConnection("hash123", {"server_a": actor})

    def test_initial_state(self, connection: MCPConnection) -> None:
        assert connection.status == ConnectionStatus.IDLE
        assert connection.metrics.use_count == 0
        assert connection.metrics.error_count == 0

    def test_tools_and_instructions_by_server(
        self, connection: MCPConnection, actor: _FakeActor
    ) -> None:
        assert connection.tools_by_server == {"server_a": actor.tools}
        assert connection.instructions_by_server == {"server_a": "hello"}

    @pytest.mark.asyncio
    async def test_call_routes_to_actor_and_updates_metrics(
        self, connection: MCPConnection, actor: _FakeActor
    ) -> None:
        result = await connection.call("server_a", "do_thing", {"x": 1})
        assert result == "result:do_thing"
        assert actor.calls == [("do_thing", {"x": 1})]
        assert connection.metrics.use_count == 1
        assert connection.status == ConnectionStatus.IDLE

    @pytest.mark.asyncio
    async def test_call_resolves_server_name_variant(self, actor: _FakeActor) -> None:
        conn = MCPConnection("h", {"my_server": _FakeActor("my_server")})
        result = await conn.call("my-server", "t", {})
        assert result == "result:t"

    @pytest.mark.asyncio
    async def test_call_unknown_server_raises(self, connection: MCPConnection) -> None:
        with pytest.raises(RuntimeError, match="MCP server not found"):
            await connection.call("missing", "t", {})

    @pytest.mark.asyncio
    async def test_call_error_marks_unhealthy(self, actor: _FakeActor) -> None:
        actor.raise_on_call = ConnectionError("pipe broken")
        actor._healthy = False
        conn = MCPConnection("h", {"server_a": actor})
        with pytest.raises(ConnectionError):
            await conn.call("server_a", "t", {})
        assert conn.metrics.error_count == 1
        assert conn.status == ConnectionStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_health_check_all_healthy(self, connection: MCPConnection) -> None:
        assert await connection.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_one_unhealthy(self, actor: _FakeActor) -> None:
        bad = _FakeActor("server_b", healthy=False)
        conn = MCPConnection("h", {"server_a": actor, "server_b": bad})
        assert await conn.health_check() is False
        assert conn.status == ConnectionStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_health_check_closed(self, connection: MCPConnection) -> None:
        connection.status = ConnectionStatus.CLOSED
        assert await connection.health_check() is False

    def test_is_expired_uses_actor_activity(self, actor: _FakeActor) -> None:
        conn = MCPConnection("h", {"server_a": actor})
        # Metrics is stale but the actor is fresh → not expired.
        conn.metrics.last_used = time.time() - 700
        assert conn.is_expired(600) is False
        # Both stale → expired.
        actor.last_activity = time.time() - 700
        assert conn.is_expired(600) is True

    def test_get_stats(self, connection: MCPConnection) -> None:
        stats = connection.get_stats()
        assert stats["status"] == "idle"
        assert stats["servers"] == ["server_a"]
        assert "error_rate" in stats

    def test_is_bound_to_current_loop_outside_loop(
        self, connection: MCPConnection
    ) -> None:
        # Constructed without a running loop (sync fixture) → not bound.
        assert connection.is_bound_to_current_loop() is False

    @pytest.mark.asyncio
    async def test_is_bound_to_current_loop_inside_loop(self) -> None:
        conn = MCPConnection("h", {"server_a": _FakeActor()})
        assert conn.is_bound_to_current_loop() is True

    @pytest.mark.asyncio
    async def test_close_idempotent_and_closes_actors(self, actor: _FakeActor) -> None:
        conn = MCPConnection("h", {"server_a": actor})
        await conn.close()
        assert conn.status == ConnectionStatus.CLOSED
        assert actor.closed is True
        await conn.close()  # idempotent
        assert conn.status == ConnectionStatus.CLOSED


# ============================================================================
# MCPConnectionManager unit tests
# ============================================================================


class TestMCPConnectionManager:
    @pytest.fixture
    def manager(self) -> MCPConnectionManager:
        MCPConnectionManager._instance = None
        return MCPConnectionManager(ttl=600, cleanup_interval=60)

    def test_make_config_hash_deterministic(self, manager: MCPConnectionManager) -> None:
        configs = [_FakeConfig(name="a"), _FakeConfig(name="b")]
        assert manager._make_config_hash(configs) == manager._make_config_hash(configs)

    def test_make_config_hash_different_for_different_configs(
        self, manager: MCPConnectionManager
    ) -> None:
        assert manager._make_config_hash([_FakeConfig(name="a")]) != manager._make_config_hash(
            [_FakeConfig(name="b")]
        )

    def test_make_config_hash_order_independent(self, manager: MCPConnectionManager) -> None:
        c1 = [_FakeConfig(name="a"), _FakeConfig(name="b")]
        c2 = [_FakeConfig(name="b"), _FakeConfig(name="a")]
        assert manager._make_config_hash(c1) == manager._make_config_hash(c2)

    def test_make_config_hash_distinguishes_args(self, manager: MCPConnectionManager) -> None:
        a = [_FakeConfig(name="x", args=["1"])]
        b = [_FakeConfig(name="x", args=["2"])]
        assert manager._make_config_hash(a) != manager._make_config_hash(b)

    def test_make_config_hash_distinguishes_tool_filter(
        self, manager: MCPConnectionManager
    ) -> None:
        a = [_FakeConfig(name="x", tool_include=["t1"])]
        b = [_FakeConfig(name="x", tool_include=["t2"])]
        assert manager._make_config_hash(a) != manager._make_config_hash(b)

    @pytest.mark.asyncio
    async def test_start_stop(self, manager: MCPConnectionManager) -> None:
        await manager.start()
        assert manager._started is True
        assert manager._cleanup_task is not None
        await manager.stop()
        assert manager._started is False

    @pytest.mark.asyncio
    async def test_stop_idempotent(self, manager: MCPConnectionManager) -> None:
        await manager.stop()
        assert manager._started is False

    @pytest.mark.asyncio
    async def test_start_idempotent(self, manager: MCPConnectionManager) -> None:
        await manager.start()
        task1 = manager._cleanup_task
        await manager.start()
        assert manager._cleanup_task is task1
        await manager.stop()

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, manager: MCPConnectionManager) -> None:
        mock_conn = MagicMock(spec=MCPConnection)
        mock_conn.is_expired.return_value = True
        mock_conn.close = AsyncMock()
        mock_conn.metrics = ConnectionMetrics(
            created_at=time.time() - 1000,
            last_used=time.time() - 1000,
            use_count=5,
            total_time=1.0,
            error_count=0,
        )
        manager._connections["expired_hash"] = mock_conn

        await manager._cleanup_expired()

        assert "expired_hash" not in manager._connections
        mock_conn.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_keeps_active(self, manager: MCPConnectionManager) -> None:
        mock_conn = MagicMock(spec=MCPConnection)
        mock_conn.is_expired.return_value = False
        manager._connections["active_hash"] = mock_conn
        await manager._cleanup_expired()
        assert "active_hash" in manager._connections

    @pytest.mark.asyncio
    async def test_close_all(self, manager: MCPConnectionManager) -> None:
        for i in range(3):
            mock_conn = MagicMock(spec=MCPConnection)
            mock_conn.close = AsyncMock()
            manager._connections[f"hash_{i}"] = mock_conn
        await manager.close_all()
        assert len(manager._connections) == 0

    def test_get_stats(self, manager: MCPConnectionManager) -> None:
        stats = manager.get_stats()
        assert stats["total_connections"] == 0
        assert stats["started"] is False

    def test_repr(self, manager: MCPConnectionManager) -> None:
        assert "MCPConnectionManager" in repr(manager)

    @pytest.mark.asyncio
    async def test_get_connection_reuses_existing(
        self, manager: MCPConnectionManager
    ) -> None:
        mock_conn = MagicMock(spec=MCPConnection)
        mock_conn.is_bound_to_current_loop.return_value = True
        mock_conn.health_check = AsyncMock(return_value=True)
        mock_conn.metrics = ConnectionMetrics(
            created_at=time.time(),
            last_used=time.time(),
            use_count=1,
            total_time=0.1,
            error_count=0,
        )

        config = [_FakeConfig()]
        manager._connections[manager._make_config_hash(config)] = mock_conn

        result = await manager.get_connection(config)
        assert result is mock_conn
        mock_conn.health_check.assert_awaited()

    @pytest.mark.asyncio
    async def test_get_connection_recreates_unhealthy(
        self, manager: MCPConnectionManager
    ) -> None:
        stale = MagicMock(spec=MCPConnection)
        stale.is_bound_to_current_loop.return_value = True
        stale.health_check = AsyncMock(return_value=False)
        stale.close = AsyncMock()

        config = [_FakeConfig()]
        manager._connections[manager._make_config_hash(config)] = stale

        fresh = MagicMock(spec=MCPConnection)
        with patch.object(
            manager, "_create_connection", AsyncMock(return_value=fresh)
        ) as create:
            result = await manager.get_connection(config)

        assert result is fresh
        stale.close.assert_awaited_once()
        create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_connection_rebuilds_on_loop_change(
        self, manager: MCPConnectionManager
    ) -> None:
        stale = MagicMock(spec=MCPConnection)
        stale.is_bound_to_current_loop.return_value = False
        stale.close = AsyncMock()

        config = [_FakeConfig()]
        manager._connections[manager._make_config_hash(config)] = stale

        fresh = MagicMock(spec=MCPConnection)
        with patch.object(manager, "_create_connection", AsyncMock(return_value=fresh)):
            result = await manager.get_connection(config)

        assert result is fresh
        # Loop changed → the stale connection is dropped, NOT awaited-closed
        # (its owning loop already finalised it).
        stale.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_instance_singleton(self) -> None:
        MCPConnectionManager._instance = None
        with patch.object(MCPConnectionManager, "start", new_callable=AsyncMock):
            inst1 = await MCPConnectionManager.get_instance()
            inst2 = await MCPConnectionManager.get_instance()
            assert inst1 is inst2
        MCPConnectionManager._instance = None
