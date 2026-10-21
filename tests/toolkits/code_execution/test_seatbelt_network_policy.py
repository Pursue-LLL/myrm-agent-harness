"""Seatbelt 禁网配置的真实行为。

这里断言的是**真的跑一遍 /usr/bin/sandbox-exec** 之后的观察结果，因为 SBPL 的
语义不能靠读字符串推断：

- `(local tcp)` / `(local udp)` 不覆盖 AF_UNIX，PTC 的 host UDS 需要
  `(local unix-socket)` 才能 `bind`/`connect`。
- `(deny default)` 下仅写 allow 规则不构成「拒绝出站」；必须显式
  `(deny network* (remote ip "*:*"))`。

这两个结论都先在本机手工复现过，再在这里固化，避免规则退化。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_execution.sandbox.providers.seatbelt import (
    _generate_sbpl_profile,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import SandboxPolicy

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or not os.path.isfile(SANDBOX_EXEC),
    reason="Seatbelt is macOS-only",
)


@pytest.fixture()
def unix_socket_server(tmp_path: Path):
    """Serve exactly one AF_UNIX connection, then stop."""
    # AF_UNIX sun_path caps at 104 bytes and tmp_path can exceed it, so build a short
    # path and hand the socket its own directory for the writable-path policy.
    import tempfile

    sock_dir = Path(tempfile.mkdtemp(prefix="sbx", dir="/tmp"))
    socket_path = sock_dir / "p.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)
    server.settimeout(15)

    result: dict[str, object] = {}

    def serve() -> None:
        try:
            conn, _ = server.accept()
            conn.sendall(b"OK")
            conn.close()
            result["accepted"] = True
        except OSError as exc:
            result["accepted"] = False
            result["error"] = exc

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield socket_path
    finally:
        thread.join(timeout=5)
        server.close()
        import shutil

        shutil.rmtree(sock_dir, ignore_errors=True)


def _run_in_sandbox(profile: str, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [SANDBOX_EXEC, "-f", profile, sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _write_profile(tmp_path: Path, *, allow_network: bool) -> str:
    profile = _generate_sbpl_profile(
        SandboxPolicy(writable_paths=(str(tmp_path),), allow_network=allow_network),
        str(tmp_path),
    )
    path = tmp_path / "policy.sb"
    path.write_text(profile, encoding="utf-8")
    return str(path)


def _free_port() -> int:
    """Pick a loopback port nothing else is listening on."""
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


_CONNECT_SCRIPT = """
import socket, sys
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.settimeout(3)
try:
    sock.connect(sys.argv[1])
    print("CONNECT_OK", sock.recv(16).decode())
except OSError as exc:
    print(f"CONNECT_FAIL {type(exc).__name__}")
finally:
    sock.close()
"""


class TestUnixSocketReachability:
    def test_blocked_network_still_reaches_unix_socket(
        self, tmp_path: Path, unix_socket_server: Path
    ) -> None:
        """A no-network policy must not sever the PTC channel."""
        script = tmp_path / "connect.py"
        script.write_text(_CONNECT_SCRIPT, encoding="utf-8")
        profile = _write_profile(tmp_path, allow_network=False)

        proc = _run_in_sandbox(profile, script, str(unix_socket_server))

        assert "CONNECT_OK OK" in proc.stdout

    def test_profile_explicitly_allows_unix_sockets(self, tmp_path: Path) -> None:
        profile = _write_profile(tmp_path, allow_network=False)
        content = Path(profile).read_text(encoding="utf-8")
        assert "(local unix-socket)" in content


class TestEgressBlocked:
    def test_external_connection_is_denied_when_network_blocked(self, tmp_path: Path) -> None:
        """The deny must actually bite, not just be expressed as an allow-list."""
        script = tmp_path / "egress.py"
        script.write_text(
            "import socket\n"
            "s = socket.socket()\n"
            "s.settimeout(2)\n"
            "try:\n"
            "    s.connect(('1.1.1.1', 53))\n"
            "    print('TCP_OK')\n"
            "except OSError as exc:\n"
            "    print(f'BLOCKED {type(exc).__name__}')\n"
            "finally:\n"
            "    s.close()\n",
            encoding="utf-8",
        )
        profile = _write_profile(tmp_path, allow_network=False)

        proc = _run_in_sandbox(profile, script)

        assert "BLOCKED" in proc.stdout
        assert "TCP_OK" not in proc.stdout

    def test_network_allowed_mode_is_unaffected(self, tmp_path: Path) -> None:
        profile = _write_profile(tmp_path, allow_network=True)
        content = Path(profile).read_text(encoding="utf-8")
        assert "(allow network*)" in content
        assert '(deny network* (remote ip "*:*"))' not in content


class TestLoopbackPreserved:
    """Sealing egress must not sever loopback.

    A blanket deny wins over an earlier allow in SBPL, so the loopback grant has to be
    repeated after the deny. Without this regression test the first fix silently broke
    localhost access while looking correct in the profile text.
    """

    def test_loopback_tcp_still_reachable(self, tmp_path: Path) -> None:
        port = _free_port()
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", port))
        server.listen(5)
        server.settimeout(15)

        def serve() -> None:
            try:
                while True:
                    conn, _ = server.accept()
                    conn.close()
            except OSError:
                pass

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            script = tmp_path / "loopback.py"
            script.write_text(
                "import socket, sys\n"
                "s = socket.socket()\n"
                "s.settimeout(3)\n"
                "try:\n"
                "    s.connect(('127.0.0.1', int(sys.argv[1])))\n"
                "    print('LOOPBACK_OK')\n"
                "except OSError as exc:\n"
                "    print(f'LOOPBACK_BLOCKED {type(exc).__name__}')\n"
                "finally:\n"
                "    s.close()\n",
                encoding="utf-8",
            )
            profile = _write_profile(tmp_path, allow_network=False)

            proc = _run_in_sandbox(profile, script, str(port))

            assert "LOOPBACK_OK" in proc.stdout
        finally:
            server.close()
            thread.join(timeout=5)


class TestWorkspaceWritesUnaffected:
    def test_writable_path_still_writable(self, tmp_path: Path, unix_socket_server: Path) -> None:
        script = tmp_path / "write.py"
        script.write_text(
            "import pathlib, sys\n"
            "pathlib.Path(sys.argv[1], 'out.txt').write_text('hi', encoding='utf-8')\n"
            "print('WROTE')\n",
            encoding="utf-8",
        )
        profile = _write_profile(tmp_path, allow_network=False)

        proc = _run_in_sandbox(profile, script, str(tmp_path))

        assert "WROTE" in proc.stdout
        assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hi"
