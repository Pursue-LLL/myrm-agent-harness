"""Unit tests for exit code semantic interpretation.

Covers _interpret_exit_code and its integration in _format_result.
"""

import pytest

from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import _format_result, _interpret_exit_code


class TestInterpretExitCode:
    """Tests for _interpret_exit_code pure function."""

    @pytest.mark.parametrize(
        "command,exit_code",
        [
            ("grep 'foo' bar.txt", 0),
            ("ls -la", 0),
            ("git diff HEAD~1", 0),
        ],
    )
    def test_returns_none_for_zero(self, command: str, exit_code: int) -> None:
        assert _interpret_exit_code(command, exit_code) is None

    @pytest.mark.parametrize(
        "command,exit_code,expected_fragment",
        [
            ("grep 'pattern' file.txt", 1, "No matches"),
            ("egrep -r 'todo' .", 1, "No matches"),
            ("rg 'needle'", 1, "No matches"),
            ("ag 'needle'", 1, "No matches"),
            ("ack 'pattern'", 1, "No matches"),
        ],
    )
    def test_search_commands_exit_1(self, command: str, exit_code: int, expected_fragment: str) -> None:
        result = _interpret_exit_code(command, exit_code)
        assert result is not None
        assert expected_fragment in result

    @pytest.mark.parametrize(
        "command,exit_code,expected_fragment",
        [
            ("diff a.txt b.txt", 1, "differ"),
            ("colordiff a.txt b.txt", 1, "differ"),
        ],
    )
    def test_diff_exit_1(self, command: str, exit_code: int, expected_fragment: str) -> None:
        result = _interpret_exit_code(command, exit_code)
        assert result is not None
        assert expected_fragment in result

    @pytest.mark.parametrize(
        "command,exit_code,expected_fragment",
        [
            ("test -f /tmp/missing", 1, "false"),
            ("[ -d /tmp/missing ]", 1, "false"),
        ],
    )
    def test_test_bracket_exit_1(self, command: str, exit_code: int, expected_fragment: str) -> None:
        result = _interpret_exit_code(command, exit_code)
        assert result is not None
        assert expected_fragment in result

    @pytest.mark.parametrize(
        "command,exit_code,expected_fragment",
        [
            ("curl https://example.com", 6, "resolve host"),
            ("curl https://example.com", 7, "connect"),
            ("curl https://example.com", 28, "timed out"),
            ("curl https://example.com", 22, "HTTP"),
        ],
    )
    def test_curl_exit_codes(self, command: str, exit_code: int, expected_fragment: str) -> None:
        result = _interpret_exit_code(command, exit_code)
        assert result is not None
        assert expected_fragment in result

    @pytest.mark.parametrize(
        "command,exit_code,expected_fragment",
        [
            ("pytest tests/", 1, "tests failed"),
            ("pytest tests/", 2, "interrupted"),
            ("pytest tests/", 5, "No tests were collected"),
        ],
    )
    def test_pytest_exit_codes(self, command: str, exit_code: int, expected_fragment: str) -> None:
        result = _interpret_exit_code(command, exit_code)
        assert result is not None
        assert expected_fragment in result

    @pytest.mark.parametrize(
        "command,exit_code,expected_fragment",
        [
            ("which python3", 1, "not found"),
            ("command -v node", 1, "not found"),
        ],
    )
    def test_which_command_exit_1(self, command: str, exit_code: int, expected_fragment: str) -> None:
        result = _interpret_exit_code(command, exit_code)
        assert result is not None
        assert expected_fragment in result

    def test_cmp_exit_1(self) -> None:
        result = _interpret_exit_code("cmp file1 file2", 1)
        assert result is not None
        assert "differ" in result

    def test_unknown_command_returns_none(self) -> None:
        assert _interpret_exit_code("my_custom_tool --run", 42) is None

    def test_known_command_signal_code_returns_signal(self) -> None:
        result = _interpret_exit_code("grep foo bar", 137)
        assert result is not None
        assert "SIGKILL" in result


class TestInterpretGitSubcommands:
    """Tests for git subcommand-level exit code interpretation."""

    @pytest.mark.parametrize(
        "command,exit_code,expected_fragment",
        [
            ("git diff HEAD~1", 1, "differences"),
            ("git grep 'pattern'", 1, "No matches"),
            ("git log --grep='missing'", 1, "No commits"),
            ("git stash", 1, "Nothing to stash"),
            ("git branch my-branch", 1, "not found"),
        ],
    )
    def test_git_subcommands(self, command: str, exit_code: int, expected_fragment: str) -> None:
        result = _interpret_exit_code(command, exit_code)
        assert result is not None
        assert expected_fragment in result

    def test_git_unknown_subcommand_returns_none(self) -> None:
        assert _interpret_exit_code("git merge --abort", 1) is None

    def test_git_with_flags_before_subcommand(self) -> None:
        result = _interpret_exit_code("git -c core.pager='' diff HEAD", 1)
        assert result is not None
        assert "differences" in result


class TestPipesAndChains:
    """Tests for pipeline and command chain parsing."""

    def test_pipe_last_command(self) -> None:
        result = _interpret_exit_code("cat file.txt | grep 'pattern'", 1)
        assert result is not None
        assert "No matches" in result

    def test_and_chain_last_command(self) -> None:
        result = _interpret_exit_code("cd /tmp && grep 'x' f.txt", 1)
        assert result is not None
        assert "No matches" in result

    def test_or_chain_last_command(self) -> None:
        result = _interpret_exit_code("false || grep 'x' f.txt", 1)
        assert result is not None
        assert "No matches" in result

    def test_semicolon_chain(self) -> None:
        result = _interpret_exit_code("echo hello; diff a b", 1)
        assert result is not None
        assert "differ" in result


class TestEnvPrefixAndAbsPath:
    """Tests for environment variable prefix stripping and absolute paths."""

    def test_env_prefix_stripped(self) -> None:
        result = _interpret_exit_code("FOO=bar grep 'pattern' file", 1)
        assert result is not None
        assert "No matches" in result

    def test_absolute_path_stripped(self) -> None:
        result = _interpret_exit_code("/usr/bin/grep 'pattern' file", 1)
        assert result is not None
        assert "No matches" in result

    def test_env_and_abs_path_combined(self) -> None:
        result = _interpret_exit_code("LANG=C /usr/local/bin/diff a b", 1)
        assert result is not None
        assert "differ" in result


class TestSignalExitCodes:
    """Tests for signal-based exit code fallback (exit > 128)."""

    @pytest.mark.parametrize(
        "exit_code,expected_signal",
        [
            (130, "SIGINT"),
            (134, "SIGABRT"),
            (137, "SIGKILL"),
            (139, "SIGSEGV"),
            (141, "SIGPIPE"),
            (143, "SIGTERM"),
        ],
    )
    def test_signal_exit_codes(self, exit_code: int, expected_signal: str) -> None:
        result = _interpret_exit_code("some_long_running_cmd", exit_code)
        assert result is not None
        assert expected_signal in result

    def test_unknown_signal_returns_none(self) -> None:
        assert _interpret_exit_code("some_cmd", 129) is None

    def test_signal_fallback_after_command_specific(self) -> None:
        result = _interpret_exit_code("grep pattern file", 137)
        assert result is not None
        assert "SIGKILL" in result


class TestFormatResultIntegration:
    """Tests for exit code semantics integration in _format_result."""

    def test_exit_0_no_annotation(self) -> None:
        result, _, _ = _format_result({"stdout": "ok", "exit_code": "0"}, "grep foo bar")
        assert "exit_code" not in result

    def test_known_semantic_annotated(self) -> None:
        result, _, _ = _format_result({"stdout": "", "exit_code": "1"}, "grep foo bar")
        assert "No matches" in result
        assert "exit_code: 1" in result

    def test_unknown_semantic_plain(self) -> None:
        result, _, _ = _format_result({"stdout": "", "exit_code": "42"}, "some_unknown_cmd")
        assert "exit_code: 42" in result
        assert "—" not in result

    def test_backward_compat_no_command(self) -> None:
        result, _, _ = _format_result({"stdout": "", "exit_code": "1"})
        assert "exit_code: 1" in result
        assert "—" not in result


class TestClassifyBackgroundExit:
    """Tests for ``_classify_background_exit`` (PR2.6 O8)."""

    def _info(self, status: str, exit_code: int | None) -> object:
        from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
            BackgroundProcessInfo,
        )

        return BackgroundProcessInfo(
            pid=4321,
            command="dummy",
            session_id="s",
            started_at=0.0,
            status=status,  # type: ignore[arg-type]
            exit_code=exit_code,
        )

    def test_clean_exit_returns_none(self) -> None:
        from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import (
            _classify_background_exit,
        )

        assert _classify_background_exit(self._info("exited", 0)) is None

    @pytest.mark.parametrize(
        "exit_code,expected",
        [
            (137, "oom_killed"),
            (139, "segfault"),
            (143, "signal_terminated"),
            (-9, "signal_terminated"),
            (-15, "signal_terminated"),
            (42, "nonzero_exit"),
        ],
    )
    def test_known_codes_mapped(self, exit_code: int, expected: str) -> None:
        from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import (
            _classify_background_exit,
        )

        assert _classify_background_exit(self._info("exited", exit_code)) == expected

    def test_user_kill_with_positive_code_is_silent(self) -> None:
        """A user-initiated kill should not raise an alarming category."""
        from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import (
            _classify_background_exit,
        )

        # SIGINT shell-style code (130) coming from a user-initiated stop must
        # not be surfaced as ``nonzero_exit``.
        assert _classify_background_exit(self._info("killed", 130)) is None
