"""Tests for PersistentSession auto-restart, process group kill, and ulimit."""

from __future__ import annotations

import asyncio
import os

import pytest

from myrm_agent_harness.toolkits.code_execution.session import (
    LocalPersistentSession,
    SessionConfig,
)
from myrm_agent_harness.toolkits.code_execution.session.persistent_session import (
    SessionState,
)


def _make_config(timeout: int = 10) -> SessionConfig:
    return SessionConfig(
        session_id="test", work_dir="/tmp", timeout=timeout, sandbox_mode="disable"
    )


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class TestBasicExecution:
    @pytest.mark.asyncio
    async def test_echo(self) -> None:
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute("echo hello")
            assert result.success
            assert "hello" in result.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_nonzero_exit_code(self) -> None:
        """Subshell exit code is captured correctly (bash itself stays alive)."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute("(exit 42)")
            assert not result.success
            assert result.exit_code == 42
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_env_persistence(self) -> None:
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            await session.execute("export TEST_VAR=hello123")
            result = await session.execute("echo $TEST_VAR")
            assert result.success
            assert "hello123" in result.stdout
        finally:
            await session.close()


class TestAutoRestartRetry:
    @pytest.mark.asyncio
    async def test_restart_on_process_death(self) -> None:
        """When bash process dies, execute() should auto-restart and succeed."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute("echo before_kill")
            assert result.success

            assert session.process is not None
            session.process.kill()
            await session.process.wait()

            result = await session.execute("echo after_kill")
            assert result.success
            assert "after_kill" in result.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_diagnostic_returncode(self) -> None:
        """Error message from _execute_in_session contains diagnostic info."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            assert session.process is not None
            session.process.kill()
            await session.process.wait()

            result = await session._execute_core("echo x", timeout=5)
            assert not result.success
            assert result.error is not None
        finally:
            await session.close()


class TestProcessGroupKill:
    @pytest.mark.asyncio
    async def test_start_new_session_set(self) -> None:
        """Verify bash process runs in its own session (process group)."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            assert session.process is not None
            pid = session.process.pid
            assert pid is not None
            pgid = os.getpgid(pid)
            assert pgid == pid
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_child_processes_killed(self) -> None:
        """Child processes spawned by bash should be killed on close."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute(
                "python3 -c 'import time,os; print(os.getpid()); time.sleep(300)' &\nsleep 0.3 && jobs -p"
            )
            if not result.success:
                pytest.skip("fork not available in test environment")

            lines = result.stdout.strip().splitlines()
            pids = [int(p) for p in lines if p.strip().isdigit()]
            if not pids:
                pytest.skip("could not capture child PID")

            child_pid = pids[0]
            assert _pid_exists(child_pid)
            await session.close()
            await asyncio.sleep(0.3)
            assert not _pid_exists(child_pid)
        finally:
            if session.process:
                await session.close()

    @pytest.mark.asyncio
    async def test_cancel_during_close_still_kills_child(self) -> None:
        """Shield ensures _kill_process_group completes even under cancellation."""
        from unittest.mock import AsyncMock, patch

        session = LocalPersistentSession(_make_config())
        await session.start()

        kill_completed = False
        original_kill = session._kill_process_group

        async def slow_kill(grace_period: float = 2.0) -> None:
            nonlocal kill_completed
            await original_kill(grace_period)
            kill_completed = True

        try:
            result = await session.execute(
                "python3 -c 'import time,os; print(os.getpid()); time.sleep(300)' &\nsleep 0.3 && jobs -p"
            )
            if not result.success:
                pytest.skip("fork not available in test environment")
            lines = result.stdout.strip().splitlines()
            pids = [int(p) for p in lines if p.strip().isdigit()]
            if not pids:
                pytest.skip("could not capture child PID")

            child_pid = pids[0]
            assert _pid_exists(child_pid)

            with patch.object(session, "_kill_process_group", side_effect=slow_kill):
                close_task = asyncio.create_task(session.close())
                await asyncio.sleep(0.05)
                close_task.cancel()
                try:
                    await close_task
                except asyncio.CancelledError:
                    pass

            await asyncio.sleep(0.5)
            assert kill_completed, "shield must let _kill_process_group finish"
            assert not _pid_exists(child_pid), "child process must be dead"
        finally:
            if session.process and session.process.returncode is None:
                session.process.kill()
                await session.process.wait()

    @pytest.mark.asyncio
    async def test_kill_process_group_already_dead(self) -> None:
        """_kill_process_group should not raise if process already exited."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        assert session.process is not None
        session.process.kill()
        await session.process.wait()
        await session._kill_process_group()

    @pytest.mark.asyncio
    async def test_kill_posix_shared_pgid_falls_back(self) -> None:
        """When child shares parent's pgid, _kill_process_tree terminates only the child."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from myrm_agent_harness.toolkits.code_execution.session.persistent_session import (
            _kill_process_tree,
        )

        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock(return_value=None)

        my_pgid = os.getpgid(os.getpid())
        with (
            patch("os.getpgid", return_value=my_pgid),
            patch("os.killpg") as mock_killpg,
        ):
            await _kill_process_tree(mock_process, is_windows=False, grace_period=1.0)
            mock_process.terminate.assert_called_once()
            mock_killpg.assert_not_called()

    @pytest.mark.asyncio
    async def test_kill_posix_different_pgid_kills_group(self) -> None:
        """When child has its own pgid, killpg should be used."""
        import signal
        from unittest.mock import AsyncMock, MagicMock, patch

        from myrm_agent_harness.toolkits.code_execution.session.persistent_session import (
            _kill_process_tree,
        )

        mock_process = MagicMock()
        mock_process.pid = 99999
        mock_process.wait = AsyncMock(return_value=None)

        real_my_pgid = os.getpgid(os.getpid())
        fake_child_pgid = 99999
        with (
            patch(
                "os.getpgid",
                side_effect=lambda pid: (
                    fake_child_pgid if pid == 99999 else real_my_pgid
                ),
            ),
            patch("os.killpg") as mock_killpg,
        ):
            await _kill_process_tree(mock_process, is_windows=False, grace_period=1.0)
            mock_killpg.assert_any_call(fake_child_pgid, signal.SIGTERM)


class TestTimeout:
    @pytest.mark.asyncio
    async def test_command_timeout(self) -> None:
        session = LocalPersistentSession(_make_config(timeout=2))
        await session.start()
        try:
            result = await session.execute("sleep 30", timeout=1)
            assert not result.success
        finally:
            await session.close()


class TestStreamThrottlingAndOOM:
    @pytest.mark.asyncio
    async def test_sse_throttle_and_valve(self) -> None:
        """Test SSE throttle (10FPS) and volume valve (500KB) during execute_stream."""
        session = LocalPersistentSession(_make_config(timeout=10))
        await session.start()
        try:
            # Output 600KB of data to trigger the 500KB valve
            cmd = "python3 -c \"print('x' * 600000)\""

            chunks = []
            async for chunk in session.execute_stream(cmd):
                chunks.append(chunk)

            warning_found = False
            for c in chunks:
                if "System Warning: Terminal stream suspended" in c:
                    warning_found = True
                    break

            assert warning_found, "Volume valve did not trigger"
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_oom_truncation(self) -> None:
        """Test the backend OOM truncation logic for 1MB+ output strings."""
        session = LocalPersistentSession(_make_config(timeout=15))
        await session.start()
        try:
            from myrm_agent_harness.toolkits.code_execution.executors.common.executor_utils import (
                MAX_OUTPUT_CHARS,
            )

            # Print 200,000 chars which is more than the default 100,000 MAX_OUTPUT_CHARS
            # The result.stdout should be truncated to MAX_OUTPUT_CHARS and contain the warning
            cmd = "python3 -c \"for i in range(10000): print('A' * 20)\""
            result = await session.execute(cmd)

            assert result.success
            assert (
                len(result.stdout) <= MAX_OUTPUT_CHARS + 500
            )  # Leave room for the warning text
            assert "[System Warning: The middle" in result.stdout
            assert (
                "characters of output were truncated to prevent memory overflow]"
                in result.stdout
            )
        finally:
            await session.close()


class TestCoverageEdgeCases:
    @pytest.mark.asyncio
    async def test_windows_flavor_and_properties(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.platform import PlatformInfo
        from myrm_agent_harness.toolkits.code_execution.session.shell_flavor import (
            WindowsFlavor,
        )
        from myrm_agent_harness.toolkits.code_execution.session.shell_flavor import (
            get_flavor as _get_flavor,
        )

        pi = PlatformInfo(
            os_type="windows",
            os_release="10",
            arch="x86_64",
            is_wsl=False,
            shell_path="cmd.exe",
            shell_args=(),
            shell_type="cmd",
            env_set_template="set {key}={value}",
            path_separator=";",
            exit_code_var="%errorlevel%",
            process_group_creation_flag=0x00000200,
            safe_env_vars=frozenset(),
        )
        flavor = _get_flavor(pi)
        assert isinstance(flavor, WindowsFlavor)

        init_cmds = flavor.build_init_commands("/tmp", 10, 2048)
        assert "cd /d" in init_cmds[2]

        env_cmd = flavor.format_env_set("VAR", "VAL%UE")
        assert "set VAR=VAL%%UE" in env_cmd

        wrap_cmd = flavor.build_wrapped_command(
            "echo hello", "EXIT:", "END", "%errorlevel%"
        )
        assert "echo hello\\r\\n" in wrap_cmd or "echo hello\r\n" in wrap_cmd
        assert "EXIT:%errorlevel%" in wrap_cmd
        assert "END" in wrap_cmd

    @pytest.mark.asyncio
    async def test_check_health(self) -> None:
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            assert session.state.name == "ACTIVE"
            assert session.is_alive is True
            assert session.sandbox_status is not None
            assert isinstance(session.is_sandboxed, bool)

            is_healthy = await session.check_health()
            assert is_healthy is True

            # Kill process and check health again
            session.process.kill()
            await session.process.wait()

            is_healthy_dead = await session.check_health()
            assert is_healthy_dead is False
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_execute_stream_timeout(self) -> None:
        session = LocalPersistentSession(_make_config(timeout=1))
        await session.start()
        try:
            # Sleep 5, timeout 1
            cmd = "sleep 5"
            chunks = []
            async for chunk in session.execute_stream(cmd, timeout=1):
                chunks.append(chunk)

            output = "".join(chunks)
            assert "[ERROR] Timeout After 1s" in output
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_execute_stream_process_death(self) -> None:
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            # Kill process during execute stream
            async def run_and_collect():
                chunks = []
                async for chunk in session.execute_stream("sleep 10"):
                    chunks.append(chunk)
                return "".join(chunks)

            task = asyncio.create_task(run_and_collect())
            await asyncio.sleep(0.5)
            await session._kill_process_group()
            output = await task

            assert "Session process ended unexpectedly" in output
        finally:
            await session.close()


class TestSmartEnvInjection:
    @pytest.mark.asyncio
    async def test_global_defense_env_vars(self) -> None:
        """Test that global defense environment variables (CI, NEXT_TELEMETRY_DISABLED) are set."""
        config = _make_config()
        session = LocalPersistentSession(config)
        await session.start()
        try:
            import os

            script_path = os.path.join(
                os.path.dirname(__file__),
                "../../../src/myrm_agent_harness/agent/meta_tools/bash/scripts/resilience_init.sh",
            )
            await session.execute(f"source {script_path}")

            # Check if CI and NEXT_TELEMETRY_DISABLED are exported globally
            result = await session.execute(
                "env | grep -E '^(CI|NEXT_TELEMETRY_DISABLED)='"
            )
            assert "CI=1" in result.stdout
            assert "NEXT_TELEMETRY_DISABLED=1" in result.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_smart_local_env_injection_for_build(self) -> None:
        """Test that SKIP_ENV_VALIDATION is injected for build commands but not for normal commands."""
        config = _make_config()
        session = LocalPersistentSession(config)
        await session.start()
        try:
            import os

            script_path = os.path.join(
                os.path.dirname(__file__),
                "../../../src/myrm_agent_harness/agent/meta_tools/bash/scripts/resilience_init.sh",
            )
            await session.execute(f"source {script_path}")

            # Create a real package.json to test actual npm behavior
            await session.execute(
                'echo \'{"scripts": {"build": "env | grep -E \\"SKIP_ENV_VALIDATION|IGNORE_ENV_VALIDATION\\" || true", "test": "env | grep -E \\"SKIP_ENV_VALIDATION|IGNORE_ENV_VALIDATION\\" || true", "dev": "env | grep -E \\"SKIP_ENV_VALIDATION|IGNORE_ENV_VALIDATION\\" || true"}}\' > package.json'
            )

            # 1. Test npm run build (should inject)
            result = await session.execute("npm run build")
            assert "SKIP_ENV_VALIDATION=1" in result.stdout
            assert "IGNORE_ENV_VALIDATION=1" in result.stdout

            # 2. Test npm test (should NOT inject)
            result2 = await session.execute("npm test")
            assert "SKIP_ENV_VALIDATION=1" not in result2.stdout
            assert "IGNORE_ENV_VALIDATION=1" not in result2.stdout

            # 3. Test npm run dev (should inject)
            result3 = await session.execute("npm run dev")
            assert "SKIP_ENV_VALIDATION=1" in result3.stdout

        finally:
            await session.execute("rm -f package.json")
            await session.close()


class TestKillProcessTreeEdgeCases:
    @pytest.mark.asyncio
    async def test_pid_is_none(self) -> None:
        """_kill_process_tree should return immediately if pid is None."""
        from unittest.mock import MagicMock

        from myrm_agent_harness.toolkits.code_execution.session.persistent_session import (
            _kill_process_tree,
        )

        mock_process = MagicMock()
        mock_process.pid = None
        await _kill_process_tree(mock_process, is_windows=False)

    @pytest.mark.asyncio
    async def test_windows_taskkill(self) -> None:
        """Windows path uses taskkill /F /T /PID."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from myrm_agent_harness.toolkits.code_execution.session.persistent_session import (
            _kill_process_tree,
        )

        mock_process = MagicMock()
        mock_process.pid = 12345

        mock_sub = MagicMock()
        mock_sub.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_sub) as mock_exec:
            await _kill_process_tree(mock_process, is_windows=True)
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            assert "taskkill" in args
            assert "/F" in args
            assert "/T" in args

    @pytest.mark.asyncio
    async def test_windows_taskkill_failure_fallback(self) -> None:
        """Windows path falls back to process.kill() on taskkill failure."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from myrm_agent_harness.toolkits.code_execution.session.persistent_session import (
            _kill_process_tree,
        )

        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.kill = MagicMock()

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, side_effect=OSError("fail")):
            await _kill_process_tree(mock_process, is_windows=True)
            mock_process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_shared_pgid_sigterm_timeout_kills(self) -> None:
        """When shared pgid and SIGTERM times out, falls back to process.kill()."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from myrm_agent_harness.toolkits.code_execution.session.persistent_session import (
            _kill_process_tree,
        )

        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock(side_effect=TimeoutError)

        my_pgid = os.getpgid(os.getpid())
        with patch("os.getpgid", return_value=my_pgid):
            await _kill_process_tree(mock_process, is_windows=False, grace_period=0.1)
            mock_process.terminate.assert_called_once()
            mock_process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_different_pgid_sigterm_timeout_sigkill(self) -> None:
        """When different pgid and SIGTERM times out, falls back to SIGKILL on group."""
        import signal
        from unittest.mock import AsyncMock, MagicMock, patch

        from myrm_agent_harness.toolkits.code_execution.session.persistent_session import (
            _kill_process_tree,
        )

        mock_process = MagicMock()
        mock_process.pid = 99999
        mock_process.wait = AsyncMock(side_effect=TimeoutError)

        real_my_pgid = os.getpgid(os.getpid())
        fake_child_pgid = 99999
        with (
            patch("os.getpgid", side_effect=lambda pid: fake_child_pgid if pid == 99999 else real_my_pgid),
            patch("os.killpg") as mock_killpg,
        ):
            await _kill_process_tree(mock_process, is_windows=False, grace_period=0.1)
            mock_killpg.assert_any_call(fake_child_pgid, signal.SIGTERM)
            mock_killpg.assert_any_call(fake_child_pgid, signal.SIGKILL)


class TestStateMachine:
    @pytest.mark.asyncio
    async def test_transit_same_state_noop(self) -> None:
        """Transitioning to same state is a no-op."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            assert session.state == SessionState.ACTIVE
            await session._transit_state(SessionState.ACTIVE)
            assert session.state == SessionState.ACTIVE
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_start_when_already_alive(self) -> None:
        """Calling start() on an active session is a no-op."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            pid_before = session.process.pid
            await session.start()
            assert session.process.pid == pid_before
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_close_when_already_closing(self) -> None:
        """_close_unlocked returns immediately when already CLOSING."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            session._state = SessionState.CLOSING
            await session._close_unlocked()
            assert session._state == SessionState.CLOSING
        finally:
            if session.process and session.process.returncode is None:
                session.process.kill()
                await session.process.wait()

    @pytest.mark.asyncio
    async def test_execute_core_no_process(self) -> None:
        """_execute_core returns error when process is None."""
        session = LocalPersistentSession(_make_config())
        session.process = None
        result = await session._execute_core("echo x", timeout=5)
        assert not result.success
        assert result.error == "Process unavailable"


class TestRecoveryPath:
    @pytest.mark.asyncio
    async def test_auto_recover_on_process_death(self) -> None:
        """Execute should auto-recover when process dies mid-flight."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute("echo alive")
            assert result.success

            assert session.process is not None
            session.process.kill()
            await session.process.wait()

            result = await session.execute("echo recovered")
            assert result.success
            assert "recovered" in result.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_start_failure_transitions_to_terminated(self) -> None:
        """When _create_process fails, state transitions to TERMINATED."""
        from unittest.mock import AsyncMock, patch

        session = LocalPersistentSession(_make_config())

        with patch.object(session, "_create_process", new_callable=AsyncMock, side_effect=OSError("spawn fail")):
            with pytest.raises(OSError, match="spawn fail"):
                await session.start()
            assert session.state == SessionState.TERMINATED

    @pytest.mark.asyncio
    async def test_recover_and_retry_failure(self) -> None:
        """_recover_and_retry returns error result when recovery itself fails."""
        from unittest.mock import AsyncMock, patch

        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            with patch.object(session, "_create_process", new_callable=AsyncMock, side_effect=OSError("fail")):
                result = await session._recover_and_retry("echo x", timeout=5)
                assert not result.success
                assert "Recovery failed" in result.error
                assert session.state == SessionState.TERMINATED
        finally:
            if session.process and session.process.returncode is None:
                session.process.kill()
                await session.process.wait()


class TestCheckHealthEdge:
    @pytest.mark.asyncio
    async def test_check_health_exception(self) -> None:
        """check_health returns False when execute raises."""
        from unittest.mock import AsyncMock, patch

        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            with patch.object(session, "execute", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
                result = await session.check_health()
                assert result is False
        finally:
            await session.close()


class TestInitializeShellEdge:
    @pytest.mark.asyncio
    async def test_initialize_shell_no_process(self) -> None:
        """_initialize_shell returns early when process is None."""
        session = LocalPersistentSession(_make_config())
        session.process = None
        await session._initialize_shell()

    @pytest.mark.asyncio
    async def test_initialize_shell_with_env(self) -> None:
        """_initialize_shell injects env vars from config."""
        config = _make_config()
        config.env = {"MY_VAR": "test_value"}
        session = LocalPersistentSession(config)
        await session.start()
        try:
            result = await session.execute("echo $MY_VAR")
            assert result.success
            assert "test_value" in result.stdout
        finally:
            await session.close()


class TestEnsureActiveEdge:
    @pytest.mark.asyncio
    async def test_ensure_active_from_idle(self) -> None:
        """_ensure_active starts session when in IDLE state."""
        session = LocalPersistentSession(_make_config())
        assert session.state == SessionState.IDLE
        await session._ensure_active()
        try:
            assert session.state == SessionState.ACTIVE
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_ensure_active_from_terminated(self) -> None:
        """_ensure_active restarts session from TERMINATED state."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        await session.close()
        assert session.state == SessionState.TERMINATED
        await session._ensure_active()
        try:
            assert session.state == SessionState.ACTIVE
        finally:
            await session.close()


class TestAutoTeeAndDiskQuota:
    @pytest.mark.asyncio
    async def test_auto_tee_generation_and_lru(self) -> None:
        """Test that tee files are generated and LRU cleanup works."""
        import glob

        config = _make_config()
        session = LocalPersistentSession(config)
        await session.start()
        try:
            # Execute a simple command
            result = await session.execute("echo 'test_tee_output'")
            assert result.success

            # Check if tee file was created
            tee_dir = os.path.join(config.work_dir, ".myrm", "tee")
            assert os.path.exists(tee_dir)
            log_files = glob.glob(os.path.join(tee_dir, "cmd_*.log"))
            assert len(log_files) >= 1

            # Read the latest tee file
            latest_log = max(log_files, key=os.path.getmtime)
            with open(latest_log, encoding="utf-8") as f:
                content = f.read()
                assert "test_tee_output" in content
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_disk_quota_truncation(self) -> None:
        """Test that the disk quota truncates the tee file and injects warnings."""
        import glob
        from unittest.mock import patch

        config = _make_config(timeout=30)
        session = LocalPersistentSession(config)

        test_limit = 1 * 1024 * 1024  # 1MB limit for fast testing

        await session.start()
        try:
            with patch(
                "myrm_agent_harness.toolkits.code_execution.session"
                ".stream_output_processor._TEE_MAX_BYTES",
                test_limit,
            ):
                cmd = "python3 -c \"print('B' * 2000000)\""

                chunks = []
                async for chunk in session.execute_stream(cmd):
                    chunks.append(chunk)

                output = "".join(chunks)
                assert "Terminal stream suspended to prevent UI freeze" in output

                tee_dir = os.path.join(config.work_dir, ".myrm", "tee")
                log_files = glob.glob(os.path.join(tee_dir, "cmd_*.log"))
                latest_log = max(log_files, key=os.path.getmtime)

                file_size = os.path.getsize(latest_log)
                assert file_size <= test_limit + 1024
                assert file_size >= test_limit * 0.8  # at least 80% written

                with open(latest_log, encoding="utf-8") as f:
                    content = f.read()
                    assert (
                        "[System Warning: Tee log file exceeded 50MB hard limit "
                        "and was truncated.]" in content
                    )

        finally:
            await session.close()
