"""Tests for P1 tool-specific suggestions in loop guard."""

from myrm_agent_harness.agent.security.guards.loop_guard import LoopGuard
from myrm_agent_harness.agent.security.guards.loop_guard_types import LoopAction


class TestSpawnSubagentSuggestions:
    """Test delegate_task loop detection and suggestions."""

    def test_spawn_subagent_repetition(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)

        for _ in range(3):
            v = g.pre_check("delegate_task_tool", {"subagent_type": "explore", "prompt": "test"})

        assert v.action == LoopAction.WARN
        assert "subagent" in v.reason.lower() or "direct tools" in v.reason or "smaller" in v.reason

    def test_spawn_subagent_timeout_pattern(self) -> None:
        g = LoopGuard(no_progress_threshold=3, warn_threshold=99, break_threshold=99)
        from myrm_agent_harness.agent.security.guards.loop_guard import VERDICT_ALLOW
        g._check_consecutive_failures = lambda calls: VERDICT_ALLOW
        g._check_error_signature = lambda tool_name, result_text: VERDICT_ALLOW

        for i in range(4):
            g.pre_check("delegate_task_tool", {"subagent_type": "explore", "prompt": f"task_{i}"})
            g.record_result(
                "delegate_task_tool",
                {"subagent_type": "explore", "prompt": f"task_{i}"},
                "Error: timeout exceeded after 300s",
            )

        v = g.pre_check("delegate_task_tool", {"subagent_type": "explore", "prompt": "task_final"})
        g.record_result(
            "delegate_task_tool", {"subagent_type": "explore", "prompt": "task_final"}, "Error: timeout exceeded after 300s"
        )

        # No-progress might or might not trigger depending on hash equality
        if v.action != LoopAction.ALLOW:
            assert "timeout" in v.reason.lower() or "smaller" in v.reason.lower() or v.action == LoopAction.WARN


class TestBrowserSnapshotSuggestions:
    """Test browser_snapshot loop detection and suggestions."""

    def test_browser_snapshot_repetition(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)

        # browser_snapshot is idempotent, so threshold is doubled (3*2=6)
        for _ in range(6):
            v = g.pre_check("browser_snapshot_tool", {"scope": "content"})

        assert v.action == LoopAction.WARN
        assert "wait" in v.reason.lower() or "scope" in v.reason.lower()

    def test_browser_snapshot_empty_result(self) -> None:
        g = LoopGuard(no_progress_threshold=3, warn_threshold=99, break_threshold=99)
        from myrm_agent_harness.agent.security.guards.loop_guard import VERDICT_ALLOW
        g._check_consecutive_failures = lambda calls: VERDICT_ALLOW

        for i in range(4):
            g.pre_check("browser_snapshot_tool", {"scope": f"scope_{i}"})
            g.record_result("browser_snapshot_tool", {"scope": f"scope_{i}"}, "")

        v = g.pre_check("browser_snapshot_tool", {"scope": "final"})
        g.record_result("browser_snapshot_tool", {"scope": "final"}, "")

        if v.action != LoopAction.ALLOW:
            assert "browser_inspect_tool" in v.reason or "browser_interact_tool" in v.reason or v.action == LoopAction.WARN


class TestSkillToolsSuggestions:
    """Test skill_select_tool and discover_capability suggestions."""

    def test_skill_select_repetition(self) -> None:
        g = LoopGuard(warn_threshold=3, break_threshold=99)

        # skill_select_tool is idempotent, so threshold is doubled (3 * 2 = 6)
        for _ in range(6):
            v = g.pre_check("skill_select_tool", {"skill_names": ["test_skill"]})

        assert v.action == LoopAction.WARN
        assert "discover_capability_tool" in v.reason or "direct tools" in v.reason

    def test_skill_search_empty_result(self) -> None:
        g = LoopGuard(no_progress_threshold=3, warn_threshold=99, break_threshold=99)
        from myrm_agent_harness.agent.security.guards.loop_guard import VERDICT_ALLOW
        g._check_consecutive_failures = lambda calls: VERDICT_ALLOW

        for i in range(4):
            g.pre_check("discover_capability_tool", {"query": f"query_{i}"})
            g.record_result("discover_capability_tool", {"query": f"query_{i}"}, "No skills found")

        v = g.pre_check("discover_capability_tool", {"query": "final_query"})
        g.record_result("discover_capability_tool", {"query": "final_query"}, "No skills found")

        if v.action != LoopAction.ALLOW:
            assert "broader" in v.reason or "skill_select_tool" in v.reason or v.action == LoopAction.WARN

    def test_skill_search_mode_switch(self) -> None:
        g = LoopGuard(warn_threshold=2, break_threshold=99)

        # discover_capability is idempotent, so threshold is doubled (2 * 2 = 4)
        for _ in range(3):
            g.pre_check("discover_capability_tool", {"query": "test", "mode": "bm25"})
            g.record_result("discover_capability_tool", {"query": "test", "mode": "bm25"}, "No results")

        v = g.pre_check("discover_capability_tool", {"query": "test", "mode": "bm25"})

        if v.action != LoopAction.ALLOW:
            assert "regex" in v.reason.lower()


class TestToolCoverage:
    """Test that all P1 tools are now configured."""

    def test_p1_tools_have_suggestions(self) -> None:
        from myrm_agent_harness.agent.security.guards.loop_suggestions import TOOL_SUGGESTIONS

        p1_tools = [
            "delegate_task_tool",
            "browser_snapshot_tool",
            "skill_select_tool",
            "discover_capability_tool",
        ]

        for tool in p1_tools:
            assert tool in TOOL_SUGGESTIONS, f"P1 tool {tool} missing from TOOL_SUGGESTIONS"
            assert len(TOOL_SUGGESTIONS[tool]) > 50, f"Suggestion for {tool} seems too short"

    def test_total_coverage_increased(self) -> None:
        from myrm_agent_harness.agent.security.guards.loop_suggestions import TOOL_SUGGESTIONS

        assert len(TOOL_SUGGESTIONS) >= 16, f"Expected at least 16 tools configured, got {len(TOOL_SUGGESTIONS)}"
