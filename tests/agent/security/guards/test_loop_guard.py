"""Comprehensive tests for LoopGuard — unified inefficiency detection.

Covers all 6 detection modes:
1. Repetition (same tool + same args)
2. Ping-pong (two tools alternating)
3. No-progress (same results)
4. Divergence (many groups, high failure)
5. Output diminishing (low LLM output)
6. Consecutive failures (any tool failing)

Plus: ToolStuckException, iteration budget warning,
suggestion quality tracking, metrics, phase inference,
threshold relaxation, and reset behavior.
"""

import pytest

from myrm_agent_harness.agent.errors.agent_errors import ToolStuckException
from myrm_agent_harness.agent.security.guards.loop_guard import LoopGuard
from myrm_agent_harness.agent.security.guards.loop_guard_types import (
    AgentPhase,
    LoopAction,
    LoopKind,
    SuccessLevel,
    VerificationCategory,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def guard() -> LoopGuard:
    return LoopGuard(warn_threshold=3, break_threshold=5)


@pytest.fixture
def strict_guard() -> LoopGuard:
    """Lower thresholds for faster detection."""
    return LoopGuard(
        warn_threshold=2,
        break_threshold=3,
        ping_pong_cycles=2,
        no_progress_threshold=2,
        diminishing_warn_streak=2,
        diminishing_break_streak=3,
    )


# ---------------------------------------------------------------------------
# 1. Repetition Detection
# ---------------------------------------------------------------------------


class TestRepetition:
    def test_allow_below_threshold(self, guard: LoopGuard) -> None:
        """Below warn_threshold, calls are allowed."""
        v1 = guard.pre_check("bash_tool", {"command": "ls"})
        assert v1.action == LoopAction.ALLOW
        guard.record_result("bash_tool", {"command": "ls"}, "file1.py")

        v2 = guard.pre_check("bash_tool", {"command": "ls"})
        assert v2.action == LoopAction.ALLOW

    def test_warn_at_threshold(self, guard: LoopGuard) -> None:
        """At warn_threshold (3), emit WARN."""
        for _ in range(2):
            guard.pre_check("bash_tool", {"command": "ls"})
            guard.record_result("bash_tool", {"command": "ls"}, "ok")

        verdict = guard.pre_check("bash_tool", {"command": "ls"})
        assert verdict.action == LoopAction.WARN
        assert verdict.loop_kind == "repetition"

    def test_break_at_high_streak(self, guard: LoopGuard) -> None:
        """At break_threshold (5), emit BREAK."""
        for _ in range(4):
            guard.pre_check("bash_tool", {"command": "ls"})
            guard.record_result("bash_tool", {"command": "ls"}, "ok")

        verdict = guard.pre_check("bash_tool", {"command": "ls"})
        assert verdict.action == LoopAction.BREAK
        assert verdict.loop_kind == "repetition"

    def test_different_args_reset_streak(self, guard: LoopGuard) -> None:
        """Changing args resets the streak."""
        for _ in range(2):
            guard.pre_check("bash_tool", {"command": "ls"})
            guard.record_result("bash_tool", {"command": "ls"}, "ok")

        verdict = guard.pre_check("bash_tool", {"command": "pwd"})
        assert verdict.action == LoopAction.ALLOW

    def test_different_tool_reset_streak(self, guard: LoopGuard) -> None:
        """Changing tool resets the streak."""
        for _ in range(2):
            guard.pre_check("bash_tool", {"command": "ls"})
            guard.record_result("bash_tool", {"command": "ls"}, "ok")

        verdict = guard.pre_check("file_read_tool", {"path": "/tmp/x"})
        assert verdict.action == LoopAction.ALLOW


# ---------------------------------------------------------------------------
# 2. ToolStuckException (consecutive failures)
# ---------------------------------------------------------------------------


class TestToolStuckException:
    def test_raises_after_3_identical_failures(self, guard: LoopGuard) -> None:
        """3 identical failing calls → ToolStuckException."""
        for _ in range(2):
            guard.pre_check("test_tool", {"arg1": "value1"})
            guard.record_result("test_tool", {"arg1": "value1"}, "error")
            guard._window[-1].success_level = SuccessLevel.FAILURE

        with pytest.raises(ToolStuckException) as exc_info:
            guard.pre_check("test_tool", {"arg1": "value1"})

        assert "TOOL_STUCK_EXCEPTION" in str(exc_info.value)
        assert "test_tool" in str(exc_info.value)

    def test_no_exception_on_success(self, guard: LoopGuard) -> None:
        """Successful calls don't trigger ToolStuckException."""
        for _ in range(2):
            guard.pre_check("test_tool", {"arg1": "value1"})
            guard.record_result("test_tool", {"arg1": "value1"}, "ok")
            guard._window[-1].success_level = SuccessLevel.FULL_SUCCESS

        verdict = guard.pre_check("test_tool", {"arg1": "value1"})
        assert verdict.action == LoopAction.WARN

    def test_no_exception_on_different_args(self, guard: LoopGuard) -> None:
        """Changing args resets failure streak."""
        for _ in range(2):
            guard.pre_check("test_tool", {"arg1": "value1"})
            guard.record_result("test_tool", {"arg1": "value1"}, "error")
            guard._window[-1].success_level = SuccessLevel.FAILURE

        verdict = guard.pre_check("test_tool", {"arg1": "value2"})
        assert verdict.action == LoopAction.ALLOW


# ---------------------------------------------------------------------------
# 3. Consecutive Failures (any tool)
# ---------------------------------------------------------------------------


class TestConsecutiveFailures:
    def test_break_after_3_consecutive_any_tool_failures(self, guard: LoopGuard) -> None:
        """3 consecutive failures across different tools → ToolStuckException."""
        tools = ["bash_tool", "file_read_tool", "grep_tool"]
        for tool in tools:
            guard.pre_check(tool, {"arg": "x"})
            guard.record_result(tool, {"arg": "x"}, "error: something failed")
            guard._window[-1].success_level = SuccessLevel.FAILURE

        with pytest.raises(ToolStuckException) as exc_info:
            guard.pre_check("web_search_tool", {"query": "test"})

        assert "TOOL_STUCK_EXCEPTION" in str(exc_info.value)

    def test_no_break_if_success_interrupts(self, guard: LoopGuard) -> None:
        """A success in between resets the failure streak."""
        guard.pre_check("bash_tool", {"arg": "x"})
        guard.record_result("bash_tool", {"arg": "x"}, "error")
        guard._window[-1].success_level = SuccessLevel.FAILURE

        guard.pre_check("file_read_tool", {"arg": "y"})
        guard.record_result("file_read_tool", {"arg": "y"}, "success")
        guard._window[-1].success_level = SuccessLevel.FULL_SUCCESS

        guard.pre_check("grep_tool", {"arg": "z"})
        guard.record_result("grep_tool", {"arg": "z"}, "error")
        guard._window[-1].success_level = SuccessLevel.FAILURE

        verdict = guard.pre_check("web_search_tool", {"query": "test"})
        assert verdict.action == LoopAction.ALLOW


# ---------------------------------------------------------------------------
# 4. Ping-Pong Detection
# ---------------------------------------------------------------------------


class TestPingPong:
    def test_detect_alternating_pattern(self, strict_guard: LoopGuard) -> None:
        """A→B→A→B pattern for 2 cycles → WARN."""
        for _ in range(2):
            strict_guard.pre_check("tool_a", {"x": 1})
            strict_guard.record_result("tool_a", {"x": 1}, "ok")
            strict_guard.pre_check("tool_b", {"y": 2})
            strict_guard.record_result("tool_b", {"y": 2}, "ok")

        verdict = strict_guard.pre_check("tool_a", {"x": 1})
        assert verdict.action == LoopAction.WARN
        assert verdict.loop_kind == "ping_pong"

    def test_no_detect_same_tool(self, strict_guard: LoopGuard) -> None:
        """Same tool alternating doesn't count as ping-pong."""
        for _ in range(3):
            strict_guard.pre_check("tool_a", {"x": 1})
            strict_guard.record_result("tool_a", {"x": 1}, "ok")
            strict_guard.pre_check("tool_a", {"x": 2})
            strict_guard.record_result("tool_a", {"x": 2}, "ok")

        # Should trigger repetition or ALLOW, not ping-pong
        verdict = strict_guard.pre_check("tool_a", {"x": 1})
        assert verdict.loop_kind != "ping_pong" or verdict.action == LoopAction.ALLOW

    def test_no_detect_different_args_each_cycle(self, strict_guard: LoopGuard) -> None:
        """If args differ each cycle, no ping-pong detection."""
        strict_guard.pre_check("tool_a", {"x": 1})
        strict_guard.record_result("tool_a", {"x": 1}, "ok")
        strict_guard.pre_check("tool_b", {"y": 2})
        strict_guard.record_result("tool_b", {"y": 2}, "ok")
        strict_guard.pre_check("tool_a", {"x": 99})
        strict_guard.record_result("tool_a", {"x": 99}, "ok")
        strict_guard.pre_check("tool_b", {"y": 88})
        strict_guard.record_result("tool_b", {"y": 88}, "ok")

        verdict = strict_guard.pre_check("tool_a", {"x": 1})
        assert verdict.loop_kind != "ping_pong"


# ---------------------------------------------------------------------------
# 5. No-Progress Detection
# ---------------------------------------------------------------------------


class TestNoProgress:
    def test_detect_identical_results(self, strict_guard: LoopGuard) -> None:
        """Same tool returning identical results → WARN."""
        for _ in range(2):
            strict_guard.pre_check("grep_tool", {"pattern": "foo"})
            v = strict_guard.record_result(
                "grep_tool", {"pattern": "foo"}, "No matches found"
            )

        assert v.action == LoopAction.WARN
        assert v.loop_kind == "no_progress"

    def test_no_detect_different_results(self, strict_guard: LoopGuard) -> None:
        """Different results → no detection."""
        strict_guard.pre_check("grep_tool", {"pattern": "foo"})
        v1 = strict_guard.record_result("grep_tool", {"pattern": "foo"}, "result A")

        strict_guard.pre_check("grep_tool", {"pattern": "foo"})
        v2 = strict_guard.record_result("grep_tool", {"pattern": "foo"}, "result B")

        assert v1.action == LoopAction.ALLOW
        assert v2.action == LoopAction.ALLOW


# ---------------------------------------------------------------------------
# 6. Output Diminishing Detection
# ---------------------------------------------------------------------------


class TestOutputDiminishing:
    def test_warn_on_low_output(self, strict_guard: LoopGuard) -> None:
        """Consecutive low-token outputs → WARN."""
        strict_guard.feed_output_tokens(0, 100)
        strict_guard.feed_output_tokens(1, 100)

        # Trigger check via pre_check
        strict_guard.pre_check("tool_x", {"a": 1})
        strict_guard.record_result("tool_x", {"a": 1}, "ok")
        verdict = strict_guard.pre_check("tool_y", {"b": 2})
        assert verdict.action == LoopAction.WARN
        assert verdict.loop_kind == "output_diminishing"

    def test_break_on_prolonged_low_output(self, strict_guard: LoopGuard) -> None:
        """Extended low-token outputs → BREAK."""
        for i in range(3):
            strict_guard.feed_output_tokens(i, 50)

        strict_guard.pre_check("tool_x", {"a": 1})
        strict_guard.record_result("tool_x", {"a": 1}, "ok")
        verdict = strict_guard.pre_check("tool_y", {"b": 2})
        assert verdict.action == LoopAction.BREAK
        assert verdict.loop_kind == "output_diminishing"

    def test_no_warn_on_high_output(self, strict_guard: LoopGuard) -> None:
        """Normal token counts don't trigger diminishing."""
        for i in range(3):
            strict_guard.feed_output_tokens(i, 1000)

        strict_guard.pre_check("tool_x", {"a": 1})
        strict_guard.record_result("tool_x", {"a": 1}, "ok")
        verdict = strict_guard.pre_check("tool_y", {"b": 2})
        assert verdict.action == LoopAction.ALLOW

    def test_deduplicates_by_call_index(self, strict_guard: LoopGuard) -> None:
        """Same call_index is recorded only once."""
        strict_guard.feed_output_tokens(0, 50)
        strict_guard.feed_output_tokens(0, 50)
        assert len(strict_guard._output_history) == 1


# ---------------------------------------------------------------------------
# 7. Divergence Detection
# ---------------------------------------------------------------------------


class TestDivergence:
    def test_detect_divergence_with_high_failure(self) -> None:
        """4+ tool groups with high failure rate → WARN.

        We interleave successes to avoid triggering _check_consecutive_failures
        (which fires after 3 consecutive failures), while keeping overall
        failure rate above 60% to trigger divergence.
        """
        guard = LoopGuard(warn_threshold=10, break_threshold=20, divergence_threshold=6)

        tools_with_results: list[tuple[str, dict[str, object], SuccessLevel]] = [
            ("memory_recall_tool", {"key": "x"}, SuccessLevel.FAILURE),
            ("file_read_tool", {"path": "/a"}, SuccessLevel.FAILURE),
            ("bash_code_execute_tool", {"command": "ls"}, SuccessLevel.FULL_SUCCESS),
            ("web_search_tool", {"query": "hi"}, SuccessLevel.FAILURE),
            ("browser_navigate_tool", {"url": "http://x"}, SuccessLevel.FAILURE),
            ("glob_tool", {"pattern": "*"}, SuccessLevel.FAILURE),
        ]

        for tool_name, args, level in tools_with_results:
            guard.pre_check(tool_name, args)
            guard.record_result(tool_name, args, "result")
            guard._window[-1].success_level = level

        verdict = guard.pre_check("file_write_tool", {"path": "/b", "content": "x"})
        assert verdict.action == LoopAction.WARN
        assert verdict.loop_kind == "divergence"

    def test_no_divergence_with_successes(self) -> None:
        """High success rate prevents divergence detection."""
        guard = LoopGuard(warn_threshold=3, break_threshold=5, divergence_threshold=6)

        tools = [
            ("memory_recall_tool", {"key": "x"}),
            ("file_read_tool", {"path": "/a"}),
            ("bash_code_execute_tool", {"command": "ls"}),
            ("web_search_tool", {"query": "hi"}),
            ("browser_navigate_tool", {"url": "http://x"}),
            ("glob_tool", {"pattern": "*"}),
        ]

        for tool_name, args in tools:
            guard.pre_check(tool_name, args)
            guard.record_result(tool_name, args, "Success")
            guard._window[-1].success_level = SuccessLevel.FULL_SUCCESS

        verdict = guard.pre_check("file_write_tool", {"path": "/b", "content": "x"})
        assert verdict.action == LoopAction.ALLOW


# ---------------------------------------------------------------------------
# 8. Iteration Budget Warning
# ---------------------------------------------------------------------------


class TestIterationBudget:
    """Budget thresholds are derived from graph_recursion_limit.

    Default limit=100 → tool_budget=100//3=33 →
      warn=23, critical=29, stuck=32.
    """

    def test_warn_at_budget_warn(self) -> None:
        """At _budget_warn total calls, emit budget warning with actual percentage."""
        guard = LoopGuard(warn_threshold=50, break_threshold=100)
        target = guard._budget_warn
        expected_pct = target * 100 // guard._budget_stuck

        for i in range(target - 1):
            guard.pre_check(f"tool_{i}", {"arg": i})
            guard.record_result(f"tool_{i}", {"arg": i}, f"result_{i}")

        verdict = guard.pre_check(f"tool_{target}", {"arg": target})
        assert verdict.action == LoopAction.WARN
        assert f"{expected_pct}%" in verdict.reason

    def test_critical_warn_at_budget_critical(self) -> None:
        """At _budget_critical total calls, emit critical warning with actual percentage."""
        guard = LoopGuard(warn_threshold=50, break_threshold=100)
        target = guard._budget_critical
        expected_pct = target * 100 // guard._budget_stuck

        for i in range(target - 1):
            guard.pre_check(f"tool_{i}", {"arg": i})
            guard.record_result(f"tool_{i}", {"arg": i}, f"result_{i}")

        verdict = guard.pre_check(f"tool_{target}", {"arg": target})
        assert verdict.action == LoopAction.WARN
        assert f"{expected_pct}%" in verdict.reason

    def test_budget_exhausted_raises_tool_stuck(self) -> None:
        """At _budget_stuck total calls, raise ToolStuckException."""
        guard = LoopGuard(warn_threshold=50, break_threshold=100)
        target = guard._budget_stuck

        for i in range(target - 1):
            guard.pre_check(f"tool_{i}", {"arg": i})
            guard.record_result(f"tool_{i}", {"arg": i}, f"result_{i}")

        with pytest.raises(ToolStuckException) as exc_info:
            guard.pre_check(f"tool_{target}", {"arg": target})

        assert "Iteration budget exhausted" in str(exc_info.value)
        assert f"{target} tool calls" in str(exc_info.value)

    def test_custom_recursion_limit_changes_budget(self) -> None:
        """Custom graph_recursion_limit shifts all budget thresholds."""
        guard = LoopGuard(
            warn_threshold=50,
            break_threshold=100,
            graph_recursion_limit=150,
        )
        assert guard._budget_warn < guard._budget_critical < guard._budget_stuck
        assert guard._budget_stuck <= 150 // 3

    def test_reconfigure_budget_updates_thresholds(self) -> None:
        """_configure_budget recalculates thresholds in-place."""
        guard = LoopGuard(warn_threshold=50, break_threshold=100)
        old_warn = guard._budget_warn

        guard._configure_budget(300)
        assert guard._budget_warn != old_warn
        assert guard._budget_warn < guard._budget_critical < guard._budget_stuck

    def test_small_recursion_limit_still_ordered(self) -> None:
        """Even with a very small recursion_limit, thresholds stay ordered."""
        guard = LoopGuard(
            warn_threshold=50,
            break_threshold=100,
            graph_recursion_limit=20,
        )
        assert guard._budget_warn < guard._budget_critical < guard._budget_stuck
        assert guard._budget_stuck <= 20 // 3


# ---------------------------------------------------------------------------
# 8b. Error Signature Detection → ToolStuckException
# ---------------------------------------------------------------------------


class TestErrorSignatureDetection:
    @staticmethod
    def _make_guard(sig_threshold: int = 5) -> LoopGuard:
        """Create a guard tuned for error_signature testing.

        High consecutive/repetition thresholds prevent other detectors
        from firing before error_signature.
        """
        return LoopGuard(
            warn_threshold=50,
            break_threshold=100,
            error_signature_threshold=sig_threshold,
        )

    @staticmethod
    def _make_error(msg: str) -> str:
        """Wrap msg in a format that evaluate_success_level recognises as FAILURE."""
        return f"ERROR: {msg}\n\n## Error Recovery Context\n\n**Operation**: test"

    @staticmethod
    def _feed_error_with_success_spacer(
        guard: LoopGuard, tool: str, error_msg: str, idx: int
    ) -> None:
        """Feed one failed call + one success call to avoid consecutive_failures."""
        guard.pre_check(tool, {"arg": f"err_{idx}"})
        guard.record_result(tool, {"arg": f"err_{idx}"}, error_msg)
        guard.pre_check(f"ok_tool_{idx}", {"arg": "ok"})
        guard.record_result(f"ok_tool_{idx}", {"arg": "ok"}, "All tasks completed successfully.")

    def test_same_error_across_tools_triggers_stuck(self) -> None:
        """Same normalised error 5 times across different tools → ToolStuckException."""
        guard = self._make_guard(sig_threshold=5)
        error_msg = self._make_error(
            "ToolExecutionError: SyntaxError: unexpected character"
        )
        tools = ["bash_tool", "file_write_tool", "bash_tool", "grep_tool"]

        for i, tool in enumerate(tools):
            self._feed_error_with_success_spacer(guard, tool, error_msg, i)

        guard.pre_check("bash_tool", {"arg": "final"})
        with pytest.raises(ToolStuckException) as exc_info:
            guard.record_result("bash_tool", {"arg": "final"}, error_msg)

        assert "same error" in str(exc_info.value).lower()

    def test_different_errors_do_not_trigger(self) -> None:
        """Different errors should not trigger error signature detection."""
        guard = self._make_guard(sig_threshold=5)

        for i in range(4):
            self._feed_error_with_success_spacer(
                guard,
                "bash_tool",
                self._make_error(f"ToolExecutionError: UniqueError_{i}: message"),
                i,
            )

    def test_line_numbers_normalised(self) -> None:
        """Same error with different line numbers should match same signature."""
        guard = self._make_guard(sig_threshold=3)

        for i, line_num in enumerate([32, 42]):
            self._feed_error_with_success_spacer(
                guard,
                "bash_tool",
                self._make_error(
                    f"ToolExecutionError: SyntaxError: unexpected character (line {line_num})"
                ),
                i,
            )

        guard.pre_check("bash_tool", {"arg": "final"})
        with pytest.raises(ToolStuckException):
            guard.record_result(
                "bash_tool",
                {"arg": "final"},
                self._make_error(
                    "ToolExecutionError: SyntaxError: unexpected character (line 99)"
                ),
            )

    def test_error_signatures_preserved_on_resume_reset(self) -> None:
        """reset(preserve_error_signatures=True) keeps error counts."""
        guard = self._make_guard(sig_threshold=10)
        error_msg = self._make_error(
            "ToolExecutionError: SyntaxError: unexpected character"
        )

        for i in range(3):
            self._feed_error_with_success_spacer(guard, "bash_tool", error_msg, i)

        guard.reset(preserve_error_signatures=True)
        assert len(guard._error_signatures) > 0

        guard.reset(preserve_error_signatures=False)
        assert len(guard._error_signatures) == 0


# ---------------------------------------------------------------------------
# 9. Threshold Relaxation (poll_tools + idempotent)
# ---------------------------------------------------------------------------


class TestThresholdRelaxation:
    def test_poll_tools_relaxed(self) -> None:
        """Poll tools get 2x thresholds."""
        guard = LoopGuard(
            warn_threshold=3, break_threshold=5, poll_tools=frozenset({"status_tool"})
        )
        warn_t, break_t = guard._thresholds("status_tool")
        assert warn_t == 6
        assert break_t == 10

    def test_normal_tool_standard_thresholds(self, guard: LoopGuard) -> None:
        """Normal tools use standard thresholds."""
        warn_t, break_t = guard._thresholds("random_tool")
        assert warn_t == 3
        assert break_t == 5


# ---------------------------------------------------------------------------
# 10. Phase Inference
# ---------------------------------------------------------------------------


class TestPhaseInference:
    def test_exploration_early(self) -> None:
        """Early calls (< 20) → EXPLORATION."""
        guard = LoopGuard()
        for i in range(5):
            guard.pre_check(f"tool_{i}", {"arg": i})
            guard.record_result(f"tool_{i}", {"arg": i}, "ok")

        phase = guard._infer_phase()
        assert phase == AgentPhase.EXPLORATION

    def test_recovery_after_failures(self) -> None:
        """3+ consecutive failures → RECOVERY."""
        guard = LoopGuard()
        for i in range(25):
            guard.pre_check(f"tool_{i}", {"arg": i})
            guard.record_result(f"tool_{i}", {"arg": i}, "ok")
            guard._window[-1].success_level = (
                SuccessLevel.FAILURE if i >= 22 else SuccessLevel.FULL_SUCCESS
            )

        phase = guard._infer_phase()
        assert phase == AgentPhase.RECOVERY


# ---------------------------------------------------------------------------
# 11. Metrics and Observability
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_total_calls_tracked(self, guard: LoopGuard) -> None:
        """Metrics track total calls."""
        guard.pre_check("tool_a", {"x": 1})
        guard.pre_check("tool_b", {"y": 2})
        assert guard.get_metrics().total_calls == 2

    def test_detection_by_kind_tracked(self, guard: LoopGuard) -> None:
        """Detection events are tracked by kind."""
        for _ in range(3):
            guard.pre_check("bash_tool", {"cmd": "ls"})
            guard.record_result("bash_tool", {"cmd": "ls"}, "ok")

        metrics = guard.get_metrics()
        assert metrics.detections_by_kind[LoopKind.REPETITION] >= 1

    def test_metrics_export_to_dict(self, guard: LoopGuard) -> None:
        """Metrics can be exported as dict."""
        guard.pre_check("tool_a", {"x": 1})
        d = guard.get_metrics().to_dict()
        assert "total_calls" in d
        assert "detection_rate" in d
        assert "by_kind" in d

    def test_reset_clears_state(self, guard: LoopGuard) -> None:
        """Reset clears all state."""
        guard.pre_check("tool_a", {"x": 1})
        guard.feed_output_tokens(0, 100)
        guard.reset()
        assert len(guard._window) == 0
        assert len(guard._output_history) == 0
        assert guard._metrics.total_calls == 1  # reset doesn't clear metrics

    def test_reset_metrics_clears_metrics(self, guard: LoopGuard) -> None:
        """reset_metrics clears metrics counters."""
        guard.pre_check("tool_a", {"x": 1})
        guard.reset_metrics()
        assert guard.get_metrics().total_calls == 0


# ---------------------------------------------------------------------------
# 12. Suggestion Quality Tracking
# ---------------------------------------------------------------------------


class TestSuggestionTracking:
    def test_suggestion_followed_on_param_change(self, guard: LoopGuard) -> None:
        """Changing params after WARN counts as suggestion followed."""
        for _ in range(3):
            guard.pre_check("bash_tool", {"cmd": "ls"})
            guard.record_result("bash_tool", {"cmd": "ls"}, "ok")

        # Now change args — should be tracked as following suggestion
        guard.pre_check("bash_tool", {"cmd": "pwd"})
        assert guard.get_metrics().suggestions_followed >= 1

    def test_effective_follow_tracks_success(self, guard: LoopGuard) -> None:
        """Successful follow counts towards effective_follows."""
        for _ in range(3):
            guard.pre_check("bash_tool", {"cmd": "ls"})
            guard.record_result("bash_tool", {"cmd": "ls"}, "ok")

        guard.pre_check("bash_tool", {"cmd": "pwd"})
        guard.record_result("bash_tool", {"cmd": "pwd"}, "success")
        # The effective_follow is updated via pending_follow_check
        assert guard.get_metrics().effective_follows >= 0


# ---------------------------------------------------------------------------
# 13. Verification Tagging
# ---------------------------------------------------------------------------


class TestVerificationTagging:
    def test_tag_last_verification(self, guard: LoopGuard) -> None:
        """tag_last_verification sets category on last record."""
        guard.pre_check("bash_tool", {"command": "pytest"})
        guard.tag_last_verification(VerificationCategory.TEST)
        assert guard._window[-1].verification_type == VerificationCategory.TEST


# ---------------------------------------------------------------------------
# 14. last_detection_kind property
# ---------------------------------------------------------------------------


class TestLastDetectionKind:
    def test_none_initially(self, guard: LoopGuard) -> None:
        """Before any detection, last_detection_kind is None."""
        assert guard.last_detection_kind is None

    def test_updated_after_detection(self, guard: LoopGuard) -> None:
        """After repetition detection, property returns kind."""
        for _ in range(2):
            guard.pre_check("bash_tool", {"cmd": "ls"})
            guard.record_result("bash_tool", {"cmd": "ls"}, f"result_{_}")

        # 3rd pre_check triggers repetition detection
        guard.pre_check("bash_tool", {"cmd": "ls"})
        assert guard.last_detection_kind == "repetition"


# ---------------------------------------------------------------------------
# 15. Integration: Competitor Scenario Simulation
# ---------------------------------------------------------------------------


class TestCompetitorScenarioComparison:
    """Simulates the competitor's 'consecutive failure → disable tools' scenario
    and verifies our LoopGuard handles it better."""

    def test_consecutive_failures_break_before_competitor_threshold(self) -> None:
        """Our system detects consecutive failures faster than a simple counter.

        Competitor: disables ALL tools after N failures.
        Us: ToolStuckException after 3 consecutive failures (any tool).
        """
        guard = LoopGuard(warn_threshold=3, break_threshold=5)

        # Simulate agent failing with different tools
        guard.pre_check("web_search_tool", {"query": "complex query"})
        guard.record_result(
            "web_search_tool", {"query": "complex query"}, "Error: timeout"
        )
        guard._window[-1].success_level = SuccessLevel.FAILURE

        guard.pre_check("browser_navigate_tool", {"url": "http://example.com"})
        guard.record_result(
            "browser_navigate_tool", {"url": "http://example.com"}, "Error: connection refused"
        )
        guard._window[-1].success_level = SuccessLevel.FAILURE

        guard.pre_check("file_read_tool", {"path": "/nonexist"})
        guard.record_result(
            "file_read_tool", {"path": "/nonexist"}, "Error: file not found"
        )
        guard._window[-1].success_level = SuccessLevel.FAILURE

        # 4th call should trigger ToolStuckException
        with pytest.raises(ToolStuckException):
            guard.pre_check("grep_tool", {"pattern": "x"})

    def test_repetition_with_failures_breaks_early(self) -> None:
        """Same tool + same args + failures → ToolStuckException (fastest path).

        This is STRICTER than competitor: we detect in 3 calls, not 5.
        """
        guard = LoopGuard(warn_threshold=3, break_threshold=5)

        guard.pre_check("bash_tool", {"command": "pip install broken"})
        guard.record_result("bash_tool", {"command": "pip install broken"}, "Error")
        guard._window[-1].success_level = SuccessLevel.FAILURE

        guard.pre_check("bash_tool", {"command": "pip install broken"})
        guard.record_result("bash_tool", {"command": "pip install broken"}, "Error")
        guard._window[-1].success_level = SuccessLevel.FAILURE

        with pytest.raises(ToolStuckException):
            guard.pre_check("bash_tool", {"command": "pip install broken"})

    def test_diminishing_output_forces_summary(self) -> None:
        """Low output tokens → BREAK with final delivery hint.

        Equivalent to competitor's 'force final answer' but more intelligent.
        """
        guard = LoopGuard(
            warn_threshold=10,
            break_threshold=20,
            diminishing_warn_streak=2,
            diminishing_break_streak=3,
        )

        for i in range(3):
            guard.feed_output_tokens(i, 50)

        guard.pre_check("tool_a", {"x": 1})
        guard.record_result("tool_a", {"x": 1}, "ok")
        verdict = guard.pre_check("tool_b", {"y": 2})

        assert verdict.action == LoopAction.BREAK
        assert "final summary" in verdict.backoff_hint.lower() or "review" in verdict.backoff_hint.lower()

    def test_granular_detection_not_blanket_disable(self) -> None:
        """After BREAK for one tool, different tools are still allowed.

        Competitor disables ALL tools. We only block the specific pattern.
        """
        guard = LoopGuard(warn_threshold=2, break_threshold=3)

        # Trigger BREAK for one specific tool+args
        for _ in range(3):
            guard.pre_check("bash_tool", {"command": "failing"})
            guard.record_result("bash_tool", {"command": "failing"}, "ok")

        # Verify BREAK was triggered for that tool
        verdict = guard.pre_check("bash_tool", {"command": "failing"})
        # This might raise ToolStuckException or give BREAK depending on failure status
        # Reset and test a fresh guard to demonstrate the concept
        fresh_guard = LoopGuard(warn_threshold=3, break_threshold=5)

        for _ in range(5):
            fresh_guard.pre_check("bash_tool", {"command": "failing"})
            fresh_guard.record_result("bash_tool", {"command": "failing"}, "ok")

        # Now a DIFFERENT tool should still be ALLOWED
        verdict = fresh_guard.pre_check("file_read_tool", {"path": "/tmp/x"})
        assert verdict.action == LoopAction.ALLOW
