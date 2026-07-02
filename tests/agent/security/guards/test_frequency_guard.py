"""Unit tests for FrequencyGuard — tool call frequency anomaly detection.

Coverage targets:
- Basic frequency detection (ALLOW/WARN/BREAK)
- Global frequency limits
- Per-tool frequency limits
- Exempted tools behavior
- Warning threshold triggers
- Sliding window expiration
- Reset functionality
- Statistics tracking
- Edge cases and error handling
"""

import time

import pytest

from myrm_agent_harness.agent.security.guards.frequency_guard import (
    FrequencyAction,
    FrequencyGuard,
    FrequencyVerdict,
    get_frequency_guard,
    reset_frequency_guard,
)


class TestFrequencyGuardBasics:
    """Test basic FrequencyGuard functionality."""

    def test_allow_under_threshold(self):
        """Test that calls under threshold are allowed."""
        guard = FrequencyGuard(global_limit=10, per_tool_limit=5)

        for _i in range(3):
            verdict = guard.check("test_tool")
            assert verdict.action == FrequencyAction.ALLOW
            guard.record("test_tool")

        assert guard.get_stats()["total_checks"] == 3
        assert guard.get_stats()["total_warns"] == 0
        assert guard.get_stats()["total_breaks"] == 0

    def test_warn_at_threshold(self):
        """Test WARN action at warning threshold (80%)."""
        guard = FrequencyGuard(global_limit=10, per_tool_limit=5, warning_ratio=0.8)

        # Fill to 80% of per-tool limit (4/5)
        for i in range(4):
            verdict = guard.check("test_tool")
            if i < 3:
                assert verdict.action == FrequencyAction.ALLOW
            guard.record("test_tool")

        # 4th check should trigger WARN
        verdict = guard.check("test_tool")
        assert verdict.action == FrequencyAction.WARN
        assert "approaching" in verdict.reason.lower()
        assert verdict.tool_count == 4
        assert verdict.tool_limit == 5
        assert verdict.tool_remaining == 1

    def test_break_at_limit(self):
        """Test BREAK action at 100% limit."""
        guard = FrequencyGuard(global_limit=10, per_tool_limit=5)

        # Fill to limit
        for _i in range(5):
            verdict = guard.check("test_tool")
            assert verdict.action in (FrequencyAction.ALLOW, FrequencyAction.WARN)
            guard.record("test_tool")

        # 6th check should trigger BREAK
        verdict = guard.check("test_tool")
        assert verdict.action == FrequencyAction.BREAK
        assert "limit exceeded" in verdict.reason.lower()
        assert verdict.tool_count == 5
        assert verdict.tool_limit == 5
        assert verdict.tool_remaining == 0


class TestGlobalLimits:
    """Test global frequency limits across all tools."""

    def test_global_limit_with_mixed_tools(self):
        """Test global limit triggers with multiple different tools."""
        guard = FrequencyGuard(global_limit=10, per_tool_limit=20)

        # Call 10 different tools (under per-tool limit but at global limit)
        tools = [f"tool_{i}" for i in range(10)]
        for tool in tools:
            verdict = guard.check(tool)
            assert verdict.action in (FrequencyAction.ALLOW, FrequencyAction.WARN)
            guard.record(tool)

        # 11th call should trigger global BREAK
        verdict = guard.check("tool_10")
        assert verdict.action == FrequencyAction.BREAK
        assert "global" in verdict.reason.lower()
        assert verdict.global_count == 10
        assert verdict.global_limit == 10

    def test_global_warn_threshold(self):
        """Test global warning at 80% threshold."""
        guard = FrequencyGuard(global_limit=10, per_tool_limit=20, warning_ratio=0.8)

        # Fill to 80% of global limit (8/10)
        for i in range(8):
            verdict = guard.check(f"tool_{i}")
            guard.record(f"tool_{i}")

        # 9th check should trigger global WARN
        verdict = guard.check("tool_8")
        assert verdict.action == FrequencyAction.WARN
        assert "global" in verdict.reason.lower()
        assert verdict.global_count == 8
        assert verdict.global_remaining == 2


class TestExemptedTools:
    """Test exempted tools behavior."""

    def test_exempted_tool_bypasses_per_tool_limit(self):
        """Test that exempted tools bypass per-tool limits."""
        guard = FrequencyGuard(
            global_limit=100,
            per_tool_limit=5,
            exempted_tools=frozenset({"memory_recall_tool"}),
        )

        # Call exempted tool 10 times (exceeds per-tool limit)
        for _i in range(10):
            verdict = guard.check("memory_recall_tool")
            assert verdict.action == FrequencyAction.ALLOW
            guard.record("memory_recall_tool")

        assert guard.get_stats()["current_window_size"] == 10

    def test_exempted_tool_still_respects_global_limit(self):
        """Test that exempted tools still count toward global limit."""
        guard = FrequencyGuard(
            global_limit=5,
            per_tool_limit=10,
            exempted_tools=frozenset({"memory_recall_tool"}),
        )

        # Fill global limit with exempted tool
        for _i in range(5):
            verdict = guard.check("memory_recall_tool")
            assert verdict.action in (FrequencyAction.ALLOW, FrequencyAction.WARN)
            guard.record("memory_recall_tool")

        # 6th call should trigger global BREAK
        verdict = guard.check("memory_recall_tool")
        assert verdict.action == FrequencyAction.BREAK
        assert "global" in verdict.reason.lower()

    def test_non_exempted_tool_has_per_tool_limit(self):
        """Test that non-exempted tools have per-tool limits."""
        guard = FrequencyGuard(
            global_limit=100,
            per_tool_limit=3,
            exempted_tools=frozenset({"memory_recall_tool"}),
        )

        # Fill per-tool limit for non-exempted tool
        for _i in range(3):
            verdict = guard.check("bash_code_execute_tool")
            guard.record("bash_code_execute_tool")

        # 4th call should trigger per-tool BREAK
        verdict = guard.check("bash_code_execute_tool")
        assert verdict.action == FrequencyAction.BREAK
        assert "bash_code_execute_tool" in verdict.reason


class TestSlidingWindow:
    """Test sliding window expiration behavior."""

    def test_window_expiration(self):
        """Test that old records expire outside the time window."""
        guard = FrequencyGuard(
            window_seconds=1.0,
            global_limit=10,
            per_tool_limit=5,
        )

        # Fill to limit
        for _i in range(5):
            verdict = guard.check("test_tool")
            guard.record("test_tool")

        # 6th call should BREAK
        verdict = guard.check("test_tool")
        assert verdict.action == FrequencyAction.BREAK

        # Wait for window to expire
        time.sleep(1.1)

        # Should be allowed again after expiration
        verdict = guard.check("test_tool")
        assert verdict.action == FrequencyAction.ALLOW
        assert verdict.tool_count == 0  # Old records expired

    def test_partial_window_expiration(self):
        """Test that only expired records are removed."""
        guard = FrequencyGuard(
            window_seconds=0.5,
            global_limit=10,
            per_tool_limit=5,
        )

        # Record 3 calls
        for _i in range(3):
            verdict = guard.check("test_tool")
            guard.record("test_tool")

        # Wait for first 3 to expire
        time.sleep(0.6)

        # Record 2 more calls (old ones should be expired)
        for _i in range(2):
            verdict = guard.check("test_tool")
            guard.record("test_tool")

        # Check should only see the 2 recent calls
        verdict = guard.check("test_tool")
        assert verdict.tool_count == 2


class TestResetFunctionality:
    """Test reset and ContextVar management."""

    def test_reset_clears_state(self):
        """Test that reset() clears all state."""
        guard = FrequencyGuard(global_limit=10, per_tool_limit=5)

        # Record some calls
        for _i in range(3):
            guard.check("test_tool")
            guard.record("test_tool")

        assert guard.get_stats()["total_checks"] == 3
        assert guard.get_stats()["current_window_size"] == 3

        # Reset
        guard.reset()

        # All state should be cleared
        assert guard.get_stats()["total_checks"] == 0
        assert guard.get_stats()["current_window_size"] == 0

        # Should be able to call again
        verdict = guard.check("test_tool")
        assert verdict.action == FrequencyAction.ALLOW

    def test_get_frequency_guard_contextvar(self):
        """Test ContextVar-based guard retrieval."""
        # Should create new guard if none exists
        guard1 = get_frequency_guard()
        assert isinstance(guard1, FrequencyGuard)

        # Should return same instance
        guard2 = get_frequency_guard()
        assert guard1 is guard2

    def test_reset_frequency_guard_contextvar(self):
        """Test ContextVar-based guard reset."""
        guard = get_frequency_guard()

        # Record some calls
        for _i in range(3):
            guard.check("test_tool")
            guard.record("test_tool")

        assert guard.get_stats()["total_checks"] == 3

        # Reset via function
        reset_frequency_guard()

        # Guard should be reset
        assert guard.get_stats()["total_checks"] == 0


class TestStatistics:
    """Test statistics tracking."""

    def test_stats_counts(self):
        """Test that statistics are correctly tracked."""
        guard = FrequencyGuard(global_limit=10, per_tool_limit=5, warning_ratio=0.8)

        # per_tool_limit=5, warning_ratio=0.8 → warn at 4 calls (80% of 5)

        # ALLOW (0-3: record 4 calls)
        for _i in range(4):
            verdict = guard.check("test_tool")
            assert verdict.action == FrequencyAction.ALLOW
            guard.record("test_tool")

        # WARN (4th check, tool_count=4, at 80% threshold)
        verdict = guard.check("test_tool")
        assert verdict.action == FrequencyAction.WARN
        guard.record("test_tool")

        # BREAK (5th check, tool_count=5, at limit)
        verdict = guard.check("test_tool")
        assert verdict.action == FrequencyAction.BREAK

        # BREAK (6th check, tool_count=5, over limit)
        verdict = guard.check("test_tool")
        assert verdict.action == FrequencyAction.BREAK

        stats = guard.get_stats()
        assert stats["total_checks"] == 7
        assert stats["total_warns"] >= 1
        assert stats["total_breaks"] >= 2
        assert stats["warn_rate"] > 0
        assert stats["break_rate"] > 0

    def test_stats_window_size(self):
        """Test current_window_size reflects active records."""
        guard = FrequencyGuard(window_seconds=10.0)

        for i in range(5):
            guard.check(f"tool_{i}")
            guard.record(f"tool_{i}")

        stats = guard.get_stats()
        assert stats["current_window_size"] == 5


class TestVerdictProperties:
    """Test FrequencyVerdict calculated properties."""

    def test_verdict_remaining_quotas(self):
        """Test verdict remaining quota calculations."""
        verdict = FrequencyVerdict(
            action=FrequencyAction.WARN,
            reason="test",
            global_count=80,
            global_limit=100,
            tool_count=24,
            tool_limit=30,
        )

        assert verdict.global_remaining == 20
        assert verdict.tool_remaining == 6

    def test_verdict_remaining_at_limit(self):
        """Test remaining quotas at limit."""
        verdict = FrequencyVerdict(
            action=FrequencyAction.BREAK,
            reason="test",
            global_count=100,
            global_limit=100,
            tool_count=30,
            tool_limit=30,
        )

        assert verdict.global_remaining == 0
        assert verdict.tool_remaining == 0

    def test_verdict_remaining_over_limit(self):
        """Test remaining quotas when over limit (should be 0)."""
        verdict = FrequencyVerdict(
            action=FrequencyAction.BREAK,
            reason="test",
            global_count=105,
            global_limit=100,
            tool_count=35,
            tool_limit=30,
        )

        assert verdict.global_remaining == 0
        assert verdict.tool_remaining == 0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_window_seconds(self):
        """Test that invalid window_seconds raises ValueError."""
        with pytest.raises(ValueError, match="window_seconds must be positive"):
            FrequencyGuard(window_seconds=0)

        with pytest.raises(ValueError, match="window_seconds must be positive"):
            FrequencyGuard(window_seconds=-1)

    def test_invalid_global_limit(self):
        """Test that invalid global_limit raises ValueError."""
        with pytest.raises(ValueError, match="global_limit must be positive"):
            FrequencyGuard(global_limit=0)

        with pytest.raises(ValueError, match="global_limit must be positive"):
            FrequencyGuard(global_limit=-1)

    def test_invalid_per_tool_limit(self):
        """Test that invalid per_tool_limit raises ValueError."""
        with pytest.raises(ValueError, match="per_tool_limit must be positive"):
            FrequencyGuard(per_tool_limit=0)

        with pytest.raises(ValueError, match="per_tool_limit must be positive"):
            FrequencyGuard(per_tool_limit=-1)

    def test_invalid_warning_ratio(self):
        """Test that invalid warning_ratio raises ValueError."""
        with pytest.raises(ValueError, match="warning_ratio must be between 0 and 1"):
            FrequencyGuard(warning_ratio=0)

        with pytest.raises(ValueError, match="warning_ratio must be between 0 and 1"):
            FrequencyGuard(warning_ratio=1.0)

        with pytest.raises(ValueError, match="warning_ratio must be between 0 and 1"):
            FrequencyGuard(warning_ratio=1.5)

    def test_empty_exempted_tools(self):
        """Test that empty exempted_tools works correctly."""
        guard = FrequencyGuard(
            global_limit=10,
            per_tool_limit=3,
            exempted_tools=frozenset(),
        )

        # All tools should have per-tool limits
        for _i in range(3):
            guard.check("memory_recall_tool")
            guard.record("memory_recall_tool")

        verdict = guard.check("memory_recall_tool")
        assert verdict.action == FrequencyAction.BREAK

    def test_check_without_record(self):
        """Test that check() without record() doesn't advance window."""
        guard = FrequencyGuard(global_limit=10, per_tool_limit=5)

        # Check 10 times without recording
        for _i in range(10):
            verdict = guard.check("test_tool")
            assert verdict.action == FrequencyAction.ALLOW

        # Window should be empty
        assert guard.get_stats()["current_window_size"] == 0

    def test_record_without_check(self):
        """Test that record() can be called independently."""
        guard = FrequencyGuard(global_limit=10, per_tool_limit=5)

        # Record without check
        for _i in range(3):
            guard.record("test_tool")

        # Next check should see those records
        verdict = guard.check("test_tool")
        assert verdict.tool_count == 3


class TestIntegration:
    """Integration tests for realistic scenarios."""

    def test_dos_attack_scenario(self):
        """Test FrequencyGuard blocks DoS-like rapid fire calls."""
        guard = FrequencyGuard(global_limit=50, per_tool_limit=20, warning_ratio=0.9)

        # Simulate attacker rapidly calling bash_tool
        for i in range(20):
            verdict = guard.check("bash_code_execute_tool")
            guard.record("bash_code_execute_tool")

        # Should be blocked at limit
        verdict = guard.check("bash_code_execute_tool")
        assert verdict.action == FrequencyAction.BREAK
        assert "bash_code_execute_tool" in verdict.reason

        # Other tools should also be affected by global limit
        for i in range(30):
            verdict = guard.check(f"tool_{i}")
            guard.record(f"tool_{i}")

        # Global limit reached
        verdict = guard.check("another_tool")
        assert verdict.action == FrequencyAction.BREAK
        assert "global" in verdict.reason.lower()

    def test_normal_usage_with_mixed_tools(self):
        """Test normal usage pattern with multiple tools."""
        guard = FrequencyGuard(global_limit=100, per_tool_limit=30)

        # Simulate normal agent execution
        tools = ["bash_code_execute_tool", "file_read_tool", "web_search_tool", "memory_recall_tool"]

        for _round in range(10):
            for tool in tools:
                verdict = guard.check(tool)
                assert verdict.action == FrequencyAction.ALLOW
                guard.record(tool)

        stats = guard.get_stats()
        assert stats["total_checks"] == 40
        assert stats["total_breaks"] == 0
        assert stats["current_window_size"] == 40

    def test_exempted_tools_allow_high_frequency(self):
        """Test that exempted tools support high-frequency operations."""
        guard = FrequencyGuard(
            global_limit=200,
            per_tool_limit=10,
            exempted_tools=frozenset({"memory_recall_tool", "skill_select_tool"}),
        )

        # High-frequency memory operations (common in agents)
        for _i in range(50):
            verdict = guard.check("memory_recall_tool")
            assert verdict.action == FrequencyAction.ALLOW
            guard.record("memory_recall_tool")

        # Should not trigger per-tool limit
        verdict = guard.check("memory_recall_tool")
        assert verdict.action == FrequencyAction.ALLOW

        # But non-exempted tool should still have limit
        for _i in range(10):
            guard.check("bash_code_execute_tool")
            guard.record("bash_code_execute_tool")

        verdict = guard.check("bash_code_execute_tool")
        assert verdict.action == FrequencyAction.BREAK


class TestPerformance:
    """Performance and stress tests."""

    def test_large_window_performance(self):
        """Test performance with large number of records."""
        guard = FrequencyGuard(global_limit=1000, per_tool_limit=500)

        # Fill window with 500 records
        start_time = time.time()
        for i in range(500):
            guard.check(f"tool_{i % 10}")
            guard.record(f"tool_{i % 10}")
        elapsed = time.time() - start_time

        # Should complete in reasonable time (< 1 second)
        assert elapsed < 1.0
        assert guard.get_stats()["current_window_size"] == 500

    def test_check_performance_with_full_window(self):
        """Test check() performance with full sliding window."""
        guard = FrequencyGuard(
            window_seconds=60.0, global_limit=1000, per_tool_limit=500
        )

        # Fill window
        for i in range(500):
            guard.record(f"tool_{i % 10}")

        # Measure check performance
        start_time = time.time()
        for i in range(100):
            guard.check("test_tool")
        elapsed = time.time() - start_time

        # Should be fast (< 0.5s for 100 checks, relaxed for CI/xdist environments)
        assert elapsed < 0.5
