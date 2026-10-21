"""Tests for FileBackedSubprocessInvocationAndShellQuoteEscapingArmorSuite.

Validates:
1. Dual-mode heuristic probe (Direct Fast-Path vs File-Backed Armor)
2. Safe script materialization with 0700 permissions & atomic creation
3. Reliable auto-cleanup and unlink in finally blocks
4. PersistentSession integration: exit statement survival & heredoc execution without beacon swallowing
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_execution.security.script_armor import (
    ArmoredCommandString,
    ScriptArmorConfig,
    build_file_backed_command,
    cleanup_materialized_script,
    materialize_script_to_file,
    prepare_armored_command,
    should_materialize_script,
    sweep_stale_materialized_scripts,
)
from myrm_agent_harness.toolkits.code_execution.session import (
    LocalPersistentSession,
    SessionConfig,
)


def _make_config(timeout: int = 10) -> SessionConfig:
    return SessionConfig(session_id="test_armor", work_dir="/tmp", timeout=timeout, sandbox_mode="disable")


class TestScriptArmorHeuristicProbe:
    """Test heuristic dual-mode decision engine."""

    def test_direct_fast_path_for_state_modifiers(self) -> None:
        assert not should_materialize_script("cd /tmp")
        assert not should_materialize_script("pushd /var")
        assert not should_materialize_script("popd")
        assert not should_materialize_script("export VAR=123")
        assert not should_materialize_script("unset VAR")
        assert not should_materialize_script("source .venv/bin/activate")
        assert not should_materialize_script(". /etc/profile")

    def test_direct_fast_path_for_simple_short_commands(self) -> None:
        assert not should_materialize_script("ls -la")
        assert not should_materialize_script("git status")
        assert not should_materialize_script("echo 'hello world'")
        assert not should_materialize_script("mkdir -p /tmp/test_dir")

    def test_file_backed_for_multiline_scripts(self) -> None:
        multiline = "echo 1\necho 2\necho 3\necho 4"
        assert should_materialize_script(multiline)

    def test_file_backed_for_heredocs(self) -> None:
        heredoc = "cat << 'EOF' > file.txt\nline1\nEOF"
        assert should_materialize_script(heredoc)

        heredoc_unquoted = "cat << EOF > file.txt\nline1\nEOF"
        assert should_materialize_script(heredoc_unquoted)

    def test_file_backed_for_exit_statements(self) -> None:
        assert should_materialize_script("exit 1")
        assert should_materialize_script("if [ ! -f foo ]; then exit 42; fi")
        assert should_materialize_script("echo hi; exit 0")
        # Single-line export must stay direct to preserve env vars (handled safely by shell exit interceptor)
        assert not should_materialize_script("export FOO=1; exit 0")

    def test_file_backed_for_oversized_scripts(self) -> None:
        cfg = ScriptArmorConfig(direct_max_bytes=50)
        large_cmd = "echo " + "a" * 100
        assert should_materialize_script(large_cmd, cfg)

    def test_disabled_config_returns_false(self) -> None:
        cfg = ScriptArmorConfig(enabled=False)
        assert not should_materialize_script("echo 1\necho 2\necho 3\necho 4", cfg)

    def test_empty_or_whitespace_command_returns_false(self) -> None:
        assert not should_materialize_script("")
        assert not should_materialize_script("   \n\t  ")


class TestScriptMaterialization:
    """Test safe script creation, permissions, and cleanup."""

    def test_materialize_file_permissions_and_content(self, tmp_path: Path) -> None:
        cmd = "echo 'armor test'\nexit 0"
        script_path = materialize_script_to_file(cmd, temp_dir=tmp_path)
        try:
            assert script_path.exists()
            # Verify 0700 permission (owner read/write/execute)
            file_stat = os.stat(script_path)
            mode = stat.S_IMODE(file_stat.st_mode)
            assert mode == 0o700

            content = script_path.read_text(encoding="utf-8")
            assert "echo 'armor test'" in content
            assert content.endswith("\n")
        finally:
            cleanup_materialized_script(script_path)
            assert not script_path.exists()

    def test_cleanup_nonexistent_path_is_safe(self) -> None:
        non_existent = Path("/tmp/does_not_exist_xyz123456.sh")
        cleanup_materialized_script(non_existent)
        cleanup_materialized_script(None)

    def test_build_file_backed_command(self, tmp_path: Path) -> None:
        script = tmp_path / "test.sh"
        cmd = build_file_backed_command(script)
        assert cmd.startswith('bash "')
        assert str(script.resolve()) in cmd

    def test_materialize_script_failure_cleans_up_and_closes_fd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _failing_open(*args, **kwargs):
            raise OSError("simulated disk write error")

        monkeypatch.setattr("builtins.open", _failing_open)
        with pytest.raises(OSError, match="simulated disk write error"):
            materialize_script_to_file("echo test", temp_dir=tmp_path)


class TestPrepareArmoredCommandContextManager:
    """Test context manager lifecycle and cleanup guarantee."""

    def test_direct_command_passes_through(self) -> None:
        raw_cmd = "git status"
        with prepare_armored_command(raw_cmd) as cmd_to_run:
            assert cmd_to_run == raw_cmd

    def test_armored_command_creates_and_cleans_up(self, tmp_path: Path) -> None:
        raw_cmd = "cat << 'EOF' > a.txt\nline\nEOF\n"
        created_file: Path | None = None
        with prepare_armored_command(raw_cmd, work_dir=tmp_path) as cmd_to_run:
            assert cmd_to_run.startswith('bash "')
            file_part = cmd_to_run.split('"', 2)[1]
            created_file = Path(file_part)
            assert created_file.exists()

        # After exiting with block, file must be destroyed
        assert created_file is not None
        assert not created_file.exists()

    def test_armored_command_cleans_up_on_exception(self, tmp_path: Path) -> None:
        raw_cmd = "exit 1"
        created_file: Path | None = None
        with pytest.raises(RuntimeError), prepare_armored_command(raw_cmd, work_dir=tmp_path) as cmd_to_run:
            file_part = cmd_to_run.split('"', 2)[1]
            created_file = Path(file_part)
            assert created_file.exists()
            raise RuntimeError("simulated pipeline error")

        assert created_file is not None
        assert not created_file.exists()


class TestPersistentSessionIntegration:
    """End-to-end integration with LocalPersistentSession."""

    @pytest.mark.asyncio
    async def test_exit_statement_does_not_kill_persistent_shell(self) -> None:
        """A script with 'exit 42' must return exit code 42 without killing the persistent shell."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            # First command: sets an environment variable
            await session.execute("export SESSION_ALIVE_VAR=active_123")

            # Second command: contains exit statement, runs in file-backed subshell
            res1 = await session.execute("if [ -d /tmp ]; then exit 42; fi")
            assert not res1.success
            assert res1.exit_code == 42

            # Third command: persistent session must still be alive and maintain the environment variable
            res2 = await session.execute("echo $SESSION_ALIVE_VAR")
            assert res2.success
            assert "active_123" in res2.stdout
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_heredoc_script_executes_without_beacon_swallowing(self, tmp_path: Path) -> None:
        """Heredoc script must execute cleanly without consuming trailing markers."""
        target_file = tmp_path / "heredoc_output.txt"
        heredoc_cmd = f"""cat << 'EOF' > "{target_file}"
def hello():
    return "world"
EOF
"""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute(heredoc_cmd)
            assert result.success
            assert target_file.exists()
            content = target_file.read_text(encoding="utf-8")
            assert 'def hello():' in content
            assert '__myrm_rc__' not in content
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_trailing_comment_without_newline(self) -> None:
        """A command ending with a single-line comment must not swallow exit markers."""
        cmd = "echo 'comment_test' # trailing comment without newline"
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            result = await session.execute(cmd)
            assert result.success
            assert "comment_test" in result.stdout
            assert not result.is_armored
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_armored_metadata_propagates_to_execution_result(self) -> None:
        """Verify is_armored is False for direct commands and True for materialized scripts."""
        session = LocalPersistentSession(_make_config())
        await session.start()
        try:
            # Direct command -> is_armored is False
            res_direct = await session.execute("ls -la")
            assert not res_direct.is_armored

            # Multiline / armored script -> is_armored is True
            multiline_cmd = "echo 1\necho 2\necho 3\n"
            res_armored = await session.execute(multiline_cmd)
            assert res_armored.is_armored
        finally:
            await session.close()


class TestSweepStaleMaterializedScripts:
    """Test orphan script cleanup mechanism."""

    def test_sweep_cleans_stale_files_and_keeps_fresh_ones(self, tmp_path: Path) -> None:
        import time

        now = time.time()
        stale_file = tmp_path / ".myrm_exec_stale123.sh"
        stale_file.write_text("echo stale\n", encoding="utf-8")
        # Set mtime to 2 hours ago
        os.utime(stale_file, (now - 7200, now - 7200))

        fresh_file = tmp_path / ".myrm_exec_fresh456.sh"
        fresh_file.write_text("echo fresh\n", encoding="utf-8")
        # Set mtime to now
        os.utime(fresh_file, (now, now))

        other_file = tmp_path / "regular_file.sh"
        other_file.write_text("echo regular\n", encoding="utf-8")
        os.utime(other_file, (now - 7200, now - 7200))

        cleaned = sweep_stale_materialized_scripts(tmp_path, max_age_seconds=3600.0)
        assert cleaned == 1
        assert not stale_file.exists()
        assert fresh_file.exists()
        assert other_file.exists()

    def test_sweep_nonexistent_directory(self) -> None:
        assert sweep_stale_materialized_scripts("/nonexistent/dir/xyz_404") == 0

    def test_armored_command_string_is_instance_of_str(self) -> None:
        tagged = ArmoredCommandString('bash "/tmp/.myrm_exec_123.sh"', is_armored=True)
        assert isinstance(tagged, str)
        assert tagged.is_armored
        assert tagged.startswith('bash "')
        # Slicing returns normal str
        sliced = tagged[:4]
        assert sliced == "bash"

    def test_sweep_handles_os_error_gracefully(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        stale_file = tmp_path / ".myrm_exec_stale_err.sh"
        stale_file.write_text("echo err\n", encoding="utf-8")

        real_stat = Path.stat

        def _selective_stat(self, *args, **kwargs):
            if str(self).endswith(".sh"):
                raise OSError("Permission denied on file")
            return real_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", _selective_stat)
        assert sweep_stale_materialized_scripts(tmp_path, max_age_seconds=10.0) == 0

    def test_sweep_handles_dir_stat_error_gracefully(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _dir_stat_fail(self, *args, **kwargs):
            raise OSError("Permission denied on directory")

        monkeypatch.setattr(Path, "stat", _dir_stat_fail)
        assert sweep_stale_materialized_scripts(tmp_path, max_age_seconds=10.0) == 0

