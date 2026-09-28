"""Asynchronous SSH and SFTP remote executor with safety guards and log distillation.

[INPUT]
- .models::SSHHostSpec, SSHCommandResult, SFTPTransferResult, SSHAuthType
- myrm_agent_harness.toolkits.code_execution.utils.log_distiller::TerminalLogDistiller

[OUTPUT]
- SSHRemoteExecutor

[POS]
Core execution engine in ssh_remote toolkit.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from re import Pattern

from myrm_agent_harness.toolkits.code_execution.utils.log_distiller import (
    TerminalLogDistiller,
)
from myrm_agent_harness.toolkits.ssh_remote.command_validator import (
    ReadOnlySSHValidator,
)
from myrm_agent_harness.toolkits.ssh_remote.models import (
    SSHAuthType,
    SSHCommandResult,
    SSHHostSpec,
)

logger = logging.getLogger(__name__)

# High risk command patterns that must be blocked or gated
DANGEROUS_COMMAND_PATTERNS: list[Pattern[str]] = [
    re.compile(r"\brm\s+-[rR]*f[rR]*\s+/(?:\s|$|\*)"),  # rm -rf /
    re.compile(r"\bmkfs(?:\.\w+)?\s+"),  # format filesystem
    re.compile(r"\bdd\s+if=.*?of=/dev/[svh]d[a-z]"),  # overwrite disk
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),  # fork bomb
    re.compile(r"\bshutdown\s+-h\s+now\b|\binit\s+0\b|\bpoweroff\b"),  # immediate poweroff
]


class SSHRemoteExecutor:
    """Safely executes commands and handles SFTP file transfers on remote hosts."""

    def __init__(
        self,
        distiller: TerminalLogDistiller | None = None,
        custom_dangerous_patterns: list[Pattern[str]] | None = None,
        readonly_validator: ReadOnlySSHValidator | None = None,
    ) -> None:
        self._distiller = distiller or TerminalLogDistiller()
        self._dangerous_patterns = custom_dangerous_patterns or DANGEROUS_COMMAND_PATTERNS
        self._readonly_validator = readonly_validator or ReadOnlySSHValidator(
            custom_destructive_patterns=self._dangerous_patterns
        )

    def check_command_safety(
        self, command: str, host: SSHHostSpec | None = None
    ) -> tuple[bool, str]:
        """Check if command matches high-risk destructive patterns or violates read-only rules."""
        normalized = command.strip()
        for pattern in self._dangerous_patterns:
            if pattern.search(normalized):
                return False, f"Command matched dangerous destructive pattern: {pattern.pattern}"

        if host and host.is_read_only:
            val_res = self._readonly_validator.validate(normalized)
            if not val_res.is_safe:
                return False, val_res.reason

        return True, ""

    async def execute_command(
        self,
        host: SSHHostSpec,
        command: str,
        timeout: float | None = None,
    ) -> SSHCommandResult:
        """Execute a command on the target host asynchronously using asyncssh/ssh client."""
        start_time = time.monotonic()

        # 1. Check high-risk destructive patterns first (universal security fence)
        is_safe, reason = self.check_command_safety(command, host=None)
        if not is_safe:
            return SSHCommandResult(
                host_id=host.host_id,
                command=command,
                exit_code=126,
                stdout="",
                stderr=reason,
                distilled_output=f"[SECURITY BLOCKED] {reason}",
                elapsed_seconds=0.0,
                blocked_by_guard=True,
                block_reason=reason,
                is_read_only_violation=False,
                blocked_command_snippet="",
            )

        # 2. Check read-only policy if host is configured as read-only
        if host.is_read_only:
            val_res = self._readonly_validator.validate(command)
            if not val_res.is_safe:
                return SSHCommandResult(
                    host_id=host.host_id,
                    command=command,
                    exit_code=126,
                    stdout="",
                    stderr=val_res.reason,
                    distilled_output=f"[READ-ONLY BLOCKED] {val_res.reason}",
                    elapsed_seconds=0.0,
                    blocked_by_guard=True,
                    block_reason=val_res.reason,
                    is_read_only_violation=True,
                    blocked_command_snippet=val_res.violation_snippet,
                )

        exec_timeout = timeout or host.timeout_seconds

        try:
            import asyncssh

            # Setup client options
            client_keys = [host.private_key] if host.private_key else None
            passphrase = host.passphrase if host.passphrase else None

            async with asyncssh.connect(
                host=host.hostname,
                port=host.port,
                username=host.username,
                password=host.password if host.auth_type == SSHAuthType.PASSWORD else None,
                client_keys=client_keys,
                passphrase=passphrase,
                known_hosts=None,  # Or managed known hosts
            ) as conn:
                res = await asyncio.wait_for(
                    conn.run(command, check=False),
                    timeout=exec_timeout,
                )
                stdout_str = str(res.stdout or "")
                stderr_str = str(res.stderr or "")
                exit_code = int(res.exit_status if res.exit_status is not None else 0)

                combined_log = stdout_str + ("\n" + stderr_str if stderr_str else "")
                distilled = self._distiller.distill(combined_log)

                elapsed = time.monotonic() - start_time
                return SSHCommandResult(
                    host_id=host.host_id,
                    command=command,
                    exit_code=exit_code,
                    stdout=stdout_str,
                    stderr=stderr_str,
                    distilled_output=distilled,
                    elapsed_seconds=elapsed,
                )
        except TimeoutError:
            elapsed = time.monotonic() - start_time
            return SSHCommandResult(
                host_id=host.host_id,
                command=command,
                exit_code=124,
                stdout="",
                stderr=f"SSH command timed out after {exec_timeout} seconds",
                distilled_output=f"[TIMEOUT] Execution exceeded {exec_timeout}s limit",
                elapsed_seconds=elapsed,
                is_timeout=True,
            )
        except ImportError:
            # Fallback to asyncio subprocess ssh if asyncssh not installed
            return await self._execute_subprocess_ssh(host, command, exec_timeout, start_time)
        except Exception as err:
            elapsed = time.monotonic() - start_time
            err_msg = str(err)
            return SSHCommandResult(
                host_id=host.host_id,
                command=command,
                exit_code=255,
                stdout="",
                stderr=err_msg,
                distilled_output=f"[SSH CONNECTION ERROR] {err_msg}",
                elapsed_seconds=elapsed,
            )

    async def _execute_subprocess_ssh(
        self,
        host: SSHHostSpec,
        command: str,
        timeout: float,
        start_time: float,
    ) -> SSHCommandResult:
        """Fallback execution using system ssh CLI."""
        ssh_cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", f"ConnectTimeout={int(timeout)}",
            "-p", str(host.port),
            f"{host.username}@{host.hostname}",
            command,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")
            combined = stdout_str + ("\n" + stderr_str if stderr_str else "")
            distilled = self._distiller.distill(combined)
            elapsed = time.monotonic() - start_time

            return SSHCommandResult(
                host_id=host.host_id,
                command=command,
                exit_code=proc.returncode if proc.returncode is not None else 0,
                stdout=stdout_str,
                stderr=stderr_str,
                distilled_output=distilled,
                elapsed_seconds=elapsed,
            )
        except TimeoutError:
            elapsed = time.monotonic() - start_time
            return SSHCommandResult(
                host_id=host.host_id,
                command=command,
                exit_code=124,
                stdout="",
                stderr=f"SSH command timed out after {timeout} seconds",
                distilled_output=f"[TIMEOUT] Execution exceeded {timeout}s limit",
                elapsed_seconds=elapsed,
                is_timeout=True,
            )
        except Exception as err:
            elapsed = time.monotonic() - start_time
            return SSHCommandResult(
                host_id=host.host_id,
                command=command,
                exit_code=255,
                stdout="",
                stderr=str(err),
                distilled_output=f"[SSH SUBPROCESS ERROR] {err}",
                elapsed_seconds=elapsed,
            )
