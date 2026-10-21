"""Pool-level contracts of ``MCPConnectionManager`` and its connection / backoff types.

Real transports are covered by the live integration tests. Here the pool is driven at the ``MCPSessionActor``
boundary so its concurrency, circuit-breaker and failure-isolation guarantees can be asserted deterministically:

- per-config singleflight and parallel spawning of distinct configs, capped by the spawn semaphore;
- the startup circuit breaker, reset by an auth refresh;
- config -> actor wiring (TLS material) and isolation of a failing server from its healthy siblings;
- loop-bound primitives, TTL sweeper self-healing and the module-level accessor.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.mcp import connection_manager as cm_module
from myrm_agent_harness.toolkits.mcp.client import MCPClientManager
from myrm_agent_harness.toolkits.mcp.config import MCPConfig
from myrm_agent_harness.toolkits.mcp.connection_manager import (
    ConnectionStatus,
    MCPConnection,
    MCPConnectionManager,
    MCPStartupBackoff,
    get_mcp_connection,
)


class _Actor:
    """In-memory stand-in for ``MCPSessionActor``."""

    def __init__(self, name: str) -> None:
        self.server_name = name
        self.tools: list[object] = []
        self.instructions: str | None = None
        self.last_activity = time.time()
        self.closed = False
        self.header_updates: list[dict[str, str]] = []
        self.resource_reads: list[str] = []

    def is_healthy(self) -> bool:
        return not self.closed

    async def close(self) -> None:
        self.closed = True

    def update_auth_headers(self, headers: dict[str, str]) -> None:
        self.header_updates.append(headers)

    async def read_resource(self, uri: str) -> bytes:
        self.resource_reads.append(uri)
        return f"resource:{uri}".encode()


class _SpawnedActor(_Actor):
    """Records what the pool hands to ``MCPSessionActor`` when it spawns a server."""

    def __init__(self, name: str, conn: dict[str, object], kwargs: dict[str, object]) -> None:
        super().__init__(name)
        self.conn = conn
        self.kwargs = kwargs

    async def start(self) -> None:
        return None


@contextmanager
def _spawning(*, fail_for: frozenset[str] = frozenset()) -> Iterator[list[_SpawnedActor]]:
    """Replace ``MCPSessionActor`` for ``_create_connection`` and yield every actor it spawns."""
    spawned: list[_SpawnedActor] = []

    class _Spawned(_SpawnedActor):
        def __init__(self, name: str, conn: dict[str, object], **kwargs: object) -> None:
            super().__init__(name, conn, kwargs)
            spawned.append(self)

        async def start(self) -> None:
            if self.server_name in fail_for:
                raise RuntimeError(f"{self.server_name} refused to start")

    with (
        patch.object(MCPClientManager, "_inject_auth_headers_into_config", AsyncMock()),
        patch("myrm_agent_harness.toolkits.mcp.session_actor.MCPSessionActor", _Spawned),
    ):
        yield spawned


def _cfg(name: str) -> MCPConfig:
    return MCPConfig(name=name, type="stdio", command="echo")


def _warm_connection(config_hash: str, *names: str) -> MCPConnection:
    """A healthy pooled connection bound to the running loop."""
    return MCPConnection(config_hash, {name: _Actor(name) for name in names})


async def _until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.fixture
def manager() -> MCPConnectionManager:
    return MCPConnectionManager(ttl=600, cleanup_interval=60)


class TestStartupBackoffClearServer:
    def test_drops_entries_naming_the_server_and_unattributed_ones(self) -> None:
        backoff = MCPStartupBackoff()
        backoff.record_failure("h-alpha", "boom", ("alpha",))
        backoff.record_failure("h-beta", "boom", ("beta",))
        backoff.record_failure("h-unattributed", "boom")

        backoff.clear_server("alpha")

        backoff.check_allowed("h-alpha")
        backoff.check_allowed("h-unattributed")
        with pytest.raises(RuntimeError, match="cooldown"):
            backoff.check_allowed("h-beta")


class TestMCPConnectionRouting:
    @pytest.mark.asyncio
    async def test_read_resource_routes_to_the_named_server_and_rejects_unknown_ones(self) -> None:
        actor = _Actor("docs")
        conn = MCPConnection("hash", {"docs": actor})

        assert await conn.read_resource("docs", "file:///a") == b"resource:file:///a"
        assert actor.resource_reads == ["file:///a"]
        with pytest.raises(RuntimeError, match=r"MCP server not found: nope.*\['docs'\]"):
            await conn.read_resource("nope", "file:///a")

    def test_refresh_server_auth_updates_the_actor_and_reports_unknown_servers(self) -> None:
        actor = _Actor("my-server")
        conn = MCPConnection("hash", {"my-server": actor})

        assert conn.refresh_server_auth("my-server", {"Authorization": "Bearer new"}) is True
        # Dash / underscore spellings resolve exactly like tool calls do.
        assert conn.refresh_server_auth("my_server", {"X-Key": "1"}) is True
        assert actor.header_updates == [{"Authorization": "Bearer new"}, {"X-Key": "1"}]
        assert conn.refresh_server_auth("other", {"X-Key": "1"}) is False


class TestSingleflightAndSpawnLimits:
    @pytest.mark.asyncio
    async def test_concurrent_requests_for_one_config_share_a_single_spawn(self, manager: MCPConnectionManager) -> None:
        started = 0
        release = asyncio.Event()

        async def fake_create(config: list[MCPConfig], config_hash: str) -> MCPConnection:
            nonlocal started
            started += 1
            await release.wait()
            conn = _warm_connection(config_hash, config[0].name)
            manager._connections[config_hash] = conn
            return conn

        config = [_cfg("srv")]
        with patch.object(manager, "_create_connection", fake_create):
            waiters = [asyncio.create_task(manager.get_connection(config)) for _ in range(5)]
            await _until(lambda: started == 1)
            await asyncio.sleep(0.05)  # let the other requests queue behind the creation lock
            release.set()
            connections = await asyncio.gather(*waiters)

        assert started == 1
        assert all(conn is connections[0] for conn in connections)

    @pytest.mark.asyncio
    async def test_distinct_configs_spawn_in_parallel(self, manager: MCPConnectionManager) -> None:
        in_flight = 0
        both_in_flight = asyncio.Event()

        async def fake_create(config: list[MCPConfig], config_hash: str) -> MCPConnection:
            nonlocal in_flight
            in_flight += 1
            if in_flight == 2:
                both_in_flight.set()
            # Serialised creation would never let the second spawn start, so this wait would time out.
            await asyncio.wait_for(both_in_flight.wait(), timeout=5.0)
            conn = _warm_connection(config_hash, config[0].name)
            manager._connections[config_hash] = conn
            return conn

        with patch.object(manager, "_create_connection", fake_create):
            first, second = await asyncio.gather(
                manager.get_connection([_cfg("a")]),
                manager.get_connection([_cfg("b")]),
            )

        assert first is not second

    @pytest.mark.asyncio
    async def test_spawn_semaphore_caps_concurrent_startups(self, manager: MCPConnectionManager) -> None:
        cap = cm_module._MAX_CONCURRENT_SPAWNS
        running = 0
        peak = 0

        async def fake_create(config: list[MCPConfig], config_hash: str) -> MCPConnection:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1
            conn = _warm_connection(config_hash, config[0].name)
            manager._connections[config_hash] = conn
            return conn

        with patch.object(manager, "_create_connection", fake_create):
            await asyncio.gather(*(manager.get_connection([_cfg(f"s{i}")]) for i in range(cap + 4)))

        assert peak == cap


class TestStartupCircuitBreaker:
    @pytest.mark.asyncio
    async def test_failure_opens_the_breaker_until_auth_is_refreshed(self, manager: MCPConnectionManager) -> None:
        attempts = 0

        async def failing_create(config: list[MCPConfig], config_hash: str) -> MCPConnection:
            nonlocal attempts
            attempts += 1
            raise RuntimeError("cannot start")

        config = [_cfg("srv")]
        with patch.object(manager, "_create_connection", failing_create):
            with pytest.raises(RuntimeError, match="cannot start"):
                await manager.get_connection(config)

            with pytest.raises(RuntimeError, match=r"startup backoff cooldown.*cannot start"):
                await manager.get_connection(config)
            assert attempts == 1  # the breaker refused it before any spawn

            manager.refresh_server_auth("srv", {})
            with pytest.raises(RuntimeError, match="cannot start"):
                await manager.get_connection(config)
            assert attempts == 2


class TestCreateConnection:
    @pytest.mark.asyncio
    async def test_tls_settings_reach_the_actor_connection(self, manager: MCPConnectionManager) -> None:
        cfg = MCPConfig(
            name="tls",
            type="streamable_http",
            url="https://mcp.example.test/mcp",
            ssl_verify="/etc/ssl/private-ca.pem",
            client_cert="/etc/ssl/client.pem",
            client_key="/etc/ssl/client.key",
            client_key_password="s3cret",
        )
        with _spawning() as spawned:
            await manager._create_connection([cfg], manager._make_config_hash([cfg]))

        conn = spawned[0].conn
        assert conn["ssl_verify"] == "/etc/ssl/private-ca.pem"
        assert conn["client_cert"] == "/etc/ssl/client.pem"
        assert conn["client_key"] == "/etc/ssl/client.key"
        assert conn["client_key_password"] == "s3cret"

    @pytest.mark.asyncio
    async def test_disabled_verification_is_forwarded_and_unset_tls_fields_are_not(
        self, manager: MCPConnectionManager
    ) -> None:
        insecure = MCPConfig(
            name="insecure", type="streamable_http", url="https://mcp.example.test/mcp", ssl_verify=False
        )
        plain = MCPConfig(name="plain", type="streamable_http", url="http://mcp.example.test/mcp")
        with _spawning() as spawned:
            await manager._create_connection([insecure, plain], manager._make_config_hash([insecure, plain]))

        by_name = {actor.server_name: actor.conn for actor in spawned}
        assert by_name["insecure"]["ssl_verify"] is False
        assert not {"ssl_verify", "client_cert", "client_key", "client_key_password"} & by_name["plain"].keys()

    @pytest.mark.asyncio
    async def test_one_failing_server_does_not_take_down_the_healthy_ones(
        self, manager: MCPConnectionManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        configs = [_cfg("good"), _cfg("bad")]
        with _spawning(fail_for=frozenset({"bad"})), caplog.at_level(logging.WARNING, logger=cm_module.logger.name):
            conn = await manager._create_connection(configs, manager._make_config_hash(configs))

        assert set(conn.instructions_by_server) == {"good"}
        assert "1/2 MCP server(s) failed to start" in caplog.text
        assert "bad refused to start" in caplog.text

    @pytest.mark.asyncio
    async def test_every_server_failing_is_an_error(self, manager: MCPConnectionManager) -> None:
        configs = [_cfg("bad-a"), _cfg("bad-b")]
        with (
            _spawning(fail_for=frozenset({"bad-a", "bad-b"})),
            pytest.raises(RuntimeError, match=r"All MCP servers failed to start: .*refused to start"),
        ):
            await manager._create_connection(configs, manager._make_config_hash(configs))

        assert not manager._connections

    @pytest.mark.asyncio
    async def test_actor_resolver_rebinds_through_the_pool_with_a_config_snapshot(
        self, manager: MCPConnectionManager
    ) -> None:
        actor = _Actor("srv")
        warm = MCPConnection("h", {"srv": actor})
        requested: list[list[str]] = []

        async def fake_get_connection(config: list[MCPConfig]) -> MCPConnection:
            requested.append([cfg.name for cfg in config])
            return warm

        configs = [_cfg("srv")]
        resolver = manager._make_actor_resolver(configs, "srv")
        missing = manager._make_actor_resolver(configs, "missing")
        configs.append(_cfg("added-later"))  # a later mutation of the caller's list must not leak in

        with patch.object(manager, "get_connection", fake_get_connection):
            assert await resolver() is actor
            assert await missing() is None

        assert requested == [["srv"], ["srv"]]


class TestAuthRefresh:
    def test_refresh_updates_live_connections_and_resets_the_breaker(self, manager: MCPConnectionManager) -> None:
        live_actor, closed_actor = _Actor("srv"), _Actor("srv")
        closed = MCPConnection("closed", {"srv": closed_actor})
        closed.status = ConnectionStatus.CLOSED
        manager._connections |= {"live": MCPConnection("live", {"srv": live_actor}), "closed": closed}
        manager._backoff.record_failure("dead-config", "boom", ("srv",))

        assert manager.refresh_server_auth("srv", {"Authorization": "Bearer new"}) is True

        assert live_actor.header_updates == [{"Authorization": "Bearer new"}]
        assert closed_actor.header_updates == []  # closed pooled connections are skipped
        manager._backoff.check_allowed("dead-config")  # the breaker for that server is reset
        assert manager.refresh_server_auth("unknown", {"Authorization": "x"}) is False


class TestLoopBoundPrimitives:
    def test_without_a_running_loop_nothing_is_bound_yet(self, manager: MCPConnectionManager) -> None:
        manager._sync_loop_primitives()

        assert manager._create_lock_loop is None
        assert manager._get_create_lock() is manager._create_lock
        assert isinstance(manager._get_spawn_semaphore(), asyncio.Semaphore)

    @pytest.mark.asyncio
    async def test_create_locks_are_per_config_hash(self, manager: MCPConnectionManager) -> None:
        assert manager._get_create_lock("a") is manager._get_create_lock("a")
        assert manager._get_create_lock("a") is not manager._get_create_lock("b")

    def test_primitives_are_rebuilt_when_the_event_loop_changes(self, manager: MCPConnectionManager) -> None:
        async def snapshot() -> tuple[asyncio.Lock, asyncio.Semaphore]:
            return manager._get_create_lock("a"), manager._get_spawn_semaphore()

        first_lock, first_semaphore = asyncio.run(snapshot())
        second_lock, second_semaphore = asyncio.run(snapshot())

        assert second_lock is not first_lock
        assert second_semaphore is not first_semaphore


class TestCleanupSweeper:
    @pytest.mark.asyncio
    async def test_a_dead_sweeper_task_is_restarted_and_a_live_one_is_left_alone(
        self, manager: MCPConnectionManager
    ) -> None:
        manager._ensure_cleanup_running()
        assert manager._cleanup_task is None  # not started: nothing to restart

        await manager.start()
        try:
            dead = manager._cleanup_task
            assert dead is not None
            dead.cancel()
            with suppress(asyncio.CancelledError):
                await dead

            manager._ensure_cleanup_running()
            revived = manager._cleanup_task
            assert revived is not dead
            assert revived is not None
            assert not revived.done()

            manager._ensure_cleanup_running()
            assert manager._cleanup_task is revived
        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_cancellation_ends_the_sweeper_loop_cleanly(self, manager: MCPConnectionManager) -> None:
        await manager.start()
        task = manager._cleanup_task
        assert task is not None
        await asyncio.sleep(0)  # let the loop reach its sleep

        task.cancel()
        await task

        assert task.done()
        assert not task.cancelled()  # the loop treats cancellation as a normal exit
        await manager.stop()

    @pytest.mark.asyncio
    async def test_a_failing_sweep_does_not_stop_later_sweeps(self) -> None:
        manager = MCPConnectionManager(ttl=600, cleanup_interval=0.01)
        sweeps = 0
        second_sweep = asyncio.Event()

        async def flaky_sweep() -> None:
            nonlocal sweeps
            sweeps += 1
            if sweeps == 1:
                raise RuntimeError("sweep failed")
            second_sweep.set()

        with patch.object(manager, "_cleanup_expired", flaky_sweep):
            await manager.start()
            try:
                await asyncio.wait_for(second_sweep.wait(), timeout=5.0)
            finally:
                await manager.stop()

        assert sweeps >= 2


@pytest.mark.asyncio
async def test_get_mcp_connection_acquires_through_the_singleton_pool() -> None:
    conn = _warm_connection("h", "srv")
    pool = MagicMock()
    pool.get_connection = AsyncMock(return_value=conn)
    config = [_cfg("srv")]

    with patch.object(cm_module, "get_mcp_connection_manager", AsyncMock(return_value=pool)):
        assert await get_mcp_connection(config) is conn

    pool.get_connection.assert_awaited_once_with(config)
