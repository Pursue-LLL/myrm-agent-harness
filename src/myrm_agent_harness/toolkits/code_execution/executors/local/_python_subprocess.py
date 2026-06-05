"""Python script subprocess execution with sandbox and timeout.

[INPUT]
executors.base::ExecutionContext (POS: Code executor base classes)
executors.base::ExecutionResult (POS: Code executor base classes)
executors.common::parse_execution_output (POS: Shared execution utilities)
code_execution.sandbox::detect_sandbox_provider (POS: Sandbox detection and wrapping)
code_execution.security.validator::sanitize_env (POS: Environment sanitization)

[OUTPUT]
run_python_subprocess: Execute a Python script in a sandboxed subprocess with timeout.

[POS]
Python subprocess execution. Handles environment preparation, sandbox wrapping,
graceful timeout (SIGTERM → SIGKILL), and output parsing for Python code execution.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import traceback
from pathlib import Path

from myrm_agent_harness.toolkits.code_execution.executors.base import (
    ExecutionContext,
    ExecutionResult,
)
from myrm_agent_harness.toolkits.code_execution.executors.common import (
    parse_execution_output,
)

logger = logging.getLogger(__name__)


async def run_python_subprocess(
    script_path: Path,
    timeout: int,
    python_executable: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    allow_network: bool = True,
    context: ExecutionContext | None = None,
) -> ExecutionResult:
    """Execute a Python script via subprocess with sandbox and timeout.

    Args:
        script_path: Path to the Python script to execute.
        timeout: Timeout in seconds.
        python_executable: Path to the Python interpreter.
        cwd: Working directory.
        env: User-defined environment variables.
        allow_network: Whether to allow network access.
        context: Optional execution context for readonly_workspace flag.

    Returns:
        Execution result with stdout, stderr, exit code.
    """
    try:
        from myrm_agent_harness.toolkits.code_execution.sandbox import (
            detect_sandbox_provider,
        )
        from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
            SandboxPolicy,
        )
        from myrm_agent_harness.toolkits.code_execution.security.validator import (
            sanitize_env,
        )

        process_env = sanitize_env(os.environ.copy())
        python_path = os.pathsep.join(sys.path)
        if "PYTHONPATH" in process_env:
            process_env["PYTHONPATH"] = python_path + os.pathsep + process_env["PYTHONPATH"]
        else:
            process_env["PYTHONPATH"] = python_path

        if env:
            process_env.update(sanitize_env(env))
            logger.debug(f" User env vars: {list(env.keys())}")

        logger.info(f" [LocalExecutor] Using Python: {python_executable}")

        work_dir_str = str(cwd) if cwd else "/tmp"
        provider, sandbox_status = detect_sandbox_provider()

        if sandbox_status.enabled:
            policy = SandboxPolicy(
                writable_paths=(("/tmp",) if context and context.readonly_workspace else (work_dir_str,)),
                allow_network=allow_network,
            )
            wrapped_cmd, wrapped_args = provider.wrap_command(
                python_executable, (str(script_path),), work_dir_str, policy
            )
            full_cmd_executable = wrapped_cmd
            full_cmd_args = wrapped_args
        else:
            full_cmd_executable = python_executable
            full_cmd_args = (str(script_path),)

        from myrm_agent_harness.utils import os_compat

        kwargs = os_compat.get_process_group_kwargs()

        process = await asyncio.create_subprocess_exec(
            full_cmd_executable,
            *full_cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=process_env,
            **kwargs,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            if process.pid:
                os_compat.kill_process_group(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                if process.pid:
                    os_compat.kill_process_group(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                await process.wait()
            return ExecutionResult(
                success=False,
                error=f"Execution timed out after {timeout}s",
                stderr="Timeout",
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        exit_code = process.returncode or 0

        output = parse_execution_output(stdout, stderr, exit_code)

        return ExecutionResult(
            success=output.success,
            result=output.result,
            stdout=output.stdout,
            stderr=output.stderr,
            error=output.error,
            exit_code=exit_code,
        )

    except Exception as e:
        traceback.print_exc()
        return ExecutionResult(
            success=False,
            error=f"{type(e).__name__}: {e!s}",
            stderr=str(e),
        )
