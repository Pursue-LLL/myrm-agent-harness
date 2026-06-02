"""Tests for the per-turn file mutation verifier.

Covers:
- State lifecycle (reset/record/get/format)
- Success overriding prior failure (self-healing)
- First-error retention
- Non-mutating tool filtering
- Max display file limit
- Exception path recording
- Edge cases (empty path, None state, multiple files)
"""


from myrm_agent_harness.agent.middlewares._mutation_verifier import (
    _FILE_MUTATING_TOOLS,
    _MAX_DISPLAY_FILES,
    _extract_path,
    _truncate_error,
    format_mutation_failures,
    get_failed_mutations,
    record_mutation_result,
    reset_mutation_state,
)


class TestResetAndEmptyState:
    """State initialization and reset."""

    def test_empty_after_reset(self) -> None:
        reset_mutation_state()
        assert get_failed_mutations() == {}

    def test_format_returns_none_when_empty(self) -> None:
        reset_mutation_state()
        assert format_mutation_failures() is None

    def test_get_returns_empty_when_not_initialized(self) -> None:
        """Before reset is called, get should return empty dict (not crash)."""
        from contextvars import copy_context
        ctx = copy_context()
        result = ctx.run(get_failed_mutations)
        assert result == {}


class TestRecordMutationResult:
    """Core recording logic."""

    def test_record_failure(self) -> None:
        reset_mutation_state()
        record_mutation_result("file_write_tool", {"path": "/a.py"}, True, "SyntaxError")
        failures = get_failed_mutations()
        assert "/a.py" in failures
        assert failures["/a.py"]["tool"] == "file_write_tool"
        assert failures["/a.py"]["error_preview"] == "SyntaxError"

    def test_record_file_edit_failure(self) -> None:
        reset_mutation_state()
        record_mutation_result("file_edit_tool", {"path": "/b.py"}, True, "old_string not found")
        failures = get_failed_mutations()
        assert "/b.py" in failures
        assert failures["/b.py"]["tool"] == "file_edit_tool"

    def test_success_clears_prior_failure(self) -> None:
        reset_mutation_state()
        record_mutation_result("file_write_tool", {"path": "/a.py"}, True, "err")
        assert len(get_failed_mutations()) == 1
        record_mutation_result("file_write_tool", {"path": "/a.py"}, False)
        assert len(get_failed_mutations()) == 0

    def test_first_error_retention(self) -> None:
        reset_mutation_state()
        record_mutation_result("file_edit_tool", {"path": "/x.py"}, True, "Error 1: root cause")
        record_mutation_result("file_edit_tool", {"path": "/x.py"}, True, "Error 2: retry noise")
        failures = get_failed_mutations()
        assert failures["/x.py"]["error_preview"] == "Error 1: root cause"

    def test_non_mutating_tool_ignored(self) -> None:
        reset_mutation_state()
        record_mutation_result("bash_code_execute_tool", {"path": "/z.py"}, True, "err")
        assert len(get_failed_mutations()) == 0

    def test_empty_path_ignored(self) -> None:
        reset_mutation_state()
        record_mutation_result("file_write_tool", {"path": ""}, True, "err")
        assert len(get_failed_mutations()) == 0

    def test_missing_path_ignored(self) -> None:
        reset_mutation_state()
        record_mutation_result("file_write_tool", {}, True, "err")
        assert len(get_failed_mutations()) == 0

    def test_whitespace_path_ignored(self) -> None:
        reset_mutation_state()
        record_mutation_result("file_write_tool", {"path": "   "}, True, "err")
        assert len(get_failed_mutations()) == 0

    def test_multiple_files(self) -> None:
        reset_mutation_state()
        record_mutation_result("file_write_tool", {"path": "/a.py"}, True, "err1")
        record_mutation_result("file_edit_tool", {"path": "/b.py"}, True, "err2")
        record_mutation_result("file_write_tool", {"path": "/c.py"}, True, "err3")
        assert len(get_failed_mutations()) == 3

    def test_success_on_never_failed_path_is_noop(self) -> None:
        reset_mutation_state()
        record_mutation_result("file_write_tool", {"path": "/new.py"}, False)
        assert len(get_failed_mutations()) == 0

    def test_none_error_content(self) -> None:
        reset_mutation_state()
        record_mutation_result("file_write_tool", {"path": "/x.py"}, True, None)
        assert get_failed_mutations()["/x.py"]["error_preview"] == ""


class TestFormatMutationFailures:
    """Formatting for SSE event payload."""

    def test_basic_format(self) -> None:
        reset_mutation_state()
        record_mutation_result("file_write_tool", {"path": "/a.py"}, True, "err")
        payload = format_mutation_failures()
        assert payload is not None
        assert payload["failed_count"] == 1
        assert len(payload["files"]) == 1
        assert payload["files"][0]["path"] == "/a.py"
        assert payload["files"][0]["tool"] == "file_write_tool"
        assert "truncated" not in payload

    def test_truncation_at_max_display(self) -> None:
        reset_mutation_state()
        for i in range(_MAX_DISPLAY_FILES + 5):
            record_mutation_result("file_write_tool", {"path": f"/file_{i}.py"}, True, f"err{i}")
        payload = format_mutation_failures()
        assert payload is not None
        assert payload["failed_count"] == _MAX_DISPLAY_FILES + 5
        assert len(payload["files"]) == _MAX_DISPLAY_FILES
        assert payload["truncated"] == 5

    def test_exactly_max_files_no_truncated_key(self) -> None:
        reset_mutation_state()
        for i in range(_MAX_DISPLAY_FILES):
            record_mutation_result("file_write_tool", {"path": f"/file_{i}.py"}, True, f"err{i}")
        payload = format_mutation_failures()
        assert payload is not None
        assert payload["failed_count"] == _MAX_DISPLAY_FILES
        assert len(payload["files"]) == _MAX_DISPLAY_FILES
        assert "truncated" not in payload


class TestHelpers:
    """Private helper functions."""

    def test_extract_path_normal(self) -> None:
        assert _extract_path("file_write_tool", {"path": "/foo/bar.py"}) == "/foo/bar.py"

    def test_extract_path_strips_whitespace(self) -> None:
        assert _extract_path("file_write_tool", {"path": "  /a.py  "}) == "/a.py"

    def test_extract_path_missing(self) -> None:
        assert _extract_path("file_write_tool", {}) is None

    def test_extract_path_non_string(self) -> None:
        assert _extract_path("file_write_tool", {"path": 123}) is None

    def test_truncate_error_short(self) -> None:
        assert _truncate_error("short error") == "short error"

    def test_truncate_error_long(self) -> None:
        long_str = "x" * 300
        result = _truncate_error(long_str, max_len=200)
        assert len(result) == 200
        assert result.endswith("\u2026")

    def test_truncate_error_none(self) -> None:
        assert _truncate_error(None) == ""

    def test_truncate_error_empty(self) -> None:
        assert _truncate_error("") == ""


class TestIntegration:
    """Realistic multi-step scenarios."""

    def test_full_turn_scenario(self) -> None:
        """Agent: write A (ok), edit B (fail), edit C (fail), retry B (ok), write D (fail)."""
        reset_mutation_state()

        record_mutation_result("file_write_tool", {"path": "/src/main.py"}, False)
        record_mutation_result("file_edit_tool", {"path": "/src/utils.py"}, True, "old_string not found")
        record_mutation_result("file_edit_tool", {"path": "/src/config.py"}, True, "SyntaxError line 42")
        record_mutation_result("file_edit_tool", {"path": "/src/utils.py"}, False)  # self-healed
        record_mutation_result("file_write_tool", {"path": "/tests/test_main.py"}, True, "PermissionError")

        payload = format_mutation_failures()
        assert payload is not None
        assert payload["failed_count"] == 2
        paths = [f["path"] for f in payload["files"]]
        assert "/src/config.py" in paths
        assert "/tests/test_main.py" in paths
        assert "/src/utils.py" not in paths  # healed

    def test_all_succeed_no_event(self) -> None:
        """When all file ops succeed, no event is emitted."""
        reset_mutation_state()
        record_mutation_result("file_write_tool", {"path": "/a.py"}, False)
        record_mutation_result("file_edit_tool", {"path": "/b.py"}, False)
        assert format_mutation_failures() is None

    def test_exception_path_records(self) -> None:
        """Simulate _handle_execution_error path where tool raises exception."""
        reset_mutation_state()
        record_mutation_result(
            "file_edit_tool",
            {"path": "/workspace/main.py"},
            True,
            "ValueError: New syntax errors after edit",
        )
        failures = get_failed_mutations()
        assert "/workspace/main.py" in failures
        assert "ValueError" in failures["/workspace/main.py"]["error_preview"]


class TestConstants:
    """Verify constant definitions."""

    def test_file_mutating_tools(self) -> None:
        assert "file_write_tool" in _FILE_MUTATING_TOOLS
        assert "file_edit_tool" in _FILE_MUTATING_TOOLS
        assert "bash_code_execute_tool" not in _FILE_MUTATING_TOOLS

    def test_max_display_files(self) -> None:
        assert _MAX_DISPLAY_FILES == 10
