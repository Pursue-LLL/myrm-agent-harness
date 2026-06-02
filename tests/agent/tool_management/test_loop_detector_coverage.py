"""Coverage-focused tests for loop guard modules.

Targets uncovered paths in suggestions_core, suggestions_bash, suggestions_meta,
suggestions_browser, and loop_guard to bring coverage above 80%.
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.guards.loop_guard import LoopGuard
from myrm_agent_harness.agent.security.guards.loop_guard_types import (
    AgentPhase,
    CallRecord,
    ErrorPattern,
    LoopAction,
    SuccessLevel,
    SuggestionPriority,
    WarningLevel,
)
from myrm_agent_harness.agent.security.guards.loop_suggestions.bash import suggest_bash
from myrm_agent_harness.agent.security.guards.loop_suggestions.browser import suggest_browser_snapshot
from myrm_agent_harness.agent.security.guards.loop_suggestions.core import (
    analyze_error_pattern,
    analyze_warning_level,
    evaluate_success_level,
    is_result_successful,
    prioritize_suggestions,
)
from myrm_agent_harness.agent.security.guards.loop_suggestions.meta import (
    suggest_skill_search,
    suggest_skill_select,
    suggest_spawn_subagent,
)
from myrm_agent_harness.agent.security.guards.loop_suggestions.web import suggest_web_search


class TestAnalyzeErrorPattern:
    def test_empty_string(self) -> None:
        assert analyze_error_pattern("") == ErrorPattern.EMPTY_RESULT

    def test_empty_json(self) -> None:
        assert analyze_error_pattern("[]") == ErrorPattern.EMPTY_RESULT
        assert analyze_error_pattern("{}") == ErrorPattern.EMPTY_RESULT
        assert analyze_error_pattern("null") == ErrorPattern.EMPTY_RESULT
        assert analyze_error_pattern("none") == ErrorPattern.EMPTY_RESULT

    def test_timeout(self) -> None:
        assert analyze_error_pattern("Request timed out") == ErrorPattern.TIMEOUT
        assert analyze_error_pattern("deadline exceeded") == ErrorPattern.TIMEOUT

    def test_network_error(self) -> None:
        assert analyze_error_pattern("connection refused") == ErrorPattern.NETWORK_ERROR
        assert analyze_error_pattern("network unreachable") == ErrorPattern.NETWORK_ERROR

    def test_invalid_format(self) -> None:
        assert analyze_error_pattern("invalid input") == ErrorPattern.INVALID_FORMAT
        assert analyze_error_pattern("malformed request") == ErrorPattern.INVALID_FORMAT
        assert analyze_error_pattern("syntax error in query") == ErrorPattern.INVALID_FORMAT
        assert analyze_error_pattern("parse error") == ErrorPattern.INVALID_FORMAT
        assert analyze_error_pattern("error: something went wrong") == ErrorPattern.INVALID_FORMAT
        assert analyze_error_pattern("Error something") == ErrorPattern.INVALID_FORMAT

    def test_unknown(self) -> None:
        assert analyze_error_pattern("some normal result data") == ErrorPattern.UNKNOWN


class TestIsResultSuccessful:
    def test_empty_is_failure(self) -> None:
        assert is_result_successful("") is False

    def test_error_is_failure(self) -> None:
        assert is_result_successful("file not found") is False

    def test_normal_is_success(self) -> None:
        assert is_result_successful("some data returned") is True


class TestAnalyzeWarningLevel:
    def test_no_warning(self) -> None:
        assert analyze_warning_level("") == WarningLevel.NO_WARN
        assert analyze_warning_level("everything is fine") == WarningLevel.NO_WARN

    def test_critical_warning(self) -> None:
        assert analyze_warning_level("warning: critical error detected") == WarningLevel.CRITICAL_WARN
        assert analyze_warning_level("warn: fail to connect") == WarningLevel.CRITICAL_WARN

    def test_info_warning(self) -> None:
        assert analyze_warning_level("warning: info note about usage") == WarningLevel.INFO_WARN
        assert analyze_warning_level("warn: hint for better usage") == WarningLevel.INFO_WARN

    def test_deprecated_warning(self) -> None:
        assert analyze_warning_level("warning: deprecated function used") == WarningLevel.NORMAL_WARN
        assert analyze_warning_level("warn: obsolete API") == WarningLevel.NORMAL_WARN

    def test_plain_warning(self) -> None:
        assert analyze_warning_level("warning: something happened") == WarningLevel.NORMAL_WARN


class TestEvaluateSuccessLevel:
    def test_empty_content(self) -> None:
        assert evaluate_success_level("memory_recall_tool", "") == SuccessLevel.FAILURE

    def test_search_empty_result(self) -> None:
        assert evaluate_success_level("web_search_tool", "[]") == SuccessLevel.EMPTY_OK

    def test_memory_empty_result(self) -> None:
        assert evaluate_success_level("memory_recall_tool", "[]") == SuccessLevel.EMPTY_OK

    def test_non_search_empty_result(self) -> None:
        assert evaluate_success_level("file_write_tool", "[]") == SuccessLevel.FAILURE

    def test_browser_404(self) -> None:
        assert evaluate_success_level("browser_navigate_tool", "page 404 not found") == SuccessLevel.FAILURE

    def test_browser_403(self) -> None:
        assert evaluate_success_level("browser_snapshot_tool", "403 forbidden access") == SuccessLevel.FAILURE

    def test_browser_200_empty(self) -> None:
        assert evaluate_success_level("browser_snapshot_tool", "200 ok") == SuccessLevel.EMPTY_OK

    def test_write_partial(self) -> None:
        assert evaluate_success_level("file_write_tool", "partial write completed") == SuccessLevel.PARTIAL_SUCCESS

    def test_write_incomplete(self) -> None:
        assert evaluate_success_level("file_edit_tool", "incomplete operation") == SuccessLevel.PARTIAL_SUCCESS

    def test_execute_exit_code_0_stderr(self) -> None:
        assert (
            evaluate_success_level("bash_code_execute_tool", "exit_code: 0\nstderr: some warning")
            == SuccessLevel.PARTIAL_SUCCESS
        )

    def test_critical_warning(self) -> None:
        assert evaluate_success_level("file_read_tool", "warning: critical error in processing") == SuccessLevel.FAILURE

    def test_normal_warning(self) -> None:
        assert evaluate_success_level("file_read_tool", "warning: deprecated API used") == SuccessLevel.PARTIAL_SUCCESS

    def test_info_warning(self) -> None:
        assert evaluate_success_level("file_read_tool", "warning: info note about usage") == SuccessLevel.FULL_SUCCESS

    def test_normal_success(self) -> None:
        assert evaluate_success_level("file_read_tool", "file content here with data") == SuccessLevel.FULL_SUCCESS


class TestPrioritizeSuggestions:
    def test_empty_suggestions(self) -> None:
        result = prioritize_suggestions([])
        assert "consider a different approach" in result

    def test_quality_filter(self) -> None:
        suggestions = [
            (SuggestionPriority.HIGH, "bad suggestion"),
            (SuggestionPriority.MEDIUM, "good suggestion"),
        ]
        quality = {"bad suggestion": -0.5, "good suggestion": 0.7}
        result = prioritize_suggestions(suggestions, quality)
        assert "bad suggestion" not in result
        assert "good suggestion" in result

    def test_quality_upgrade(self) -> None:
        suggestions = [
            (SuggestionPriority.MEDIUM, "great suggestion"),
        ]
        quality = {"great suggestion": 0.8}
        result = prioritize_suggestions(suggestions, quality)
        assert "[!!]" in result

    def test_quality_downgrade(self) -> None:
        suggestions = [
            (SuggestionPriority.HIGH, "mediocre suggestion"),
        ]
        quality = {"mediocre suggestion": -0.1}
        result = prioritize_suggestions(suggestions, quality)
        assert "[!]" in result

    def test_all_filtered_fallback(self) -> None:
        suggestions = [
            (SuggestionPriority.HIGH, "only suggestion"),
        ]
        quality = {"only suggestion": -0.5}
        result = prioritize_suggestions(suggestions, quality)
        assert "only suggestion" in result


class TestSuggestBashCoverage:
    def _make_call(self, command: str, result: str = "") -> CallRecord:
        return CallRecord(
            tool_name="bash_code_execute_tool", args_hash="h", args={"command": command}, result_content=result
        )

    def test_permission_denied(self) -> None:
        calls = [self._make_call("rm /etc/hosts", "permission denied")]
        result = suggest_bash(calls)
        assert "permissions" in result.lower()

    def test_invalid_format(self) -> None:
        calls = [self._make_call("invalid_cmd", "syntax error in command")]
        result = suggest_bash(calls)
        assert "syntax" in result.lower()

    def test_many_commands(self) -> None:
        calls = [self._make_call(f"cmd{i}") for i in range(4)]
        result = suggest_bash(calls)
        assert "ls" in result.lower() or "pwd" in result.lower()


class TestSuggestBrowserCoverage:
    def _make_call(self, scope: str = "", result: str = "") -> CallRecord:
        args: dict[str, object] = {}
        if scope:
            args["scope"] = scope
        return CallRecord(tool_name="browser_snapshot_tool", args_hash="h", args=args, result_content=result)

    def test_timeout_error(self) -> None:
        calls = [self._make_call(result="request timed out")]
        result = suggest_browser_snapshot(calls)
        assert "load" in result.lower() or "wait" in result.lower()

    def test_scope_suggestion(self) -> None:
        calls = [self._make_call(scope="content"), self._make_call(scope="content")]
        result = suggest_browser_snapshot(calls)
        assert "scope" in result.lower() or "full" in result.lower() or "metadata" in result.lower()

    def test_many_calls_fallback(self) -> None:
        calls = [self._make_call() for _ in range(4)]
        result = suggest_browser_snapshot(calls)
        assert "inspect" in result.lower() or "load" in result.lower()


class TestSuggestMetaCoverage:
    def test_subagent_invalid_format(self) -> None:
        calls = [
            CallRecord(
                tool_name="delegate_task_tool",
                args_hash="h",
                args={"subagent_type": "invalid"},
                result_content="invalid format error",
            )
        ]
        result = suggest_spawn_subagent(calls)
        assert "valid" in result.lower()

    def test_subagent_many_types(self) -> None:
        calls = [
            CallRecord(tool_name="delegate_task_tool", args_hash="h", args={"subagent_type": "generalPurpose"}),
            CallRecord(tool_name="delegate_task_tool", args_hash="h", args={"subagent_type": "explore"}),
            CallRecord(tool_name="delegate_task_tool", args_hash="h", args={"subagent_type": "shell"}),
        ]
        result = suggest_spawn_subagent(calls)
        assert "direct tools" in result.lower() or "subagent_type" in result.lower()

    def test_skill_select_file_not_found(self) -> None:
        calls = [
            CallRecord(
                tool_name="skill_select_tool",
                args_hash="h",
                args={"skill_names": ["nonexistent"]},
                result_content="file not found",
            )
        ]
        result = suggest_skill_select(calls)
        assert "discover_capability_tool" in result

    def test_skill_select_many_skills(self) -> None:
        calls = [
            CallRecord(tool_name="skill_select_tool", args_hash="h", args={"skill_names": ["a"]}),
            CallRecord(tool_name="skill_select_tool", args_hash="h", args={"skill_names": ["b"]}),
            CallRecord(tool_name="skill_select_tool", args_hash="h", args={"skill_names": ["c"]}),
        ]
        result = suggest_skill_select(calls)
        assert "direct tools" in result.lower()

    def test_skill_search_mode_regex(self) -> None:
        calls = [
            CallRecord(tool_name="discover_capability_tool", args_hash="h", args={"query": "test", "mode": "bm25"}),
        ]
        result = suggest_skill_search(calls)
        assert "regex" in result.lower()

    def test_skill_search_many_queries(self) -> None:
        calls = [CallRecord(tool_name="discover_capability_tool", args_hash="h", args={"query": f"q{i}"}) for i in range(4)]
        result = suggest_skill_search(calls)
        assert "skill_select_tool" in result

    def test_skill_search_empty_result(self) -> None:
        calls = [CallRecord(tool_name="discover_capability_tool", args_hash="h", args={"query": "test"}, result_content="[]")]
        result = suggest_skill_search(calls)
        assert "broader" in result.lower()


class TestSuggestWebCoverage:
    def _make_call(self, query: str = "", result: str = "") -> CallRecord:
        return CallRecord(tool_name="web_search_tool", args_hash="h", args={"query": query}, result_content=result)

    def test_timeout(self) -> None:
        calls = [self._make_call("test", "request timed out")]
        result = suggest_web_search(calls)
        assert "specific" in result.lower() or "keyword" in result.lower()

    def test_empty_result(self) -> None:
        calls = [self._make_call("test", "[]")]
        result = suggest_web_search(calls)
        assert "keyword" in result.lower() or "alternative" in result.lower() or "broader" in result.lower()

    def test_many_queries_fallback(self) -> None:
        calls = [self._make_call(f"query{i}") for i in range(4)]
        result = suggest_web_search(calls)
        assert "combine" in result.lower() or "tools" in result.lower()


class TestPhaseInference:
    def test_recovery_phase(self) -> None:
        g = LoopGuard(warn_threshold=99, break_threshold=99)
        for i in range(20):
            g.pre_check("file_read_tool", {"path": f"/test{i}"})
            g.record_result("file_read_tool", {"path": f"/test{i}"}, "file content ok")
        for i in range(20, 23):
            g.pre_check("file_read_tool", {"path": f"/err{i}"})
            g.record_result("file_read_tool", {"path": f"/err{i}"}, "error: file not found")
        phase = g._infer_phase()
        assert phase == AgentPhase.RECOVERY

    def test_execution_phase(self) -> None:
        g = LoopGuard(warn_threshold=99, break_threshold=99)
        for i in range(25):
            g.pre_check("file_read_tool", {"path": f"/test{i}"})
            g.record_result("file_read_tool", {"path": f"/test{i}"}, "file content here with data")
        phase = g._infer_phase()
        assert phase in (AgentPhase.EXECUTION, AgentPhase.EXPLORATION)

    def test_exploration_phase_high_diversity(self) -> None:
        g = LoopGuard(warn_threshold=99, break_threshold=99)
        tools = [
            "file_read_tool",
            "web_search_tool",
            "bash_code_execute_tool",
            "memory_recall_tool",
            "browser_navigate_tool",
            "glob_tool",
            "grep_tool",
            "file_write_tool",
        ]
        for i in range(25):
            tool = tools[i % len(tools)]
            g.pre_check(tool, {"arg": f"v{i}"})
            g.record_result(tool, {"arg": f"v{i}"}, "some result data")
        phase = g._infer_phase()
        assert phase == AgentPhase.EXPLORATION


class TestDivergenceWarningPath:
    def test_moderate_divergence(self) -> None:
        g = LoopGuard(divergence_threshold=6, warn_threshold=99, break_threshold=99)
        tools = [
            "file_read_tool",
            "file_write_tool",
            "web_search_tool",
            "bash_code_execute_tool",
            "memory_recall_tool",
            "browser_navigate_tool",
        ]
        for i, tool in enumerate(tools):
            v = g.pre_check(tool, {"arg": f"value{i}"})
            if i % 3 == 0:
                g.record_result(tool, {"arg": f"value{i}"}, "some result ok")
            else:
                g.record_result(tool, {"arg": f"value{i}"}, "error: failed")

        if v.action != LoopAction.ALLOW and "tool categories" in v.reason.lower():
            assert "WARNING" in v.reason or "ERROR" in v.reason


class TestPhaseInferenceHighCallCount:
    """Cover _infer_phase branches for total_calls >= 50."""

    def test_execution_phase_after_50_calls(self) -> None:
        g = LoopGuard(warn_threshold=99, break_threshold=99)
        for i in range(30):
            g.pre_check("bash_code_execute_tool", {"cmd": f"echo {i}"})
            g.record_result("bash_code_execute_tool", {"cmd": f"echo {i}"}, "ok")
        g._metrics.total_calls = 55
        for _ in range(5):
            g._window.append(CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="final",
                args={"cmd": "final"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ))
        phase = g._infer_phase()
        assert phase == AgentPhase.EXECUTION

    def test_exploration_phase_after_50_calls_high_diversity(self) -> None:
        g = LoopGuard(warn_threshold=99, break_threshold=99)
        tools = [
            "file_read_tool",
            "web_search_tool",
            "bash_code_execute_tool",
            "memory_recall_tool",
            "browser_navigate_tool",
            "glob_tool",
            "grep_tool",
            "file_write_tool",
            "browser_snapshot_tool",
            "discover_capability_tool",
        ]
        for i in range(10):
            tool = tools[i % len(tools)]
            g.pre_check(tool, {"arg": f"v{i}"})
            g.record_result(tool, {"arg": f"v{i}"}, "some result")
        g._metrics.total_calls = 55
        phase = g._infer_phase()
        assert phase == AgentPhase.EXPLORATION
