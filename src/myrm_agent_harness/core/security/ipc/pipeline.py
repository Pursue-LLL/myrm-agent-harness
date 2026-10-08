"""Safe Subprocess and IPC Pipeline eliminating shell injection risks.

[INPUT]
- Subprocess command args, payload string, transport mode

[OUTPUT]
- SafeIpcPipeline: Subprocess executor with zero-CLI-string-argument policy
- execute_with_query_file, execute_with_stdin

[POS]
Harness core security pipeline. Replaces command line string concatenation with pure
POSIX file descriptors or 0600 temporary query files, preventing shell quotation crashes and RCE.
"""

from __future__ import annotations

import asyncio
import logging
import time

from myrm_agent_harness.core.security.ipc.secure_file import SecureIpcFile
from myrm_agent_harness.core.security.ipc.types import (
    IpcExecutionResult,
    IpcPayloadTransport,
    SecureIpcFileOptions,
    ShellArgumentInjectionError,
)

logger = logging.getLogger(__name__)

_PROHIBITED_INLINE_FLAGS: frozenset[str] = frozenset({
    "-q",
    "-m",
    "-p",
    "--query",
    "--message",
    "--prompt",
})

_SHELL_WRAPPERS: tuple[str, ...] = ("sh", "bash", "zsh", "dash", "ksh")


class SafeIpcPipeline:
    """Executes subprocesses via safe file descriptor / query-file pipelines without shell interpretation."""

    def __init__(self, file_options: SecureIpcFileOptions | None = None) -> None:
        self._file_options = file_options if file_options is not None else SecureIpcFileOptions()

    def validate_command_safety(self, cmd_args: list[str]) -> None:
        """Assert command does not employ shell concatenation or prohibited inline prompt arguments."""
        if not cmd_args:
            raise ValueError("Command arguments list cannot be empty")

        # 1. Reject shell -c execution
        first_arg = cmd_args[0].lower()
        if any(
            first_arg.endswith(wrapper) or first_arg == wrapper for wrapper in _SHELL_WRAPPERS
        ) and ("-c" in cmd_args or "-e" in cmd_args):
            raise ShellArgumentInjectionError(
                f"Shell wrapper execution ('{first_arg} -c') is strictly forbidden. "
                "Use native executable dispatch.",
                flag="-c",
            )

        # 2. Reject passing long or structured prompt text directly via inline flags
        for i, arg in enumerate(cmd_args):
            if arg in _PROHIBITED_INLINE_FLAGS and i + 1 < len(cmd_args):
                next_val = cmd_args[i + 1]
                # If argument contains newlines, quotes, or is lengthy, it must use query-file
                if "\n" in next_val or len(next_val) > 128 or any(ch in next_val for ch in ('"', "'", "`", "$")):
                    raise ShellArgumentInjectionError(
                        f"Prohibited inline prompt argument detected under '{arg}'. "
                        "Transfer large or unescaped text via --query-file or stdin stream.",
                        flag=arg,
                    )

    async def execute_with_query_file(
        self,
        cmd_args: list[str],
        payload: str,
        query_flag: str = "--query-file",
        timeout_seconds: float = 60.0,
    ) -> IpcExecutionResult:
        """Execute subprocess by writing payload to a secure 0600 file and appending query-file flag."""
        self.validate_command_safety(cmd_args)

        with SecureIpcFile(payload, options=self._file_options) as safe_file_path:
            full_cmd = [*cmd_args, query_flag, safe_file_path]
            logger.debug("Executing IPC subprocess with query file: %s", safe_file_path)

            start_time = time.monotonic()
            try:
                proc = await asyncio.create_subprocess_exec(
                    *full_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                logger.error("IPC process timed out after %s seconds: %s", timeout_seconds, cmd_args)
                return IpcExecutionResult(
                    returncode=-1,
                    stdout="",
                    stderr=f"Process timed out after {timeout_seconds}s",
                    duration_seconds=time.monotonic() - start_time,
                    query_file_path=safe_file_path,
                )

            duration = time.monotonic() - start_time
            returncode = proc.returncode if proc.returncode is not None else -1

            return IpcExecutionResult(
                returncode=returncode,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                duration_seconds=duration,
                query_file_path=safe_file_path,
            )

    async def execute_with_stdin(
        self,
        cmd_args: list[str],
        payload: str,
        timeout_seconds: float = 60.0,
    ) -> IpcExecutionResult:
        """Execute subprocess by streaming payload directly into standard input stream."""
        self.validate_command_safety(cmd_args)

        logger.debug("Executing IPC subprocess with stdin stream: %s", cmd_args)
        start_time = time.monotonic()
        payload_bytes = payload.encode("utf-8")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=payload_bytes),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            logger.error("IPC process timed out after %s seconds: %s", timeout_seconds, cmd_args)
            return IpcExecutionResult(
                returncode=-1,
                stdout="",
                stderr=f"Process timed out after {timeout_seconds}s",
                duration_seconds=time.monotonic() - start_time,
            )

        duration = time.monotonic() - start_time
        returncode = proc.returncode if proc.returncode is not None else -1

        return IpcExecutionResult(
            returncode=returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            duration_seconds=duration,
        )

    async def dispatch(
        self,
        cmd_args: list[str],
        payload: str,
        transport: IpcPayloadTransport = IpcPayloadTransport.QUERY_FILE,
        query_flag: str = "--query-file",
        timeout_seconds: float = 60.0,
    ) -> IpcExecutionResult:
        """Dispatch IPC execution using requested transport."""
        if transport == IpcPayloadTransport.QUERY_FILE:
            return await self.execute_with_query_file(
                cmd_args=cmd_args,
                payload=payload,
                query_flag=query_flag,
                timeout_seconds=timeout_seconds,
            )
        return await self.execute_with_stdin(
            cmd_args=cmd_args,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
