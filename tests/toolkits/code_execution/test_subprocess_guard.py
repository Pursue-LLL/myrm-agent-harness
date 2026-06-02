"""Tests for subprocess_guard: guarded_communicate timeout and cleanup."""

import asyncio
import sys

import pytest

from myrm_agent_harness.toolkits.code_execution.executors.common.subprocess_guard import (
    SubprocessTimeoutError,
    guarded_communicate,
)


class TestSubprocessTimeoutError:
    def test_message_with_label(self):
        err = SubprocessTimeoutError(30.0, "docker cp")
        assert "30" in str(err)
        assert "docker cp" in str(err)
        assert err.timeout == 30.0
        assert err.label == "docker cp"

    def test_message_without_label(self):
        err = SubprocessTimeoutError(10.0)
        assert "10" in str(err)
        assert err.label == ""

    def test_inherits_timeout_error(self):
        err = SubprocessTimeoutError(5.0)
        assert isinstance(err, TimeoutError)


class TestGuardedCommunicate:
    @pytest.mark.asyncio
    async def test_success(self):
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "print('hello')",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await guarded_communicate(proc, 10, label="test echo")
        assert b"hello" in stdout
        assert proc.returncode == 0

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self):
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        with pytest.raises(SubprocessTimeoutError) as exc_info:
            await guarded_communicate(proc, 0.5, label="sleep hang")

        assert exc_info.value.timeout == 0.5
        assert exc_info.value.label == "sleep hang"
        assert proc.returncode is not None

    @pytest.mark.asyncio
    async def test_already_finished_process(self):
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "pass",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()
        _stdout, _stderr = await guarded_communicate(proc, 5, label="already done")
        assert proc.returncode == 0

    @pytest.mark.asyncio
    async def test_nonzero_exit_code_preserved(self):
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import sys; sys.exit(42)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await guarded_communicate(proc, 5, label="exit 42")
        assert proc.returncode == 42

    @pytest.mark.asyncio
    async def test_stderr_captured(self):
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('oops')",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await guarded_communicate(proc, 5, label="stderr test")
        assert b"oops" in stderr
