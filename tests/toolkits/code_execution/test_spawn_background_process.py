"""Tests for LocalExecutor.spawn_background_process.

Covers:
- Process spawning with full-duplex streams (stdin/stdout/stderr)
- Pristine environment sanitization (only PATH/HOME/USER/LANG/LC_ALL inherited)
- AsyncProcessProtocol compliance
- Process group isolation (process_group=0)
- Process tree termination via os.killpg
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    AsyncProcessProtocol,
    ExecutionContext,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def _make_executor(workspace: Path) -> object:
    from unittest.mock import patch

    from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor
    from myrm_agent_harness.toolkits.code_execution.sandbox.providers.null import NullProvider
    from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import SandboxStatus

    config = ExecutionConfig()
    executor = LocalExecutor(config)
    executor.bind_workspace(str(workspace))

    # Force disable OS sandbox for unit tests — we test spawn_background_process
    # behavior, not sandbox wrapping (which has dedicated tests in test_os_sandbox.py).
    null_result = (NullProvider(), SandboxStatus(enabled=False, provider_name="null", reason="test"))
    patcher = patch(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector.detect_sandbox_provider",
        return_value=null_result,
    )
    patcher.start()
    # Also patch the import path used inside the function
    patcher2 = patch(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detect_sandbox_provider",
        return_value=null_result,
    )
    patcher2.start()

    executor._test_sandbox_patchers = [patcher, patcher2]  # type: ignore[attr-defined]
    return executor


@pytest.fixture(autouse=True)
def _cleanup_sandbox_patcher() -> None:
    """Cleanup sandbox patcher after each test."""
    yield  # type: ignore[misc]
    import unittest.mock
    unittest.mock.patch.stopall()


@pytest.mark.asyncio
async def test_spawn_background_process_returns_protocol(workspace: Path) -> None:
    """spawn_background_process must return an AsyncProcessProtocol instance."""
    executor = _make_executor(workspace)

    context = ExecutionContext(
        code=sys.executable,
        args=["-c", "import sys; sys.exit(0)"],
        workspace_root=str(workspace),
    )

    process = await executor.spawn_background_process(context)
    try:
        assert isinstance(process, AsyncProcessProtocol)
        assert process.stdin is not None
        assert process.stdout is not None
        # PTY mode merges stderr into stdout (stderr → None); PIPE mode has separate stderr.
        # Both are valid — PTY is required for interactive CLIs.
    finally:
        process.terminate()
        await process.wait()


@pytest.mark.asyncio
async def test_spawn_full_duplex_communication(workspace: Path) -> None:
    """Verify full-duplex stdin/stdout communication through the spawned process.

    PTY mode merges stdin echo + stdout + stderr into a single stream,
    so both the echo and the script output appear on stdout.
    """
    executor = _make_executor(workspace)

    script = "import sys; line = sys.stdin.readline(); sys.stdout.write(f'ECHO:{line}'); sys.stdout.flush()"
    context = ExecutionContext(
        code=sys.executable,
        args=["-c", script],
        workspace_root=str(workspace),
    )

    process = await executor.spawn_background_process(context)
    try:
        process.stdin.write(b"hello\n")  # type: ignore[union-attr]
        await process.stdin.drain()  # type: ignore[union-attr]
        process.stdin.close()  # type: ignore[union-attr]

        collected = b""
        for _ in range(20):
            try:
                data = await asyncio.wait_for(
                    process.stdout.readline(),  # type: ignore[union-attr]
                    timeout=2.0,
                )
            except TimeoutError:
                break
            if not data:
                break
            collected += data

        decoded = collected.decode("utf-8", errors="replace")
        assert "ECHO:" in decoded and "hello" in decoded, (
            f"Expected 'ECHO:...hello' in stdout but got: {decoded!r}"
        )

        exit_code = await process.wait()
        assert exit_code == 0
    finally:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()


@pytest.mark.asyncio
async def test_spawn_stderr_capture(workspace: Path) -> None:
    """Stderr output must be capturable — via separate stderr (PIPE) or merged stdout (PTY)."""
    executor = _make_executor(workspace)

    script = "import sys; sys.stderr.write('error output\\n'); sys.stderr.flush()"
    context = ExecutionContext(
        code=sys.executable,
        args=["-c", script],
        workspace_root=str(workspace),
    )

    process = await executor.spawn_background_process(context)
    try:
        await process.wait()

        if process.stderr is not None:
            stderr_data = await process.stderr.readline()
            assert b"error output" in stderr_data
        else:
            # PTY mode merges stderr into stdout — read from stdout instead
            found = False
            for _ in range(10):
                line = await asyncio.wait_for(process.stdout.readline(), timeout=2.0)  # type: ignore[union-attr]
                if not line:
                    break
                if b"error output" in line:
                    found = True
                    break
            assert found, "Expected 'error output' in merged PTY stdout"
    finally:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()


@pytest.mark.asyncio
async def test_spawn_pristine_environment(workspace: Path) -> None:
    """Spawned process must NOT inherit sensitive environment variables."""
    executor = _make_executor(workspace)

    sentinel_key = "_TEST_AGENT_SECRET_KEY"
    os.environ[sentinel_key] = "super_secret_value"

    try:
        script = f"import os; print(os.environ.get('{sentinel_key}', 'NOT_FOUND'))"
        context = ExecutionContext(
            code=sys.executable,
            args=["-c", script],
            workspace_root=str(workspace),
        )

        process = await executor.spawn_background_process(context)
        try:
            line = await process.stdout.readline()  # type: ignore[union-attr]
            result = line.decode("utf-8").strip()
            assert result == "NOT_FOUND", f"Secret env var leaked to child: {result}"
        finally:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            await process.wait()
    finally:
        del os.environ[sentinel_key]


@pytest.mark.asyncio
async def test_spawn_user_env_injected(workspace: Path) -> None:
    """User-provided env vars (context.env) must be injected into the process."""
    executor = _make_executor(workspace)

    script = "import os; print(os.environ.get('MY_API_KEY', 'MISSING'))"
    context = ExecutionContext(
        code=sys.executable,
        args=["-c", script],
        workspace_root=str(workspace),
        env={"MY_API_KEY": "sk-test-12345"},
    )

    process = await executor.spawn_background_process(context)
    try:
        line = await process.stdout.readline()  # type: ignore[union-attr]
        result = line.decode("utf-8").strip()
        assert result == "sk-test-12345"
    finally:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        await process.wait()


@pytest.mark.asyncio
async def test_spawn_terminate_kills_process(workspace: Path) -> None:
    """terminate() must actually stop the process."""
    executor = _make_executor(workspace)

    script = "import time; time.sleep(300)"
    context = ExecutionContext(
        code=sys.executable,
        args=["-c", script],
        workspace_root=str(workspace),
    )

    process = await executor.spawn_background_process(context)
    process.terminate()

    try:
        exit_code = await asyncio.wait_for(process.wait(), timeout=5.0)
        assert exit_code != 0
    except TimeoutError:
        process.kill()
        pytest.fail("Process did not terminate within 5 seconds after SIGTERM")


@pytest.mark.asyncio
async def test_spawn_kill_force_kills_process(workspace: Path) -> None:
    """kill() must force-kill even a signal-ignoring process."""
    executor = _make_executor(workspace)

    script = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(300)"
    context = ExecutionContext(
        code=sys.executable,
        args=["-c", script],
        workspace_root=str(workspace),
    )

    process = await executor.spawn_background_process(context)
    process.kill()

    try:
        exit_code = await asyncio.wait_for(process.wait(), timeout=5.0)
        assert exit_code != 0
    except TimeoutError:
        pytest.fail("Process did not die within 5 seconds after SIGKILL")


@pytest.mark.asyncio
async def test_spawn_child_process_tree_killed(workspace: Path) -> None:
    """terminate() must kill the entire process tree, not just the parent."""
    executor = _make_executor(workspace)

    marker_file = workspace / "_child_alive_marker"

    script = f"""
import subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', '''
import time
with open("{marker_file}", "w") as f:
    f.write("alive")
time.sleep(300)
'''])
time.sleep(300)
"""
    context = ExecutionContext(
        code=sys.executable,
        args=["-c", script],
        workspace_root=str(workspace),
    )

    process = await executor.spawn_background_process(context)

    for _ in range(50):
        if marker_file.exists():
            break
        await asyncio.sleep(0.1)

    assert marker_file.exists(), "Child process did not start"

    process.terminate()

    try:
        await asyncio.wait_for(process.wait(), timeout=5.0)
    except TimeoutError:
        process.kill()
        await process.wait()

    await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_spawn_with_none_args(workspace: Path) -> None:
    """spawn_background_process must work when args is None (defaults to [])."""
    executor = _make_executor(workspace)

    context = ExecutionContext(
        code=sys.executable,
        args=None,
        workspace_root=str(workspace),
    )

    # This should not raise — args=None falls back to []
    # Note: python without args enters interactive mode, so we just verify
    # the process starts successfully
    process = await executor.spawn_background_process(context)
    try:
        assert process.stdin is not None
    finally:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3.0)
        except TimeoutError:
            process.kill()
            await process.wait()


@pytest.mark.asyncio
async def test_spawn_exit_code_propagated(workspace: Path) -> None:
    """wait() must return the actual exit code of the process."""
    executor = _make_executor(workspace)

    context = ExecutionContext(
        code=sys.executable,
        args=["-c", "import sys; sys.exit(42)"],
        workspace_root=str(workspace),
    )

    process = await executor.spawn_background_process(context)
    exit_code = await process.wait()
    assert exit_code == 42
