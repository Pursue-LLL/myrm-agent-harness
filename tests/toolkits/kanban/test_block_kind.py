"""Tests for BlockKind, scheduled blocking, and auto-wakeup."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.kanban.dispatcher import KanbanDispatcher
from myrm_agent_harness.toolkits.kanban.kanban_agent_tools import (
    _parse_until,
    create_kanban_tools,
)
from myrm_agent_harness.toolkits.kanban.stores import InMemoryKanbanStore
from myrm_agent_harness.toolkits.kanban.types import (
    BlockKind,
    BoardSettings,
    KanbanBoard,
    KanbanTask,
    TaskEventKind,
    TaskRunOutcome,
    TaskStatus,
)


def _make_board(board_id: str = "b1") -> KanbanBoard:
    return KanbanBoard(
        board_id=board_id,
        name="Test Board",
        settings=BoardSettings(
            max_concurrent_tasks=3,
            zombie_timeout_seconds=60,
            auto_block_after_consecutive_failures=3,
        ),
    )


def _make_task(
    task_id: str = "t1",
    board_id: str = "b1",
    status: TaskStatus = TaskStatus.READY,
) -> KanbanTask:
    return KanbanTask(
        task_id=task_id,
        board_id=board_id,
        title=f"Task {task_id}",
        status=status,
    )


# ---------------------------------------------------------------------------
# BlockKind enum
# ---------------------------------------------------------------------------


class TestBlockKind:
    def test_values(self) -> None:
        assert BlockKind.HUMAN == "human"
        assert BlockKind.SCHEDULED == "scheduled"
        assert BlockKind.EXTERNAL == "external"

    def test_from_str(self) -> None:
        assert BlockKind("human") is BlockKind.HUMAN
        assert BlockKind("scheduled") is BlockKind.SCHEDULED
        assert BlockKind("external") is BlockKind.EXTERNAL


# ---------------------------------------------------------------------------
# KanbanTask block fields
# ---------------------------------------------------------------------------


class TestKanbanTaskBlockFields:
    def test_defaults_none(self) -> None:
        task = _make_task()
        assert task.block_kind is None
        assert task.scheduled_until is None

    def test_to_dict_with_block_kind(self) -> None:
        task = _make_task()
        task.block_kind = BlockKind.SCHEDULED
        task.scheduled_until = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        d = task.to_dict()
        assert d["block_kind"] == "scheduled"
        assert d["scheduled_until"] == "2026-06-01T00:00:00+00:00"

    def test_to_dict_without_block_kind(self) -> None:
        task = _make_task()
        d = task.to_dict()
        assert d["block_kind"] is None
        assert d["scheduled_until"] is None


# ---------------------------------------------------------------------------
# _parse_until
# ---------------------------------------------------------------------------


class TestParseUntil:
    def test_empty(self) -> None:
        assert _parse_until("") is None

    def test_duration_minutes(self) -> None:
        result = _parse_until("30m")
        assert result is not None
        assert result > datetime.now(UTC)
        assert result < datetime.now(UTC) + timedelta(minutes=31)

    def test_duration_hours(self) -> None:
        result = _parse_until("2h")
        assert result is not None
        delta = result - datetime.now(UTC)
        assert timedelta(hours=1, minutes=59) < delta < timedelta(hours=2, minutes=1)

    def test_duration_combined(self) -> None:
        result = _parse_until("1d2h30m")
        assert result is not None
        delta = result - datetime.now(UTC)
        expected = timedelta(days=1, hours=2, minutes=30)
        assert abs(delta - expected) < timedelta(seconds=2)

    def test_iso_with_tz(self) -> None:
        result = _parse_until("2026-06-01T04:00:00+00:00")
        assert result is not None
        assert result.tzinfo is not None
        assert result.year == 2026

    def test_iso_without_tz(self) -> None:
        result = _parse_until("2026-06-01T04:00:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_invalid(self) -> None:
        assert _parse_until("abc") is None
        assert _parse_until("next tuesday") is None


# ---------------------------------------------------------------------------
# InMemoryKanbanStore.list_due_scheduled_tasks
# ---------------------------------------------------------------------------


class TestStoreListDueScheduledTasks:
    @pytest.fixture
    async def store_with_tasks(self) -> InMemoryKanbanStore:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)

        past = datetime.now(UTC) - timedelta(minutes=5)
        future = datetime.now(UTC) + timedelta(hours=1)

        t1 = _make_task("t1", status=TaskStatus.BLOCKED)
        t1.block_kind = BlockKind.SCHEDULED
        t1.scheduled_until = past
        await store.save_task(t1)

        t2 = _make_task("t2", status=TaskStatus.BLOCKED)
        t2.block_kind = BlockKind.SCHEDULED
        t2.scheduled_until = future
        await store.save_task(t2)

        t3 = _make_task("t3", status=TaskStatus.BLOCKED)
        t3.block_kind = BlockKind.HUMAN
        await store.save_task(t3)

        t4 = _make_task("t4", status=TaskStatus.READY)
        await store.save_task(t4)

        return store

    @pytest.mark.asyncio
    async def test_returns_only_due_tasks(
        self, store_with_tasks: InMemoryKanbanStore,
    ) -> None:
        due = await store_with_tasks.list_due_scheduled_tasks("b1")
        assert len(due) == 1
        assert due[0].task_id == "t1"

    @pytest.mark.asyncio
    async def test_empty_board(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        due = await store.list_due_scheduled_tasks("b1")
        assert due == []


# ---------------------------------------------------------------------------
# kanban_block tool with until param
# ---------------------------------------------------------------------------


class TestKanbanBlockTool:
    @pytest.fixture
    async def setup(self) -> tuple[InMemoryKanbanStore, list]:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task("t1", status=TaskStatus.RUNNING)
        await store.save_task(task)
        tools = create_kanban_tools(
            store, mode="worker", current_task_id="t1", agent_id="a1",
        )
        return store, tools

    def _get_tool(self, tools: list, name: str):
        for t in tools:
            if t.name == name:
                return t
        raise ValueError(f"Tool {name} not found")

    @pytest.mark.asyncio
    async def test_block_with_until(
        self, setup: tuple[InMemoryKanbanStore, list],
    ) -> None:
        _store, tools = setup
        block_tool = self._get_tool(tools, "kanban_block")
        result = json.loads(await block_tool.ainvoke({
            "reason": "Waiting for build",
            "until": "30m",
        }))
        assert result["status"] == "blocked"
        task = result["task"]
        assert task["block_kind"] == "scheduled"
        assert task["scheduled_until"] is not None

    @pytest.mark.asyncio
    async def test_block_without_until(
        self, setup: tuple[InMemoryKanbanStore, list],
    ) -> None:
        _store, tools = setup
        block_tool = self._get_tool(tools, "kanban_block")
        result = json.loads(await block_tool.ainvoke({
            "reason": "Needs PR review",
        }))
        assert result["status"] == "blocked"
        task = result["task"]
        assert task["block_kind"] == "human"
        assert task["scheduled_until"] is None

    @pytest.mark.asyncio
    async def test_block_invalid_until(
        self, setup: tuple[InMemoryKanbanStore, list],
    ) -> None:
        _store, tools = setup
        block_tool = self._get_tool(tools, "kanban_block")
        result = json.loads(await block_tool.ainvoke({
            "reason": "test",
            "until": "invalid_format",
        }))
        assert "error" in result
        assert "Invalid" in result["error"]


# ---------------------------------------------------------------------------
# Dispatcher auto-wakeup
# ---------------------------------------------------------------------------


class _DummyRunner:
    async def run(self, task: KanbanTask) -> tuple[bool, str]:
        return True, "done"


class TestDispatcherAutoWakeup:
    @pytest.mark.asyncio
    async def test_wakeup_scheduled_task(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)

        task = _make_task("t1", status=TaskStatus.BLOCKED)
        task.block_kind = BlockKind.SCHEDULED
        task.scheduled_until = datetime.now(UTC) - timedelta(minutes=1)
        task.blocked_reason = "Waiting for build"
        await store.save_task(task)

        dispatcher = KanbanDispatcher(
            board=board, store=store, runner=_DummyRunner(),
        )

        await dispatcher._wakeup_scheduled_tasks()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.READY
        assert updated.block_kind is None
        assert updated.scheduled_until is None
        assert updated.blocked_reason is None

        events = await store.list_events("t1")
        unblocked_events = [e for e in events if e.kind == TaskEventKind.UNBLOCKED]
        assert len(unblocked_events) == 1
        assert unblocked_events[0].payload["source"] == "auto_schedule"

    @pytest.mark.asyncio
    async def test_wakeup_respects_dependencies(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)

        parent = _make_task("parent", status=TaskStatus.RUNNING)
        await store.save_task(parent)

        child = _make_task("child", status=TaskStatus.BLOCKED)
        child.block_kind = BlockKind.SCHEDULED
        child.scheduled_until = datetime.now(UTC) - timedelta(minutes=1)
        await store.save_task(child)

        await store.add_edge("parent", "child")

        dispatcher = KanbanDispatcher(
            board=board, store=store, runner=_DummyRunner(),
        )

        await dispatcher._wakeup_scheduled_tasks()

        updated = await store.get_task("child")
        assert updated is not None
        assert updated.status == TaskStatus.BACKLOG

    @pytest.mark.asyncio
    async def test_no_wakeup_for_future_tasks(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)

        task = _make_task("t1", status=TaskStatus.BLOCKED)
        task.block_kind = BlockKind.SCHEDULED
        task.scheduled_until = datetime.now(UTC) + timedelta(hours=1)
        await store.save_task(task)

        dispatcher = KanbanDispatcher(
            board=board, store=store, runner=_DummyRunner(),
        )

        await dispatcher._wakeup_scheduled_tasks()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.BLOCKED


# ---------------------------------------------------------------------------
# Auto-block sets block_kind=HUMAN
# ---------------------------------------------------------------------------


class TestAutoBlockSetsHuman:
    @pytest.mark.asyncio
    async def test_auto_block_failure_sets_human(self) -> None:
        store = InMemoryKanbanStore()
        board = KanbanBoard(
            board_id="b1",
            name="Test Board",
            settings=BoardSettings(
                max_concurrent_tasks=3,
                zombie_timeout_seconds=60,
                auto_block_after_consecutive_failures=2,
            ),
        )
        await store.save_board(board)

        task = _make_task("t1", status=TaskStatus.RUNNING)
        task.consecutive_failures = 1
        task.last_heartbeat_at = datetime.now(UTC)
        await store.save_task(task)

        run = await store.create_run("t1", "w1")

        class _FailRunner:
            async def run(self, task: KanbanTask) -> tuple[bool, str]:
                raise RuntimeError("boom")

        dispatcher = KanbanDispatcher(
            board=board, store=store, runner=_FailRunner(),
        )

        await dispatcher._apply_failure_pipeline(
            task, "boom", run.run_id,
            outcome=TaskRunOutcome.CRASHED, reason="crash",
        )

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.BLOCKED
        assert updated.block_kind == BlockKind.HUMAN


# ---------------------------------------------------------------------------
# kanban_move_task clears block fields on READY
# ---------------------------------------------------------------------------


class TestMoveTaskClearsBlockFields:
    @pytest.mark.asyncio
    async def test_move_to_ready_clears_block(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)

        task = _make_task("t1", status=TaskStatus.BLOCKED)
        task.block_kind = BlockKind.SCHEDULED
        task.scheduled_until = datetime.now(UTC) + timedelta(hours=1)
        task.blocked_reason = "scheduled wait"
        await store.save_task(task)

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        move_tool = None
        for t in tools:
            if t.name == "kanban_move_task":
                move_tool = t
                break
        assert move_tool is not None

        result = json.loads(await move_tool.ainvoke({
            "task_id": "t1",
            "status": "ready",
        }))
        assert result["status"] == "moved"
        task_data = result["task"]
        assert task_data["block_kind"] is None
        assert task_data["scheduled_until"] is None
        assert task_data["blocked_reason"] is None
