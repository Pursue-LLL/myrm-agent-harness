"""Tests for shell bleed detection."""

from __future__ import annotations

import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.code_execution.security.shell_bleed import (
    scan_content_for_env_leaks,
    scan_file_for_env_leaks,
)


class TestScanContentForEnvLeaks:
    """Content-level scanning."""

    def test_empty_content(self) -> None:
        assert scan_content_for_env_leaks("") == []

    def test_safe_vars_ignored(self) -> None:
        content = "echo $HOME\necho $PATH\necho $USER"
        assert scan_content_for_env_leaks(content) == []

    def test_detects_shell_var(self) -> None:
        content = 'curl -H "Authorization: $API_KEY"'
        warnings = scan_content_for_env_leaks(content)
        assert len(warnings) == 1
        assert warnings[0].var_name == "API_KEY"
        assert warnings[0].line_number == 1

    def test_detects_shell_braced_var(self) -> None:
        content = "echo ${OPENAI_API_KEY}"
        warnings = scan_content_for_env_leaks(content)
        assert len(warnings) == 1
        assert warnings[0].var_name == "OPENAI_API_KEY"

    def test_detects_python_environ(self) -> None:
        content = 'import os\nkey = os.environ["MY_SECRET"]'
        warnings = scan_content_for_env_leaks(content)
        assert len(warnings) == 1
        assert warnings[0].var_name == "MY_SECRET"
        assert warnings[0].access_pattern == "Python os.environ"

    def test_detects_python_getenv(self) -> None:
        content = "token = os.getenv('AUTH_TOKEN')"
        warnings = scan_content_for_env_leaks(content)
        assert len(warnings) == 1
        assert warnings[0].var_name == "AUTH_TOKEN"

    def test_detects_node_process_env(self) -> None:
        content = "const key = process.env.DATABASE_PASSWORD;"
        warnings = scan_content_for_env_leaks(content)
        assert len(warnings) == 1
        assert warnings[0].var_name == "DATABASE_PASSWORD"

    def test_detects_ruby_env(self) -> None:
        content = 'key = ENV["AWS_SECRET_KEY"]'
        warnings = scan_content_for_env_leaks(content)
        assert len(warnings) == 1
        assert warnings[0].var_name == "AWS_SECRET_KEY"

    def test_non_suspicious_var_ignored(self) -> None:
        content = "echo $CUSTOM_VARIABLE"
        assert scan_content_for_env_leaks(content) == []

    def test_multiple_vars_on_same_line(self) -> None:
        content = "echo $API_KEY $SECRET_TOKEN"
        warnings = scan_content_for_env_leaks(content)
        assert len(warnings) == 2
        var_names = {w.var_name for w in warnings}
        assert var_names == {"API_KEY", "SECRET_TOKEN"}

    def test_deduplicate_same_line(self) -> None:
        content = "echo $API_KEY $API_KEY"
        warnings = scan_content_for_env_leaks(content)
        names = [w.var_name for w in warnings]
        assert names.count("API_KEY") == 1

    def test_multiline_detection(self) -> None:
        content = "line1\necho $MY_PASSWORD\nline3\necho $ANOTHER_SECRET\n"
        warnings = scan_content_for_env_leaks(content)
        assert len(warnings) == 2
        assert warnings[0].line_number == 2
        assert warnings[1].line_number == 4


class TestScanFileForEnvLeaks:
    """File-level scanning."""

    def test_script_file_detected(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sh", mode="w", delete=False) as f:
            f.write('#!/bin/bash\ncurl -H "Auth: $API_KEY" http://example.com\n')
            f.flush()
            warnings = scan_file_for_env_leaks(f.name)
        assert len(warnings) == 1
        Path(f.name).unlink()

    def test_non_script_file_ignored(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("echo $API_KEY")
            f.flush()
            warnings = scan_file_for_env_leaks(f.name)
        assert warnings == []
        Path(f.name).unlink()

    def test_python_file_detected(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write('import os\nkey = os.environ["MY_SECRET_KEY"]\n')
            f.flush()
            warnings = scan_file_for_env_leaks(f.name)
        assert len(warnings) == 1
        Path(f.name).unlink()

    def test_nonexistent_file(self) -> None:
        warnings = scan_file_for_env_leaks("/nonexistent/path/script.sh")
        assert warnings == []

    def test_empty_script_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sh", mode="w", delete=False) as f:
            f.write("")
            f.flush()
            warnings = scan_file_for_env_leaks(f.name)
        assert warnings == []
        Path(f.name).unlink()

    def test_oversized_file_skipped(self) -> None:
        from unittest.mock import patch

        with tempfile.NamedTemporaryFile(suffix=".sh", mode="w", delete=False) as f:
            f.write("echo $MY_SECRET_KEY\n")
            f.flush()
            with patch(
                "myrm_agent_harness.toolkits.code_execution.security.shell_bleed.MAX_SCAN_SIZE",
                1,
            ):
                warnings = scan_file_for_env_leaks(f.name)
        assert warnings == []
        Path(f.name).unlink()
