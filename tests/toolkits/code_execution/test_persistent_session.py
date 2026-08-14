"""Tests for PersistentSession auto-restart, process group kill, and ulimit."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import shutil

import pytest

from myrm_agent_harness.toolkits.code_execution.session import (
    LocalPersistentSession,
    SessionConfig,
)
from myrm_agent_harness.toolkits.code_execution.session.persistent_session import (
    SessionState,
)


def _make_config(timeout: int = 10) -> SessionConfig:
    return SessionConfig(session_id="test", work_dir="/tmp", timeout=timeout, sandbox_mode="disable")


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


class TestSessionWedgeRecovery:
    """A wedged shell (blocking command / stdin-swallowing command) must be
    killed and transparently rebuilt on the next call, not left poisoned."""

    @pytest.mark.asyncio
    async def test_timeout_wedge_recovered_on_next_execute(self) -> None:
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute("sleep 30", timeout=1)
            assert not result.success
            assert result.error == "Timeout"
            assert session.state == SessionState.TERMINATED
            assert session.is_alive is False

            recovered = await session.execute("echo ok", timeout=5)
            assert recovered.success
            assert recovered.stdout == "ok"
            assert session.state == SessionState.ACTIVE
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_stdin_swallowing_command_detected_and_recovered(self) -> None:
        """`cat` consumes the trailing marker commands from stdin and echoes
        them back; the corrupted boundary must poison-kill the shell."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            poisoned = await session.execute("cat", timeout=2)
            assert not poisoned.success
            assert poisoned.error in ("Session corrupted", "Timeout")
            assert session.state == SessionState.TERMINATED

            recovered = await session.execute("echo ok", timeout=5)
            assert recovered.success
            assert recovered.stdout == "ok"
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_stream_timeout_wedge_recovered(self) -> None:
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            chunks: list[str] = []
            async for chunk in session.execute_stream("sleep 30", timeout=1):
                chunks.append(chunk)
            assert any("Timeout" in c for c in chunks)
            assert session.state == SessionState.TERMINATED

            recovered = await session.execute("echo ok", timeout=5)
            assert recovered.success
            assert recovered.stdout == "ok"
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_stream_stdin_swallowing_command_detected(self) -> None:
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            chunks: list[str] = []
            async for chunk in session.execute_stream("cat", timeout=2):
                chunks.append(chunk)
            assert any("corrupted" in c for c in chunks)
            assert session.state == SessionState.TERMINATED
        finally:
            await session.close()


class TestRealUserFlow:
    """End-to-end session flow as a real user would drive it: consecutive
    commands, env persistence across rebuilds, special-char output fidelity,
    wedge recovery mid-flow, and the exit interceptor."""

    @pytest.mark.asyncio
    async def test_full_session_lifecycle(self) -> None:
        config = _make_config()
        config.env = {
            "APP_TOKEN": 'sk-x"y$HOME`id`\txyz',
        }
        session = LocalPersistentSession(config)
        await session.start()
        try:
            # 1. Special-char env stays literal.
            result = await session.execute("printf '%s' \"$APP_TOKEN\"")
            assert result.success
            assert result.stdout == 'sk-x"y$HOME`id`\txyz'

            # 2. cwd + env persist across commands.
            await session.execute("mkdir -p /tmp/myrm-user-flow && cd /tmp/myrm-user-flow")
            assert (await session.execute("pwd")).stdout == "/tmp/myrm-user-flow"
            assert (await session.execute('echo "$APP_TOKEN"')).stdout == 'sk-x"y$HOME`id`\txyz'

            # 3. Multi-line output round-trips.
            result = await session.execute("printf 'a\\nb\\nc\\n'")
            assert result.success
            assert result.stdout == "a\nb\nc"

            # 4. Wedge (blocking command) kills + rebuilds; env re-injected.
            wedged = await session.execute("sleep 30", timeout=1)
            assert wedged.error == "Timeout"
            assert session.state == SessionState.TERMINATED
            result = await session.execute("printf '%s' \"$APP_TOKEN\"")
            assert result.success
            assert result.stdout == 'sk-x"y$HOME`id`\txyz'
            assert session.state == SessionState.ACTIVE

            # 5. exit N is intercepted; shell survives.
            result = await session.execute("exit 3")
            assert not result.success
            assert result.exit_code == 3
            assert (await session.execute("echo final-ok")).stdout == "final-ok"
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
        from unittest.mock import patch

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
                with contextlib.suppress(asyncio.CancelledError):
                    await close_task

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
                side_effect=lambda pid: fake_child_pgid if pid == 99999 else real_my_pgid,
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
            assert len(result.stdout) <= MAX_OUTPUT_CHARS + 500  # Leave room for the warning text
            assert "[System Warning: The middle" in result.stdout
            assert "characters of output were truncated to prevent memory overflow]" in result.stdout
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

        wrap_cmd = flavor.build_wrapped_command("echo hello", "EXIT:", "END", "%errorlevel%")
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
            # SIGKILL (untrappable) mimics a real unexpected crash — the EXIT
            # trap cannot fire, stdout hits EOF and the session must surface
            # the fatal error instead of hanging.
            import os
            import signal

            os.killpg(os.getpgid(session.process.pid), signal.SIGKILL)
            output = await task

            assert "Session process ended unexpectedly" in output
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_execute_stream_sigterm_graceful_markers(self) -> None:
        """SIGTERM is catchable: the EXIT trap emits the marker pair so the
        stream finishes normally instead of misreporting an unexpected crash."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:

            async def run_and_collect():
                chunks = []
                async for chunk in session.execute_stream("sleep 10"):
                    chunks.append(chunk)
                return "".join(chunks)

            task = asyncio.create_task(run_and_collect())
            await asyncio.sleep(0.5)
            import os
            import signal

            os.killpg(os.getpgid(session.process.pid), signal.SIGTERM)
            output = await task

            assert "Session process ended unexpectedly" not in output
            assert "[ERROR]" not in output
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
            result = await session.execute("env | grep -E '^(CI|NEXT_TELEMETRY_DISABLED)='")
            assert "CI=1" in result.stdout
            assert "NEXT_TELEMETRY_DISABLED=1" in result.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        shutil.which("npm") is None,
        reason="npm is not installed in the current environment",
    )
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


class TestResilienceGitCredentialInjection:
    """GitHub credential/identity injection guards in resilience_init.sh (git push/commit).

    Verifies: HTTPS push gets an env-ref credential helper (token never inlined),
    SSH pushes passthrough, and commits resolve/inject identity only when the
    sandbox has none.
    """

    _FAKE_DIR = "/tmp/myrm_resilience_fake"
    _RESILIENCE = os.path.join(
        os.path.dirname(__file__),
        "../../../src/myrm_agent_harness/agent/meta_tools/bash/scripts/resilience_init.sh",
    )

    _FAKE_GIT = """#!/bin/bash
echo "$@" >> "${FAKE_GIT_LOG}"
case "$1" in
  rev-parse)
    if [ "$2" = "--is-inside-work-tree" ]; then
      [ "$FAKE_GIT_IS_REPO" = "1" ] && exit 0 || exit 128
    fi
    exit 0;;
  config)
    case "$2" in
      --get)
        case "$3" in
          credential.helper) [ -n "$FAKE_GIT_CRED_HELPER" ] && { echo "$FAKE_GIT_CRED_HELPER"; exit 0; } || exit 1;;
          user.name) [ -n "$FAKE_GIT_NAME" ] && { echo "$FAKE_GIT_NAME"; exit 0; } || exit 1;;
          user.email) [ -n "$FAKE_GIT_EMAIL" ] && { echo "$FAKE_GIT_EMAIL"; exit 0; } || exit 1;;
          *) exit 1;;
        esac;;
      *) exit 0;;
    esac;;
  remote) echo "$FAKE_GIT_REMOTE"; exit 0;;
  symbolic-ref) echo "feat/test"; exit 0;;
esac
exit 0
"""

    _FAKE_CURL = """#!/bin/bash
if [[ "$*" == *"api.github.com/user"* ]]; then
  echo '{"login":"octocat","id":1}'
fi
exit 0
"""

    @staticmethod
    def _env(
        *,
        remote: str,
        token: str,
        cred_helper: str = "",
        name: str = "",
        email: str = "",
        is_repo: str = "1",
    ) -> str:
        return (
            f"FAKE_GIT_LOG={TestResilienceGitCredentialInjection._FAKE_DIR}/git.log "
            f"FAKE_GIT_IS_REPO={is_repo} FAKE_GIT_NAME={name} FAKE_GIT_EMAIL={email} "
            f"FAKE_GIT_CRED_HELPER={cred_helper} FAKE_GIT_REMOTE={remote} GITHUB_TOKEN={token}"
        )

    async def _run(self, env: str, cmd: str, pre_cache: str = "") -> str:
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            await session.execute(f"rm -rf {self._FAKE_DIR} && mkdir -p {self._FAKE_DIR}/home")
            await session.execute('rm -f "${TMPDIR:-/tmp}"/myrm_gh_identity')
            if pre_cache:
                await session.execute(f"printf '%s' '{pre_cache}' > \"${{TMPDIR:-/tmp}}\"/myrm_gh_identity")
            for name, body in (("git", self._FAKE_GIT), ("curl", self._FAKE_CURL)):
                b64 = base64.b64encode(body.encode()).decode()
                await session.execute(
                    f"echo {b64} | base64 -d > {self._FAKE_DIR}/{name} && chmod +x {self._FAKE_DIR}/{name}"
                )
            # Isolate HOME so a host-level ~/.git-credentials (e.g. gh auth) cannot
            # flip _git_has_existing_credentials and skip helper injection.
            await session.execute(f"export PATH={self._FAKE_DIR}:$PATH HOME={self._FAKE_DIR}/home {env}")
            await session.execute(f"source {self._RESILIENCE}")
            await session.execute(cmd)
            result = await session.execute(f"cat {self._FAKE_DIR}/git.log 2>/dev/null || true")
            return result.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_push_https_injects_host_scoped_helper(self) -> None:
        """HTTPS GitHub push without existing credentials gets an env-ref helper gated on github.com hosts."""
        log = await self._run(
            self._env(remote="https://github.com/owner/repo.git", token="ghp_testtoken"),
            "git push origin main",
        )
        assert 'host=*) host="${line#host=}"' in log
        assert '"github.com"' in log
        assert 'password="${GITHUB_TOKEN}"' in log
        assert "password=ghp_testtoken" not in log

    @pytest.mark.asyncio
    async def test_push_ssh_passthrough(self) -> None:
        """SSH remote never receives a credential helper injection."""
        log = await self._run(
            self._env(remote="git@github.com:owner/repo.git", token="ghp_testtoken"),
            "git push origin main",
        )
        assert "-c credential.helper=" not in log
        assert "origin main" in log

    @pytest.mark.asyncio
    async def test_push_existing_helper_passthrough(self) -> None:
        """Existing credential.helper config suppresses injection."""
        log = await self._run(
            self._env(
                remote="https://github.com/owner/repo.git",
                token="ghp_testtoken",
                cred_helper="osxkeychain",
            ),
            "git push origin main",
        )
        assert "-c credential.helper=" not in log

    @pytest.mark.asyncio
    async def test_push_https_non_github_remote_passthrough(self) -> None:
        """HTTPS push to a third-party git host never gets the GitHub token."""
        log = await self._run(
            self._env(
                remote="https://gitlab.example.com/owner/repo.git",
                token="ghp_testtoken",
            ),
            "git push origin main",
        )
        assert "-c credential.helper=" not in log
        assert "origin main" in log

    @pytest.mark.asyncio
    async def test_push_www_github_host_scope(self) -> None:
        """www.github.com HTTPS push gets the host-scoped helper."""
        log = await self._run(
            self._env(remote="https://www.github.com/owner/repo.git", token="ghp_testtoken"),
            "git push origin main",
        )
        assert 'host=*) host="${line#host=}"' in log
        assert '"www.github.com"' in log
        assert "password=ghp_testtoken" not in log

    @pytest.mark.asyncio
    async def test_push_no_token_passthrough(self) -> None:
        """No GITHUB_TOKEN → no credential helper injection."""
        log = await self._run(
            self._env(remote="https://github.com/owner/repo.git", token=""),
            "git push origin main",
        )
        assert "-c credential.helper=" not in log
        assert "origin main" in log

    @pytest.mark.asyncio
    async def test_commit_injects_resolved_identity(self) -> None:
        """Commit with no sandbox identity resolves GitHub login and injects user.name/email."""
        log = await self._run(
            self._env(remote="https://github.com/owner/repo.git", token="ghp_testtoken"),
            "git commit -m x",
        )
        assert "-c user.name=octocat" in log
        assert "user.email=octocat@users.noreply.github.com" in log

    @pytest.mark.asyncio
    async def test_commit_passthrough_with_identity(self) -> None:
        """Commit with configured identity passes through without injection."""
        log = await self._run(
            self._env(
                remote="https://github.com/owner/repo.git",
                token="ghp_testtoken",
                name="Jane",
                email="jane@example.com",
            ),
            "git commit -m x",
        )
        assert "user.name=" not in log
        assert "-m x" in log

    @pytest.mark.asyncio
    async def test_commit_non_repo_passthrough(self) -> None:
        """Commit outside a work tree passes through without identity resolution."""
        log = await self._run(
            self._env(
                remote="https://github.com/owner/repo.git",
                token="ghp_testtoken",
                is_repo="0",
            ),
            "git commit -m x",
        )
        assert "user.name=" not in log
        assert "-m x" in log

    @pytest.mark.asyncio
    async def test_commit_uses_cached_identity(self) -> None:
        """Commit identity resolution reuses the TMPDIR cache instead of calling the GitHub API."""
        log = await self._run(
            self._env(remote="https://github.com/owner/repo.git", token="ghp_testtoken"),
            "git commit -m x",
            pre_cache="cacheduser|cacheduser@users.noreply.github.com",
        )
        assert "-c user.name=cacheduser" in log
        assert "user.email=cacheduser@users.noreply.github.com" in log


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

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=mock_sub,
        ) as mock_exec:
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

        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=OSError("fail"),
        ):
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
            patch(
                "os.getpgid",
                side_effect=lambda pid: fake_child_pgid if pid == 99999 else real_my_pgid,
            ),
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

        with patch.object(
            session,
            "_create_process",
            new_callable=AsyncMock,
            side_effect=OSError("spawn fail"),
        ):
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
            with patch.object(
                session,
                "_create_process",
                new_callable=AsyncMock,
                side_effect=OSError("fail"),
            ):
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
            with patch.object(
                session,
                "execute",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ):
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

    @pytest.mark.asyncio
    async def test_initialize_shell_special_chars_env_preserved(self) -> None:
        """Env values with $, backticks, quotes and backslashes stay literal.

        ``format_env_set`` must not let the shell re-expand ``$VAR``/backticks
        embedded in a user-provided env value (e.g. API tokens).
        """
        config = _make_config()
        config.env = {"MY_SPECIAL": "a\"b\\c d$HOME `whoami` 'q'"}
        session = LocalPersistentSession(config)
        await session.start()
        try:
            result = await session.execute("printf '%s' \"$MY_SPECIAL\"")
            assert result.success
            assert result.stdout == "a\"b\\c d$HOME `whoami` 'q'"
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


class TestLifecycleSafety:
    """Lifecycle-safety guards for the persistent-session bug class: marker
    collision, ``exit`` killing the shell, and syntax errors killing the shell.
    Enforced via random markers + ``exit`` interceptor + ``bash -n`` gate.
    """

    @pytest.mark.asyncio
    async def test_marker_text_in_output_does_not_collide(self) -> None:
        """User output containing the legacy marker literals is not truncated."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute('echo "hello __MYRM_EXIT__ world"; echo after')
            assert result.success
            assert result.exit_code == 0
            assert "hello __MYRM_EXIT__ world" in result.stdout
            assert "after" in result.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_stream_path_marker_like_output_not_truncated(self) -> None:
        """Stream path keeps marker-like user output intact (mirror of execute)."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            chunks = []
            async for chunk in session.execute_stream(
                'echo "__MYRM_END_00000000__"; echo "__MYRM_EXIT_ffffffff__"; echo done'
            ):
                chunks.append(chunk)
            combined = "".join(chunks)
            assert "__MYRM_END_00000000__" in combined
            assert "__MYRM_EXIT_ffffffff__" in combined
            assert "done" in combined
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_marker_sequence_in_output_not_truncated(self) -> None:
        """A multi-line payload containing both marker literals passes through."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute("printf 'a\\n__MYRM_EXIT__\\nb\\n__MYRM_END__\\nc\\n'")
            assert result.success
            assert result.exit_code == 0
            assert "a" in result.stdout and "b" in result.stdout and "c" in result.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_markers_are_random_per_command(self) -> None:
        """Each execution gets unique boundary markers."""
        from myrm_agent_harness.toolkits.code_execution.session.persistent_session import (
            _generate_marker,
        )

        a_end, b_end = _generate_marker("END"), _generate_marker("END")
        a_exit, b_exit = _generate_marker("EXIT"), _generate_marker("EXIT")
        assert a_end != b_end
        assert a_exit != b_exit
        assert a_end.startswith("__MYRM_END_")
        assert a_exit.startswith("__MYRM_EXIT_")

    @pytest.mark.asyncio
    async def test_exit_keeps_session_alive_and_cwd(self) -> None:
        """Trailing ``exit 0`` must not kill the persistent shell nor reset cwd."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute("cd /tmp; pwd; exit 0")
            assert result.success
            assert session.is_alive
            cwd = await session.execute("pwd")
            assert "/tmp" in cwd.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_exit_nonzero_propagates(self) -> None:
        """``exit 5`` surfaces rc=5 while the session survives."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute("exit 5")
            assert not result.success
            assert result.exit_code == 5
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_exit_keeps_env(self) -> None:
        """Exported variables survive a command that ends with ``exit``."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            await session.execute("export MYRM_LC=42; exit 0")
            result = await session.execute('echo "v=$MYRM_LC"')
            assert "v=42" in result.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_nested_bash_exit_unaffected(self) -> None:
        """A nested ``bash -c`` process still honors real ``exit`` semantics."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute('bash -c "exit 3"; echo rc=$?')
            assert result.success
            assert "rc=3" in result.stdout
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_bare_brace_rejected_without_killing_session(self) -> None:
        """A bare ``}`` line is a syntax error caught by the pre-check gate."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute("echo hi\n}\necho bye")
            assert not result.success
            assert "syntax error" in (result.error or "")
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_unclosed_if_rejected_without_killing_session(self) -> None:
        """An unterminated ``if`` block is caught before reaching the shell."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute("if true; then\n echo x")
            assert not result.success
            assert "unexpected end of file" in (result.error or "")
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_stream_path_rejects_syntax_error(self) -> None:
        """execute_stream applies the same syntax gate as execute."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            chunks = [c async for c in session.execute_stream("echo hi\n}\necho bye")]
            combined = "".join(chunks)
            assert "[ERROR]" in combined
            assert "syntax error" in combined
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_stream_path_comment_only_returns(self) -> None:
        """execute_stream also survives comment-only commands (shared wrapper)."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            chunks = []
            async with asyncio.timeout(6):
                async for c in session.execute_stream("# just a comment"):
                    chunks.append(c)
            combined = "".join(chunks)
            assert "[ERROR]" not in combined
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_stream_path_empty_command_returns(self) -> None:
        """execute_stream also survives blank commands (shared wrapper)."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            chunks = []
            async with asyncio.timeout(6):
                async for c in session.execute_stream("   "):
                    chunks.append(c)
            combined = "".join(chunks)
            assert "[ERROR]" not in combined
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_multiline_for_loop_fidelity(self) -> None:
        """Multi-line compound commands still execute faithfully."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute('for i in 1 2; do\n  echo "x$i"\ndone')
            assert result.success
            assert "x1" in result.stdout and "x2" in result.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_heredoc_fidelity(self) -> None:
        """Heredoc bodies pass the pre-check and run correctly."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute(
                "cat <<'EOF' > /tmp/myrm_lc_heredoc.txt\nhello\n}\nEOF\ncat /tmp/myrm_lc_heredoc.txt"
            )
            assert result.success
            assert "hello" in result.stdout and "}" in result.stdout
        finally:
            await session.execute("rm -f /tmp/myrm_lc_heredoc.txt")
            await session.close()

    @pytest.mark.asyncio
    async def test_background_child_does_not_delay_main(self) -> None:
        """A background child holding the stdout pipe must not block execution."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await asyncio.wait_for(session.execute("sleep 5 & echo done", timeout=5), timeout=6)
            assert result.success
            assert "done" in result.stdout
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_nohup_background_returns_immediately(self) -> None:
        """Detached background processes do not delay the current command."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await asyncio.wait_for(
                session.execute("nohup sleep 3 >/dev/null 2>&1 & echo started", timeout=5),
                timeout=6,
            )
            assert result.success
            assert "started" in result.stdout
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_comment_only_command_returns_immediately(self) -> None:
        """A lone comment line must not wedge the wrapper into an open block."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await asyncio.wait_for(session.execute("# just a comment", timeout=5), timeout=6)
            assert result.success
            assert result.exit_code == 0
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_empty_command_no_crash(self) -> None:
        """Blank commands are no-ops that succeed without killing the shell."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await asyncio.wait_for(session.execute("   ", timeout=5), timeout=6)
            assert result.success
            assert result.exit_code == 0
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_comment_then_command(self) -> None:
        """A leading comment line does not interfere with the real command."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute("# header\necho real")
            assert result.success
            assert "real" in result.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_exit_inside_loop(self) -> None:
        """exit() interceptor works from inside a compound command."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute("for i in 1 2; do exit 7; done")
            assert not result.success
            assert result.exit_code == 7
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_trailing_backslash_no_hang(self) -> None:
        """A trailing backslash continuation must not hang or crash the shell."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            _ = await asyncio.wait_for(session.execute("echo a \\", timeout=5), timeout=6)
            assert session.is_alive
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_set_e_crash_emits_markers_not_sentinel(self) -> None:
        """Errexit crash (``set -e`` failing) terminates the non-interactive
        shell, but the injected EXIT trap still emits the marker pair with the
        real rc — the result reports the failure instead of misreporting an
        unexpected crash (which would trigger a pointless recovery)."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute("set -e; false; echo NEVER")
            assert not result.success
            assert result.exit_code == 1
            assert result.error is None or "Session process ended unexpectedly" not in result.error
            assert "NEVER" not in result.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_stream_path_scrubs_sensitive_info(self) -> None:
        """execute_stream PII-scrubs the real-time SSE output like the execute
        path: host paths and credential tokens must not reach the UI."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            chunks = []
            async for chunk in session.execute_stream(
                "echo /Users/alice/secret sk-ant-abcdefghijklmnopqrstuvwxyz123456"
            ):
                chunks.append(chunk)
            combined = "".join(chunks)
            assert "/Users/alice" not in combined
            assert "sk-ant-abcdefghijklmnopqrstuvwxyz123456" not in combined
            assert "<HOME>" in combined
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
                "myrm_agent_harness.toolkits.code_execution.session.stream_output_processor._TEE_MAX_BYTES",
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
                    assert "[System Warning: Tee log file exceeded 50MB hard limit and was truncated.]" in content

        finally:
            await session.close()
