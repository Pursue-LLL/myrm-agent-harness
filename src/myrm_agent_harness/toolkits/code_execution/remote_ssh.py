"""Remote SSH Command Execution and Distilled Log Bridge.

Enables secure, batch-mode command execution against configured SSH hosts
with automatic log distillation and timeout enforcement.

[INPUT]
- .utils.log_distiller::TerminalLogDistiller
- asyncio, time, subprocess, logging, dataclasses
- typing::Dict, Any, Optional, Tuple, List

[OUTPUT]
- RemoteSSHConfig, RemoteSSHResult, RemoteSSHExecutor, execute_remote_ssh_command

[POS]
Harness code execution toolkit in myrm_agent_harness/toolkits/code_execution/.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Optional, Tuple

from myrm_agent_harness.toolkits.code_execution.utils.log_distiller import (
    TerminalLogDistiller,
)

logger = logging.getLogger("myrm.harness.remote_ssh")


@dataclass
class RemoteSSHConfig:
    """Connection parameters for remote SSH execution."""

    host: str
    port: int = 22
    user: Optional[str] = None
    identity_file: Optional[str] = None
    connect_timeout: int = 10
    timeout_seconds: int = 60


@dataclass
class RemoteSSHResult:
    """Execution output from remote host."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    is_distilled: bool = False


class RemoteSSHExecutor:
    """Autonomous execution agent for remote SSH targets."""

    def __init__(self, config: RemoteSSHConfig, distill_logs: bool = True) -> None:
        self.config = config
        self.distill_logs = distill_logs
        self.distiller = TerminalLogDistiller() if distill_logs else None

    async def execute(self, command: str, timeout_seconds: int = 60) -> RemoteSSHResult:
        """Execute command asynchronously with timeout and log distillation."""
        exit_code, stdout, stderr, duration = await execute_remote_ssh_command(
            host=self.config.host,
            command=command,
            timeout_seconds=timeout_seconds,
            port=self.config.port,
            user=self.config.user,
            identity_file=self.config.identity_file,
            distill_logs=self.distill_logs,
        )
        return RemoteSSHResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration,
            is_distilled=self.distill_logs,
        )


async def execute_remote_ssh_command(
    host: str,
    command: str,
    timeout_seconds: int = 60,
    port: int = 22,
    user: Optional[str] = None,
    identity_file: Optional[str] = None,
    distill_logs: bool = True,
) -> Tuple[int, str, str, int]:
    """Execute command on remote SSH host with batch mode and log distillation.

    Returns:
        (exit_code, stdout, stderr, duration_ms)
    """
    ssh_args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=10",
        "-p",
        str(port),
    ]

    if identity_file:
        ssh_args.extend(["-i", identity_file])

    target = f"{user}@{host}" if user else host
    ssh_args.append(target)
    ssh_args.append(command)

    start_time = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            *ssh_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=float(timeout_seconds),
        )
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        stdout_str = stdout_bytes.decode("utf-8", errors="replace")
        stderr_str = stderr_bytes.decode("utf-8", errors="replace")

        if distill_logs and stdout_str:
            distiller = TerminalLogDistiller()
            distilled_res = distiller.distill(stdout_str)
            stdout_str = distilled_res.distilled_text

        return proc.returncode or 0, stdout_str, stderr_str, duration_ms

    except asyncio.TimeoutError:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return 124, "", f"Command timed out after {timeout_seconds}s", duration_ms
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return 1, "", str(exc), duration_ms
