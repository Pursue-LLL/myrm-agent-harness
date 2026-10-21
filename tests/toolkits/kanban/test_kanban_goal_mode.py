"""Tests for kanban goal mode data model integration.

Covers KanbanTask goal_mode / goal_max_turns field serialization,
default values, and to_dict round-trip.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.kanban.types import (
    KanbanTask,
    TaskPriority,
    TaskStatus,
)


def _make_task(**kwargs) -> KanbanTask:
    defaults = {
        "task_id": "t1",
        "board_id": "b1",
        "title": "Test Task",
        "status": TaskStatus.READY,
        "priority": TaskPriority.NORMAL,
    }
    defaults.update(kwargs)
    return KanbanTask(**defaults)


class TestKanbanTaskGoalModeFields:
    def test_goal_mode_defaults_false(self):
        task = _make_task()
        assert task.goal_mode is False
        assert task.goal_max_turns is None

    def test_goal_mode_enabled(self):
        task = _make_task(goal_mode=True, goal_max_turns=10)
        assert task.goal_mode is True
        assert task.goal_max_turns == 10

    def test_goal_mode_to_dict(self):
        task = _make_task(goal_mode=True, goal_max_turns=5)
        d = task.to_dict()
        assert d["goal_mode"] is True
        assert d["goal_max_turns"] == 5

    def test_goal_mode_disabled_to_dict(self):
        task = _make_task()
        d = task.to_dict()
        assert d["goal_mode"] is False
        assert d["goal_max_turns"] is None

    def test_goal_max_turns_none_when_mode_enabled(self):
        """goal_mode=True with goal_max_turns=None means unlimited (server defaults to 10)."""
        task = _make_task(goal_mode=True)
        assert task.goal_mode is True
        assert task.goal_max_turns is None
        d = task.to_dict()
        assert d["goal_mode"] is True
        assert d["goal_max_turns"] is None


class TestGoalModeDoesNotAffectExistingBehavior:
    """Verify goal_mode fields do not break existing task properties."""

    def test_is_terminal_unaffected(self):
        for status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.ARCHIVED]:
            task = _make_task(status=status, goal_mode=True, goal_max_turns=10)
            assert task.is_terminal is True

    def test_is_active_unaffected(self):
        for status in [TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.BLOCKED]:
            task = _make_task(status=status, goal_mode=True, goal_max_turns=5)
            assert task.is_active is True

    def test_is_retriable_unaffected(self):
        task = _make_task(goal_mode=True, retry_count=0, max_retries=3)
        assert task.is_retriable is True

    def test_priority_order_unaffected(self):
        task = _make_task(goal_mode=True, priority=TaskPriority.URGENT)
        assert task.priority_order == 0

    def test_to_dict_contains_all_original_fields(self):
        task = _make_task(goal_mode=True, goal_max_turns=10)
        d = task.to_dict()
        required_keys = {
            "task_id",
            "board_id",
            "title",
            "description",
            "status",
            "priority",
            "goal_mode",
            "goal_max_turns",
            "retry_count",
            "max_retries",
            "metadata",
            "created_at",
            "updated_at",
        }
        assert required_keys.issubset(set(d.keys()))
