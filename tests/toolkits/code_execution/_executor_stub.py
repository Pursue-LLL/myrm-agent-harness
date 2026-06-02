"""Lightweight in-process executor for PTC integration tests.

Executes Python code in a subprocess (matching production behavior) but
without sandbox/security wrappers for test isolation speed.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator

from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    ExecutionContext,
    ExecutionResult,
)


class InProcessExecutor(CodeExecutor):
    """Test executor that runs Python in a real subprocess with injected env."""

    async def execute(self, context: ExecutionContext) -> ExecutionResult:
        env = dict(os.environ)
        if context.env:
            env.update(context.env)
        env.setdefault("PYTHONPATH", "")

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            context.code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=context.work_dir if context.work_dir != "/workspace" else None,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=context.timeout or 30
        )
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        return ExecutionResult(
            success=proc.returncode == 0,
            result=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    async def execute_bash(self, context: ExecutionContext) -> ExecutionResult:
        env = dict(os.environ)
        if context.env:
            env.update(context.env)
        proc = await asyncio.create_subprocess_shell(
            context.code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=context.timeout or 30
        )
        return ExecutionResult(
            success=proc.returncode == 0,
            result=proc.returncode,
            stdout=stdout_bytes.decode(errors="replace"),
            stderr=stderr_bytes.decode(errors="replace"),
        )

    async def execute_bash_stream(
        self, context: ExecutionContext
    ) -> AsyncIterator[str]:
        result = await self.execute_bash(context)
        if result.stdout:
            yield result.stdout
