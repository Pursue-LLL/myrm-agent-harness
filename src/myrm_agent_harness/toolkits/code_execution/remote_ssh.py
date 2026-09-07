"""Remote SSH Command Execution and Distilled Log Bridge.

Enables secure, batch-mode command execution against configured SSH hosts
with automatic log distillation and timeout enforcement.

[INPUT]
- .utils.log_distiller::TerminalLogDistiller
- asyncio, time, subprocess, logging
- typing::Dict, Any, Optional, Tuple
- pydantic::BaseModel, Field

[OUTPUT]
- RemoteSSHConfig: Connection configuration for remote host.
- RemoteSSHResult: Result payload from SSH command run.
- RemoteSSHExecutor: Class interface for remote command execution.
- execute_remote_ssh_command: Core dispatch function for remote SSH execution.

[POS]
Harness code execution toolkit in myrm_agent_harness/toolkits/code_execution/.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Tuple

from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.code_execution.utils.log_distiller import (
    TerminalLogDistiller,
)

logger = logging.getLogger("myrm.harness.remote_ssh")


class RemoteSSHConfig(BaseModel):
    """Configuration descriptor for remote SSH target host."""

    host: str = Field(..., description="Target hostname or IP address")
    port: int = Field(default=22, ge=1, le=65535, description="SSH port")
    user: Optional[str] = Field(default=None, description="SSH username")
    identity_file: Optional[str] = Field(default=None, description="Path to SSH private key")
    timeout_seconds: int = Field(default=60, ge=1, le=3600, description="Execution timeout in seconds")


class RemoteSSHResult(BaseModel):
    """Structured execution output from remote SSH invocation."""

    exit_code: int = Field(..., description="Process exit code")
    stdout: str = Field(default="", description="Captured standard output (distilled)")
    stderr: str = Field(default="", description="Captured standard error")
    duration_ms: int = Field(default=0, ge=0, description="Execution duration in milliseconds")


class RemoteSSHExecutor:
    """Class wrapper for remote SSH execution."""

    def __init__(self, config: RemoteSSHConfig) -> None:
        self.config = config

    async def execute(self, command: str, distill_logs: bool = True) -> RemoteSSHResult:
        exit_code, stdout, stderr, duration_ms = await execute_remote_ssh_command(
            host=self.config.host,
            command=command,
            timeout_seconds=self.config.timeout_seconds,
            port=self.config.port,
            user=self.config.user,
            identity_file=self.config.identity_file,
            distill_logs=distill_logs,
        )
        return RemoteSSHResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
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
        try:
            proc.kill()
        except Exception:
            pass
        return (
            -1,
            "",
            f"Remote SSH execution timed out after {timeout_seconds}s on {target}",
            duration_ms,
        )
    except Exception as e:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return -1, "", f"Failed to execute SSH command: {e}", duration_ms
