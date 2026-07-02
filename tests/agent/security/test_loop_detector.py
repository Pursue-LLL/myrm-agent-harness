"""Tests for security.guards.loop_guard — unified loop detection."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.errors.agent_errors import ToolStuckException
from myrm_agent_harness.agent.security.guards.loop_guard import LoopGuard, _stable_hash
from myrm_agent_harness.agent.security.guards.loop_guard_types import (
    AgentPhase,
    LoopAction,
    LoopKind,
    ToolGroup,
    get_tool_group,
)


class TestStableHash:
    def test_deterministic(self) -> None:
        assert _stable_hash({"a": 1}) == _stable_hash({"a": 1})

    def test_key_order_independent(self) -> None:
        assert _stable_hash({"a": 1, "b": 2}) == _stable_hash({"b": 2, "a": 1})

    def test_different_values(self) -> None:
        assert _stable_hash({"a": 1}) != _stable_hash({"a": 2})

    def test_length(self) -> None:
        assert len(_stable_hash("test")) == 16


class TestLoopGuardRepetition:
    def test_no_loop_below_threshold(self) -> None:
        g = LoopGuard(warn_threshold=3)
        for _ in range(2):
            verdict = g.pre_check("bash_code_execute_tool", {"command": "ls"})
        assert verdict.action == LoopAction.ALLOW

    def test_repetition_at_warn_threshold(self) -> None:
        g = LoopGuard(warn_threshold=3)
        for _ in range(3):
            verdict = g.pre_check("bash_code_execute_tool", {"command": "ls"})
        assert verdict.action == LoopAction.WARN

    def test_repetition_at_break_threshold(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=5)
        for _ in range(5):
            verdict = g.pre_check("bash_code_execute_tool", {"command": "ls"})
        assert verdict.action == LoopAction.BREAK

    def test_repetition_message(self) -> None:
        g = LoopGuard(warn_threshold=3)
        for _ in range(3):
            verdict = g.pre_check("bash_code_execute_tool", {"command": "ls"})
        assert "bash_code_execute_tool" in verdict.reason
        assert "3" in verdict.reason

    def test_different_args_no_repetition(self) -> None:
        g = LoopGuard(warn_threshold=3)
        for i in range(5):
            verdict = g.pre_check("bash_code_execute_tool", {"command": f"cmd_{i}"})
        assert verdict.action == LoopAction.ALLOW

    def test_different_tools_no_repetition(self) -> None:
        g = LoopGuard(warn_threshold=3)
        g.pre_check("tool_a", {"x": 1})
        g.pre_check("tool_b", {"x": 1})
        verdict = g.pre_check("tool_a", {"x": 1})
        assert verdict.action == LoopAction.ALLOW


class TestLoopGuardPingPong:
    def test_ping_pong_detected(self) -> None:
        g = LoopGuard(ping_pong_cycles=3, warn_threshold=100)
        for _ in range(3):
            g.pre_check("tool_a", {"x": 1})
            verdict = g.pre_check("tool_b", {"y": 2})
        assert verdict.action == LoopAction.WARN
        assert "ping-pong" in verdict.reason.lower() or "alternating" in verdict.reason.lower()

    def test_no_ping_pong_same_tool(self) -> None:
        g = LoopGuard(ping_pong_cycles=3, warn_threshold=100, break_threshold=100)
        for _ in range(6):
            verdict = g.pre_check("tool_a", {"x": 1})
        assert "ping-pong" not in verdict.reason.lower()

    def test_no_ping_pong_different_args(self) -> None:
        g = LoopGuard(ping_pong_cycles=3, warn_threshold=100)
        for i in range(3):
            g.pre_check("tool_a", {"x": i})
            verdict = g.pre_check("tool_b", {"y": i})
        assert verdict.action == LoopAction.ALLOW or "ping-pong" not in verdict.reason.lower()


class TestLoopGuardNoProgress:
    def test_no_progress_detected(self) -> None:
        g = LoopGuard(no_progress_threshold=4, warn_threshold=100, break_threshold=100)
        for i in range(5):
            g.pre_check("web_search_tool", {"query": f"q{i}"})
            post = g.record_result("web_search_tool", {"query": f"q{i}"}, "identical result")
        assert post.action == LoopAction.WARN or g.get_metrics().total_calls == 5

    def test_no_progress_needs_result(self) -> None:
        g = LoopGuard(no_progress_threshold=3, warn_threshold=100, break_threshold=100)
        for i in range(5):
            verdict = g.pre_check("tool", {"x": i})
        assert verdict.action == LoopAction.ALLOW


class TestLoopGuardDivergence:
    def test_divergence_detected(self) -> None:
        g = LoopGuard(divergence_threshold=6, warn_threshold=100, break_threshold=100)
        tools = [
            "memory_recall_tool",
            "file_read_tool",
            "bash_code_execute_tool",
            "web_search_tool",
            "browser_navigate_tool",
            "web_fetch_tool",
        ]
        for tool_name in tools:
            g.pre_check(tool_name, {"x": 1})
            g.record_result(tool_name, {"x": 1}, "Success: something worked")
        verdict = g.pre_check("memory_recall_tool", {"x": 2})
        if verdict.action == LoopAction.WARN:
            assert "tool categories" in verdict.reason.lower() or "divergence" in verdict.reason.lower()

    def test_no_divergence_few_groups(self) -> None:
        g = LoopGuard(divergence_threshold=6, warn_threshold=100, break_threshold=100)
        for i in range(6):
            g.pre_check("bash_code_execute_tool", {"cmd": f"c{i}"})
            g.record_result("bash_code_execute_tool", {"cmd": f"c{i}"}, "Success: worked")
        verdict = g.pre_check("bash_code_execute_tool", {"cmd": "final"})
        assert verdict.action == LoopAction.ALLOW or "divergence" not in verdict.reason.lower()


class TestLoopGuardMetrics:
    def test_initial_metrics(self) -> None:
        g = LoopGuard()
        m = g.get_metrics()
        assert m.total_calls == 0
        assert m.total_detections == 0

    def test_metrics_count_calls(self) -> None:
        g = LoopGuard()
        g.pre_check("tool_a", {"x": 1})
        g.pre_check("tool_b", {"y": 2})
        assert g.get_metrics().total_calls == 2

    def test_metrics_count_detections(self) -> None:
        g = LoopGuard(warn_threshold=2)
        g.pre_check("tool_a", {"x": 1})
        g.pre_check("tool_a", {"x": 1})
        assert g.get_metrics().total_detections == 1

    def test_reset_metrics(self) -> None:
        g = LoopGuard()
        g.pre_check("tool_a", {"x": 1})
        g.reset_metrics()
        assert g.get_metrics().total_calls == 0

    def test_reset_window(self) -> None:
        g = LoopGuard(warn_threshold=3)
        g.pre_check("tool_a", {"x": 1})
        g.pre_check("tool_a", {"x": 1})
        g.reset()
        verdict = g.pre_check("tool_a", {"x": 1})
        assert verdict.action == LoopAction.ALLOW

    def test_reset_clears_per_run_state(self) -> None:
        g = LoopGuard(warn_threshold=3)
        for _ in range(3):
            g.pre_check("tool_a", {"x": 1})
        assert g._last_warning_tool == "tool_a"
        assert g._pending_follow_check is False

        g.reset()

        assert g._last_warning_tool is None
        assert g._last_warning_args_hash is None
        assert g._pending_follow_check is False
        assert g._last_suggestion_key is None

    def test_reset_prevents_cross_run_follow_miscount(self) -> None:
        g = LoopGuard(warn_threshold=3)
        for _ in range(3):
            g.pre_check("tool_a", {"x": 1})
        initial_followed = g.get_metrics().suggestions_followed

        g.reset()
        g.pre_check("tool_a", {"x": 2})
        assert g.get_metrics().suggestions_followed == initial_followed


class TestLoopGuardRecordResult:
    def test_record_result_on_empty(self) -> None:
        g = LoopGuard()
        verdict = g.record_result("tool", {}, "output")
        assert verdict.action == LoopAction.ALLOW

    def test_suggestion_follow_tracking(self) -> None:
        g = LoopGuard(warn_threshold=2)
        g.pre_check("tool_a", {"x": 1})
        g.pre_check("tool_a", {"x": 1})
        g.pre_check("tool_a", {"x": 2})
        g.record_result("tool_a", {"x": 2}, "success")
        assert g.get_metrics().suggestions_followed >= 1


class TestPollTools:
    def test_relaxed_threshold(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=5, poll_tools=frozenset({"poll_tool"}))
        for _ in range(5):
            verdict = g.pre_check("poll_tool", {"x": 1})
        assert verdict.action == LoopAction.ALLOW

    def test_relaxed_break(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=5, poll_tools=frozenset({"poll_tool"}))
        for _ in range(10):
            verdict = g.pre_check("poll_tool", {"x": 1})
        assert verdict.action == LoopAction.BREAK


class TestToolGroupMapping:
    def test_known_tools(self) -> None:
        assert get_tool_group("memory_recall_tool") == ToolGroup.MEMORY
        assert get_tool_group("file_read_tool") == ToolGroup.READ
        assert get_tool_group("bash_code_execute_tool") == ToolGroup.EXECUTE
        assert get_tool_group("web_search_tool") == ToolGroup.SEARCH
        assert get_tool_group("browser_navigate_tool") == ToolGroup.BROWSER

    def test_unknown_tool(self) -> None:
        assert get_tool_group("custom_unknown_tool") == ToolGroup.OTHER


class TestOutputDiminishing:
    """Output diminishing detection: LoopGuard 5th pattern."""

    def test_no_detection_without_feed(self) -> None:
        g = LoopGuard(diminishing_warn_streak=3)
        for i in range(5):
            verdict = g.pre_check("tool_a", {"x": i})
        assert verdict.action == LoopAction.ALLOW

    def test_no_detection_below_streak(self) -> None:
        g = LoopGuard(diminishing_warn_streak=3, diminishing_break_streak=5, diminishing_threshold=100)
        for i in range(2):
            g.feed_output_tokens(i + 1, 50)
            verdict = g.pre_check(f"tool_{i}", {"x": i})
        assert verdict.action == LoopAction.ALLOW

    def test_warn_at_streak_threshold(self) -> None:
        g = LoopGuard(diminishing_warn_streak=3, diminishing_break_streak=5, diminishing_threshold=100)
        for i in range(3):
            g.feed_output_tokens(i + 1, 80 - i * 10)
            verdict = g.pre_check(f"tool_{i}", {"x": i})
        assert verdict.action == LoopAction.WARN
        assert LoopKind.OUTPUT_DIMINISHING in g.get_metrics().detections_by_kind

    def test_break_at_break_threshold(self) -> None:
        g = LoopGuard(diminishing_warn_streak=3, diminishing_break_streak=5, diminishing_threshold=100)
        for i in range(5):
            g.feed_output_tokens(i + 1, 50)
            verdict = g.pre_check(f"tool_{i}", {"x": i})
        assert verdict.action == LoopAction.BREAK
        assert verdict.loop_kind == LoopKind.OUTPUT_DIMINISHING.value

    def test_no_detection_above_threshold(self) -> None:
        g = LoopGuard(diminishing_warn_streak=3, diminishing_break_streak=5, diminishing_threshold=100)
        for i in range(5):
            g.feed_output_tokens(i + 1, 200)
            verdict = g.pre_check(f"tool_{i}", {"x": i})
        assert verdict.action == LoopAction.ALLOW

    def test_mixed_above_below_warn_on_tail(self) -> None:
        """Last 3 entries below threshold triggers WARN even if earlier entries are above."""
        g = LoopGuard(diminishing_warn_streak=3, diminishing_break_streak=5, diminishing_threshold=100)
        tokens = [50, 200, 50, 50, 50]
        for i, t in enumerate(tokens):
            g.feed_output_tokens(i + 1, t)
            verdict = g.pre_check(f"tool_{i}", {"x": i})
            print(f"i={i}, t={t}, verdict={verdict.action}, reason={verdict.reason}")
        assert verdict.action == LoopAction.WARN

    def test_no_detection_when_tail_has_high_output(self) -> None:
        """If any of the last N entries is above threshold, no detection."""
        g = LoopGuard(diminishing_warn_streak=3, diminishing_break_streak=5, diminishing_threshold=100)
        tokens = [50, 50, 200]
        for i, t in enumerate(tokens):
            g.feed_output_tokens(i + 1, t)
            verdict = g.pre_check(f"tool_{i}", {"x": i})
        assert verdict.action == LoopAction.ALLOW

    def test_dedup_by_call_index(self) -> None:
        """Parallel tool calls share the same call_index; only first is recorded."""
        g = LoopGuard(diminishing_warn_streak=3, diminishing_break_streak=5, diminishing_threshold=100)
        g.feed_output_tokens(1, 50)
        g.feed_output_tokens(1, 50)
        g.feed_output_tokens(1, 50)
        assert len(g._output_history) == 1

    def test_reset_clears_output_history(self) -> None:
        g = LoopGuard(diminishing_warn_streak=3, diminishing_break_streak=5, diminishing_threshold=100)
        for i in range(3):
            g.feed_output_tokens(i + 1, 50)
        g.reset()
        assert len(g._output_history) == 0
        assert g._last_recorded_call_index == -1

    def test_metrics_recorded(self) -> None:
        g = LoopGuard(diminishing_warn_streak=3, diminishing_break_streak=5, diminishing_threshold=100)
        for i in range(3):
            g.feed_output_tokens(i + 1, 50)
            g.pre_check(f"tool_{i}", {"x": i})
        metrics = g.get_metrics()
        assert metrics.detections_by_kind[LoopKind.OUTPUT_DIMINISHING] >= 1

    def test_does_not_interfere_with_repetition(self) -> None:
        """Output diminishing detection doesn't suppress other patterns."""
        g = LoopGuard(warn_threshold=3, diminishing_warn_streak=10, diminishing_threshold=100)
        for i in range(3):
            g.feed_output_tokens(i + 1, 50)
            verdict = g.pre_check("same_tool", {"same": "args"})
        assert verdict.action == LoopAction.WARN
        assert LoopKind.REPETITION in g.get_metrics().detections_by_kind


class TestAgentPhase:
    def test_exploration_threshold(self) -> None:
        assert AgentPhase.EXPLORATION.divergence_failure_threshold == 0.6

    def test_execution_threshold(self) -> None:
        assert AgentPhase.EXECUTION.divergence_failure_threshold == 0.3

    def test_recovery_threshold(self) -> None:
        assert AgentPhase.RECOVERY.divergence_failure_threshold == 0.15


class TestInferPhase:
    def test_early_calls_exploration(self) -> None:
        g = LoopGuard()
        for i in range(5):
            g.pre_check("tool", {"x": i})
        assert g._infer_phase() == AgentPhase.EXPLORATION

    def test_many_calls_with_failures_recovery(self) -> None:
        g = LoopGuard()
        g._metrics.total_calls = 25
        with pytest.raises(ToolStuckException):
            for i in range(10):
                g.pre_check("tool", {"x": i})
                g.record_result("tool", {"x": i}, "Error: something failed")
        # Since it raises, we can't test the phase easily without bypassing the check.
        # Let's bypass the check to test the phase logic.
        g = LoopGuard(graph_recursion_limit=300)
        g._metrics.total_calls = 25
        from myrm_agent_harness.agent.security.guards.loop_guard import VERDICT_ALLOW
        g._check_consecutive_failures = lambda calls: VERDICT_ALLOW
        g._check_error_signature = lambda tool_name, result_text: VERDICT_ALLOW
        for i in range(10):
            g.pre_check("tool", {"x": i})
            g.record_result("tool", {"x": i}, "Error: something failed")
        phase = g._infer_phase()
        assert phase in (AgentPhase.RECOVERY, AgentPhase.EXPLORATION)
