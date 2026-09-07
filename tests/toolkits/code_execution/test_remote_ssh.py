"""Unit tests for Harness Remote SSH Execution Bridge."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.code_execution.remote_ssh import (
    RemoteSSHConfig,
    RemoteSSHExecutor,
    execute_remote_ssh_command,
)


@pytest.mark.asyncio
async def test_execute_remote_ssh_command_mock_success() -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"NVIDIA-SMI 550.54.14 Driver Version: 550.54.14", b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        exit_code, stdout, stderr, duration = await execute_remote_ssh_command(
            host="10.0.0.15",
            command="nvidia-smi",
            timeout_seconds=5,
            user="ubuntu",
        )

        assert exit_code == 0
        assert "NVIDIA-SMI" in stdout
        assert stderr == ""
        assert duration >= 0


@pytest.mark.asyncio
async def test_remote_ssh_executor_wrapper() -> None:
    config = RemoteSSHConfig(host="10.0.0.15", user="ubuntu")
    executor = RemoteSSHExecutor(config=config, distill_logs=True)

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"OK 200", b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await executor.execute("echo OK 200")
        assert result.exit_code == 0
        assert "OK 200" in result.stdout
        assert result.is_distilled is True
