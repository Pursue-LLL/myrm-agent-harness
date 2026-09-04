"""Tests for wrapper_script JS/JSON literal compatibility injection.

Validates that generate_wrapper_script produces code containing
null/true/false/undefined bindings in exec_globals, preventing
NameError when LLMs generate JavaScript-style literals in Python code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_execution.executors.common.wrapper_script import (
    generate_wrapper_script,
    parse_execution_output,
)


class TestJsLiteralCompatibility:
    """exec_globals must include JS/JSON literal compatibility bindings."""

    def test_null_binding_present(self) -> None:
        script = generate_wrapper_script()
        assert 'exec_globals["null"] = None' in script

    def test_true_binding_present(self) -> None:
        script = generate_wrapper_script()
        assert 'exec_globals["true"] = True' in script

    def test_false_binding_present(self) -> None:
        script = generate_wrapper_script()
        assert 'exec_globals["false"] = False' in script

    def test_undefined_binding_present(self) -> None:
        script = generate_wrapper_script()
        assert 'exec_globals["undefined"] = None' in script

    def test_bindings_after_mcp_injection(self) -> None:
        """JS literal bindings should appear after MCP client object injection."""
        script = generate_wrapper_script()
        mcp_injection_pos = script.find('for key in ["skills"')
        js_compat_pos = script.find('exec_globals["null"]')
        assert mcp_injection_pos < js_compat_pos, "JS literal bindings must appear after MCP client injection"

    def test_bindings_before_stdout_redirect(self) -> None:
        """JS literal bindings should appear before stdout redirection."""
        script = generate_wrapper_script()
        js_compat_pos = script.find('exec_globals["null"]')
        stdout_pos = script.find("sys.stdout = captured_stdout")
        assert js_compat_pos < stdout_pos, "JS literal bindings must appear before stdout redirection"


class TestMatplotlibFigureCapture:
    """Inline figure capture must be Jupyter-grade: capture every open figure."""

    def test_emit_iterates_all_open_figures(self) -> None:
        """H1: capture must iterate all open figures, not just the active one."""
        script = generate_wrapper_script()
        assert "plt.get_fignums()" in script, "must iterate every open figure so multi-figure scripts do not lose plots"

    def test_emit_closes_each_figure(self) -> None:
        """Closing per figure makes 'open figures' the single source of truth."""
        script = generate_wrapper_script()
        assert "plt.close(fig)" in script

    def test_show_emits_all_open_figures(self) -> None:
        """plt.show() must delegate to the emit-all-open-figures routine."""
        script = generate_wrapper_script()
        assert "plt.show = myrm_show" in script
        assert "_myrm_emit_open_figures" in script

    def test_end_of_run_flush_present(self) -> None:
        """H2: figures created without plt.show() are flushed at end of run."""
        script = generate_wrapper_script()
        assert 'if _myrm_flush_figures is not None and "matplotlib.pyplot" in sys.modules:' in script

    def test_vault_pointer_zero_copy(self) -> None:
        """Figures are surfaced as zero-copy vault:// pointers, not raw bytes."""
        script = generate_wrapper_script()
        assert "_MyrmImage:vault://.myrm_plots/" in script

    def test_flush_in_finally_before_stdout_restore(self) -> None:
        """Flush runs in finally (survives exceptions) before stdout restore."""
        script = generate_wrapper_script()
        flush_pos = script.find("_myrm_flush_figures()")
        finally_pos = script.find("finally:")
        stdout_restore_pos = script.find("sys.stdout = original_stdout")
        assert -1 < finally_pos < flush_pos < stdout_restore_pos


class TestParseExecutionOutput:
    """parse_execution_output should handle various output formats."""

    def test_successful_json_output(self) -> None:
        stdout = '__RESULT_START__\n{"success": true, "result": null, "error": null, "stdout": "ok", "stderr": ""}\n__RESULT_END__'
        result = parse_execution_output(stdout, "", 0)
        assert result.success is True
        assert result.error is None
        assert result.stdout == "ok"

    def test_failed_execution_fallback(self) -> None:
        result = parse_execution_output("", "NameError: name 'null'", 1)
        assert result.success is False
        assert "NameError" in (result.error or "")

    def test_empty_output(self) -> None:
        result = parse_execution_output("", "", 0)
        assert result.success is True
        assert result.error is None

    def test_malformed_json_fallback(self) -> None:
        """Corrupt JSON inside markers must fall back gracefully."""
        stdout = "__RESULT_START__\n{broken json\n__RESULT_END__"
        result = parse_execution_output(stdout, "", 0)
        assert result.success is True
        assert result.result is None

    def test_exit_code_nonzero_without_markers(self) -> None:
        """Non-zero exit without result markers => success=False."""
        result = parse_execution_output("some output", "Traceback...", 137)
        assert result.success is False
        assert result.error == "Traceback..."
        assert result.stdout == "some output"

    def test_result_with_error_field(self) -> None:
        """Wrapper reports error inside JSON when user code raises."""
        stdout = '__RESULT_START__\n{"success": false, "result": null, "error": "ValueError: bad", "stdout": "", "stderr": "tb"}\n__RESULT_END__'
        result = parse_execution_output(stdout, "", 0)
        assert result.success is False
        assert result.error == "ValueError: bad"
        assert result.stderr == "tb"

    def test_user_stdout_before_markers_preserved(self) -> None:
        """Print output before __RESULT_START__ must be preserved."""
        stdout = 'hello world\n__RESULT_START__\n{"success": true, "result": null, "error": null, "stdout": "captured", "stderr": ""}\n__RESULT_END__'
        result = parse_execution_output(stdout, "", 0)
        assert result.success is True
        assert result.stdout == "captured"

    def test_stderr_fallback_to_subprocess_when_json_empty(self) -> None:
        """Empty JSON stderr key must not discard the real subprocess stderr.

        The wrapper JSON always carries a (possibly empty) ``stderr`` key, so a
        plain ``.get("stderr", default)`` never falls back. When the wrapper saw
        no exception (empty key), the captured subprocess stderr — warnings and
        user ``sys.stderr`` writes — must win.
        """
        stdout = '__RESULT_START__\n{"success": true, "result": null, "error": null, "stdout": "ok", "stderr": ""}\n__RESULT_END__'
        subprocess_stderr = "WARN: download http://example/0 retry\nWARN: skip row 3"
        result = parse_execution_output(stdout, subprocess_stderr, 0)
        assert result.success is True
        assert result.stderr == subprocess_stderr

    def test_stderr_merges_json_traceback_with_pipe_user_stderr(self) -> None:
        """Non-empty JSON stderr (wrapper traceback) merges, not replaces.

        When user code wrote to sys.stderr before raising, the subprocess pipe
        carries that output while the wrapper JSON carries only the traceback.
        Both are diagnostic context for the LLM, so they merge pipe-first with
        the traceback last.
        """
        stdout = '__RESULT_START__\n{"success": false, "result": null, "error": "ValueError: bad", "stdout": "", "stderr": "Traceback (most recent call last):\\nValueError: bad"}\n__RESULT_END__'
        subprocess_stderr = "row 149 failed\nrow 150 failed"
        result = parse_execution_output(stdout, subprocess_stderr, 1)
        assert result.success is False
        assert result.stderr.startswith("row 149 failed")
        assert "ValueError: bad" in result.stderr
        assert result.stderr.index("row 149 failed") < result.stderr.index("Traceback")

    def test_stderr_keeps_pipe_when_it_already_contains_traceback(self) -> None:
        """A pipe that already carries the traceback is kept verbatim."""
        traceback_text = "Traceback (most recent call last):\nValueError: bad"
        stdout = (
            '__RESULT_START__\n{"success": false, "result": null, "error": "ValueError: bad", '
            f'"stdout": "", "stderr": "{traceback_text}"}}\n__RESULT_END__'
        )
        subprocess_stderr = f"prefix noise\n{traceback_text}"
        result = parse_execution_output(stdout, subprocess_stderr, 1)
        assert result.success is False
        assert result.stderr == subprocess_stderr
        assert result.stderr.count("ValueError") == 1


class TestGenerateWrapperScript:
    """generate_wrapper_script produces a valid, compilable Python script."""

    def test_compilable(self) -> None:
        """Generated script must be valid Python."""
        script = generate_wrapper_script()
        compile(script, "<wrapper>", "exec")

    def test_contains_main_guard(self) -> None:
        script = generate_wrapper_script()
        assert 'if __name__ == "__main__":' in script

    def test_bounded_stdout_present(self) -> None:
        """BoundedStringIO must cap stdout to prevent log bombs."""
        script = generate_wrapper_script()
        assert "BoundedStringIO" in script

    def test_agg_backend_forced(self) -> None:
        """Headless Agg backend must be forced for matplotlib."""
        script = generate_wrapper_script()
        assert 'matplotlib.use("Agg", force=True)' in script

    def test_webp_format(self) -> None:
        """Figures must be saved as WebP for size efficiency."""
        script = generate_wrapper_script()
        assert 'format="webp"' in script

    def test_original_stdout_preserved(self) -> None:
        """original_stdout must be captured before redirection."""
        script = generate_wrapper_script()
        assert "original_stdout = sys.stdout" in script
        orig_pos = script.find("original_stdout = sys.stdout")
        redirect_pos = script.find("sys.stdout = captured_stdout")
        assert orig_pos < redirect_pos

    def test_resource_limits_with_timeout_and_memory(self) -> None:
        """timeout and memory_limit_mb inject RLIMIT_CPU and RLIMIT_AS."""
        script = generate_wrapper_script(timeout=30, memory_limit_mb=512)
        assert "RLIMIT_CPU" in script
        assert "RLIMIT_AS" in script
        compile(script, "<wrapper>", "exec")


class TestAsyncExecutionModesEndToEnd:
    """Generated wrapper must execute every documented async entry pattern.

    Runs the real wrapper in a subprocess for all four execution modes. This is
    the behavioural contract behind ``_tool_description.py`` §异步写法: if a
    future change to the wrapper or the syntax pre-check breaks any documented
    entry point, these tests fail before the LLM ever sees a drifted prompt.
    """

    @pytest.mark.parametrize(
        ("name", "user_code", "marker"),
        [
            (
                "sync",
                "print('MARK_SYNC')",
                "MARK_SYNC",
            ),
            (
                "sync_main_under_if_name",
                "def main():\n    print('MARK_SYNC_MAIN_UNDER_IF_NAME')\nif __name__ == '__main__':\n    main()",
                "MARK_SYNC_MAIN_UNDER_IF_NAME",
            ),
            (
                "asyncio_run",
                "import asyncio\nasync def main():\n    print('MARK_ASYNC_RUN')\nasyncio.run(main())",
                "MARK_ASYNC_RUN",
            ),
            (
                "async_main_bare_call",
                "async def main():\n    print('MARK_BARE_MAIN')\nmain()",
                "MARK_BARE_MAIN",
            ),
            (
                "async_main_indented_under_if_name",
                "async def main():\n    print('MARK_INDENTED_MAIN')\nif __name__ == '__main__':\n    main()",
                "MARK_INDENTED_MAIN",
            ),
            (
                "async_main_assigned_to_variable",
                "async def main():\n    print('MARK_ASSIGNED_MAIN')\nres = main()",
                "MARK_ASSIGNED_MAIN",
            ),
            (
                "async_main_ann_assigned_under_if_name",
                "from typing import Any\nasync def main():\n    print('MARK_ANN_ASSIGNED_MAIN')\nif __name__ == '__main__':\n    res: Any = main()",
                "MARK_ANN_ASSIGNED_MAIN",
            ),
            (
                "async_main_with_comment_mentioning_asyncio_run",
                "# Note: do not call asyncio.run(main()) directly\nasync def main():\n    print('MARK_COMMENT_ASYNC_RUN')\nif __name__ == '__main__':\n    main()",
                "MARK_COMMENT_ASYNC_RUN",
            ),
            (
                "async_main_with_string_mentioning_asyncio_run",
                "msg = 'testing asyncio.run(main()) here'\nasync def main():\n    print('MARK_STRING_ASYNC_RUN')\nmain()",
                "MARK_STRING_ASYNC_RUN",
            ),
            (
                "top_level_await",
                "import asyncio\nasync def f():\n    return 'MARK_TOP_AWAIT'\nprint(await f())",
                "MARK_TOP_AWAIT",
            ),
            (
                "top_level_await_with_future_annotations",
                "from __future__ import annotations\nimport asyncio\nasync def f() -> str:\n    return 'MARK_FUTURE_AWAIT'\nprint(await f())",
                "MARK_FUTURE_AWAIT",
            ),
            (
                "sync_function_with_internal_await_not_misclassified",
                "x = 500\nasync def helper():\n    pass\nprint(f'MARK_SYNC_NO_AWAIT_{x}')",
                "MARK_SYNC_NO_AWAIT_500",
            ),
            (
                "sys_exit_zero_graceful_success",
                "import sys\nprint('MARK_SYS_EXIT_ZERO')\nsys.exit(0)",
                "MARK_SYS_EXIT_ZERO",
            ),
            (
                "from_asyncio_import_run_single_execution",
                "from asyncio import run\ncount = 0\nasync def main():\n    global count\n    count += 1\n    print(f'MARK_FROM_IMPORT_COUNT_{count}')\nrun(main())",
                "MARK_FROM_IMPORT_COUNT_1",
            ),
            (
                "import_asyncio_as_aio_single_execution",
                "import asyncio as aio\ncount = 0\nasync def main():\n    global count\n    count += 1\n    print(f'MARK_AIO_COUNT_{count}')\naio.run(main())",
                "MARK_AIO_COUNT_1",
            ),
        ],
    )
    def test_mode_runs_in_subprocess(
        self,
        tmp_path: Path,
        name: str,
        user_code: str,
        marker: str,
    ) -> None:
        code_file = tmp_path / f"{name}_user_code.py"
        wrapper_file = tmp_path / f"{name}_wrapper.py"
        code_file.write_text(user_code, encoding="utf-8")
        wrapper_file.write_text(
            generate_wrapper_script(str(code_file)),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(wrapper_file)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert '"success": true' in result.stdout
        assert marker in result.stdout

    def test_sys_exit_nonzero_reports_error_without_crash(self, tmp_path: Path) -> None:
        code_file = tmp_path / "exit_nonzero_user_code.py"
        wrapper_file = tmp_path / "exit_nonzero_wrapper.py"
        code_file.write_text("import sys\nprint('MARK_BEFORE_EXIT_42')\nsys.exit(42)", encoding="utf-8")
        wrapper_file.write_text(
            generate_wrapper_script(str(code_file)),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(wrapper_file)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert '"success": false' in result.stdout
        assert "SystemExit: 42" in result.stdout
        parsed = parse_execution_output(result.stdout, result.stderr, result.returncode)
        assert parsed.success is False
        assert "SystemExit: 42" in (parsed.error or "")
        assert "MARK_BEFORE_EXIT_42" in parsed.stdout
