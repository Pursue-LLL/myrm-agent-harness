"""Tests for Smart Auto-Verify module."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.validators.auto_verify import (
    LINTER_REGISTRY,
    Diagnostic,
    _filter_diagnostics,
    _format_diagnostics,
    _parse_generic_output,
    _parse_pyright_output,
    _reset_cache,
    run_auto_verify,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear linter availability cache before each test."""
    _reset_cache()
    yield
    _reset_cache()


class TestLinterRegistry:
    def test_python_extension_registered(self):
        assert ".py" in LINTER_REGISTRY
        assert "pyright" in LINTER_REGISTRY[".py"].command_template

    def test_typescript_extension_registered(self):
        assert ".ts" in LINTER_REGISTRY
        assert "tsc" in LINTER_REGISTRY[".ts"].command_template
        assert "--skipLibCheck" in LINTER_REGISTRY[".ts"].command_template

    def test_tsx_extension_registered(self):
        assert ".tsx" in LINTER_REGISTRY
        assert LINTER_REGISTRY[".tsx"].detect_cmd == "tsc"

    def test_go_extension_registered(self):
        assert ".go" in LINTER_REGISTRY
        assert "go vet" in LINTER_REGISTRY[".go"].command_template

    def test_rust_extension_registered(self):
        assert ".rs" in LINTER_REGISTRY
        assert "cargo" in LINTER_REGISTRY[".rs"].detect_cmd

    def test_unsupported_extension(self):
        assert ".md" not in LINTER_REGISTRY
        assert ".txt" not in LINTER_REGISTRY
        assert ".html" not in LINTER_REGISTRY


class TestParsePyrightOutput:
    def test_valid_json_output(self):
        raw = '''{
            "generalDiagnostics": [
                {
                    "file": "/workspace/src/main.py",
                    "severity": "error",
                    "message": "Cannot access attribute 'namee' on type 'User'",
                    "range": {"start": {"line": 4, "character": 11}}
                }
            ]
        }'''
        result = _parse_pyright_output(raw)
        assert len(result) == 1
        assert result[0].file == "/workspace/src/main.py"
        assert result[0].line == 5
        assert result[0].col == 12
        assert result[0].severity == "error"
        assert "namee" in result[0].message

    def test_filters_warnings(self):
        raw = '''{
            "generalDiagnostics": [
                {
                    "file": "/workspace/src/main.py",
                    "severity": "warning",
                    "message": "Variable is unused",
                    "range": {"start": {"line": 1, "character": 0}}
                },
                {
                    "file": "/workspace/src/main.py",
                    "severity": "error",
                    "message": "Type error",
                    "range": {"start": {"line": 2, "character": 5}}
                }
            ]
        }'''
        result = _parse_pyright_output(raw)
        assert len(result) == 1
        assert result[0].severity == "error"

    def test_invalid_json_fallback_to_generic(self):
        raw = "src/main.py(5,12): error TS2322: Type 'string' is not assignable"
        result = _parse_pyright_output(raw)
        assert len(result) == 1

    def test_empty_diagnostics(self):
        raw = '{"generalDiagnostics": []}'
        result = _parse_pyright_output(raw)
        assert len(result) == 0

    def test_missing_range_fields_uses_defaults(self):
        """Pyright diag with missing range/start fields defaults to line=1, col=1."""
        raw = '{"generalDiagnostics": [{"file": "x.py", "severity": "error", "message": "err"}]}'
        result = _parse_pyright_output(raw)
        assert len(result) == 1
        assert result[0].line == 1
        assert result[0].col == 1

    def test_missing_file_field_uses_empty(self):
        """Pyright diag missing file field defaults to empty string."""
        raw = '{"generalDiagnostics": [{"severity": "error", "message": "err", "range": {"start": {"line": 0, "character": 0}}}]}'
        result = _parse_pyright_output(raw)
        assert len(result) == 1
        assert result[0].file == ""


class TestParseGenericOutput:
    def test_tsc_format(self):
        raw = "src/app.ts(10,5): error TS2322: Type 'string' is not assignable to type 'number'."
        result = _parse_generic_output(raw)
        assert len(result) == 1
        assert result[0].file == "src/app.ts"
        assert result[0].line == 10
        assert result[0].col == 5
        assert "not assignable" in result[0].message

    def test_multiple_errors(self):
        raw = (
            "src/a.ts(1,1): error TS001: First error\n"
            "src/b.ts(2,3): error TS002: Second error\n"
        )
        result = _parse_generic_output(raw)
        assert len(result) == 2

    def test_colon_format(self):
        raw = "src/main.py:5:12 - error: Cannot access attribute"
        result = _parse_generic_output(raw)
        assert len(result) == 1
        assert result[0].line == 5
        assert result[0].col == 12

    def test_ignores_non_error_lines(self):
        raw = "Compiling...\nDone. No errors found."
        result = _parse_generic_output(raw)
        assert len(result) == 0


class TestFilterDiagnostics:
    def test_filters_by_file(self):
        diags = [
            Diagnostic(file="src/main.py", line=5, col=1, severity="error", message="err"),
            Diagnostic(file="src/other.py", line=3, col=1, severity="error", message="err"),
        ]
        result = _filter_diagnostics(diags, "src/main.py", None, None)
        assert len(result) == 1
        assert result[0].file == "src/main.py"

    def test_filters_by_edit_range(self):
        diags = [
            Diagnostic(file="main.py", line=5, col=1, severity="error", message="near edit"),
            Diagnostic(file="main.py", line=100, col=1, severity="error", message="far away"),
        ]
        result = _filter_diagnostics(diags, "main.py", 3, 7)
        assert len(result) == 1
        assert result[0].line == 5

    def test_margin_of_10_lines(self):
        diags = [
            Diagnostic(file="main.py", line=20, col=1, severity="error", message="within margin"),
        ]
        result = _filter_diagnostics(diags, "main.py", 15, 15)
        assert len(result) == 1

    def test_respects_max_limit(self):
        diags = [
            Diagnostic(file="main.py", line=i, col=1, severity="error", message=f"err {i}")
            for i in range(1, 20)
        ]
        result = _filter_diagnostics(diags, "main.py", None, None)
        assert len(result) == 5

    def test_no_range_reports_all_errors_in_file(self):
        diags = [
            Diagnostic(file="main.py", line=1, col=1, severity="error", message="e1"),
            Diagnostic(file="main.py", line=50, col=1, severity="error", message="e2"),
            Diagnostic(file="main.py", line=100, col=1, severity="error", message="e3"),
        ]
        result = _filter_diagnostics(diags, "main.py", None, None)
        assert len(result) == 3

    def test_excludes_non_error_severity(self):
        """Non-error severities are excluded even if in range."""
        diags = [
            Diagnostic(file="main.py", line=5, col=1, severity="warning", message="w"),
            Diagnostic(file="main.py", line=5, col=1, severity="information", message="i"),
            Diagnostic(file="main.py", line=5, col=1, severity="error", message="e"),
        ]
        result = _filter_diagnostics(diags, "main.py", None, None)
        assert len(result) == 1
        assert result[0].severity == "error"

    def test_endswith_path_matching(self):
        """Diagnostics with absolute paths match when file_path is relative suffix."""
        diags = [
            Diagnostic(file="/home/user/project/src/main.py", line=1, col=1, severity="error", message="e"),
        ]
        result = _filter_diagnostics(diags, "src/main.py", None, None)
        assert len(result) == 1

    def test_reverse_endswith_path_matching(self):
        """file_path is absolute, diagnostic has relative path."""
        diags = [
            Diagnostic(file="src/main.py", line=1, col=1, severity="error", message="e"),
        ]
        result = _filter_diagnostics(diags, "/home/user/project/src/main.py", None, None)
        assert len(result) == 1


class TestFormatDiagnostics:
    def test_basic_format(self):
        diags = [
            Diagnostic(file="src/main.py", line=5, col=12, severity="error", message="Type mismatch"),
        ]
        result = _format_diagnostics(diags)
        assert "src/main.py:5:12" in result
        assert "error" in result
        assert "Type mismatch" in result


class TestRunAutoVerify:
    @pytest.mark.asyncio
    async def test_unsupported_extension_returns_none(self):
        executor = AsyncMock()
        result = await run_auto_verify(executor, "/workspace/readme.md")
        assert result is None
        executor.execute_bash.assert_not_called()

    @pytest.mark.asyncio
    async def test_linter_not_available_returns_none(self):
        executor = AsyncMock()
        exec_result = AsyncMock()
        exec_result.success = False
        executor.execute_bash.return_value = exec_result

        result = await run_auto_verify(executor, "/workspace/main.py")
        assert result is None

    @pytest.mark.asyncio
    async def test_linter_available_no_errors_returns_none(self):
        executor = AsyncMock()

        which_result = AsyncMock()
        which_result.success = True

        lint_result = AsyncMock()
        lint_result.success = True
        lint_result.stdout = ""
        lint_result.stderr = ""

        executor.execute_bash.side_effect = [which_result, lint_result]

        result = await run_auto_verify(executor, "/workspace/main.py")
        assert result is None

    @pytest.mark.asyncio
    async def test_linter_finds_errors(self):
        executor = AsyncMock()

        which_result = AsyncMock()
        which_result.success = True

        lint_result = AsyncMock()
        lint_result.success = False
        lint_result.stdout = '{"generalDiagnostics": [{"file": "/workspace/main.py", "severity": "error", "message": "Type mismatch", "range": {"start": {"line": 4, "character": 0}}}]}'
        lint_result.stderr = ""

        executor.execute_bash.side_effect = [which_result, lint_result]

        result = await run_auto_verify(executor, "/workspace/main.py")
        assert result is not None
        assert "[Auto-Verify]" in result
        assert "Type mismatch" in result

    @pytest.mark.asyncio
    async def test_uses_cache_for_availability(self):
        executor = AsyncMock()

        which_result = AsyncMock()
        which_result.success = True

        lint_result = AsyncMock()
        lint_result.success = True
        lint_result.stdout = ""
        lint_result.stderr = ""

        executor.execute_bash.side_effect = [which_result, lint_result, lint_result]

        await run_auto_verify(executor, "/workspace/a.py")
        await run_auto_verify(executor, "/workspace/b.py")

        # 'which pyright' should only be called once (cached)
        calls = executor.execute_bash.call_args_list
        which_calls = [c for c in calls if "which" in str(c)]
        assert len(which_calls) == 1

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        executor = AsyncMock()

        which_result = AsyncMock()
        which_result.success = True

        executor.execute_bash.side_effect = [
            which_result,
            TimeoutError("timed out"),
        ]

        result = await run_auto_verify(executor, "/workspace/main.py")
        assert result is None

    @pytest.mark.asyncio
    async def test_with_edit_range_filters_diagnostics(self):
        """Verify edit_line_start/end params trigger incremental filtering."""
        executor = AsyncMock()

        which_result = AsyncMock()
        which_result.success = True

        lint_result = AsyncMock()
        lint_result.success = False
        lint_result.stdout = '{"generalDiagnostics": [{"file": "/workspace/main.py", "severity": "error", "message": "Near edit", "range": {"start": {"line": 9, "character": 0}}}, {"file": "/workspace/main.py", "severity": "error", "message": "Far away", "range": {"start": {"line": 99, "character": 0}}}]}'
        lint_result.stderr = ""

        executor.execute_bash.side_effect = [which_result, lint_result]

        result = await run_auto_verify(
            executor, "/workspace/main.py", edit_line_start=8, edit_line_end=12
        )
        assert result is not None
        assert "Near edit" in result
        assert "Far away" not in result

    @pytest.mark.asyncio
    async def test_pyright_invalid_json_falls_back_to_generic(self):
        """When pyright outputs non-JSON, fallback to generic parser."""
        executor = AsyncMock()

        which_result = AsyncMock()
        which_result.success = True

        lint_result = AsyncMock()
        lint_result.success = False
        lint_result.stdout = "/workspace/main.py(5,3): error PY001: Undefined variable 'foo'"
        lint_result.stderr = ""

        executor.execute_bash.side_effect = [which_result, lint_result]

        result = await run_auto_verify(executor, "/workspace/main.py")
        assert result is not None
        assert "Undefined variable" in result

    @pytest.mark.asyncio
    async def test_executor_generic_exception_returns_none(self):
        """Any non-timeout exception from executor is handled gracefully."""
        executor = AsyncMock()

        which_result = AsyncMock()
        which_result.success = True

        executor.execute_bash.side_effect = [
            which_result,
            RuntimeError("Connection reset"),
        ]

        result = await run_auto_verify(executor, "/workspace/main.py")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_executor_returns_none_early(self):
        """Unsupported extension still returns None even if executor is weird."""
        executor = AsyncMock()
        result = await run_auto_verify(executor, "/workspace/file.xyz")
        assert result is None
        executor.execute_bash.assert_not_called()

    @pytest.mark.asyncio
    async def test_linter_unavailable_cached_on_second_call(self):
        """Second call for same linter uses cached False result."""
        executor = AsyncMock()

        which_result = AsyncMock()
        which_result.success = False
        executor.execute_bash.return_value = which_result

        result1 = await run_auto_verify(executor, "/workspace/a.go")
        assert result1 is None

        result2 = await run_auto_verify(executor, "/workspace/b.go")
        assert result2 is None

        which_calls = [c for c in executor.execute_bash.call_args_list if "which" in str(c)]
        assert len(which_calls) == 1

    @pytest.mark.asyncio
    async def test_check_available_exception_returns_false(self):
        """Exception during `which` check marks linter as unavailable."""
        executor = AsyncMock()
        executor.execute_bash.side_effect = OSError("broken pipe")

        result = await run_auto_verify(executor, "/workspace/main.py")
        assert result is None

    @pytest.mark.asyncio
    async def test_diagnostics_all_outside_edit_range_returns_none(self):
        """All diagnostics outside edit range => filtered to empty => return None."""
        executor = AsyncMock()

        which_result = AsyncMock()
        which_result.success = True

        lint_result = AsyncMock()
        lint_result.success = False
        lint_result.stdout = '{"generalDiagnostics": [{"file": "/workspace/main.py", "severity": "error", "message": "Far error", "range": {"start": {"line": 99, "character": 0}}}]}'
        lint_result.stderr = ""

        executor.execute_bash.side_effect = [which_result, lint_result]

        result = await run_auto_verify(
            executor, "/workspace/main.py", edit_line_start=1, edit_line_end=3
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_unparseable_linter_output_returns_none(self):
        """Linter fails but output is garbage => no parseable diagnostics => None."""
        executor = AsyncMock()

        which_result = AsyncMock()
        which_result.success = True

        lint_result = AsyncMock()
        lint_result.success = False
        lint_result.stdout = "Some random garbage output\nSegfault at 0x0"
        lint_result.stderr = ""

        executor.execute_bash.side_effect = [which_result, lint_result]

        result = await run_auto_verify(executor, "/workspace/main.py")
        assert result is None
