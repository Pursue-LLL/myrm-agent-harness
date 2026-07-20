"""RuntimePool MCP passthrough tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.acp.runtime.pool import RuntimePool
from myrm_agent_harness.toolkits.acp.types import McpServerConfig, RuntimeConfig, RuntimeEventType, create_event


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
