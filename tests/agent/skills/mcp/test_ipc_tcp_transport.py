"""Track 1 的 loopback TCP transport（非 POSIX 平台路径）。

Windows 上 asyncio 默认 ProactorEventLoop 不实现 ``create_unix_connection``，
所以 Track 1 必须有 TCP 分支，否则 MCP PTC 在这些平台上完全不可用。

这里的用例直接在 TCP 模式下启服务、走真实 socket 请求，验证三件事：
1. 端口真的绑上了，且可通过 loopback 连
2. 鉴权在这个 transport 上同样生效（不能因为换了通道就漏掉 token 校验）
3. 生成的客户端代码在 TCP 模式下走 ``open_connection`` 而不是 ``open_unix_connection``
"""

from __future__ import annotations

import ast
import asyncio
import json
from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.skills.mcp import ipc_proxy
from myrm_agent_harness.agent.skills.mcp.client_templates import generate_ipc_client_code
from myrm_agent_harness.agent.skills.mcp.ipc_proxy import MCPIPCServer


def _tcp_request(port: int, token: str | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "skill_name": "__builtin__",
        "tool_name": "notify",
        "params": {"message": "probe"},
        "trace_id": "t",
        "session_id": "s",
    }
    if token is not None:
        payload["auth_token"] = token
    return payload


async def _call(port: int, payload: dict[str, object]) -> dict[str, object]:
    data = json.dumps(payload).encode()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(len(data).to_bytes(4, "big") + data)
        await writer.drain()
        length = int.from_bytes(await reader.readexactly(4), "big")
        return json.loads((await reader.readexactly(length)).decode())
    finally:
        writer.close()
        await writer.wait_closed()


class TestTcpTransport:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture()
    async def tcp_server(self):
        """Run the server as if on a platform without AF_UNIX streams."""
        with patch.object(ipc_proxy.os_compat, "IS_WIN", True):
            server = MCPIPCServer("/tmp/tcp_transport_never_used.sock")
            await server.start()
            try:
                yield server
            finally:
                await server.stop()

    async def test_binds_a_loopback_port(self, tcp_server: MCPIPCServer) -> None:
        assert tcp_server.tcp_port > 0

    async def test_authenticated_call_succeeds(self, tcp_server: MCPIPCServer) -> None:
        response = await _call(tcp_server.tcp_port, _tcp_request(tcp_server.tcp_port, tcp_server.auth_token))
        # notify without a live run cannot emit an event, but the request itself must be
        # authorized — an auth failure surfaces as "Unauthorized".
        assert "Unauthorized" not in str(response.get("error") or "")

    async def test_missing_token_is_rejected(self, tcp_server: MCPIPCServer) -> None:
        response = await _call(tcp_server.tcp_port, _tcp_request(tcp_server.tcp_port, None))
        assert "unauthorized" in str(response.get("error") or "").lower()

    async def test_wrong_token_is_rejected(self, tcp_server: MCPIPCServer) -> None:
        response = await _call(tcp_server.tcp_port, _tcp_request(tcp_server.tcp_port, "wrong"))
        assert "unauthorized" in str(response.get("error") or "").lower()


class TestGeneratedClientChoosesTransport:
    def test_tcp_port_switches_to_open_connection(self) -> None:
        code = generate_ipc_client_code("/tmp/x.sock", auth_token="t", tcp_port=12345)
        assert "_TCP_PORT = 12345" in code
        assert 'asyncio.open_connection("127.0.0.1", _TCP_PORT)' in code
        ast.parse(code)

    def test_zero_port_keeps_unix_transport(self) -> None:
        code = generate_ipc_client_code("/tmp/x.sock", auth_token="t", tcp_port=0)
        assert "_TCP_PORT = 0" in code
        assert "open_unix_connection(_SOCKET_PATH)" in code
        ast.parse(code)
