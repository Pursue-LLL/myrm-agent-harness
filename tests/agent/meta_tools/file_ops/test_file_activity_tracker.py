"""Unit tests for FileActivityTracker — concurrent subagent file conflict detection."""

from __future__ import annotations

import time

from myrm_agent_harness.agent.meta_tools.file_ops.core.file_activity_tracker import (
    ConflictLevel,
    ConflictResult,
    FileActivityTracker,
    get_file_activity_tracker,
)


class TestFileActivityTracker:
    """Core FileActivityTracker tests."""

    def test_no_conflict_on_empty_tracker(self) -> None:
        tracker = FileActivityTracker()
        result = tracker.check_conflict("a", "/f.py", 1, 10)
        assert result is None

    def test_no_conflict_same_agent(self) -> None:
        """An agent's own writes should never conflict with itself."""
        tracker = FileActivityTracker()
        tracker.record_write("agent-a", "/f.py", 1, 10)
        result = tracker.check_conflict("agent-a", "/f.py", 1, 10)
        assert result is None

    def test_overlapping_lines_detected(self) -> None:
        """Agent A writes lines 10-20, Agent B tries lines 15-25 → OVERLAPPING."""
        tracker = FileActivityTracker()
        tracker.record_write("agent-a", "/f.py", 10, 20)
        result = tracker.check_conflict("agent-b", "/f.py", 15, 25)
        assert result is not None
        assert result.level == ConflictLevel.OVERLAPPING
        assert result.is_blocking
        assert result.conflicting_agent_id == "agent-a"

    def test_non_overlapping_same_file_detected(self) -> None:
        """Agent A writes lines 1-10, Agent B tries lines 20-30 → SAME_FILE_NON_OVERLAPPING."""
        tracker = FileActivityTracker()
        tracker.record_write("agent-a", "/f.py", 1, 10)
        result = tracker.check_conflict("agent-b", "/f.py", 20, 30)
        assert result is not None
        assert result.level == ConflictLevel.SAME_FILE_NON_OVERLAPPING
        assert not result.is_blocking

    def test_no_conflict_different_files(self) -> None:
        tracker = FileActivityTracker()
        tracker.record_write("agent-a", "/a.py", 1, 10)
        result = tracker.check_conflict("agent-b", "/b.py", 1, 10)
        assert result is None

    def test_overlapping_takes_priority(self) -> None:
        """When both overlapping and non-overlapping exist, overlapping wins."""
        tracker = FileActivityTracker()
        tracker.record_write("agent-a", "/f.py", 50, 60)
        tracker.record_write("agent-c", "/f.py", 5, 15)
        result = tracker.check_conflict("agent-b", "/f.py", 8, 12)
        assert result is not None
        assert result.level == ConflictLevel.OVERLAPPING
        assert result.conflicting_agent_id == "agent-c"

    def test_boundary_overlap(self) -> None:
        """Exact boundary touch (line_end == other.line_start) is an overlap."""
        tracker = FileActivityTracker()
        tracker.record_write("agent-a", "/f.py", 1, 10)
        result = tracker.check_conflict("agent-b", "/f.py", 10, 20)
        assert result is not None
        assert result.level == ConflictLevel.OVERLAPPING

    def test_adjacent_lines_no_overlap(self) -> None:
        """Lines 1-9 and 10-20 do NOT overlap (end < start)."""
        tracker = FileActivityTracker()
        tracker.record_write("agent-a", "/f.py", 1, 9)
        result = tracker.check_conflict("agent-b", "/f.py", 10, 20)
        assert result is not None
        assert result.level == ConflictLevel.SAME_FILE_NON_OVERLAPPING

    def test_path_normalization(self) -> None:
        tracker = FileActivityTracker()
        tracker.record_write("agent-a", "./dir/../f.py", 1, 10)
        result = tracker.check_conflict("agent-b", "f.py", 5, 15)
        assert result is not None
        assert result.level == ConflictLevel.OVERLAPPING

    def test_clear_agent(self) -> None:
        tracker = FileActivityTracker()
        tracker.record_write("agent-a", "/f.py", 1, 10)
        tracker.record_write("agent-b", "/f.py", 5, 15)

        tracker.clear_agent("agent-a")

        # Agent A's writes are gone — no conflict for agent-c checking against agent-a's range
        result = tracker.check_conflict("agent-c", "/f.py", 1, 10)
        # But agent-b's writes are still there
        assert result is not None
        assert result.conflicting_agent_id == "agent-b"

    def test_clear_all(self) -> None:
        tracker = FileActivityTracker()
        tracker.record_write("agent-a", "/f.py", 1, 10)
        tracker.record_write("agent-b", "/g.py", 1, 10)
        tracker.clear()
        assert tracker.check_conflict("agent-c", "/f.py", 1, 10) is None
        assert tracker.check_conflict("agent-c", "/g.py", 1, 10) is None

    def test_multiple_writes_same_agent_same_file(self) -> None:
        """Multiple writes by the same agent don't conflict with each other."""
        tracker = FileActivityTracker()
        tracker.record_write("agent-a", "/f.py", 1, 10)
        tracker.record_write("agent-a", "/f.py", 20, 30)
        result = tracker.check_conflict("agent-a", "/f.py", 5, 25)
        assert result is None

    def test_single_line_overlap(self) -> None:
        """Single line writes that overlap on the same line."""
        tracker = FileActivityTracker()
        tracker.record_write("agent-a", "/f.py", 5, 5)
        result = tracker.check_conflict("agent-b", "/f.py", 5, 5)
        assert result is not None
        assert result.level == ConflictLevel.OVERLAPPING

    def test_clear_agent_nonexistent_is_safe(self) -> None:
        """Clearing a non-existent agent should not raise."""
        tracker = FileActivityTracker()
        tracker.clear_agent("does-not-exist")

    def test_three_agents_same_file(self) -> None:
        """Three agents writing to the same file — pairwise conflict detection."""
        tracker = FileActivityTracker()
        tracker.record_write("a", "/f.py", 1, 10)
        tracker.record_write("b", "/f.py", 15, 25)
        tracker.record_write("c", "/f.py", 30, 40)

        result_a_vs_b = tracker.check_conflict("a", "/f.py", 15, 25)
        assert result_a_vs_b is not None
        assert result_a_vs_b.conflicting_agent_id == "b"

        result_d_no_overlap = tracker.check_conflict("d", "/f.py", 11, 14)
        assert result_d_no_overlap is not None
        assert result_d_no_overlap.level == ConflictLevel.SAME_FILE_NON_OVERLAPPING


    def test_timestamp_auto_populated(self) -> None:
        """FileAccess timestamp should be auto-populated to current time."""
        import os

        before = time.time()
        tracker = FileActivityTracker()
        tracker.record_write("a", "/f.py", 1, 5)
        after = time.time()

        norm = os.path.normpath("/f.py")
        accesses = tracker._activities.get(norm)
        assert accesses is not None
        assert len(accesses) == 1
        assert before <= accesses[0].timestamp <= after


class TestConflictResult:
    """ConflictResult message formatting tests."""

    def test_overlapping_message(self) -> None:
        result = ConflictResult(
            level=ConflictLevel.OVERLAPPING,
            conflicting_agent_id="agent-a",
            conflicting_lines=(10, 20),
            your_lines=(15, 25),
            seconds_ago=5.0,
        )
        msg = result.to_message("/f.py")
        assert "overlap" in msg.lower()
        assert "agent-a" in msg
        assert result.is_blocking

    def test_non_overlapping_message(self) -> None:
        result = ConflictResult(
            level=ConflictLevel.SAME_FILE_NON_OVERLAPPING,
            conflicting_agent_id="agent-a",
            conflicting_lines=(1, 10),
            your_lines=(20, 30),
            seconds_ago=3.0,
        )
        msg = result.to_message("/f.py")
        assert "non-overlapping" in msg.lower()
        assert not result.is_blocking

    def test_to_message_includes_path(self) -> None:
        result = ConflictResult(
            level=ConflictLevel.OVERLAPPING,
            conflicting_agent_id="agent-x",
            conflicting_lines=(1, 5),
            your_lines=(3, 8),
            seconds_ago=0.5,
        )
        msg = result.to_message("/some/deep/path.py")
        assert "/some/deep/path.py" in msg
        assert "agent-x" in msg
        assert "0s ago" in msg


class TestSingleton:
    """Module-level singleton tests."""

    def test_singleton_returns_same_instance(self) -> None:
        t1 = get_file_activity_tracker()
        t2 = get_file_activity_tracker()
        assert t1 is t2

    def teardown_method(self) -> None:
        get_file_activity_tracker().clear()
