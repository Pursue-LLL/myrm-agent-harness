"""Tests for non-zero exit code classification."""


from myrm_agent_harness.toolkits.code_execution.executors.common.exit_classify import (
    _extract_base_command,
    classify_exit_code,
)


class TestExtractBaseCommand:
    def test_simple_command(self) -> None:
        assert _extract_base_command("grep -r 'TODO' src/") == "grep"

    def test_absolute_path(self) -> None:
        assert _extract_base_command("/usr/bin/diff file1 file2") == "diff"

    def test_sudo_prefix(self) -> None:
        assert _extract_base_command("sudo rg 'pattern' .") == "rg"

    def test_pipe_takes_last(self) -> None:
        assert _extract_base_command("cat file | grep foo") == "grep"

    def test_pipe_diff_last(self) -> None:
        assert _extract_base_command("sort file | diff - other") == "diff"

    def test_leading_whitespace(self) -> None:
        assert _extract_base_command("  grep foo bar") == "grep"

    def test_empty_string(self) -> None:
        assert _extract_base_command("") == ""


class TestClassifyExitCode:
    def test_exit_zero_always_success(self) -> None:
        assert classify_exit_code("any command", 0, "") is True

    def test_grep_no_match_with_stdout(self) -> None:
        assert classify_exit_code("grep -r 'TODO' src/", 1, "") is True

    def test_grep_no_match_informational(self) -> None:
        assert classify_exit_code("grep -r 'pattern' .", 1, "some output") is True

    def test_rg_no_match_informational(self) -> None:
        assert classify_exit_code("rg 'pattern' src/", 1, "file.py:10:match") is True

    def test_diff_has_changes(self) -> None:
        assert classify_exit_code("diff file1 file2", 1, "< line1\n> line2") is True

    def test_diff_with_path(self) -> None:
        assert classify_exit_code("/usr/bin/diff a.txt b.txt", 1, "1c1") is True

    def test_exit_code_2_is_error(self) -> None:
        assert classify_exit_code("grep -r 'foo' .", 2, "output") is False

    def test_unknown_command_exit_1_is_error(self) -> None:
        assert classify_exit_code("python script.py", 1, "Traceback...") is False

    def test_curl_exit_1_is_error(self) -> None:
        assert classify_exit_code("curl http://example.com", 1, "data") is False

    def test_empty_stdout_is_error(self) -> None:
        assert classify_exit_code("grep foo bar", 1, "   ") is True

    def test_ag_informational(self) -> None:
        assert classify_exit_code("ag 'pattern' src/", 1, "result line") is True

    def test_egrep_informational(self) -> None:
        assert classify_exit_code("egrep 'regex' file.txt", 1, "matched") is True

    def test_pipe_grep_last_informational(self) -> None:
        assert classify_exit_code("cat file | grep pattern", 1, "match") is True

    def test_pipe_diff_last_informational(self) -> None:
        assert classify_exit_code("sort a | diff - b", 1, "1c1\n< x\n> y") is True
