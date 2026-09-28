"""Unit tests for ssh_remote toolkit."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.ssh_remote import (
    SSHAuthType,
    SSHCommandResult,
    SSHHostSpec,
    SSHRemoteExecutor,
)


def test_ssh_host_spec_init() -> None:
    host = SSHHostSpec(
        host_id="gpu-node-1",
        hostname="192.168.1.100",
        port=2222,
        username="ubuntu",
        auth_type=SSHAuthType.PRIVATE_KEY,
        private_key="-----BEGIN OPENSSH PRIVATE KEY-----...",
    )
    assert host.host_id == "gpu-node-1"
    assert host.hostname == "192.168.1.100"
    assert host.port == 2222
    assert host.username == "ubuntu"
    assert host.auth_type == SSHAuthType.PRIVATE_KEY


def test_dangerous_command_blocking() -> None:
    executor = SSHRemoteExecutor()

    # Test safety checks
    safe_cmds = [
        "ls -la /var/log",
        "nvidia-smi",
        "docker ps",
        "cat /etc/os-release",
        "systemctl status nginx",
    ]
    for cmd in safe_cmds:
        is_safe, reason = executor.check_command_safety(cmd)
        assert is_safe is True
        assert reason == ""

    dangerous_cmds = [
        "rm -rf /",
        "rm -rf /*",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        ":(){ :|:& };:",
        "shutdown -h now",
    ]
    for cmd in dangerous_cmds:
        is_safe, reason = executor.check_command_safety(cmd)
        assert is_safe is False
        assert "dangerous" in reason.lower()


@pytest.mark.asyncio
async def test_execute_blocked_command_returns_result() -> None:
    executor = SSHRemoteExecutor()
    host = SSHHostSpec(host_id="test", hostname="127.0.0.1")

    res: SSHCommandResult = await executor.execute_command(host, "rm -rf /")
    assert res.exit_code == 126
    assert res.blocked_by_guard is True
    assert "[SECURITY BLOCKED]" in res.distilled_output


def test_command_safety_with_readonly_host() -> None:
    executor = SSHRemoteExecutor()
    ro_host = SSHHostSpec(host_id="ro-node", hostname="10.0.0.1", is_read_only=True)

    is_safe, reason = executor.check_command_safety("echo hello", host=ro_host)
    assert is_safe is True
    assert reason == ""

    is_safe_w, reason_w = executor.check_command_safety("touch /tmp/test", host=ro_host)
    assert is_safe_w is False
    assert "not in the read-only whitelist" in reason_w


@pytest.mark.asyncio
async def test_execute_readonly_violation_returns_structured_result() -> None:
    executor = SSHRemoteExecutor()
    ro_host = SSHHostSpec(host_id="ro-node", hostname="10.0.0.1", is_read_only=True)

    res = await executor.execute_command(ro_host, "echo foo > /tmp/bar")
    assert res.is_read_only_violation is True
    assert res.blocked_by_guard is True
    assert res.exit_code == 126
    assert "[READ-ONLY BLOCKED]" in res.distilled_output


@pytest.mark.asyncio
async def test_execute_command_asyncssh_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from unittest.mock import AsyncMock, MagicMock

    mock_asyncssh = MagicMock()
    mock_conn = MagicMock()
    mock_res = MagicMock()
    mock_res.stdout = "node-ready"
    mock_res.stderr = ""
    mock_res.exit_status = 0

    mock_conn.run = AsyncMock(return_value=mock_res)
    mock_asyncssh.connect = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock()))

    monkeypatch.setitem(sys.modules, "asyncssh", mock_asyncssh)

    executor = SSHRemoteExecutor()
    host = SSHHostSpec(
        host_id="node-1",
        hostname="192.168.1.1",
        auth_type=SSHAuthType.PASSWORD,
        password="secretpassword",
        private_key="keydata",
        passphrase="pass",
    )

    res = await executor.execute_command(host, "uname -a")
    assert res.exit_code == 0
    assert res.stdout == "node-ready"
    assert res.host_id == "node-1"


@pytest.mark.asyncio
async def test_execute_command_asyncssh_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from unittest.mock import AsyncMock, MagicMock

    mock_asyncssh = MagicMock()
    mock_conn = MagicMock()
    mock_conn.run = AsyncMock(side_effect=TimeoutError())
    mock_asyncssh.connect = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_conn), __aexit__=AsyncMock(return_value=False)))

    monkeypatch.setitem(sys.modules, "asyncssh", mock_asyncssh)

    executor = SSHRemoteExecutor()
    host = SSHHostSpec(host_id="node-timeout", hostname="192.168.1.1", timeout_seconds=1.0, is_read_only=False)

    res = await executor.execute_command(host, "sleep 10")
    assert res.is_timeout is True
    assert res.exit_code == 124
    assert "[TIMEOUT]" in res.distilled_output


@pytest.mark.asyncio
async def test_execute_command_asyncssh_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from unittest.mock import AsyncMock, MagicMock

    mock_asyncssh = MagicMock()
    mock_asyncssh.connect = MagicMock(side_effect=ConnectionRefusedError("Connection refused by peer"))
    monkeypatch.setitem(sys.modules, "asyncssh", mock_asyncssh)

    executor = SSHRemoteExecutor()
    host = SSHHostSpec(host_id="node-fail", hostname="192.168.1.1")

    res = await executor.execute_command(host, "ls")
    assert res.exit_code == 255
    assert "[SSH CONNECTION ERROR]" in res.distilled_output


@pytest.mark.asyncio
async def test_execute_subprocess_ssh_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"fallback-output\n", b""))
    mock_proc.returncode = 0

    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=mock_proc))

    executor = SSHRemoteExecutor()
    host = SSHHostSpec(host_id="node-fallback", hostname="10.0.0.2")

    res = await executor._execute_subprocess_ssh(host, "whoami", timeout=5.0, start_time=0.0)
    assert res.exit_code == 0
    assert "fallback-output" in res.stdout


@pytest.mark.asyncio
async def test_execute_subprocess_ssh_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        AsyncMock(side_effect=TimeoutError()),
    )

    executor = SSHRemoteExecutor()
    host = SSHHostSpec(host_id="node-sub-timeout", hostname="10.0.0.2")

    res = await executor._execute_subprocess_ssh(host, "sleep 100", timeout=2.0, start_time=0.0)
    assert res.is_timeout is True
    assert res.exit_code == 124
    assert "[TIMEOUT]" in res.distilled_output


@pytest.mark.asyncio
async def test_execute_subprocess_ssh_generic_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        AsyncMock(side_effect=OSError("ssh executable not found")),
    )

    executor = SSHRemoteExecutor()
    host = SSHHostSpec(host_id="node-sub-err", hostname="10.0.0.2")

    res = await executor._execute_subprocess_ssh(host, "ls", timeout=5.0, start_time=0.0)
    assert res.exit_code == 255
    assert "[SSH SUBPROCESS ERROR]" in res.distilled_output

