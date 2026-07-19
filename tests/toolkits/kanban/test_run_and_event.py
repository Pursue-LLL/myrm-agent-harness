"""Tests for TaskRun execution history and TaskEvent lifecycle trail.

Verifies the InMemoryKanbanStore and KanbanDispatcher correctly create,
complete, and query run/event records across success, failure, retry,
and zombie-reclaim scenarios.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.kanban.dispatcher import KanbanDispatcher
from myrm_agent_harness.toolkits.kanban.stores import InMemoryKanbanStore
from myrm_agent_harness.toolkits.kanban.types import (
    KanbanBoard,
    KanbanTask,
    TaskEventKind,
    TaskRunOutcome,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SuccessRunner:
    async def run(self, task: KanbanTask) -> tuple[bool, str]:
        return True, "done"


class FailRunner:
    async def run(self, task: KanbanTask) -> tuple[bool, str]:
        return False, "something went wrong"


class CrashRunner:
    async def run(self, task: KanbanTask) -> tuple[bool, str]:
        raise RuntimeError("unhandled crash")


async def _setup_board_and_task(
    store: InMemoryKanbanStore,
    *,
    status: TaskStatus = TaskStatus.READY,
    max_retries: int = 3,
) -> tuple[KanbanBoard, KanbanTask]:
    board = KanbanBoard(board_id="b1", name="Test Board")
    await store.save_board(board)
    task = KanbanTask(
        task_id="t1",
        board_id="b1",
        title="Test Task",
        status=status,
        max_retries=max_retries,
    )
    await store.save_task(task)
    return board, task


# ---------------------------------------------------------------------------
# InMemoryKanbanStore — Run CRUD
# ---------------------------------------------------------------------------


class TestInMemoryRunCrud:
    @pytest.mark.asyncio
    async def test_create_and_list_runs(self) -> None:
        store = InMemoryKanbanStore()
        run = await store.create_run("t1", "w1")
        assert run.task_id == "t1"
        assert run.worker_id == "w1"
        assert run.outcome is None

        runs = await store.list_runs("t1")
        assert len(runs) == 1
        assert runs[0].run_id == run.run_id

    @pytest.mark.asyncio
    async def test_complete_run(self) -> None:
        store = InMemoryKanbanStore()
        run = await store.create_run("t1", "w1")
        completed = await store.complete_run(
            run.run_id, TaskRunOutcome.COMPLETED, summary="all good",
        )
        assert completed.outcome == TaskRunOutcome.COMPLETED
        assert completed.summary == "all good"
        assert completed.ended_at is not None
        assert completed.duration_seconds is not None
        assert completed.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_complete_run_not_found(self) -> None:
        store = InMemoryKanbanStore()
        with pytest.raises(ValueError, match="not found"):
            await store.complete_run("nope", TaskRunOutcome.CRASHED)

    @pytest.mark.asyncio
    async def test_list_runs_ordered(self) -> None:
        store = InMemoryKanbanStore()
        r1 = await store.create_run("t1", "w1")
        r2 = await store.create_run("t1", "w2")
        runs = await store.list_runs("t1")
        assert runs[0].run_id == r1.run_id
        assert runs[1].run_id == r2.run_id

    @pytest.mark.asyncio
    async def test_list_runs_empty(self) -> None:
        store = InMemoryKanbanStore()
        runs = await store.list_runs("nonexistent")
        assert runs == []


# ---------------------------------------------------------------------------
# InMemoryKanbanStore — Event CRUD
# ---------------------------------------------------------------------------


class TestInMemoryEventCrud:
    @pytest.mark.asyncio
    async def test_append_and_list_events(self) -> None:
        store = InMemoryKanbanStore()
        ev = await store.append_event("t1", TaskEventKind.CREATED)
        assert ev.event_id == 1
        assert ev.task_id == "t1"
        assert ev.kind == TaskEventKind.CREATED

        events = await store.list_events("t1")
        assert len(events) == 1
        assert events[0].event_id == ev.event_id

    @pytest.mark.asyncio
    async def test_event_sequence_monotonic(self) -> None:
        store = InMemoryKanbanStore()
        e1 = await store.append_event("t1", TaskEventKind.CREATED)
        e2 = await store.append_event("t1", TaskEventKind.CLAIMED, run_id="r1")
        e3 = await store.append_event("t2", TaskEventKind.CREATED)
        assert e1.event_id < e2.event_id < e3.event_id

    @pytest.mark.asyncio
    async def test_list_events_filtered_by_task(self) -> None:
        store = InMemoryKanbanStore()
        await store.append_event("t1", TaskEventKind.CREATED)
        await store.append_event("t2", TaskEventKind.CREATED)
        events_t1 = await store.list_events("t1")
        events_t2 = await store.list_events("t2")
        assert len(events_t1) == 1
        assert len(events_t2) == 1

    @pytest.mark.asyncio
    async def test_event_with_payload_and_run_id(self) -> None:
        store = InMemoryKanbanStore()
        ev = await store.append_event(
            "t1", TaskEventKind.BLOCKED,
            payload={"reason": "rate limit"}, run_id="r42",
        )
        assert ev.payload == {"reason": "rate limit"}
        assert ev.run_id == "r42"

    @pytest.mark.asyncio
    async def test_list_events_empty(self) -> None:
        store = InMemoryKanbanStore()
        events = await store.list_events("nonexistent")
        assert events == []


# ---------------------------------------------------------------------------
# Dispatcher integration — success path
# ---------------------------------------------------------------------------


class TestDispatcherRunEventIntegration:
    @pytest.mark.asyncio
    async def test_success_creates_run_and_events(self) -> None:
        store = InMemoryKanbanStore()
        board, _ = await _setup_board_and_task(store)
        dispatcher = KanbanDispatcher(store, SuccessRunner(), board)

        await dispatcher.start()
        await asyncio.sleep(0.3)
        await dispatcher.stop()

        runs = await store.list_runs("t1")
        assert len(runs) == 1
        assert runs[0].outcome == TaskRunOutcome.COMPLETED
        assert runs[0].summary == "done"
        assert runs[0].ended_at is not None

        events = await store.list_events("t1")
        kinds = [e.kind for e in events]
        assert TaskEventKind.CLAIMED in kinds
        assert TaskEventKind.COMPLETED in kinds

    @pytest.mark.asyncio
    async def test_failure_with_retry_creates_multiple_runs(self) -> None:
        store = InMemoryKanbanStore()
        board, _ = await _setup_board_and_task(store, max_retries=3)
        dispatcher = KanbanDispatcher(store, FailRunner(), board)

        await dispatcher.start()
        await asyncio.sleep(1.0)
        await dispatcher.stop()

        runs = await store.list_runs("t1")
        assert len(runs) >= 2
        for run in runs:
            assert run.outcome is not None
            assert run.is_finished

        events = await store.list_events("t1")
        kinds = [e.kind for e in events]
        assert TaskEventKind.RETRYING in kinds

    @pytest.mark.asyncio
    async def test_crash_creates_run_with_error(self) -> None:
        store = InMemoryKanbanStore()
        board, _ = await _setup_board_and_task(store, max_retries=1)
        dispatcher = KanbanDispatcher(store, CrashRunner(), board)

        await dispatcher.start()
        await asyncio.sleep(0.5)
        await dispatcher.stop()

        runs = await store.list_runs("t1")
        assert len(runs) >= 1
        last_run = runs[-1]
        assert last_run.outcome in (TaskRunOutcome.CRASHED, TaskRunOutcome.BLOCKED)
        assert "unhandled crash" in last_run.error


# ---------------------------------------------------------------------------
# Domain type serialization
# ---------------------------------------------------------------------------


class TestDomainSerialization:
    def test_task_run_to_dict(self) -> None:
        run = _make_task_run()
        d = run.to_dict()
        assert d["run_id"] == "r1"
        assert d["outcome"] is None
        assert d["duration_seconds"] is None

    def test_task_run_to_dict_completed(self) -> None:
        run = _make_task_run()
        run.outcome = TaskRunOutcome.COMPLETED
        run.ended_at = datetime(2026, 1, 1, 0, 1, 0, tzinfo=UTC)
        d = run.to_dict()
        assert d["outcome"] == "completed"
        assert d["duration_seconds"] == 60.0

    def test_task_event_to_dict(self) -> None:
        ev = _make_task_event()
        d = ev.to_dict()
        assert d["event_id"] == 1
        assert d["kind"] == "created"
        assert d["payload"] is None

    def test_task_run_is_finished(self) -> None:
        run = _make_task_run()
        assert not run.is_finished
        run.outcome = TaskRunOutcome.CRASHED
        assert run.is_finished

    def test_task_run_outcome_values(self) -> None:
        assert TaskRunOutcome.COMPLETED.value == "completed"
        assert TaskRunOutcome.RECLAIMED.value == "reclaimed"
        assert TaskRunOutcome.BLOCKED.value == "blocked"
        assert TaskRunOutcome.CRASHED.value == "crashed"

    def test_task_event_kind_values(self) -> None:
        assert TaskEventKind.CREATED.value == "created"
        assert TaskEventKind.RECLAIMED.value == "reclaimed"
        assert TaskEventKind.USER_COMMENT.value == "user_comment"
        assert TaskEventKind.UNBLOCKED.value == "unblocked"
        assert TaskEventKind.EDITED.value == "edited"


# ---------------------------------------------------------------------------
# Agent tools — unblock event
# ---------------------------------------------------------------------------


class TestEditedEventStore:
    """EDITED event creation and retrieval via InMemoryKanbanStore."""

    @pytest.mark.asyncio
    async def test_edited_event_with_payload(self) -> None:
        store = InMemoryKanbanStore()
        ev = await store.append_event(
            "t1", TaskEventKind.EDITED,
            payload={"fields": ["result"]},
        )
        assert ev.kind == TaskEventKind.EDITED
        assert ev.payload == {"fields": ["result"]}

    @pytest.mark.asyncio
    async def test_edited_event_multiple_fields(self) -> None:
        store = InMemoryKanbanStore()
        ev = await store.append_event(
            "t1", TaskEventKind.EDITED,
            payload={"fields": ["result", "metadata"]},
        )
        assert ev.payload is not None
        assert "result" in ev.payload["fields"]
        assert "metadata" in ev.payload["fields"]

    @pytest.mark.asyncio
    async def test_edited_event_coexists_with_other_events(self) -> None:
        store = InMemoryKanbanStore()
        await store.append_event("t1", TaskEventKind.CREATED)
        await store.append_event("t1", TaskEventKind.EDITED, payload={"fields": ["result"]})
        await store.append_event("t1", TaskEventKind.COMPLETED)

        events = await store.list_events("t1")
        kinds = [e.kind for e in events]
        assert kinds == [TaskEventKind.CREATED, TaskEventKind.EDITED, TaskEventKind.COMPLETED]

    @pytest.mark.asyncio
    async def test_edited_event_to_dict(self) -> None:
        store = InMemoryKanbanStore()
        ev = await store.append_event(
            "t1", TaskEventKind.EDITED,
            payload={"fields": ["metadata"]},
        )
        d = ev.to_dict()
        assert d["kind"] == "edited"
        assert d["payload"] == {"fields": ["metadata"]}


class TestAgentToolsUnblockEvent:
    def _get_tool(self, tools, name):
        return next(t for t in tools if t.name == name)

    @pytest.mark.asyncio
    async def test_unblock_generates_unblocked_event(self) -> None:
        from myrm_agent_harness.toolkits.kanban.kanban_agent_tools import (
            create_kanban_tools,
        )

        store = InMemoryKanbanStore()
        _board, _ = await _setup_board_and_task(store, status=TaskStatus.BLOCKED)
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        unblock = self._get_tool(tools, "kanban_unblock")

        result = await unblock.ainvoke({"task_id": "t1"})
        assert '"unblocked"' in result

        events = await store.list_events("t1")
        assert len(events) == 1
        assert events[0].kind == TaskEventKind.UNBLOCKED
        assert events[0].payload["from"] == "blocked"
        assert events[0].payload["source"] == "orchestrator"
        assert events[0].payload["dependencies_met"] is True
        assert events[0].payload["outcome"] == "unblocked"

    @pytest.mark.asyncio
    async def test_add_task_generates_created_event(self) -> None:
        from myrm_agent_harness.toolkits.kanban.kanban_agent_tools import (
            create_kanban_tools,
        )

        store = InMemoryKanbanStore()
        board = KanbanBoard(board_id="b1", name="Test Board")
        await store.save_board(board)
        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        add_task = self._get_tool(tools, "kanban_add_task")

        result = await add_task.ainvoke({"title": "My Task"})
        assert '"added"' in result

        import json
        data = json.loads(result)
        task_id = data["task"]["task_id"]
        events = await store.list_events(task_id)
        assert len(events) == 1
        assert events[0].kind == TaskEventKind.CREATED

# ---------------------------------------------------------------------------
# InMemory cleanup on delete
# ---------------------------------------------------------------------------


class TestInMemoryDeleteCleanup:
    @pytest.mark.asyncio
    async def test_delete_task_cleans_runs_and_events(self) -> None:
        store = InMemoryKanbanStore()
        _board, _ = await _setup_board_and_task(store)
        await store.create_run("t1", "w1")
        await store.append_event("t1", TaskEventKind.CREATED)

        await store.delete_task("t1")

        assert await store.list_runs("t1") == []
        assert await store.list_events("t1") == []

    @pytest.mark.asyncio
    async def test_delete_board_cleans_runs_and_events(self) -> None:
        store = InMemoryKanbanStore()
        _board, _ = await _setup_board_and_task(store)
        await store.create_run("t1", "w1")
        await store.append_event("t1", TaskEventKind.CREATED)

        await store.delete_board("b1")

        assert await store.list_runs("t1") == []
        assert await store.list_events("t1") == []


# ---------------------------------------------------------------------------
# list_events since_id
# ---------------------------------------------------------------------------


class TestSinceId:
    @pytest.mark.asyncio
    async def test_list_events_since_id(self) -> None:
        store = InMemoryKanbanStore()
        e1 = await store.append_event("t1", TaskEventKind.CREATED)
        e2 = await store.append_event("t1", TaskEventKind.CLAIMED)
        e3 = await store.append_event("t1", TaskEventKind.COMPLETED)

        result = await store.list_events("t1", since_id=e1.event_id)
        assert len(result) == 2
        assert result[0].event_id == e2.event_id
        assert result[1].event_id == e3.event_id

    @pytest.mark.asyncio
    async def test_list_events_since_id_none_returns_all(self) -> None:
        store = InMemoryKanbanStore()
        await store.append_event("t1", TaskEventKind.CREATED)
        await store.append_event("t1", TaskEventKind.CLAIMED)
        result = await store.list_events("t1", since_id=None)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _board_summary uses count_tasks_grouped
# ---------------------------------------------------------------------------


class TestListTasksIncludeStats:
    @pytest.mark.asyncio
    async def test_list_tasks_include_stats_returns_counts(self) -> None:
        import json

        from myrm_agent_harness.toolkits.kanban.kanban_agent_tools import (
            create_kanban_tools,
        )

        store = InMemoryKanbanStore()
        board = KanbanBoard(board_id="b1", name="Test Board")
        await store.save_board(board)

        for i in range(3):
            task = KanbanTask(
                task_id=f"t{i}", board_id="b1", title=f"Task {i}",
                status=TaskStatus.READY,
            )
            await store.save_task(task)

        tools = create_kanban_tools(store, mode="orchestrator", default_board_id="b1")
        list_tasks = next(t for t in tools if t.name == "kanban_list_tasks")
        result = await list_tasks.ainvoke({"include_stats": True})
        data = json.loads(result)
        assert data["total_tasks"] == 3
        assert data["task_counts"]["ready"] == 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from myrm_agent_harness.toolkits.kanban.types import TaskEvent, TaskRun


def _make_task_run() -> TaskRun:
    return TaskRun(
        run_id="r1",
        task_id="t1",
        worker_id="w1",
        started_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
    )


def _make_task_event() -> TaskEvent:
    return TaskEvent(
        event_id=1,
        task_id="t1",
        kind=TaskEventKind.CREATED,
    )
