"""Security properties of the MCP IPC transport.

The socket sits in a shared temp directory on a multi-user host. World-writable
permissions plus a client-supplied ``session_id`` let any local process inject
``notify`` events into someone else's conversation. These tests pin the three
properties that make that impossible:

1. the socket is owner-only (0600) inside a 0700 directory;
2. a request must carry the per-process bearer token;
3. a session cannot exceed its tool-call budget.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Unix socket semantics")

from myrm_agent_harness.agent.skills.mcp.ipc_proxy import MCPIPCServer
from myrm_agent_harness.core.network.ipc_socket import default_ipc_socket_path


def _stats(path: str) -> os.stat_result:
    return os.stat(path)


def test_socket_is_owner_only_inside_private_dir() -> None:
    socket_path = default_ipc_socket_path()

    async def _run() -> None:
        server = MCPIPCServer(socket_path)
        await server.start()
        try:
            dir_mode = stat.S_IMODE(_stats(os.path.dirname(socket_path)).st_mode)
            sock_mode = stat.S_IMODE(_stats(socket_path).st_mode)
            assert sock_mode == 0o600, f"socket mode {oct(sock_mode)} must be owner-only"
            assert dir_mode == 0o700, f"dir mode {oct(dir_mode)} must be owner-only"
        finally:
            await server.stop()

    asyncio.run(_run())


def test_socket_path_is_not_the_shared_default() -> None:
    """A predictable shared path lets another local user pre-create the socket."""
    assert default_ipc_socket_path() != "/tmp/myrm-agent-mcp/mcp.sock"
    assert str(os.getpid()) in default_ipc_socket_path()


def test_request_without_token_is_rejected() -> None:
    async def _run() -> dict[str, object]:
        server = MCPIPCServer(default_ipc_socket_path())
        await server.start()
        try:
            payload = json.dumps(
                {"skill_name": "__builtin__", "tool_name": "notify", "params": {}, "session_id": "victim"}
            ).encode()
            reader, writer = await asyncio.open_unix_connection(server.socket_path)
            writer.write(len(payload).to_bytes(4, "big") + payload)
            await writer.drain()
            size = int.from_bytes(await reader.readexactly(4), "big")
            body = json.loads(await reader.readexactly(size))
            writer.close()
            await writer.wait_closed()
            return body
        finally:
            await server.stop()

    body = asyncio.run(_run())
    assert body["success"] is False
    assert "unauthorized" in str(body["error"]).lower()


def test_request_with_wrong_token_is_rejected() -> None:
    async def _run() -> dict[str, object]:
        server = MCPIPCServer(default_ipc_socket_path())
        await server.start()
        try:
            payload = json.dumps(
                {
                    "skill_name": "__builtin__",
                    "tool_name": "notify",
                    "params": {},
                    "session_id": "victim",
                    "auth_token": "not-the-token",
                }
            ).encode()
            reader, writer = await asyncio.open_unix_connection(server.socket_path)
            writer.write(len(payload).to_bytes(4, "big") + payload)
            await writer.drain()
            size = int.from_bytes(await reader.readexactly(4), "big")
            body = json.loads(await reader.readexactly(size))
            writer.close()
            await writer.wait_closed()
            return body
        finally:
            await server.stop()

    body = asyncio.run(_run())
    assert body["success"] is False
    assert "unauthorized" in str(body["error"]).lower()


def test_call_budget_is_enforced_per_session() -> None:
    async def _run() -> list[dict[str, object]]:
        server = MCPIPCServer(default_ipc_socket_path(), max_calls_per_session=2)
        await server.start()
        try:
            token = server.auth_token
            reader, writer = await asyncio.open_unix_connection(server.socket_path)
            responses: list[dict[str, object]] = []
            for index in range(3):
                payload = json.dumps(
                    {
                        "skill_name": "__builtin__",
                        "tool_name": "notify",
                        "params": {"message": f"m{index}"},
                        "session_id": "s1",
                        "auth_token": token,
                    }
                ).encode()
                writer.write(len(payload).to_bytes(4, "big") + payload)
                await writer.drain()
                size = int.from_bytes(await reader.readexactly(4), "big")
                responses.append(json.loads(await reader.readexactly(size)))
            writer.close()
            await writer.wait_closed()
            return responses
        finally:
            await server.stop()

    responses = asyncio.run(_run())
    assert responses[0]["success"] is True
    assert responses[1]["success"] is True
    assert responses[2]["success"] is False
    assert "budget" in str(responses[2]["error"]).lower()


def _request_once(server: MCPIPCServer, body: dict[str, object]) -> dict[str, object]:
    async def _run() -> dict[str, object]:
        await server.start()
        try:
            payload = json.dumps({**body, "auth_token": server.auth_token}).encode()
            reader, writer = await asyncio.open_unix_connection(server.socket_path)
            writer.write(len(payload).to_bytes(4, "big") + payload)
            await writer.drain()
            size = int.from_bytes(await reader.readexactly(4), "big")
            result = json.loads(await reader.readexactly(size))
            writer.close()
            await writer.wait_closed()
            return result
        finally:
            await server.stop()

    return asyncio.run(_run())


def _register_mcp_tool(*, read_only: bool) -> None:
    from myrm_agent_harness.core.security.tool_registry.registry import (
        register_ptc_safety_metadata,
    )
    from myrm_agent_harness.core.security.tool_registry.safety_table import SafetyMetadata

    register_ptc_safety_metadata(
        "mcp_demo_skill",
        "create-record",
        SafetyMetadata(is_read_only=read_only),
        {"readOnlyHint": read_only},
    )


def test_read_only_scope_blocks_mutating_mcp_tool() -> None:
    """A read-only verifier must not mutate external state through a script."""
    _register_mcp_tool(read_only=False)
    server = MCPIPCServer(default_ipc_socket_path())

    body = _request_once(
        server,
        {
            "skill_name": "mcp_demo_skill",
            "tool_name": "create-record",
            "params": {},
            "session_id": "s1",
            "readonly_workspace": True,
        },
    )

    assert body["success"] is False
    assert "read-only" in str(body["error"]).lower()


def test_read_only_scope_allows_read_only_mcp_tool() -> None:
    """readOnlyHint tools remain usable inside a read-only sandbox."""
    _register_mcp_tool(read_only=True)
    server = MCPIPCServer(default_ipc_socket_path())

    body = _request_once(
        server,
        {
            "skill_name": "mcp_demo_skill",
            "tool_name": "create-record",
            "params": {},
            "session_id": "s1",
            "readonly_workspace": True,
        },
    )

    # The tool has no real MCP config registered, so dispatch fails on lookup;
    # what matters is that the policy gate let the call through.
    assert "read-only" not in str(body.get("error") or "").lower()


def test_call_budget_matches_track_two() -> None:
    """Both PTC tracks must expose one number, not two independent guesses.

    A second, arbitrary ceiling makes the next reader ask why they differ and gives
    one track a looser bound than the other for no stated reason.
    """
    from myrm_agent_harness.agent.skills.mcp.ipc_proxy import (
        DEFAULT_MAX_CALLS_PER_SESSION,
    )
    from myrm_agent_harness.toolkits.code_execution.ptc.models import PtcConfig

    assert PtcConfig.model_fields["max_tool_calls"].default == DEFAULT_MAX_CALLS_PER_SESSION


def test_ipc_path_policy_blocks_path_outside_workspace() -> None:
    """Path policy must block path traversal outside the workspace in IPC calls."""
    server = MCPIPCServer(default_ipc_socket_path())
    body = _request_once(
        server,
        {
            "skill_name": "__builtin__",
            "tool_name": "notify",
            "params": {"path": "/etc/passwd"},
            "session_id": "s1",
            "workspace_root": "/safe/workspace",
        },
    )
    assert body["success"] is False
    assert "path policy" in str(body["error"]).lower()


def test_ipc_client_carries_agent_id_separately_from_session_id() -> None:
    """Agent scope policies are keyed by agent_id, not by the user/chat session id."""
    from myrm_agent_harness.agent.skills.mcp.client_templates import generate_ipc_client_code

    code = generate_ipc_client_code("/tmp/agent.sock", session_id="user-1_chat-1", agent_id="restricted_agent")

    assert '_AGENT_ID = "restricted_agent"' in code
    assert '_SESSION_ID = "user-1_chat-1"' in code
    assert '"agent_id": _AGENT_ID' in code


def test_ipc_scope_gate_enforces_agent_allowlist() -> None:
    """Agent scope gate must block unapproved MCP tools for restricted agents."""
    from myrm_agent_harness.agent.sub_agents.mcp_scope_gate.scope_gate import (
        EmployeeScopedMcpDiscoveryGate,
    )
    from myrm_agent_harness.agent.sub_agents.mcp_scope_gate.types import (
        EmployeeToolScopePolicy,
    )

    gate = EmployeeScopedMcpDiscoveryGate.get_instance()
    gate.register_policy(
        EmployeeToolScopePolicy(
            agent_id="restricted_agent",
            allowed_mcp_servers=["12306"],
        )
    )

    server = MCPIPCServer(default_ipc_socket_path())
    body = _request_once(
        server,
        {
            "skill_name": "mcp_github_skill",
            "tool_name": "read_file",
            "params": {},
            "session_id": "user-1_chat-1",
            "agent_id": "restricted_agent",
        },
    )
    assert body["success"] is False
    assert "agent scope" in str(body["error"]).lower()
