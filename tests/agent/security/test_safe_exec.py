"""Tests for security.safe_exec — safe command execution with shell/direct mode."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.security.safe_exec import ExecResult, _kill_process_tree, needs_shell, safe_exec
from myrm_agent_harness.core.security.types import (
    EphemeralUserCredential,
    with_user_credentials,
)


class TestNeedsShell:
    def test_simple_command(self) -> None:
        assert needs_shell("ls -la") is False

    def test_pipe(self) -> None:
        assert needs_shell("cat file | grep foo") is True

    def test_redirect(self) -> None:
        assert needs_shell("echo hello > out.txt") is True

    def test_ampersand(self) -> None:
        assert needs_shell("sleep 10 &") is True

    def test_semicolon(self) -> None:
        assert needs_shell("echo a; echo b") is True

    def test_dollar_expansion(self) -> None:
        assert needs_shell("echo $HOME") is True

    def test_backtick(self) -> None:
        assert needs_shell("echo `date`") is True

    def test_glob_star(self) -> None:
        assert needs_shell("ls *.py") is True

    def test_parentheses(self) -> None:
        assert needs_shell("(cd /tmp && ls)") is True

    def test_quoted_args_no_shell(self) -> None:
        assert needs_shell('echo "hello world"') is False

    def test_backslash_no_shell(self) -> None:
        assert needs_shell("echo hello\\ world") is False


class TestExecResult:
    def test_frozen(self) -> None:
        r = ExecResult(stdout="ok", stderr="", returncode=0, mode="direct")
        with pytest.raises(AttributeError):
            r.stdout = "changed"  # type: ignore[misc]


@pytest.mark.asyncio
class TestSafeExec:
    async def test_direct_mode_simple(self) -> None:
        result = await safe_exec("echo hello", timeout=10)
        assert result.mode == "direct"
        assert result.returncode == 0
        assert "hello" in result.stdout

    async def test_shell_mode_pipe(self) -> None:
        result = await safe_exec("echo hello | cat", timeout=10)
        assert result.mode == "shell"
        assert "hello" in result.stdout

    async def test_empty_command(self) -> None:
        result = await safe_exec("", timeout=5)
        assert result.returncode == 1
        assert result.mode == "direct"

    async def test_nonzero_exit(self) -> None:
        result = await safe_exec("false", timeout=5)
        assert result.returncode != 0

    async def test_stderr_capture(self) -> None:
        result = await safe_exec("ls /nonexistent_path_xyz_12345", timeout=5)
        assert result.returncode != 0
        assert result.stderr != ""

    async def test_timeout(self) -> None:
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await safe_exec("sleep 60", timeout=1)


@pytest.mark.asyncio
class TestSafeExecEnvSanitization:
    """Env sanitization must prevent injection/escape through safe_exec."""

    async def test_explicit_env_strips_dangerous_vars(self) -> None:
        """Dangerous vars passed explicitly must be removed before launch."""
        result = await safe_exec(
            "env",
            timeout=10,
            env={
                "LD_PRELOAD": "/tmp/evil.so",
                "PYTHONPATH": "/tmp/evil",
                "MY_APP_TOKEN": "sekrit",
                "SAFE_FLAG": "keep-me",
            },
        )
        assert result.returncode == 0
        assert "LD_PRELOAD" not in result.stdout
        assert "PYTHONPATH" not in result.stdout
        assert "MY_APP_TOKEN" not in result.stdout
        assert "SAFE_FLAG=keep-me" in result.stdout

    async def test_inherited_parent_env_is_sanitized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Host pollution must not leak into subprocess environment, while safe core vars pass."""
        monkeypatch.setenv("LD_PRELOAD", "/tmp/evil.so")
        monkeypatch.setenv("PYTHONHOME", "/tmp/evil")
        monkeypatch.setenv("MY_SERVICE_API_KEY", "sekrit")
        monkeypatch.setenv("PAGER", "test-safe-pager")
        result = await safe_exec("env", timeout=10)
        assert result.returncode == 0
        assert "LD_PRELOAD" not in result.stdout
        assert "PYTHONHOME" not in result.stdout
        assert "MY_SERVICE_API_KEY" not in result.stdout
        assert "PAGER=test-safe-pager" in result.stdout

    async def test_credential_injection_overrides_sanitized_env(self) -> None:
        """Authentic credentials are injected after sanitization and must reach child."""
        credential = EphemeralUserCredential(issuer="github", token="real-user-token")
        async with with_user_credentials((credential,)):
            result = await safe_exec(
                "env",
                timeout=10,
                env={"GITHUB_TOKEN": "evil-parent-token"},
                allowed_issuers=["github"],
            )
        assert result.returncode == 0
        assert "real-user-token" in result.stdout
        assert "evil-parent-token" not in result.stdout


class TestKillProcessTreeSafety:
    """Validate _kill_process_tree does not kill parent when pgid is shared."""

    def test_same_pgid_falls_back_to_proc_kill(self) -> None:
        """When child shares parent's process group, only os.kill is called."""
        mock_proc = MagicMock(spec=asyncio.subprocess.Process)
        mock_proc.pid = 12345

        my_pgid = os.getpgid(os.getpid())

        with (
            patch("myrm_agent_harness.utils.os_compat.os.getpgid", return_value=my_pgid),
            patch("myrm_agent_harness.utils.os_compat.os.kill") as mock_kill,
            patch("myrm_agent_harness.utils.os_compat.os.killpg") as mock_killpg,
        ):
            _kill_process_tree(mock_proc)
            import signal

            mock_kill.assert_called_once_with(12345, signal.SIGKILL)
            mock_killpg.assert_not_called()

    def test_different_pgid_kills_group(self) -> None:
        """When child has its own process group, killpg is used."""
        import signal

        mock_proc = MagicMock(spec=asyncio.subprocess.Process)
        mock_proc.pid = 99999

        real_my_pgid = os.getpgid(os.getpid())

        with (
            patch(
                "myrm_agent_harness.utils.os_compat.os.getpgid",
                side_effect=lambda pid: 99999 if pid == 99999 else real_my_pgid,
            ),
            patch("myrm_agent_harness.utils.os_compat.os.killpg") as mock_killpg,
            patch("myrm_agent_harness.utils.os_compat.os.kill") as mock_kill,
        ):
            _kill_process_tree(mock_proc)
            mock_killpg.assert_called_once_with(99999, signal.SIGKILL)
            mock_kill.assert_not_called()

    def test_pid_none_returns_early(self) -> None:
        """If proc.pid is None, should return without error."""
        mock_proc = MagicMock(spec=asyncio.subprocess.Process)
        mock_proc.pid = None

        with patch("myrm_agent_harness.utils.os_compat.os.killpg") as mock_killpg:
            _kill_process_tree(mock_proc)
            mock_killpg.assert_not_called()

    def test_process_lookup_error_handled(self) -> None:
        """ProcessLookupError should be silently caught."""
        mock_proc = MagicMock(spec=asyncio.subprocess.Process)
        mock_proc.pid = 88888

        with patch("myrm_agent_harness.utils.os_compat.os.getpgid", side_effect=ProcessLookupError):
            _kill_process_tree(mock_proc)

    def test_credential_env_overrides_xai(self) -> None:
        from myrm_agent_harness.core.security.safe_exec import credential_env_overrides

        creds = (
            EphemeralUserCredential(issuer="xai", token="test-key-123", scope="https://custom.x.ai/v1"),
            EphemeralUserCredential(issuer="google_workspace", token="goog-token-abc"),
        )
        env = credential_env_overrides(creds)
        assert env["XAI_API_KEY"] == "test-key-123"
        assert env["XAI_BASE_URL"] == "https://custom.x.ai/v1"
        assert env["GOOGLE_WORKSPACE_TOKEN"] == "goog-token-abc"
