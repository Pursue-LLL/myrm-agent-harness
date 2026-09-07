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
