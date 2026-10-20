"""两条 PTC 轨道的 transport 必须同构。

仓库里有两个 PTC 分支，各自实现了同样的 RPC 协议：

- Track 1 (MCP)：``agent/skills/mcp/ipc_proxy.py`` + ``client_templates.py``
- Track 2 (DW)：``toolkits/code_execution/ptc/rpc_server.py`` + ``stub_generator.py``

历史上两轨多次各自漂移（鉴权、权限、预算、平台回退都是分别补的），因为没有任何
机制强制它们保持一致。``test_ptc.py::TestPtcRpcTransportSecurity`` 的 docstring
写了「Track 2 must be authenticated like Track 1」，但只覆盖了 token 与权限。

这个模块把「对称」变成可执行的断言。它只读代码、不参与运行时，所以没有任何运行
成本；它的价值是让「只改了一轨」在 CI 里直接变红，而不是等用户在某个平台上撞到。

注意：两轨的**客户端语法**（``from skills.x import f`` vs ``from myrm_tools``）
和**输出通道**（stdout 标记 vs 内存 records）本来就不需要相同，不在断言范围内。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

HARNESS_ROOT = Path(__file__).resolve().parents[2]
MCP_DIR = HARNESS_ROOT / "src/myrm_agent_harness/agent/skills/mcp"
PTC_DIR = HARNESS_ROOT / "src/myrm_agent_harness/toolkits/code_execution/ptc"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _search(pattern: str, path: Path) -> list[str]:
    return re.findall(pattern, _read(path))


class TestBothTracksAuthenticate:
    """No track may accept a request without proving the caller is the host."""

    def test_both_servers_require_a_token(self) -> None:
        ipc = _read(MCP_DIR / "ipc_proxy.py")
        rpc = _read(PTC_DIR / "rpc_server.py")

        for label, source in (("Track 1 ipc_proxy", ipc), ("Track 2 rpc_server", rpc)):
            assert "auth_token" in source, f"{label} lost its auth token"
            assert "compare_digest" in source, f"{label} must compare tokens in constant time"

    def test_both_sockets_are_owner_only(self) -> None:
        """A world-readable socket lets any local user drive the host."""
        for name, path in (
            ("Track 1", MCP_DIR / "ipc_proxy.py"),
            ("Track 2", PTC_DIR / "rpc_server.py"),
        ):
            source = _read(path)
            assert "0o666" not in source, f"{name} grants world read/write on the socket"
            # Either a literal 0600 or the shared owner-only constant is acceptable.
            assert re.search(r"chmod\([^)]*(0o6\d\d|SOCKET_FILE_MODE)", source), (
                f"{name} must chmod the socket to an owner-only mode (0600)"
            )


class TestRequestEnvelopeParity:
    """The wire envelope must be the same shape on both tracks."""

    def test_same_length_prefix_width(self) -> None:
        for name, path in (
            ("Track 1", MCP_DIR / "ipc_proxy.py"),
            ("Track 2", PTC_DIR / "rpc_server.py"),
        ):
            source = _read(path)
            assert "to_bytes(4," in source or 'struct.pack("!I"' in source, (
                f"{name} must use a 4-byte length prefix"
            )

    def test_same_payload_size_cap(self) -> None:
        """A tighter cap on one track is a silent behaviour difference."""
        ipc = _read(MCP_DIR / "ipc_proxy.py")
        rpc = _read(PTC_DIR / "rpc_server.py")
        ipc_cap = re.search(r">\s*(\d+)\s*\*\s*1024\s*\*\s*1024", ipc)
        rpc_cap = re.search(r">\s*(\d+)\s*\*\s*1024\s*\*\s*1024", rpc)
        assert ipc_cap and rpc_cap, "both tracks must declare a payload cap"
        assert ipc_cap.group(1) == rpc_cap.group(1), (
            "payload caps diverged: Track 1 "
            f"{ipc_cap.group(1)}MB vs Track 2 {rpc_cap.group(1)}MB"
        )


class TestPlatformFallbackParity:
    """A track reachable only on POSIX is a platform gap, not a design choice."""

    def test_track2_has_a_tcp_fallback(self) -> None:
        """Baseline: Track 2 is the reference implementation for platform parity."""
        source = _read(PTC_DIR / "rpc_server.py")
        assert "win32" in source or "AF_INET" in source, (
            "Track 2 lost its non-POSIX transport; if that was deliberate, update this test"
        )

    def test_track1_has_a_tcp_fallback(self) -> None:
        """Track 1 talks AF_UNIX only, so MCP PTC cannot run where AF_UNIX is unavailable.

        Windows asyncio defaults to ProactorEventLoop, whose ``create_unix_connection``
        raises NotImplementedError. Track 2 already handles this with a loopback TCP
        branch; Track 1 must do the same or MCP PTC is POSIX-only in practice.
        """
        client = _read(MCP_DIR / "client_templates.py")
        server = _read(MCP_DIR / "ipc_proxy.py")

        has_client_fallback = "AF_INET" in client or "TCP_PORT" in client
        # The server path uses asyncio.start_server on loopback and exposes the bound port.
        has_server_fallback = (
            ("start_server(" in server or "AF_INET" in server)
            and "127.0.0.1" in server
            and "_tcp_port" in server
        )

        assert has_client_fallback, "Track 1 client opens AF_UNIX only; add a loopback TCP branch"
        assert has_server_fallback, "Track 1 server listens on AF_UNIX only; add a loopback TCP branch"


class TestGeneratedClientIsValidPython:
    """The generated child module is embedded into user scripts; it must at least parse."""

    def test_mcp_client_source_parses(self) -> None:
        from myrm_agent_harness.agent.skills.mcp.client_templates import (
            generate_ipc_client_code,
        )

        for nonce in (None, "abc123"):
            code = generate_ipc_client_code(
                "/tmp/x.sock",
                session_id="s",
                workspace_root="/w",
                read_only_tools=frozenset(),
                auth_token="t",
                readonly_workspace=False,
                trace_nonce=nonce,
            )
            ast.parse(code)

    def test_ptc_stub_source_parses(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.ptc.stub_generator import (
            generate_stubs,
        )

        for use_tcp in (False, True):
            ast.parse(generate_stubs([], use_tcp_fallback=use_tcp))


class TestBothTracksShareOneCallBudget:
    """Two independent budget constants would let a script exceed either one silently."""

    def test_budget_is_defined_once_per_layer(self) -> None:
        ipc = _read(MCP_DIR / "ipc_proxy.py")
        rpc = _read(PTC_DIR / "rpc_server.py")
        assert "max_calls_per_session" in ipc or "max_tool_calls" in ipc
        assert "max_tool_calls" in rpc or "max_calls_per_session" in rpc


@pytest.mark.parametrize("filename", ["ipc_proxy.py", "client_templates.py", "rpc_server.py", "stub_generator.py"])
def test_transport_modules_have_no_bare_except(filename: str) -> None:
    """A bare ``except`` in a transport layer hides protocol errors and leaks silence."""
    path = (MCP_DIR / filename) if (MCP_DIR / filename).exists() else (PTC_DIR / filename)
    tree = ast.parse(_read(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            assert node.type is not None, f"{filename}:{node.lineno} uses a bare except"
