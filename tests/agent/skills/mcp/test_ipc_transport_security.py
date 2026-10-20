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
from myrm_agent_harness.agent.skills.mcp.ipc_socket import default_ipc_socket_path


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
