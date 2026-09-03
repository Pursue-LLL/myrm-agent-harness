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

    def test_cat_heredoc_extraction_with_trailing_python3(self):
        cmd = (
            "cat > /tmp/query_12306.py << 'EOF'\n"
            "import asyncio\n"
            "from skills.mcp_12306_skill import get_station_code_of_citys\n"
            "asyncio.run(get_station_code_of_citys(citys='北京'))\n"
            "EOF\n"
            "python3 /tmp/query_12306.py"
        )
        result = extract_python_from_bash(cmd)
        assert result is not None
        assert "import asyncio" in result
        assert "get_station_code_of_citys" in result
        assert "cat >" not in result
        assert validate_python_syntax(result) is None

    def test_cat_heredoc_shell_wrapper_does_not_return_raw_command(self):
        cmd = "cat > /tmp/x.py << EOF\nfrom skills.mcp_12306_skill import get_tickets\nEOF"
        result = extract_python_from_bash(cmd)
        assert result == "from skills.mcp_12306_skill import get_tickets"

    def test_skill_import_inside_shell_wrapper_returns_none(self):
        cmd = "cat broken\nfrom skills.daily_briefing_skill import run"
        assert extract_python_from_bash(cmd) is None

    def test_cat_heredoc_yaml_content_returns_none(self):
        cmd = (
            "cat > .myrm/filters.yaml << 'EOF'\n"
            "filters:\n"
            "  - name: e2e-filter-run\n"
            "    match_command: 'run\\\\.sh'\n"
            "EOF"
        )
        assert extract_python_from_bash(cmd) is None

    def test_cat_heredoc_shell_script_returns_none(self):
        cmd = "cat > run.sh << 'EOF'\n#!/bin/bash\necho 'E2E_BEGIN_LINE ok'\nEOF"
        assert extract_python_from_bash(cmd) is None

    def test_cat_heredoc_python_file_still_extracted(self):
        cmd = "cat > /tmp/run.py << 'EOF'\nimport os\nprint(os.getcwd())\nEOF"
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


class TestExtractCatPyPathsFromPipeFeeders:
    def test_cat_py_pipe_python3(self):
        from myrm_agent_harness.toolkits.code_execution.python_extractor import (
            extract_cat_py_paths_from_pipe_feeders,
        )

        paths = extract_cat_py_paths_from_pipe_feeders("cat /workspace/run.py | python3")
        assert paths == ["/workspace/run.py"]

    def test_cat_py_pipe_grep_not_extracted(self):
        from myrm_agent_harness.toolkits.code_execution.python_extractor import (
            extract_cat_py_paths_from_pipe_feeders,
        )

        assert extract_cat_py_paths_from_pipe_feeders("cat run.py | grep x") == []

    def test_python_c_not_cat_pipe_surface(self):
        from myrm_agent_harness.toolkits.code_execution.python_extractor import (
            extract_cat_py_paths_from_pipe_feeders,
        )

        assert extract_cat_py_paths_from_pipe_feeders('python3 -c "print(1)"') == []


class TestValidatePythonSyntax:
    def test_valid_code_returns_none(self):
        assert validate_python_syntax("print(1)") is None

    def test_top_level_await_syntax_allowed(self):
        code = "res = await fetch_data()\nprint(res)"
        assert validate_python_syntax(code) is None

    def test_top_level_await_with_actual_syntax_error_still_fails(self):
        code = "res = await fetch_data(\nprint(res)"
        error = validate_python_syntax(code)
        assert error is not None
        assert "SyntaxError" in error

    def test_invalid_code_returns_error_message(self):
        error = validate_python_syntax("def broken(")
        assert error is not None
        assert "SyntaxError" in error

    def test_invalid_code_includes_line_number(self):
        error = validate_python_syntax("x = \n def bad(")
        assert error is not None
        assert "line" in error
