"""Tests for python_extractor SSOT — quote-aware extraction and syntax validation."""

from myrm_agent_harness.toolkits.code_execution.python_extractor import (
    extract_python_from_bash,
    extract_python_from_pipe_stdin,
    validate_python_syntax,
)


class TestExtractPythonFromBash:
    def test_python_c_double_quotes(self):
        assert extract_python_from_bash('python3 -c "print(1)"') == "print(1)"

    def test_python_c_single_quotes_with_escape(self):
        cmd = r"python -c 'print(\"hi\")'"
        result = extract_python_from_bash(cmd)
        assert result is not None
        assert "print" in result

    def test_python_c_empty_rest_returns_none(self):
        assert extract_python_from_bash("python3 -c ") is None

    def test_heredoc_extraction(self):
        cmd = "python3 <<EOF\nimport os\nprint(os.getcwd())\nEOF"
        result = extract_python_from_bash(cmd)
        assert result is not None
        assert "import os" in result

    def test_skill_import_raw_python(self):
        cmd = "from skills.daily_briefing_skill import run"
        assert extract_python_from_bash(cmd) == cmd

    def test_tools_import_raw_python(self):
        cmd = "from tools.notify import send"
        assert extract_python_from_bash(cmd) == cmd

    def test_non_python_command_returns_none(self):
        assert extract_python_from_bash("ls -la") is None

    def test_unclosed_quote_returns_partial_or_none(self):
        result = extract_python_from_bash('python3 -c "unclosed')
        assert result is None or isinstance(result, str)


class TestExtractPythonFromPipeStdin:
    def test_printf_pipe_python3(self):
        result = extract_python_from_pipe_stdin('printf "import myrm_tools" | python3')
        assert result == "import myrm_tools"

    def test_echo_skills_pipe_allowed_extraction(self):
        result = extract_python_from_pipe_stdin('echo "from skills.x import y" | python3')
        assert result == "from skills.x import y"

    def test_python_c_not_pipe_stdin_surface(self):
        assert extract_python_from_pipe_stdin('python -c "print(1)"') is None

    def test_pipe_to_grep_not_python_stdin(self):
        assert extract_python_from_pipe_stdin('echo "import myrm_tools" | grep x') is None

    def test_echo_unquoted_pipe_python3(self):
        result = extract_python_from_pipe_stdin("echo import myrm_tools | python3")
        assert result == "import myrm_tools"


class TestValidatePythonSyntax:
    def test_valid_code_returns_none(self):
        assert validate_python_syntax("print(1)") is None

    def test_invalid_code_returns_error_message(self):
        error = validate_python_syntax("def broken(")
        assert error is not None
        assert "SyntaxError" in error

    def test_invalid_code_includes_line_number(self):
        error = validate_python_syntax("x = \n def bad(")
        assert error is not None
        assert "line" in error
