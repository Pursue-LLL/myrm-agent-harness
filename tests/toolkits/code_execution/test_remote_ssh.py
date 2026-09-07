"""Unit tests for remote SSH execution engine in code_execution toolkit.

Verifies command building, log distillation integration, and timeout handling.

[INPUT]
- myrm_agent_harness.toolkits.code_execution.remote_ssh::execute_remote_ssh_command
- pytest, unittest.mock

[OUTPUT]
- Test cases for remote SSH command execution.

[POS]
Unit tests in myrm-agent-harness/tests/toolkits/code_execution/.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from myrm_agent_harness.toolkits.code_execution.remote_ssh import (
    execute_remote_ssh_command,
)


@pytest.mark.asyncio
async def test_execute_remote_ssh_command_success() -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (
        b"\x1b[32mBuild Success\x1b[0m\nDetails: ok",
        b"",
    )
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        code, stdout, stderr, dur = await execute_remote_ssh_command(
            host="192.168.1.100",
            command="make build",
            port=2222,
            user="ubuntu",
            identity_file="~/.ssh/id_rsa",
            distill_logs=True,
        )

        assert code == 0
        assert "Build Success" in stdout
        assert "\x1b[32m" not in stdout  # ANSI stripped by distiller
        assert stderr == ""
        assert dur >= 0
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert "ssh" in args
        assert "-p" in args
        assert "2222" in args
        assert "-i" in args
        assert "ubuntu@192.168.1.100" in args
        assert "make build" in args


@pytest.mark.asyncio
async def test_execute_remote_ssh_command_timeout() -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate.side_effect = asyncio.TimeoutError()
    mock_proc.kill = AsyncMock()

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        code, stdout, stderr, dur = await execute_remote_ssh_command(
            host="gpu-node-1",
            command="sleep 100",
            timeout_seconds=1,
            user="root",
        )

        assert code == -1
        assert "timed out after 1s" in stderr
        mock_proc.kill.assert_called_once()
