"""Integration proof: the warm-session pool spawns a stdio MCP **once** per server.

Unlike the unit tests (which stub transports), these spin up a *real* stdio MCP
subprocess via the production ``MCPConnectionManager`` and count process starts
through a side-channel file the server appends to on every launch. This is the
hard evidence for the core claim: N tool calls reuse one warm session instead of
re-spawning + re-initializing per call.
"""

from __future__ import annotations

import sys

import pytest

from myrm_agent_harness.toolkits.mcp.config import MCPConfig
from myrm_agent_harness.toolkits.mcp.connection_manager import MCPConnectionManager

# A minimal real MCP server: records each process launch (one line per spawn),
# then serves two trivial tools over stdio.
_PROBE_SERVER_SRC = '''
import sys
from pathlib import Path

# Record one line per process launch — the spawn counter.
Path(sys.argv[1]).open("a", encoding="utf-8").write("spawn\\n")

from mcp.server.fastmcp import FastMCP

server = FastMCP("spawn-probe")


@server.tool()
def echo(text: str) -> str:
    return f"echo:{text}"


@server.tool()
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    server.run(transport="stdio")
'''


def _count_spawns(spawn_log: object) -> int:
    text = spawn_log.read_text(encoding="utf-8") if spawn_log.exists() else ""
    return len([line for line in text.splitlines() if line.strip()])


@pytest.fixture
def _reset_manager() -> object:
    MCPConnectionManager._instance = None
    yield
    MCPConnectionManager._instance = None


@pytest.mark.asyncio
async def test_stdio_session_reused_single_spawn(tmp_path, _reset_manager: object) -> None:
    script = tmp_path / "probe_server.py"
    script.write_text(_PROBE_SERVER_SRC, encoding="utf-8")
    spawn_log = tmp_path / "spawns.log"

    cfg = MCPConfig(
        name="spawnprobe",
        type="stdio",
        command=sys.executable,
        args=[str(script), str(spawn_log)],
        description="spawn probe",
        connect_timeout=30.0,
    )

    manager = await MCPConnectionManager.get_instance()
    try:
        conn = await manager.get_connection([cfg])

        # Many calls on the same warm session.
        for i in range(5):
            result = await conn.call("spawnprobe", "echo", {"text": str(i)})
            assert f"echo:{i}" in str(result)

        # A second acquisition reuses the same warm connection (no new spawn).
        conn2 = await manager.get_connection([cfg])
        assert conn2 is conn
        assert "5" in str(await conn2.call("spawnprobe", "add", {"a": 2, "b": 3}))

        spawns = _count_spawns(spawn_log)
        assert spawns == 1, f"expected exactly 1 subprocess spawn, got {spawns}"
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_distinct_args_do_not_share_session(
    tmp_path, _reset_manager: object
) -> None:
    script = tmp_path / "probe_server.py"
    script.write_text(_PROBE_SERVER_SRC, encoding="utf-8")
    spawn_log = tmp_path / "spawns.log"

    base = {
        "name": "spawnprobe",
        "type": "stdio",
        "command": sys.executable,
        "description": "spawn probe",
        "connect_timeout": 30.0,
    }
    cfg_a = MCPConfig(args=[str(script), str(spawn_log)], **base)
    cfg_b = MCPConfig(args=[str(script), str(spawn_log), "variant-b"], **base)

    manager = await MCPConnectionManager.get_instance()
    try:
        conn_a = await manager.get_connection([cfg_a])
        conn_b = await manager.get_connection([cfg_b])

        # Differing args must not collide onto one pooled connection.
        assert conn_a is not conn_b
        assert "echo:a" in str(await conn_a.call("spawnprobe", "echo", {"text": "a"}))
        assert "echo:b" in str(await conn_b.call("spawnprobe", "echo", {"text": "b"}))

        spawns = _count_spawns(spawn_log)
        assert spawns == 2, f"expected 2 distinct spawns, got {spawns}"
    finally:
        await manager.stop()
