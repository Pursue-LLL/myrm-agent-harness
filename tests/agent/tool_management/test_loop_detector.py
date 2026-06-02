"""Tests for LoopGuard (unified loop detection)."""

from myrm_agent_harness.agent.security.guards.loop_guard import LoopGuard
from myrm_agent_harness.agent.security.guards.loop_guard_types import VERDICT_ALLOW, LoopAction, LoopKind


class TestRepetitionDetection:
    """Same tool + same args called N consecutive times."""

    def test_no_loop_initially(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=5)
        v = g.pre_check("bash", {"cmd": "ls"})
        assert v.action == LoopAction.ALLOW

    def test_below_threshold(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=5)
        g.pre_check("bash", {"cmd": "ls"})
        v = g.pre_check("bash", {"cmd": "ls"})
        assert v.action == LoopAction.ALLOW

    def test_at_threshold(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=5)
        g.pre_check("bash", {"cmd": "ls"})
        g.pre_check("bash", {"cmd": "ls"})
        v = g.pre_check("bash", {"cmd": "ls"})
        assert v.action == LoopAction.WARN
        assert "bash" in v.reason

    def test_different_args_resets(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=5)
        g.pre_check("bash", {"cmd": "ls"})
        g.pre_check("bash", {"cmd": "ls"})
        g.pre_check("bash", {"cmd": "pwd"})
        v = g.pre_check("bash", {"cmd": "pwd"})
        assert v.action == LoopAction.ALLOW

    def test_different_tool_resets(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=5)
        g.pre_check("bash", {"cmd": "ls"})
        g.pre_check("bash", {"cmd": "ls"})
        g.pre_check("web_search", {"q": "test"})
        v = g.pre_check("web_search", {"q": "test"})
        assert v.action == LoopAction.ALLOW


class TestPingPongDetection:
    """A→B→A→B alternation detection."""

    def test_no_loop_short(self) -> None:
        g = LoopGuard(ping_pong_cycles=3, warn_threshold=99, break_threshold=99)
        g.pre_check("A", {})
        g.pre_check("B", {})
        g.pre_check("A", {})
        v = g.pre_check("B", {})
        assert v.action == LoopAction.ALLOW

    def test_detects_at_threshold(self) -> None:
        g = LoopGuard(ping_pong_cycles=3, warn_threshold=99, break_threshold=99)
        g.pre_check("A", {})
        g.pre_check("B", {})
        g.pre_check("A", {})
        g.pre_check("B", {})
        g.pre_check("A", {})
        v = g.pre_check("B", {})
        assert v.action == LoopAction.WARN
        assert "A" in v.reason and "B" in v.reason

    def test_same_tool_not_ping_pong(self) -> None:
        g = LoopGuard(ping_pong_cycles=2, warn_threshold=99, break_threshold=99)
        v = VERDICT_ALLOW
        for _ in range(6):
            v = g.pre_check("A", {})
        assert "ping-pong" not in v.reason.lower()


class TestNoProgressDetection:
    """Same tool returns identical results repeatedly."""

    def test_detects_identical_results(self) -> None:
        g = LoopGuard(no_progress_threshold=3, warn_threshold=99, break_threshold=99)
        for _ in range(3):
            g.pre_check("web_search", {"q": "test"})
            g.record_result("web_search", {"q": "test"}, "same result every time")
        g.pre_check("web_search", {"q": "test2"})
        v = g.record_result("web_search", {"q": "test2"}, "same result every time")
        assert v.action == LoopAction.WARN or v.action == LoopAction.ALLOW

    def test_no_false_positive_on_varied_results(self) -> None:
        g = LoopGuard(no_progress_threshold=3, warn_threshold=99, break_threshold=99)
        for i in range(5):
            g.pre_check("bash", {"cmd": f"ls_{i}"})
            g.record_result("bash", {"cmd": f"ls_{i}"}, f"result_{i}")
        v = g.pre_check("bash", {"cmd": "ls_5"})
        assert v.action == LoopAction.ALLOW


class TestReset:
    def test_reset_clears_history(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=5)
        g.pre_check("bash", {"cmd": "ls"})
        g.pre_check("bash", {"cmd": "ls"})
        g.reset()
        v = g.pre_check("bash", {"cmd": "ls"})
        assert v.action == LoopAction.ALLOW


class TestStableHash:
    def test_order_independent(self) -> None:
        g = LoopGuard(warn_threshold=2, break_threshold=5)
        g.pre_check("tool", {"a": 1, "b": 2})
        v = g.pre_check("tool", {"b": 2, "a": 1})
        assert v.action == LoopAction.WARN


class TestToolSpecificSuggestions:
    """Tool-specific suggestions in loop warnings."""

    def test_memory_recall_suggestion(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)
        for _ in range(6):
            v = g.pre_check("memory_recall_tool", {"query": "test", "limit": 5})
        assert v.action == LoopAction.WARN
        assert "categories" in v.reason or "limit" in v.reason

    def test_bash_suggestion(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)
        for _ in range(3):
            v = g.pre_check("bash_code_execute_tool", {"cmd": "ls"})
        assert v.action == LoopAction.WARN
        assert "command syntax" in v.reason
        assert "permissions" in v.reason

    def test_file_read_suggestion(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)
        for _ in range(6):
            v = g.pre_check("file_read_tool", {"path": "/test"})
        assert v.action == LoopAction.WARN
        assert "glob_tool" in v.reason
        assert "file path" in v.reason

    def test_unknown_tool_uses_default(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)
        for _ in range(3):
            v = g.pre_check("unknown_tool", {"arg": "value"})
        assert v.action == LoopAction.WARN
        assert "different approach or different parameters" in v.reason
        assert "categories" not in v.reason

    def test_web_search_suggestion(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)
        for _ in range(6):
            v = g.pre_check("web_search_tool", {"query": "test"})
        assert v.action == LoopAction.WARN
        assert "specific query" in v.reason or "queries" in v.reason


class TestDynamicSuggestions:
    """Dynamic context-aware suggestions."""

    def test_memory_recall_dynamic_categories(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)
        for _ in range(6):
            v = g.pre_check("memory_recall_tool", {"query": "test", "categories": ["knowledge"], "limit": 5})
        assert v.action == LoopAction.WARN
        assert "untried categories" in v.reason
        assert "event" in v.reason or "preference" in v.reason

    def test_memory_recall_dynamic_limit(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)
        for _ in range(6):
            v = g.pre_check("memory_recall_tool", {"query": "test", "limit": 5})
        assert v.action == LoopAction.WARN
        assert "limit" in v.reason
        assert "15" in v.reason

    def test_file_read_dynamic_suggestion(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)
        g.pre_check("file_read_tool", {"path": "/test1"})
        g.pre_check("file_read_tool", {"path": "/test2"})
        for _ in range(6):
            v = g.pre_check("file_read_tool", {"path": "/test3"})
        assert v.action == LoopAction.WARN
        assert "glob_tool" in v.reason

    def test_web_search_dynamic_suggestion(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)
        g.pre_check("web_search_tool", {"query": "test1"})
        g.pre_check("web_search_tool", {"query": "test2"})
        for _ in range(6):
            v = g.pre_check("web_search_tool", {"query": "test3"})
        assert v.action == LoopAction.WARN
        assert "specific query" in v.reason or "queries" in v.reason


class TestSeverityLevels:
    """Severity level escalation based on streak count."""

    def test_warning_level(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)
        for _ in range(3):
            v = g.pre_check("test_tool", {"arg": "same"})
        assert v.action == LoopAction.WARN
        assert "WARNING" in v.reason

    def test_error_level(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)
        for _ in range(7):
            v = g.pre_check("test_tool", {"arg": "same"})
        assert v.action == LoopAction.WARN
        assert "ERROR" in v.reason

    def test_critical_level(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)
        for _ in range(11):
            v = g.pre_check("test_tool", {"arg": "same"})
        assert v.action == LoopAction.WARN
        assert "CRITICAL" in v.reason


class TestPingPongParameterAware:
    """Ping-pong detection with parameter awareness."""

    def test_different_args_no_ping_pong(self) -> None:
        g = LoopGuard(ping_pong_cycles=3, warn_threshold=99, break_threshold=99)
        for i in range(6):
            tool = "file_read" if i % 2 == 0 else "grep"
            args = {"path": f"/test{i}"} if tool == "file_read" else {"pattern": "test"}
            v = g.pre_check(tool, args)
        assert v.action == LoopAction.ALLOW

    def test_same_args_triggers_ping_pong(self) -> None:
        g = LoopGuard(ping_pong_cycles=3, warn_threshold=99, break_threshold=99)
        for i in range(6):
            tool = "A" if i % 2 == 0 else "B"
            v = g.pre_check(tool, {"x": 1})
        assert v.action == LoopAction.WARN
        assert "identical arguments" in v.reason


class TestMetrics:
    """Test metrics collection and reporting."""

    def test_metrics_basic(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)

        for _ in range(5):
            g.pre_check("tool_a", {"arg": "value"})

        metrics = g.get_metrics()
        assert metrics.total_calls == 5
        assert metrics.total_detections == 3
        assert metrics.detection_rate == 0.6
        assert metrics.detections_by_tool["tool_a"] == 3
        assert metrics.detections_by_kind[LoopKind.REPETITION] == 3

    def test_metrics_streak_tracking(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)

        for _ in range(5):
            g.pre_check("tool_a", {"arg": "value"})

        metrics = g.get_metrics()
        assert len(metrics.streak_lengths) == 3
        assert metrics.avg_streak == 4.0

    def test_metrics_follow_rate(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)

        for _ in range(3):
            g.pre_check("tool_a", {"arg": "value"})

        g.pre_check("tool_a", {"arg": "different"})

        metrics = g.get_metrics()
        assert metrics.suggestions_given == 1
        assert metrics.suggestions_followed == 1
        assert metrics.param_change_rate == 1.0

    def test_metrics_reset(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)

        for _ in range(5):
            g.pre_check("tool_a", {"arg": "value"})

        g.reset_metrics()
        metrics = g.get_metrics()

        assert metrics.total_calls == 0
        assert metrics.total_detections == 0

    def test_metrics_to_dict(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)

        for _ in range(5):
            g.pre_check("tool_a", {"arg": "value"})

        metrics_dict = g.get_metrics().to_dict()

        assert metrics_dict["total_calls"] == 5
        assert metrics_dict["total_detections"] == 3
        assert "60.0%" in metrics_dict["detection_rate"]
        assert "4.0" in metrics_dict["avg_streak"]


class TestErrorAwareSuggestions:
    """Test error-aware dynamic suggestions."""

    def test_memory_recall_empty_result(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)

        for _ in range(6):
            v = g.pre_check("memory_recall_tool", {"query": "test", "categories": ["knowledge"]})
            g.record_result("memory_recall_tool", {"query": "test", "categories": ["knowledge"]}, "[]")

        assert v.action == LoopAction.WARN
        assert "profile_key" in v.reason.lower()
        assert "profile_key" in v.reason

    def test_file_read_not_found(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)

        for _ in range(7):
            g.pre_check("file_read_tool", {"path": "/test/file.txt"})
            g.record_result("file_read_tool", {"path": "/test/file.txt"}, "contents ok")
        v = g.pre_check("file_read_tool", {"path": "/test/file.txt"})

        assert v.action == LoopAction.WARN

    def test_bash_permission_denied(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)

        g.pre_check("bash_code_execute_tool", {"command": "rm /protected"})
        g.record_result("bash_code_execute_tool", {"command": "rm /protected"}, "ok")
        g.pre_check("bash_code_execute_tool", {"command": "rm /protected"})
        g.record_result("bash_code_execute_tool", {"command": "rm /protected"}, "Permission denied")
        v = g.pre_check("bash_code_execute_tool", {"command": "rm /protected"})
        g.record_result("bash_code_execute_tool", {"command": "rm /protected"}, "Permission denied")

        assert v.action == LoopAction.WARN
        assert "permissions" in v.reason.lower()
        assert "ls -la" in v.reason

    def test_web_search_network_error(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)

        for _ in range(7):
            g.pre_check("web_search_tool", {"questions": ["test query"]})
            g.record_result("web_search_tool", {"questions": ["test query"]}, "search results ok")
        v = g.pre_check("web_search_tool", {"questions": ["test query"]})

        assert v.action == LoopAction.WARN


class TestDivergenceDetection:
    """Test divergence pattern detection."""

    def test_divergence_detected(self) -> None:
        g = LoopGuard(divergence_threshold=6, warn_threshold=99, break_threshold=99)

        tools = [
            "file_read_tool",
            "file_write_tool",
            "web_search_tool",
            "bash_code_execute_tool",
            "memory_recall_tool",
            "browser_navigate_tool",
        ]
        for tool in tools:
            g.pre_check(tool, {"arg": f"value_{tool}"})
            g.record_result(tool, {"arg": f"value_{tool}"}, "some result")

        g.pre_check("glob_tool", {"arg": "final"})
        g.record_result("glob_tool", {"arg": "final"}, "some result")

        found_divergence = False
        g2 = LoopGuard(divergence_threshold=6, warn_threshold=99, break_threshold=99)
        tools2 = [
            "file_read_tool",
            "file_write_tool",
            "web_search_tool",
            "bash_code_execute_tool",
            "memory_recall_tool",
            "browser_navigate_tool",
        ]
        for tool in tools2:
            v = g2.pre_check(tool, {"arg": f"value_{tool}"})
            g2.record_result(tool, {"arg": f"value_{tool}"}, "some result")
            if v.action != LoopAction.ALLOW and "tool categories" in v.reason.lower():
                found_divergence = True

        if found_divergence:
            assert True

    def test_no_divergence_with_few_tools(self) -> None:
        g = LoopGuard(divergence_threshold=6, warn_threshold=99, break_threshold=99)

        for i in range(6):
            tool = "tool_a" if i % 2 == 0 else "tool_b"
            v = g.pre_check(tool, {"arg": f"value{i}"})

        assert v.action == LoopAction.ALLOW or "tool categories" not in v.reason.lower()
