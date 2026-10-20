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


class TestPythonSubprocessIsolation:
    @pytest.mark.asyncio
    async def test_pythonpath_pollution_sanitized(self, tmp_path):
        from myrm_agent_harness.toolkits.code_execution.executors.local._python_subprocess import (
            run_python_subprocess,
        )

        test_script = tmp_path / "check_path.py"
        test_script.write_text("import os, sys\nprint('PATH:' + os.environ.get('PYTHONPATH', ''))")

        # Inject hostile parent PYTHONPATH
        import os
        from unittest.mock import patch

        hostile_dir = "/malicious/host/incompatible_binary_dir"
        with patch.dict(os.environ, {"PYTHONPATH": hostile_dir}):
            res = await run_python_subprocess(
                script_path=test_script,
                timeout=10,
                python_executable=sys.executable,
                cwd=tmp_path,
            )
            assert res.success is True
            # Assert hostile dir was stripped
            assert hostile_dir not in res.stdout

    @pytest.mark.asyncio
    async def test_ptc_session_keeps_stub_pythonpath(self, tmp_path):
        from myrm_agent_harness.toolkits.code_execution.executors.local._python_subprocess import (
            run_python_subprocess,
        )

        test_script = tmp_path / "check_path.py"
        test_script.write_text("import os\nprint('PATH:' + os.environ.get('PYTHONPATH', ''))")

        import os
        from unittest.mock import patch

        stub_dir = str(tmp_path / "stubs")
        user_env = {"PYTHONPATH": stub_dir, "_MYRM_PTC_SOCKET": "/tmp/fake.sock"}
        with patch.dict(os.environ, {}, clear=False):
            res = await run_python_subprocess(
                script_path=test_script,
                timeout=10,
                python_executable=sys.executable,
                cwd=tmp_path,
                env=user_env,
            )
            assert res.success is True
            # PTC stub dir must survive the post-override scrub
            # (stdout redacts absolute prefixes, so match the tail component)
            assert "stubs" in res.stdout

    @pytest.mark.asyncio
    async def test_non_ptc_user_pythonpath_still_scrubbed(self, tmp_path):
        from myrm_agent_harness.toolkits.code_execution.executors.local._python_subprocess import (
            run_python_subprocess,
        )

        test_script = tmp_path / "check_path.py"
        test_script.write_text("import os\nprint('PATH:' + os.environ.get('PYTHONPATH', ''))")

        import os
        from unittest.mock import patch

        evil_dir = "/evil/plain_pythonpath"
        with patch.dict(os.environ, {}, clear=False):
            res = await run_python_subprocess(
                script_path=test_script,
                timeout=10,
                python_executable=sys.executable,
                cwd=tmp_path,
                env={"PYTHONPATH": evil_dir},
            )
            assert res.success is True
            # No PTC markers: user PYTHONPATH must still be scrubbed
            assert evil_dir not in res.stdout

    @pytest.mark.asyncio
    async def test_cancellation_kills_child_process_group(self, tmp_path):
        """Cancelling the host task must reap the sandboxed child, not orphan it."""
        import os

        from myrm_agent_harness.toolkits.code_execution.executors.local._python_subprocess import (
            run_python_subprocess,
        )

        pid_file = tmp_path / "child.pid"
        script = tmp_path / "sleeper.py"
        script.write_text(
            "import os, pathlib, time\n"
            "pathlib.Path('child.pid').write_text(str(os.getpid()))\n"
            "time.sleep(300)\n"
        )

        task = asyncio.create_task(
            run_python_subprocess(
                script_path=script,
                timeout=299,
                python_executable=sys.executable,
                cwd=tmp_path,
            )
        )

        child_pid: int | None = None
        for _ in range(100):
            await asyncio.sleep(0.05)
            if pid_file.exists():
                child_pid = int(pid_file.read_text().strip())
                break
        assert child_pid is not None, "child never started"

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # The child must be gone shortly after cancellation.
        for _ in range(50):
            if not _process_alive(child_pid):
                return
            await asyncio.sleep(0.05)
        pytest.fail(f"child process {child_pid} survived cancellation (orphan leak)")


def _process_alive(pid: int) -> bool:
    """Return True when ``pid`` still exists (zombies count as dead)."""
    import os
    import signal

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    if sys.platform != "win32":
        try:
            reaped, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return True
        if reaped == pid:
            return False
    return True
