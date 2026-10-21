"""Unit tests for FileActivityObserver — records file writes to FileActivityTracker."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.core.file_activity_tracker import (
    get_file_activity_tracker,
)
from myrm_agent_harness.agent.meta_tools.file_ops.observers.activity_observer import (
    FileActivityObserver,
    _diff_line_range,
)


class TestDiffLineRange:
    """Tests for _diff_line_range — finds the changed region between old and new content."""

    def test_single_line_change_in_middle(self) -> None:
        old = "a\nb\nc\nd"
        new = "a\nBB\nc\nd"
        start, end = _diff_line_range(old, new)
        assert start == 2
        assert end == 2

    def test_multi_line_change(self) -> None:
        old = "a\nb\nc\nd\ne"
        new = "a\nX\nY\nd\ne"
        start, end = _diff_line_range(old, new)
        assert start == 2
        assert end == 3

    def test_insertion_at_end(self) -> None:
        old = "a\nb"
        new = "a\nb\nc\nd"
        start, end = _diff_line_range(old, new)
        assert start == 3
        assert end == 4

    def test_deletion(self) -> None:
        old = "a\nb\nc\nd"
        new = "a\nd"
        start, end = _diff_line_range(old, new)
        assert start == 2
        assert end == 3

    def test_identical_content(self) -> None:
        old = "a\nb\nc"
        new = "a\nb\nc"
        start, end = _diff_line_range(old, new)
        assert start == end

    def test_insertion_at_beginning(self) -> None:
        old = "c\nd"
        new = "a\nb\nc\nd"
        start, end = _diff_line_range(old, new)
        assert start == 1
        assert end == 2

    def test_complete_replacement(self) -> None:
        old = "a\nb"
        new = "x\ny"
        start, end = _diff_line_range(old, new)
        assert start == 1
        assert end == 2

    def test_empty_old_to_new(self) -> None:
        old = ""
        new = "a\nb"
        start, end = _diff_line_range(old, new)
        assert start == 1
        assert end == 2

    def test_single_line_change(self) -> None:
        old = "hello"
        new = "world"
        start, end = _diff_line_range(old, new)
        assert start == 1
        assert end == 1


class TestFileActivityObserver:
    """Tests for FileActivityObserver event handling."""

    def setup_method(self) -> None:
        self.observer = FileActivityObserver()
        get_file_activity_tracker().clear()

    @pytest.mark.asyncio
    async def test_on_file_created_records_write_in_subagent(self) -> None:
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.observers.activity_observer.get_is_subagent",
                return_value=True,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.observers.activity_observer.get_subagent_task_id",
                return_value="task-1",
            ),
        ):
            await self.observer.on_file_created("/f.py", "line1\nline2\nline3")

        tracker = get_file_activity_tracker()
        result = tracker.check_conflict("other-agent", "/f.py", 1, 3)
        assert result is not None
        assert result.conflicting_agent_id == "task-1"

    @pytest.mark.asyncio
    async def test_on_file_created_noop_when_not_subagent(self) -> None:
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.observers.activity_observer.get_is_subagent",
            return_value=False,
        ):
            await self.observer.on_file_created("/f.py", "content")

        tracker = get_file_activity_tracker()
        assert tracker.check_conflict("any", "/f.py", 1, 1) is None

    @pytest.mark.asyncio
    async def test_on_file_modified_records_changed_range(self) -> None:
        old = "a\nb\nc\nd\ne"
        new = "a\nX\nY\nd\ne"

        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.observers.activity_observer.get_is_subagent",
                return_value=True,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.observers.activity_observer.get_subagent_task_id",
                return_value="task-2",
            ),
        ):
            await self.observer.on_file_modified("/f.py", old, new)

        tracker = get_file_activity_tracker()
        # Lines 2-3 changed
        result = tracker.check_conflict("other-agent", "/f.py", 2, 3)
        assert result is not None
        assert result.conflicting_agent_id == "task-2"
        assert result.level.value == "overlapping"

    @pytest.mark.asyncio
    async def test_on_file_modified_noop_when_not_subagent(self) -> None:
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.observers.activity_observer.get_is_subagent",
            return_value=False,
        ):
            await self.observer.on_file_modified("/f.py", "old", "new")

        tracker = get_file_activity_tracker()
        assert tracker.check_conflict("any", "/f.py", 1, 1) is None

    @pytest.mark.asyncio
    async def test_on_file_created_empty_content(self) -> None:
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.observers.activity_observer.get_is_subagent",
                return_value=True,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_ops.observers.activity_observer.get_subagent_task_id",
                return_value="task-empty",
            ),
        ):
            await self.observer.on_file_created("/empty.py", "")

        tracker = get_file_activity_tracker()
        result = tracker.check_conflict("other", "/empty.py", 1, 1)
        assert result is not None
        assert result.conflicting_agent_id == "task-empty"

    @pytest.mark.asyncio
    async def test_on_file_viewed_is_noop(self) -> None:
        await self.observer.on_file_viewed("/f.py")

    def teardown_method(self) -> None:
        get_file_activity_tracker().clear()
