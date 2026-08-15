"""Live-wire integration tests for SafeStructuredTool reserved-name handling.

Boots a real stdio MCP server whose tools declare arguments named ``config``
and ``run_manager`` (reserved keyword-only params in langchain-core
``BaseTool._arun``), then drives the *full* production path — proxy tool
``ainvoke`` → ``SafeStructuredTool._arun`` → actor queue → real wire
``call_tool`` — asserting the server actually receives the arguments. Nothing
is mocked on the wire path; only the LLM-produced argument dict is simulated.

Regression guard: before the SafeStructuredTool fix, langchain's
``StructuredTool._arun`` swallowed a ``config`` argument into its own keyword
parameter and the server rejected the call with ``Field required``.
"""

from __future__ import annotations

import sys

import pytest
import pytest_asyncio

from myrm_agent_harness.toolkits.mcp.session_actor import MCPSessionActor

_SERVER_SRC = """
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

server = MCPServer("fuzzy-reserved-probe")


@server.tool()
def apply_config(config: dict[str, Any], tags: list[str]) -> str:
    return f"config={config!r} tags={tags!r}"


@server.tool()
def manage(run_manager: dict[str, Any]) -> str:
    return f"run_manager={run_manager!r}"


if __name__ == "__main__":
    server.run(transport="stdio")
"""


@pytest_asyncio.fixture
async def _actor(tmp_path) -> object:
    """A live stdio MCP session exposing reserved-named tools via the actor."""
    script = tmp_path / "fuzzy_reserved_probe_server.py"
    script.write_text(_SERVER_SRC, encoding="utf-8")

    actor = MCPSessionActor(
        "fuzzy-reserved-probe",
        {"transport": "stdio", "command": sys.executable, "args": [str(script)]},
        connect_timeout=20.0,
    )
    await actor.start()
    try:
        yield actor
    finally:
        await actor.close()


@pytest.mark.asyncio
async def test_config_argument_reaches_server_via_proxy_ainvoke(_actor: object) -> None:
    """A ``config``-named tool argument survives proxy ainvoke end-to-end."""
    proxy = _find_tool(_actor, "apply_config")
    result = await proxy.ainvoke(
        {"config": {"env": "dev", "retention_days": 30}, "tags": ["ops"]}
    )
    assert isinstance(result, str)
    assert "config={'env': 'dev', 'retention_days': 30}" in result
    assert "tags=['ops']" in result


@pytest.mark.asyncio
async def test_config_fuzzy_object_fields_preserved(_actor: object) -> None:
    """Unknown nested fields inside a config object must arrive verbatim."""
    proxy = _find_tool(_actor, "apply_config")
    result = await proxy.ainvoke(
        {
            "config": {
                "known": 1,
                "unknown": {"deep": [1, 2], "flag": True},
                "extra": "keep",
            },
            "tags": ["dev"],
        }
    )
    assert isinstance(result, str)
    assert "'known': 1" in result
    assert "'flag': True" in result
    assert "'extra': 'keep'" in result


@pytest.mark.asyncio
async def test_run_manager_argument_reaches_server_via_proxy_ainvoke(_actor: object) -> None:
    """A ``run_manager``-named tool argument survives proxy ainvoke end-to-end."""
    proxy = _find_tool(_actor, "manage")
    result = await proxy.ainvoke({"run_manager": {"scope": "team"}})
    assert isinstance(result, str)
    assert "run_manager={'scope': 'team'}" in result


def _find_tool(actor: object, suffix: str) -> object:
    tools = actor.tools  # type: ignore[attr-defined]
    for tool in tools:
        if tool.name.endswith(f"__{suffix}"):
            return tool
    raise AssertionError(f"tool {suffix!r} not found in {[t.name for t in tools]}")
