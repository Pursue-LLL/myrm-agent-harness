"""Live integration: real MCP server → skill generation → virtual /mcp/ doc read.

Exercises the production progressive-disclosure chain without mocks:

1. Boot a real streamable-http MCP server (4 tools > threshold 3).
2. Connect through ``MCPConnectionManager`` (real wire protocol).
3. Generate SkillMetadata from the real tools.
4. ``generate_skill_content`` — SKILL.md must carry the conditional
   ``timeout=120`` wording (prompt fix B), never the old "Always set".
5. ``MCPFileSystemStrategy.read_file`` over ``/mcp/...`` — doc must include
   the MCP Function Call Rules whose example code references ``result`` only
   (prompt fix A), plus a live ``conn.call`` to prove the wire path.
"""

from __future__ import annotations

import asyncio
import socket
from contextlib import suppress

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.strategies.mcp_strategy import (
    MCPFileSystemStrategy,
)
from myrm_agent_harness.agent.skills.mcp.core_generator import MCPSkillGenerator
from myrm_agent_harness.toolkits.mcp.config import MCPConfig
from myrm_agent_harness.toolkits.mcp.connection_manager import MCPConnectionManager


def _make_server_app():
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("live-skill-probe")

    @server.tool()
    def echo(text: str) -> str:
        return f"echo:{text}"

    @server.tool()
    def add(a: int, b: int) -> int:
        return a + b

    @server.tool()
    def multiply(a: int, b: int) -> int:
        return a * b

    @server.tool()
    def get_status() -> str:
        return "ok"

    return server.streamable_http_app()


async def _start_live_server() -> tuple[object, str]:
    import uvicorn

    app = _make_server_app()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    runner = uvicorn.Server(config)
    serve_task = asyncio.create_task(runner.serve(sockets=[sock]))
    for _ in range(200):
        if runner.started:
            break
        await asyncio.sleep(0.05)
    assert runner.started, "streamable-http server failed to start"

    async def teardown() -> None:
        runner.should_exit = True
        with suppress(Exception):
            await serve_task

    return teardown, f"http://127.0.0.1:{port}/mcp"


@pytest.fixture
def _reset_manager() -> object:
    MCPConnectionManager._instance = None
    yield
    MCPConnectionManager._instance = None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_skill_gen_live_chain_prompt_fixes(_reset_manager: object) -> None:
    teardown, url = await _start_live_server()
    try:
        cfg = MCPConfig(name="livesrv", type="streamable_http", url=url)
        manager = MCPConnectionManager()
        conn = await manager.get_connection([cfg])
        assert conn is not None
        tools = conn.tools_by_server.get("livesrv")
        assert tools is not None and len(tools) == 4

        # Real wire call proves the transport is live (no mocks on this path).
        echo_out = await conn.call("livesrv", "echo", {"text": "hello"})
        assert "echo:hello" in str(echo_out)

        # --- Build SkillMetadata from the real tools ---
        generator = MCPSkillGenerator()
        skill_meta = generator._create_skill_metadata(
            "livesrv", tools, user_description="live skill probe"
        )
        assert skill_meta.is_mcp_skill is True
        assert len(skill_meta.mcp.tools) == 4

        # --- Level 2 SKILL.md: prompt fix B (conditional timeout) ---
        content = generator.generate_skill_content(skill_meta)
        assert "Usage Guide" in content  # 4 tools > threshold 3
        assert (
            "If a tool doc declares a `timeout` parameter, set `timeout=120`" in content
        )
        assert "Always set" not in content

        # --- Level 3 doc via MCPFileSystemStrategy: prompt fix A ---
        skill_name = skill_meta.name
        strategy = MCPFileSystemStrategy([skill_meta])
        lines = await strategy.read_file(f"/mcp/{skill_name}/echo.md")
        joined = "\n".join(lines)
        assert "MCP Function Call Rules" in joined
        # Fix A: the generic example (last code block) resolves through `result`.
        assert 'print(f"[OBSERVATION] {result}")' in joined
        example_block = joined.split("```python")[-1].split("```")[0]
        assert "{variable}" not in example_block
        assert "result = await function_name(param1=" in example_block
    finally:
        await teardown()
