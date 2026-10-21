"""Retry policy for the generated MCP IPC client.

A connection failure can happen after the request reached the server, so replaying
a mutating call risks duplicate side effects (two issues, two messages). Only
tools advertising ``readOnlyHint`` may be retried.
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.agent.skills.mcp.client_templates import generate_ipc_client_code


def _build_client(*, read_only: frozenset[str], attempts: list[str]) -> dict[str, object]:
    """Compile the generated client and stub its transport with a counter."""
    source = generate_ipc_client_code(
        "/tmp/does-not-matter.sock",
        session_id="s1",
        workspace_root="/w",
        read_only_tools=read_only,
    )
    namespace: dict[str, object] = {}
    exec(compile(source, "<generated_client>", "exec"), namespace)  # noqa: S102 - executing our own generated module

    async def failing_request(skill: str, tool: str, params: dict[str, object]) -> object:
        attempts.append(f"{skill}.{tool}")
        raise ConnectionError("simulated mid-flight disconnect")

    namespace["_ipc_request"] = failing_request
    return namespace


def test_mutating_tool_is_not_retried() -> None:
    attempts: list[str] = []
    client = _build_client(read_only=frozenset(), attempts=attempts)

    with pytest.raises(Exception, match="Connection"):
        asyncio.run(client["_call"]("mcp_skill", "create-issue", {"title": "x"}))  # type: ignore[operator]

    assert attempts == ["mcp_skill.create-issue"], "a write must be attempted exactly once"


def test_read_only_tool_is_retried_once() -> None:
    attempts: list[str] = []
    client = _build_client(read_only=frozenset({"mcp_skill.ping"}), attempts=attempts)

    with pytest.raises(Exception, match="Failed after"):
        asyncio.run(client["_call"]("mcp_skill", "ping", {}))  # type: ignore[operator]

    assert attempts == ["mcp_skill.ping", "mcp_skill.ping"], "read-only may retry once"


def test_host_reported_error_is_never_retried() -> None:
    """A server-side error is deterministic; retrying cannot change the outcome."""
    attempts: list[str] = []
    client = _build_client(read_only=frozenset({"mcp_skill.ping"}), attempts=attempts)

    async def failing_request(skill: str, tool: str, params: dict[str, object]) -> object:
        attempts.append(f"{skill}.{tool}")
        raise client["MCPError"]("boom", skill, tool)  # type: ignore[operator]

    client["_ipc_request"] = failing_request

    with pytest.raises(Exception, match="boom"):
        asyncio.run(client["_call"]("mcp_skill", "ping", {}))  # type: ignore[operator]

    assert attempts == ["mcp_skill.ping"]
