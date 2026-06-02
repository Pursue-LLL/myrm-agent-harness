"""CodeTypeDetector tests — code type detection for Bash/Python."""

from myrm_agent_harness.agent.meta_tools.bash.code_detector import CodeType, CodeTypeDetector, code_detector


class TestCodeTypeDetector:
    def test_await_keyword_detected_as_async_python(self):
        result = code_detector.detect("result = await some_func()")
        assert result.code_type == CodeType.PYTHON
        assert result.is_async is True
        assert "await" in result.detection_reason

    def test_python_c_command(self):
        result = code_detector.detect('python -c "print(1)"')
        assert result.code_type == CodeType.PYTHON
        assert result.extracted_code == "print(1)"
        assert "python -c" in result.detection_reason

    def test_python3_c_command_single_quotes(self):
        result = code_detector.detect("python3 -c 'import sys; print(sys.version)'")
        assert result.code_type == CodeType.PYTHON
        assert "import sys" in result.extracted_code

    def test_python_c_no_quotes_raw_fallback_to_python(self):
        """python -c with extraction failure stays PYTHON via raw fallback.

        Falling back to BASH would mean running raw Python source as a shell
        command — guaranteed to produce a cascade of cryptic ``not found``
        errors. Raw fallback keeps the language as PYTHON so downstream
        ``ast.parse`` can emit the canonical ``python -c`` hint to the LLM.
        """
        result = code_detector.detect("python -c something_without_quotes")
        assert result.code_type == CodeType.PYTHON
        assert result.extracted_code == "something_without_quotes"
        assert "raw fallback" in result.detection_reason

    def test_python_c_raw_fallback_preserves_await_async(self):
        """Raw fallback path must still detect await for async-mode dispatch."""
        cmd = "python3 -c await crazy_unquoted_token"
        result = code_detector.detect(cmd)
        assert result.code_type == CodeType.PYTHON
        assert result.is_async is True
        assert "raw fallback" in result.detection_reason

    def test_multiline_python_syntax(self):
        code = """
import os
import sys
def main():
    pass
main()
"""
        result = code_detector.detect(code)
        assert result.code_type == CodeType.PYTHON
        assert "python syntax" in result.detection_reason

    def test_simple_bash_command(self):
        result = code_detector.detect("ls -la")
        assert result.code_type == CodeType.BASH
        assert result.detection_reason == "default to bash"

    def test_git_command(self):
        result = code_detector.detect("git status")
        assert result.code_type == CodeType.BASH

    def test_short_code_defaults_to_bash(self):
        result = code_detector.detect("echo hello")
        assert result.code_type == CodeType.BASH

    def test_multiline_bash_stays_bash(self):
        code = "echo hello\necho world\nls"
        result = code_detector.detect(code)
        assert result.code_type == CodeType.BASH

    def test_is_python_convenience(self):
        assert code_detector.is_python("result = await func()") is True
        assert code_detector.is_python("ls -la") is False

    def test_is_bash_convenience(self):
        assert code_detector.is_bash("ls -la") is True
        assert code_detector.is_bash("result = await func()") is False

    def test_python_with_for_loop(self):
        code = """
import os
data = []
for item in range(10):
    data.append(item)
print(data)
"""
        result = code_detector.detect(code)
        assert result.code_type == CodeType.PYTHON

    def test_python_with_class_definition(self):
        code = """
import dataclasses
class Foo:
    x: int = 0
    def bar(self):
        pass
"""
        result = code_detector.detect(code)
        assert result.code_type == CodeType.PYTHON

    def test_python_with_dict_assignment(self):
        code = """
import json
x = 1
y = 2
data = {"key": "value"}
print(data)
"""
        result = code_detector.detect(code)
        assert result.code_type == CodeType.PYTHON

    def test_python_with_asyncio_run(self):
        code = """
import asyncio
async def main():
    pass
asyncio.run(main())
print("done")
"""
        result = code_detector.detect(code)
        assert result.code_type == CodeType.PYTHON

    def test_global_singleton_exists(self):
        assert isinstance(code_detector, CodeTypeDetector)

    def test_short_python_like_treated_as_bash(self):
        result = code_detector.detect("print('hello')")
        assert result.code_type == CodeType.BASH

    def test_python_c_with_nested_quotes_extracted(self):
        """python -c with nested quotes: greedy regex extracts outer content."""
        cmd = """python3 -c 'import asyncio; exec("async def main(): pass")'"""
        result = code_detector.detect(cmd)
        assert result.code_type == CodeType.PYTHON
        assert "python3" not in result.extracted_code
        assert "import asyncio" in result.extracted_code
        assert "extracted" in result.detection_reason

    def test_python_c_complex_nested_quotes_greedy_match(self):
        """Greedy regex matches from first to last quote, extracting valid Python."""
        cmd = "python3 -c 'print('hello')'"
        result = code_detector.detect(cmd)
        assert result.code_type == CodeType.PYTHON

    def test_comments_excluded_from_line_count(self):
        code = "# comment 1\n# comment 2\n# comment 3\n# comment 4\necho hello"
        result = code_detector.detect(code)
        assert result.code_type == CodeType.BASH

    def test_multiline_bash_above_threshold_no_python_patterns(self):
        """Multiline bash above threshold but no Python syntax patterns returns Bash."""
        code = "echo hello\necho world\necho foo\necho bar"
        result = code_detector.detect(code)
        assert result.code_type == CodeType.BASH
        assert result.detection_reason == "default to bash"

    def test_empty_string_defaults_to_bash(self):
        result = code_detector.detect("")
        assert result.code_type == CodeType.BASH
        assert result.detection_reason == "default to bash"

    def test_python_c_with_await_extracts_then_detects_async(self):
        """python -c extraction takes priority; await is detected in extracted code."""
        cmd = 'python -c "result = await some_func()"'
        result = code_detector.detect(cmd)
        assert result.code_type == CodeType.PYTHON
        assert result.is_async is True
        assert "python -c" in result.detection_reason
        assert result.extracted_code == "result = await some_func()"
