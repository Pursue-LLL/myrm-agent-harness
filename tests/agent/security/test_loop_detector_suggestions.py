"""Tests for loop_suggestions — suggestion generation and error analysis."""

from __future__ import annotations

from myrm_agent_harness.agent.security.guards.loop_guard_types import (
    CallRecord,
    ErrorPattern,
    SuccessLevel,
    SuggestionPriority,
    WarningLevel,
)
from myrm_agent_harness.agent.security.guards.loop_suggestions import generate_dynamic_suggestion
from myrm_agent_harness.agent.security.guards.loop_suggestions.core import (
    DEFAULT_SUGGESTION,
    analyze_error_pattern,
    analyze_warning_level,
    evaluate_success_level,
    get_severity_level,
    get_tool_suggestion,
    is_result_successful,
    prioritize_suggestions,
)


class TestGetSeverityLevel:
    def test_warning(self) -> None:
        label, _emoji = get_severity_level(3)
        assert label == "WARNING"

    def test_error(self) -> None:
        label, _ = get_severity_level(7)
        assert label == "ERROR"

    def test_critical(self) -> None:
        label, _ = get_severity_level(10)
        assert label == "CRITICAL"


class TestAnalyzeErrorPattern:
    def test_empty(self) -> None:
        assert analyze_error_pattern("") == ErrorPattern.EMPTY_RESULT

    def test_empty_json(self) -> None:
        assert analyze_error_pattern("[]") == ErrorPattern.EMPTY_RESULT
        assert analyze_error_pattern("{}") == ErrorPattern.EMPTY_RESULT

    def test_file_not_found(self) -> None:
        assert analyze_error_pattern("Error: file not found") == ErrorPattern.FILE_NOT_FOUND

    def test_permission_denied(self) -> None:
        assert analyze_error_pattern("Permission denied: /etc/shadow") == ErrorPattern.PERMISSION_DENIED

    def test_timeout(self) -> None:
        assert analyze_error_pattern("Request timed out") == ErrorPattern.TIMEOUT

    def test_network_error(self) -> None:
        assert analyze_error_pattern("Connection refused") == ErrorPattern.NETWORK_ERROR

    def test_invalid_format(self) -> None:
        assert analyze_error_pattern("Invalid JSON syntax error") == ErrorPattern.INVALID_FORMAT

    def test_error_prefix(self) -> None:
        assert analyze_error_pattern("Error: something went wrong") == ErrorPattern.INVALID_FORMAT

    def test_normal_content(self) -> None:
        assert analyze_error_pattern("Hello world, this is fine") == ErrorPattern.UNKNOWN


class TestIsResultSuccessful:
    def test_empty_is_failure(self) -> None:
        assert is_result_successful("") is False

    def test_error_is_failure(self) -> None:
        assert is_result_successful("file not found") is False

    def test_normal_is_success(self) -> None:
        assert is_result_successful("Hello world, all good") is True


class TestAnalyzeWarningLevel:
    def test_no_warning(self) -> None:
        assert analyze_warning_level("All good") == WarningLevel.NO_WARN

    def test_empty(self) -> None:
        assert analyze_warning_level("") == WarningLevel.NO_WARN

    def test_critical_warning(self) -> None:
        assert analyze_warning_level("Warning: critical error detected") == WarningLevel.CRITICAL_WARN

    def test_info_warning(self) -> None:
        assert analyze_warning_level("Warning: this is fine, just a note") == WarningLevel.INFO_WARN

    def test_deprecated_warning(self) -> None:
        assert analyze_warning_level("Warning: deprecated API") == WarningLevel.NORMAL_WARN

    def test_generic_warning(self) -> None:
        assert analyze_warning_level("Warning: something happened") == WarningLevel.NORMAL_WARN


class TestEvaluateSuccessLevel:
    def test_empty_is_failure(self) -> None:
        assert evaluate_success_level("tool", "") == SuccessLevel.FAILURE

    def test_error_is_failure(self) -> None:
        assert evaluate_success_level("tool", "file not found") == SuccessLevel.FAILURE

    def test_normal_is_success(self) -> None:
        assert evaluate_success_level("tool", "Hello world") == SuccessLevel.FULL_SUCCESS

    def test_search_empty_is_empty_ok(self) -> None:
        assert evaluate_success_level("web_search_tool", "[]") == SuccessLevel.EMPTY_OK

    def test_memory_empty_is_empty_ok(self) -> None:
        assert evaluate_success_level("memory_recall_tool", "[]") == SuccessLevel.EMPTY_OK

    def test_browser_404_is_failure(self) -> None:
        assert evaluate_success_level("browser_navigate_tool", "Page 404 not found") == SuccessLevel.FAILURE

    def test_write_partial_is_partial(self) -> None:
        assert evaluate_success_level("file_write_tool", "partial write completed") == SuccessLevel.PARTIAL_SUCCESS

    def test_execute_exit0_stderr(self) -> None:
        result = evaluate_success_level("bash_code_execute_tool", "exit_code: 0\nstderr: warning")
        assert result == SuccessLevel.PARTIAL_SUCCESS

    def test_critical_warning_is_failure(self) -> None:
        assert evaluate_success_level("tool", "Warning: critical error in process") == SuccessLevel.FAILURE

    def test_deprecated_warning_is_partial(self) -> None:
        assert evaluate_success_level("tool", "Warning: deprecated function used") == SuccessLevel.PARTIAL_SUCCESS


class TestPrioritizeSuggestions:
    def test_empty(self) -> None:
        assert prioritize_suggestions([]) == DEFAULT_SUGGESTION

    def test_single(self) -> None:
        result = prioritize_suggestions([(SuggestionPriority.HIGH, "do this")])
        assert "do this" in result

    def test_sorted_by_priority(self) -> None:
        result = prioritize_suggestions(
            [
                (SuggestionPriority.LOW, "low"),
                (SuggestionPriority.HIGH, "high"),
                (SuggestionPriority.MEDIUM, "medium"),
            ]
        )
        parts = result.split(" | ")
        assert "high" in parts[0]

    def test_quality_scores_filter(self) -> None:
        result = prioritize_suggestions(
            [(SuggestionPriority.HIGH, "bad"), (SuggestionPriority.MEDIUM, "good")],
            quality_scores={"bad": -0.5, "good": 0.8},
        )
        assert "bad" not in result
        assert "good" in result

    def test_quality_scores_promote(self) -> None:
        result = prioritize_suggestions([(SuggestionPriority.MEDIUM, "promoted")], quality_scores={"promoted": 0.8})
        assert "promoted" in result


class TestGetToolSuggestion:
    def test_known_tool(self) -> None:
        s = get_tool_suggestion("memory_recall_tool")
        assert "categories" in s or "profile_key" in s

    def test_unknown_tool(self) -> None:
        assert get_tool_suggestion("unknown_tool_xyz") == DEFAULT_SUGGESTION


class TestGenerateDynamicSuggestion:
    def test_no_relevant_calls(self) -> None:
        result = generate_dynamic_suggestion("memory_recall_tool", [])
        assert result == get_tool_suggestion("memory_recall_tool")

    def test_with_relevant_calls(self) -> None:
        calls = [
            CallRecord(tool_name="memory_recall_tool", args_hash="abc", args={"query": "test"}),
        ]
        result = generate_dynamic_suggestion("memory_recall_tool", calls)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_unknown_tool_fallback(self) -> None:
        calls = [
            CallRecord(tool_name="custom_tool", args_hash="abc", args={}),
        ]
        result = generate_dynamic_suggestion("custom_tool", calls)
        assert result == DEFAULT_SUGGESTION
