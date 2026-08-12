"""RuntimePool MCP passthrough tests."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.acp.runtime.cli_runtime import CliRuntime
from myrm_agent_harness.toolkits.acp.runtime.pool import RuntimePool
from myrm_agent_harness.toolkits.acp.types import (
    BackendCapabilities,
    McpServerConfig,
    RuntimeConfig,
    RuntimeEventType,
    create_event,
)


@pytest.mark.asyncio
async def test_run_turn_forwards_config_mcp_servers_to_backend() -> None:
    pool = RuntimePool(max_concurrent=1)
    pool.register(
        "codex",
        RuntimeConfig(
            backend_type="cli",
            command="codex",
            mcp_servers=[McpServerConfig(name="fs", command="mcp-fs", args=["--ro"])],
        ),
    )

    backend = MagicMock()
    backend.capabilities = BackendCapabilities(supports_mcp=True)

    async def fake_run_turn(
        prompt: str,
        session_id: str,
        *,
        mcp_servers: list[McpServerConfig] | None = None,
    ):
        assert mcp_servers is not None
        assert len(mcp_servers) == 1
        assert mcp_servers[0].name == "fs"
        yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

    backend.run_turn = fake_run_turn
    pool.get = MagicMock(return_value=backend)

    events = [event async for event in pool.run_turn("codex", "hello", session_id="codex-default")]
    assert events[-1].type == RuntimeEventType.DONE


@pytest.mark.asyncio
async def test_run_turn_explicit_mcp_overrides_config() -> None:
    pool = RuntimePool(max_concurrent=1)
    pool.register("claude", RuntimeConfig(backend_type="cli", command="claude"))

    backend = MagicMock()
    backend.capabilities = BackendCapabilities(supports_mcp=True)
    captured: list[list[McpServerConfig] | None] = []

    async def fake_run_turn(
        prompt: str,
        session_id: str,
        *,
        mcp_servers: list[McpServerConfig] | None = None,
    ):
        captured.append(mcp_servers)
        yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

    backend.run_turn = fake_run_turn
    pool.get = MagicMock(return_value=backend)

    override = [McpServerConfig(name="x", command="cmd", args=[])]
    async for _ in pool.run_turn(
        "claude",
        "hi",
        session_id="claude-default",
        mcp_servers=override,
    ):
        pass

    assert captured == [override]


@pytest.mark.asyncio
async def test_run_turn_serializes_same_backend_concurrent_turns() -> None:
    """Concurrent turns on the same backend must never overlap.

    Regression: a single RuntimeBackend instance (e.g. CliRuntime) holds
    mutable per-turn state (active process handle). Without a per-backend
    lock, two concurrent turns overwrite that handle and mix up process
    state (cancel target / stderr / wait).
    """
    pool = RuntimePool(max_concurrent=2)
    pool.register("claude", RuntimeConfig(backend_type="cli", command="claude"))

    backend = MagicMock()
    active = 0
    peak_active = 0

    async def fake_run_turn(
        prompt: str,
        session_id: str,
        *,
        mcp_servers: list[McpServerConfig] | None = None,
    ):
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        await asyncio.sleep(0.02)
        yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")
        active -= 1

    backend.run_turn = fake_run_turn
    pool.get = MagicMock(return_value=backend)

    async def consume(session_id: str) -> None:
        async for _ in pool.run_turn("claude", "hello", session_id=session_id):
            pass

    await asyncio.gather(consume("s1"), consume("s2"))
    assert peak_active == 1, "same-backend turns must run strictly sequentially"


@pytest.mark.asyncio
async def test_run_turn_allows_parallel_different_backends() -> None:
    """Concurrent turns on different backends must run in parallel.

    The per-backend lock must serialize turns only within one backend instance;
    unrelated backends share the global semaphore but never block each other.
    """
    pool = RuntimePool(max_concurrent=2)
    pool.register("claude", RuntimeConfig(backend_type="cli", command="claude"))
    pool.register("codex", RuntimeConfig(backend_type="cli", command="codex"))

    backend_a = MagicMock()
    backend_b = MagicMock()
    active = 0
    peak_active = 0

    def _make_fake_run_turn() -> object:
        async def fake_run_turn(
            prompt: str,
            session_id: str,
            *,
            mcp_servers: list[McpServerConfig] | None = None,
        ):
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            await asyncio.sleep(0.02)
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")
            active -= 1

        return fake_run_turn

    backend_a.run_turn = _make_fake_run_turn()  # type: ignore[method-assign]
    backend_b.run_turn = _make_fake_run_turn()  # type: ignore[method-assign]
    pool.get = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda name: {"claude": backend_a, "codex": backend_b}[name]
    )

    async def consume(name: str) -> None:
        async for _ in pool.run_turn(name, "hello", session_id=f"s-{name}"):
            pass

    await asyncio.gather(consume("claude"), consume("codex"))
    assert peak_active == 2, "different-backend turns must run in parallel"


@pytest.mark.asyncio
async def test_run_turn_skips_mcp_for_unsupported_backend() -> None:
    """MCP servers must not reach a backend whose capabilities declare no MCP support."""
    pool = RuntimePool(max_concurrent=1)
    pool.register("codex", RuntimeConfig(backend_type="cli", command="codex"))
    config = pool.get_config("codex")
    assert config is not None

    rt = CliRuntime("codex", config)
    captured: list[list[McpServerConfig] | None] = []

    async def fake_run_turn(
        prompt: str,
        session_id: str,
        *,
        mcp_servers: list[McpServerConfig] | None = None,
    ):
        captured.append(mcp_servers)
        yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

    rt.run_turn = fake_run_turn  # type: ignore[method-assign]
    pool.get = MagicMock(return_value=rt)

    override = [McpServerConfig(name="fs", command="mcp-fs", args=["--ro"])]
    async for _ in pool.run_turn(
        "codex",
        "hello",
        session_id="codex-default",
        mcp_servers=override,
    ):
        pass

    assert captured == [None], "unsupported backend must receive no mcp_servers"


@pytest.mark.asyncio
async def test_run_turn_skips_config_mcp_for_unsupported_backend() -> None:
    """Config-level mcp_servers are also dropped for unsupported backends."""
    pool = RuntimePool(max_concurrent=1)
    pool.register(
        "codex",
        RuntimeConfig(
            backend_type="cli",
            command="codex",
            mcp_servers=[McpServerConfig(name="fs", command="mcp-fs", args=["--ro"])],
        ),
    )
    config = pool.get_config("codex")
    assert config is not None

    rt = CliRuntime("codex", config)
    captured: list[list[McpServerConfig] | None] = []

    async def fake_run_turn(
        prompt: str,
        session_id: str,
        *,
        mcp_servers: list[McpServerConfig] | None = None,
    ):
        captured.append(mcp_servers)
        yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

    rt.run_turn = fake_run_turn  # type: ignore[method-assign]
    pool.get = MagicMock(return_value=rt)

    async for _ in pool.run_turn("codex", "hello", session_id="codex-default"):
        pass

    assert captured == [None], "unsupported backend must not receive config mcp_servers"
