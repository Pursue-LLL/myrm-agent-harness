"""Tests for wrapper_script JS/JSON literal compatibility injection.

Validates that generate_wrapper_script produces code containing
null/true/false/undefined bindings in exec_globals, preventing
NameError when LLMs generate JavaScript-style literals in Python code.
"""

from __future__ import annotations

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
        assert mcp_injection_pos < js_compat_pos, (
            "JS literal bindings must appear after MCP client injection"
        )

    def test_bindings_before_stdout_redirect(self) -> None:
        """JS literal bindings should appear before stdout redirection."""
        script = generate_wrapper_script()
        js_compat_pos = script.find('exec_globals["null"]')
        stdout_pos = script.find("sys.stdout = captured_stdout")
        assert js_compat_pos < stdout_pos, (
            "JS literal bindings must appear before stdout redirection"
        )


class TestMatplotlibFigureCapture:
    """Inline figure capture must be Jupyter-grade: capture every open figure."""

    def test_emit_iterates_all_open_figures(self) -> None:
        """H1: capture must iterate all open figures, not just the active one."""
        script = generate_wrapper_script()
        assert "plt.get_fignums()" in script, (
            "must iterate every open figure so multi-figure scripts do not lose plots"
        )

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
        assert (
            'if _myrm_flush_figures is not None and "matplotlib.pyplot" in sys.modules:'
            in script
        )

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
