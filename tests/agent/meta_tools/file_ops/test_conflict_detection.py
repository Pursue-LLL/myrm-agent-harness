"""Unit tests for file conflict detection integration in FileOperationService.

Tests the compute_edit_line_range helper and check_conflict_pre_write
function that integrates FileActivityTracker with file operations.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.core.file_activity_tracker import (
    get_file_activity_tracker,
)
from myrm_agent_harness.agent.meta_tools.file_ops.core.file_conflict_guard import (
    check_conflict_pre_write,
    compute_edit_line_range,
)


class TestComputeEditLineRange:
    """Tests for compute_edit_line_range — determines which lines an edit affects."""

    def test_single_line_match_at_start(self) -> None:
        content = "line1\nline2\nline3"
        start, end = compute_edit_line_range(content, "line1")
        assert start == 1
        assert end == 1

    def test_single_line_match_in_middle(self) -> None:
        content = "line1\nline2\nline3"
        start, end = compute_edit_line_range(content, "line2")
        assert start == 2
        assert end == 2

    def test_multi_line_match(self) -> None:
        content = "line1\nline2\nline3\nline4\nline5"
        start, end = compute_edit_line_range(content, "line2\nline3\nline4")
        assert start == 2
        assert end == 4

    def test_no_match_returns_whole_file(self) -> None:
        content = "line1\nline2\nline3"
        start, end = compute_edit_line_range(content, "nonexistent")
        assert start == 1
        assert end == 3

    def test_match_at_end(self) -> None:
        content = "line1\nline2\nline3"
        start, end = compute_edit_line_range(content, "line3")
        assert start == 3
        assert end == 3

    def test_empty_content(self) -> None:
        start, end = compute_edit_line_range("", "anything")
        assert start == 1
        assert end == 1


class TestCheckConflictPreWrite:
    """Tests for check_conflict_pre_write — integration with FileActivityTracker."""

    def setup_method(self) -> None:
        get_file_activity_tracker().clear()

    def test_no_check_when_not_subagent(self) -> None:
        """Should return None when not in a subagent context."""
        tracker = get_file_activity_tracker()
        tracker.record_write("other-agent", "/f.py", 1, 10)

        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_conflict_guard.get_is_subagent",
            return_value=False,
        ):
            result = check_conflict_pre_write("/f.py", 1, 10)
        assert result is None

    def test_blocking_conflict_raises(self) -> None:
        """Overlapping lines should raise ValueError."""
        tracker = get_file_activity_tracker()
        tracker.record_write("agent-a", "/f.py", 10, 20)

        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_conflict_guard.get_is_subagent",
                return_value=True,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_conflict_guard.get_subagent_task_id",
                return_value="agent-b",
            ),
            pytest.raises(ValueError, match="overlap"),
        ):
            check_conflict_pre_write("/f.py", 15, 25)

    def test_non_blocking_conflict_returns_warning(self) -> None:
        """Same file, non-overlapping lines should return a warning string."""
        tracker = get_file_activity_tracker()
        tracker.record_write("agent-a", "/f.py", 1, 10)

        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_conflict_guard.get_is_subagent",
                return_value=True,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_conflict_guard.get_subagent_task_id",
                return_value="agent-b",
            ),
        ):
            result = check_conflict_pre_write("/f.py", 20, 30)
        assert result is not None
        assert "non-overlapping" in result.lower()

    def test_no_conflict_returns_none(self) -> None:
        """Different file, should return None."""
        tracker = get_file_activity_tracker()
        tracker.record_write("agent-a", "/a.py", 1, 10)

        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_conflict_guard.get_is_subagent",
                return_value=True,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_conflict_guard.get_subagent_task_id",
                return_value="agent-b",
            ),
        ):
            result = check_conflict_pre_write("/b.py", 1, 10)
        assert result is None

    def test_subagent_task_id_none_uses_main(self) -> None:
        """When get_subagent_task_id returns None, falls back to '__main__'."""
        tracker = get_file_activity_tracker()
        tracker.record_write("other", "/f.py", 1, 10)

        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_conflict_guard.get_is_subagent",
                return_value=True,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.core.file_conflict_guard.get_subagent_task_id",
                return_value=None,
            ),
        ):
            result = check_conflict_pre_write("/f.py", 20, 30)
        assert result is not None
        assert "non-overlapping" in result.lower()

    def testcompute_edit_line_range_trailing_newline(self) -> None:
        """Content with trailing newline should handle extra empty line correctly."""
        content = "line1\nline2\n"
        start, end = compute_edit_line_range(content, "line2")
        assert start == 2
        assert end == 2

    def teardown_method(self) -> None:
        get_file_activity_tracker().clear()
