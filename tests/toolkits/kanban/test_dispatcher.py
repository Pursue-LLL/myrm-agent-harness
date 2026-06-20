"""Tests for KanbanDispatcher: scheduling, heartbeat, zombie, status-drift guard, progress notes."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.kanban.dispatcher import KanbanDispatcher
from myrm_agent_harness.toolkits.kanban.kanban_agent_tools import (
    create_kanban_tools,
)
from myrm_agent_harness.toolkits.kanban.stores import InMemoryKanbanStore
from myrm_agent_harness.toolkits.kanban.types import (
    BoardSettings,
    KanbanBoard,
    KanbanTask,
    TaskEventKind,
    TaskPriority,
    TaskRunOutcome,
    TaskStatus,
    TaskTimeoutError,
)


class _FakeRunner:
    """Minimal TaskRunner that records calls and can succeed/fail on demand."""

    def __init__(self, succeed: bool = True, delay: float = 0.0) -> None:
        self.calls: list[str] = []
        self._succeed = succeed
        self._delay = delay

    async def run(self, task: KanbanTask) -> tuple[bool, str]:
        self.calls.append(task.task_id)
        if self._delay:
            await asyncio.sleep(self._delay)
        return (self._succeed, "ok" if self._succeed else "fail")


def _make_board(
    *,
    max_concurrent: int = 3,
    heartbeat_interval: int = 1,
    zombie_timeout: int = 3,
    auto_block_failures: int = 2,
) -> KanbanBoard:
    return KanbanBoard(
        board_id="b1",
        name="Test",
        settings=BoardSettings(
            max_concurrent_tasks=max_concurrent,
            heartbeat_interval_seconds=heartbeat_interval,
            zombie_timeout_seconds=zombie_timeout,
            auto_block_after_consecutive_failures=auto_block_failures,
        ),
    )


def _make_task(
    board_id: str = "b1",
    task_id: str = "t1",
    status: TaskStatus = TaskStatus.READY,
) -> KanbanTask:
    return KanbanTask(
        task_id=task_id,
        board_id=board_id,
        title=f"Task {task_id}",
        status=status,
        priority=TaskPriority.NORMAL,
    )


# ---------------------------------------------------------------------------
# Basic lifecycle
# ---------------------------------------------------------------------------


class TestDispatcherLifecycle:

    @pytest.mark.asyncio
    async def test_start_stop(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        d = KanbanDispatcher(store, _FakeRunner(), board)
        assert not d.is_running
        await d.start()
        assert d.is_running
        await d.stop()
        assert not d.is_running

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        d = KanbanDispatcher(store, _FakeRunner(), board)
        await d.start()
        await d.start()  # second start is no-op
        assert d.is_running
        await d.stop()

    @pytest.mark.asyncio
    async def test_worker_id_default_and_custom(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        d1 = KanbanDispatcher(store, _FakeRunner(), board)
        assert d1.worker_id.startswith("worker-")

        d2 = KanbanDispatcher(store, _FakeRunner(), board, worker_id="w-custom")
        assert d2.worker_id == "w-custom"


# ---------------------------------------------------------------------------
# Dispatch & execution
# ---------------------------------------------------------------------------


class TestDispatchExecution:

    @pytest.mark.asyncio
    async def test_dispatch_claims_and_executes_ready_task(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        runner = _FakeRunner(succeed=True)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(0.3)
        await d.stop()

        assert "t1" in runner.calls
        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_dispatch_failure_retries(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board(auto_block_failures=3)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        task.max_retries = 5
        await store.save_task(task)

        runner = _FakeRunner(succeed=False)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(1.5)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.retry_count >= 1

    @pytest.mark.asyncio
    async def test_event_callback_fires(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        events: list[tuple[str, str]] = []
        runner = _FakeRunner(succeed=True)
        d = KanbanDispatcher(store, runner, board)
        d.on_event(lambda etype, t: events.append((etype, t.task_id)))
        await d.start()
        await asyncio.sleep(0.3)
        await d.stop()

        event_types = [e[0] for e in events]
        assert "task_started" in event_types
        assert "task_completed" in event_types


# ---------------------------------------------------------------------------
# Status-drift guard (TODO-56)
# ---------------------------------------------------------------------------


class TestStatusDriftGuard:

    @pytest.mark.asyncio
    async def test_aborts_when_status_drifts_after_claim(self) -> None:
        """If task status changes between claim and execute, execution aborts."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        runner = _FakeRunner(succeed=True, delay=0.1)

        original_claim = store.claim_task

        async def claim_then_block(task_id: str, worker_id: str) -> bool:
            result = await original_claim(task_id, worker_id)
            if result:
                t = await store.get_task(task_id)
                if t:
                    t.status = TaskStatus.BLOCKED
                    t.blocked_reason = "User blocked during claim"
                    await store.save_task(t)
            return result

        store.claim_task = claim_then_block  # type: ignore[assignment]

        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(0.5)
        await d.stop()

        assert len(runner.calls) == 0

    @pytest.mark.asyncio
    async def test_executes_normally_when_status_is_running(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        runner = _FakeRunner(succeed=True)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(0.3)
        await d.stop()

        assert "t1" in runner.calls


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


class TestHeartbeat:

    @pytest.mark.asyncio
    async def test_heartbeat_updates_timestamp(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board(heartbeat_interval=1)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        runner = _FakeRunner(succeed=True, delay=2.5)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(1.5)

        t = await store.get_task("t1")
        assert t is not None
        assert t.last_heartbeat_at is not None

        await d.stop()


# ---------------------------------------------------------------------------
# Zombie detection
# ---------------------------------------------------------------------------


class TestZombieDetection:

    @pytest.mark.asyncio
    async def test_zombie_task_is_reclaimed(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board(zombie_timeout=2, auto_block_failures=10)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.RUNNING)
        task.last_heartbeat_at = datetime.now(UTC) - timedelta(seconds=10)
        task.max_retries = 5
        await store.save_task(task)

        runner = _FakeRunner(succeed=True)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(2.5)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.retry_count >= 1

    @pytest.mark.asyncio
    async def test_heartbeat_loop_survives_store_error(self) -> None:
        """Bug 1 fix: _heartbeat_loop must survive transient store errors."""

        class _FlakeyStore(InMemoryKanbanStore):
            _hb_call_count: int = 0

            async def update_heartbeat(
                self,
                task_id: str,
                note: str | None = None,
            ) -> None:
                self._hb_call_count += 1
                if self._hb_call_count == 2:
                    raise ConnectionError("DB gone")
                await super().update_heartbeat(task_id, note)

        store = _FlakeyStore()
        board = _make_board(heartbeat_interval=1, zombie_timeout=30)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        runner = _FakeRunner(succeed=True, delay=4.0)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(4.5)
        await d.stop()

        assert store._hb_call_count >= 3, (
            "Heartbeat loop should have continued past the error"
        )
        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_reclaim_cancels_active_worker(self) -> None:
        """Bug 2 fix: _reclaim_task must cancel the active asyncio.Task."""
        store = InMemoryKanbanStore()
        board = _make_board(zombie_timeout=60, auto_block_failures=10)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        task.max_retries = 5
        await store.save_task(task)

        runner = _FakeRunner(succeed=True, delay=10.0)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(0.5)

        exec_task = d._task_id_to_exec.get("t1")
        assert exec_task is not None, "Worker should be registered"
        assert not exec_task.done(), "Worker should still be running"

        fresh = await store.get_task("t1")
        assert fresh is not None
        await d._reclaim_task(fresh)

        assert exec_task.done(), (
            "Worker asyncio.Task should have been cancelled by _reclaim_task"
        )
        await d.stop()


# ---------------------------------------------------------------------------
# Dependency promotion
# ---------------------------------------------------------------------------


class TestDependencyPromotion:

    @pytest.mark.asyncio
    async def test_child_promoted_when_parent_completes(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)

        parent = _make_task(task_id="parent", status=TaskStatus.READY)
        await store.save_task(parent)

        child = _make_task(task_id="child", status=TaskStatus.BACKLOG)
        await store.save_task(child)
        await store.add_edge("parent", "child")

        runner = _FakeRunner(succeed=True)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(1.0)
        await d.stop()

        updated_child = await store.get_task("child")
        assert updated_child is not None
        assert updated_child.status in (TaskStatus.READY, TaskStatus.COMPLETED)


# ---------------------------------------------------------------------------
# Stop with pending tasks
# ---------------------------------------------------------------------------


class TestGracefulStop:

    @pytest.mark.asyncio
    async def test_stop_waits_for_executing_tasks(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        runner = _FakeRunner(succeed=True, delay=0.5)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(0.2)
        await d.stop(graceful_timeout=5.0)

        assert "t1" in runner.calls

    @pytest.mark.asyncio
    async def test_wake_triggers_immediate_dispatch(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board(heartbeat_interval=10)
        await store.save_board(board)

        runner = _FakeRunner(succeed=True)
        d = KanbanDispatcher(store, runner, board)
        await d.start()

        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)
        d.wake()
        await asyncio.sleep(0.5)
        await d.stop()

        assert "t1" in runner.calls


# ---------------------------------------------------------------------------
# Exception handling in runner
# ---------------------------------------------------------------------------


class TestRunnerException:

    @pytest.mark.asyncio
    async def test_runner_exception_handled_as_failure(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board(auto_block_failures=10)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        task.max_retries = 5
        await store.save_task(task)

        class _CrashRunner:
            async def run(self, task: KanbanTask) -> tuple[bool, str]:
                raise RuntimeError("boom")

        d = KanbanDispatcher(store, _CrashRunner(), board)
        await d.start()
        await asyncio.sleep(0.5)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.retry_count >= 1
        assert "boom" in updated.error


# ---------------------------------------------------------------------------
# Heartbeat progress note
# ---------------------------------------------------------------------------


class TestHeartbeatProgressNote:

    @pytest.mark.asyncio
    async def test_update_heartbeat_stores_note(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.RUNNING)
        task.last_heartbeat_at = datetime.now(UTC)
        await store.save_task(task)

        await store.update_heartbeat("t1", note="Searching web...")
        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.progress_note == "Searching web..."

    @pytest.mark.asyncio
    async def test_update_heartbeat_without_note_preserves_existing(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.RUNNING)
        task.progress_note = "Step 1/3"
        task.last_heartbeat_at = datetime.now(UTC)
        await store.save_task(task)

        await store.update_heartbeat("t1")
        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.progress_note == "Step 1/3"

    @pytest.mark.asyncio
    async def test_progress_note_cleared_on_success(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        store._tasks["t1"].progress_note = "In progress..."

        runner = _FakeRunner(succeed=True)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(0.5)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED
        assert updated.progress_note is None

    @pytest.mark.asyncio
    async def test_progress_note_cleared_on_failure(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board(auto_block_failures=10)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        task.max_retries = 0
        await store.save_task(task)

        store._tasks["t1"].progress_note = "In progress..."

        runner = _FakeRunner(succeed=False)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(0.5)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.FAILED
        assert updated.progress_note is None

    @pytest.mark.asyncio
    async def test_progress_note_cleared_on_zombie_reclaim(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board(zombie_timeout=1, auto_block_failures=10)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.RUNNING)
        task.progress_note = "Step 2/4 — compiling..."
        task.last_heartbeat_at = datetime.now(UTC) - timedelta(seconds=10)
        task.max_retries = 5
        await store.save_task(task)

        runner = _FakeRunner(succeed=True)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(2.0)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.progress_note is None

    @pytest.mark.asyncio
    async def test_progress_note_in_to_dict(self) -> None:
        task = _make_task(status=TaskStatus.RUNNING)
        task.progress_note = "Analyzing data..."
        d = task.to_dict()
        assert d["progress_note"] == "Analyzing data..."

    @pytest.mark.asyncio
    async def test_progress_note_absent_from_to_dict_when_none(self) -> None:
        task = _make_task(status=TaskStatus.RUNNING)
        task.progress_note = None
        d = task.to_dict()
        assert "progress_note" not in d


# ---------------------------------------------------------------------------
# Heartbeat tool handler (_heartbeat)
# ---------------------------------------------------------------------------


class TestHeartbeatToolHandler:

    def _get_heartbeat_tool(self, store, task_id="t1"):
        tools = create_kanban_tools(store, mode="worker", current_task_id=task_id)
        return next(t for t in tools if t.name == "kanban_heartbeat")

    @pytest.mark.asyncio
    async def test_heartbeat_with_note_updates_task_and_appends_event(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.RUNNING)
        task.last_heartbeat_at = datetime.now(UTC)
        await store.save_task(task)

        heartbeat = self._get_heartbeat_tool(store)
        result = json.loads(await heartbeat.ainvoke({"note": "Parsing file..."}))
        assert result["status"] == "heartbeat_ok"
        assert result["task_id"] == "t1"

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.progress_note == "Parsing file..."

        events = await store.list_events("t1")
        heartbeat_events = [e for e in events if e.kind == TaskEventKind.HEARTBEAT]
        assert len(heartbeat_events) == 1
        assert heartbeat_events[0].payload == {"note": "Parsing file..."}

    @pytest.mark.asyncio
    async def test_heartbeat_without_note_returns_error(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.RUNNING)
        task.last_heartbeat_at = datetime.now(UTC)
        await store.save_task(task)

        heartbeat = self._get_heartbeat_tool(store)
        result = json.loads(await heartbeat.ainvoke({"note": ""}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_heartbeat_missing_task_id(self) -> None:
        store = InMemoryKanbanStore()
        tools = create_kanban_tools(store, mode="worker", current_task_id=None)
        heartbeat = next(t for t in tools if t.name == "kanban_heartbeat")
        result = json.loads(await heartbeat.ainvoke({"note": "some note", "task_id": ""}))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_heartbeat_nonexistent_task(self) -> None:
        store = InMemoryKanbanStore()
        heartbeat = self._get_heartbeat_tool(store, "nonexistent")
        result = json.loads(await heartbeat.ainvoke({"note": "note"}))
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_heartbeat_non_running_task(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        heartbeat = self._get_heartbeat_tool(store)
        result = json.loads(await heartbeat.ainvoke({"note": "note"}))
        assert "error" in result
        assert "not running" in result["error"]


class TestHeartbeatSSEEmitPath:
    """Test kanban_heartbeat tool with dispatcher.emit for SSE."""

    @pytest.mark.asyncio
    async def test_heartbeat_via_tool_emits_sse(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.RUNNING)
        task.last_heartbeat_at = datetime.now(UTC)
        await store.save_task(task)

        emitted: list[tuple[str, object]] = []
        dispatcher = KanbanDispatcher(store, _FakeRunner(), board.settings)
        dispatcher.on_event(lambda action, t: emitted.append((action, t)))

        tools = create_kanban_tools(
            store, dispatcher, mode="worker", current_task_id="t1",
        )
        heartbeat = next(t for t in tools if t.name == "kanban_heartbeat")

        result_str = await heartbeat.ainvoke({"note": "Analyzing data..."})
        result = json.loads(result_str)
        assert result["status"] == "heartbeat_ok"

        assert len(emitted) == 1
        assert emitted[0][0] == "heartbeat_progress"
        assert emitted[0][1].task_id == "t1"

    @pytest.mark.asyncio
    async def test_heartbeat_via_tool_no_emit_without_note(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.RUNNING)
        task.last_heartbeat_at = datetime.now(UTC)
        await store.save_task(task)

        emitted: list[tuple[str, object]] = []
        dispatcher = KanbanDispatcher(store, _FakeRunner(), board.settings)
        dispatcher.on_event(lambda action, t: emitted.append((action, t)))

        tools = create_kanban_tools(
            store, dispatcher, mode="worker", current_task_id="t1",
        )
        heartbeat = next(t for t in tools if t.name == "kanban_heartbeat")

        result_str = await heartbeat.ainvoke({"note": ""})
        result = json.loads(result_str)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_heartbeat_via_tool_no_dispatcher(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.RUNNING)
        task.last_heartbeat_at = datetime.now(UTC)
        await store.save_task(task)

        tools = create_kanban_tools(
            store, None, mode="worker", current_task_id="t1",
        )
        heartbeat = next(t for t in tools if t.name == "kanban_heartbeat")

        result_str = await heartbeat.ainvoke({"note": "Progress note"})
        result = json.loads(result_str)
        assert result["status"] == "heartbeat_ok"

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.progress_note == "Progress note"


# ---------------------------------------------------------------------------
# TaskTimeoutError handling
# ---------------------------------------------------------------------------


class TestTaskTimeout:

    def test_timeout_error_attributes(self) -> None:
        err = TaskTimeoutError(task_id="t1", elapsed_seconds=65.2, limit_seconds=60)
        assert err.task_id == "t1"
        assert err.elapsed_seconds == 65.2
        assert err.limit_seconds == 60
        assert "t1" in str(err)

    @pytest.mark.asyncio
    async def test_timeout_creates_timed_out_event_and_outcome(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board(auto_block_failures=10)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        task.max_retries = 5
        await store.save_task(task)

        class _TimeoutRunner:
            async def run(self, task: KanbanTask) -> tuple[bool, str]:
                raise TaskTimeoutError(
                    task_id=task.task_id,
                    elapsed_seconds=62.0,
                    limit_seconds=60,
                )

        d = KanbanDispatcher(store, _TimeoutRunner(), board)
        await d.start()
        await asyncio.sleep(1.0)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.retry_count >= 1

        events = await store.list_events("t1")
        timed_out_events = [e for e in events if e.kind == TaskEventKind.TIMED_OUT]
        assert len(timed_out_events) >= 1
        payload = timed_out_events[0].payload
        assert payload is not None
        assert payload["elapsed_seconds"] == 62.0
        assert payload["limit_seconds"] == 60

        runs = await store.list_runs("t1")
        timed_out_runs = [r for r in runs if r.outcome == TaskRunOutcome.TIMED_OUT]
        assert len(timed_out_runs) >= 1

    @pytest.mark.asyncio
    async def test_timeout_auto_blocks_after_consecutive_failures(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board(auto_block_failures=2)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        task.max_retries = 10
        await store.save_task(task)

        class _TimeoutRunner:
            async def run(self, task: KanbanTask) -> tuple[bool, str]:
                raise TaskTimeoutError(
                    task_id=task.task_id,
                    elapsed_seconds=65.0,
                    limit_seconds=60,
                )

        d = KanbanDispatcher(store, _TimeoutRunner(), board)
        await d.start()
        await asyncio.sleep(1.0)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.BLOCKED
        assert "timed_out" in (updated.blocked_reason or "").lower()

    @pytest.mark.asyncio
    async def test_timeout_exhausts_retries_then_fails(self) -> None:
        store = InMemoryKanbanStore()
        board = _make_board(auto_block_failures=100)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        task.max_retries = 1
        await store.save_task(task)

        class _TimeoutRunner:
            async def run(self, task: KanbanTask) -> tuple[bool, str]:
                raise TaskTimeoutError(
                    task_id=task.task_id,
                    elapsed_seconds=70.0,
                    limit_seconds=60,
                )

        d = KanbanDispatcher(store, _TimeoutRunner(), board)
        await d.start()
        await asyncio.sleep(1.0)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.FAILED

    def test_max_runtime_seconds_in_to_dict(self) -> None:
        task = _make_task()
        task.max_runtime_seconds = 300
        d = task.to_dict()
        assert d["max_runtime_seconds"] == 300

    def test_max_runtime_seconds_none_in_to_dict(self) -> None:
        task = _make_task()
        d = task.to_dict()
        assert d["max_runtime_seconds"] is None


class TestManualReclaim:
    """Tests for KanbanDispatcher.reclaim_task() — operator-driven task abort."""

    @pytest.mark.asyncio
    async def test_reclaim_running_task_cancels_and_resets(self) -> None:
        """reclaim_task cancels the asyncio worker and resets task to READY."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task()
        await store.save_task(task)

        runner = _FakeRunner(succeed=True, delay=10.0)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(0.3)

        final_before = await store.get_task("t1")
        assert final_before is not None
        assert final_before.status == TaskStatus.RUNNING

        result = await d.reclaim_task("t1", reason="user wants to reassign")
        assert result is True

        final = await store.get_task("t1")
        assert final is not None
        assert final.status == TaskStatus.READY
        assert final.consecutive_failures == 0
        assert final.error == ""
        assert final.last_heartbeat_at is None

        runs = await store.list_runs("t1")
        assert len(runs) >= 1
        last_run = runs[-1]
        assert last_run.outcome == TaskRunOutcome.RECLAIMED

        events = await store.list_events("t1")
        reclaim_events = [e for e in events if e.kind == TaskEventKind.RECLAIMED]
        assert len(reclaim_events) >= 1
        last_reclaim = reclaim_events[-1]
        assert last_reclaim.payload.get("manual") is True
        assert last_reclaim.payload.get("reason") == "user wants to reassign"

        await d.stop()

    @pytest.mark.asyncio
    async def test_reclaim_nonexistent_task_returns_false(self) -> None:
        """reclaim_task returns False if task is not being executed."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)

        d = KanbanDispatcher(store, _FakeRunner(), board)
        await d.start()
        result = await d.reclaim_task("nonexistent", reason="test")
        assert result is False
        await d.stop()

    @pytest.mark.asyncio
    async def test_reclaim_already_completed_returns_false(self) -> None:
        """reclaim_task returns False if task has already finished."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task()
        await store.save_task(task)

        runner = _FakeRunner(succeed=True, delay=0.0)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(0.5)

        final = await store.get_task("t1")
        assert final is not None
        assert final.status == TaskStatus.COMPLETED

        result = await d.reclaim_task("t1", reason="too late")
        assert result is False
        await d.stop()

    @pytest.mark.asyncio
    async def test_reclaim_clears_task_id_to_exec_mapping(self) -> None:
        """After reclaim, _task_id_to_exec no longer holds the entry."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task()
        await store.save_task(task)

        runner = _FakeRunner(succeed=True, delay=10.0)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(0.3)
        assert "t1" in d._task_id_to_exec

        await d.reclaim_task("t1")
        assert "t1" not in d._task_id_to_exec
        await d.stop()

    @pytest.mark.asyncio
    async def test_reclaim_emits_event_callback(self) -> None:
        """reclaim_task fires the 'task_reclaimed' event via emit()."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task()
        await store.save_task(task)

        runner = _FakeRunner(succeed=True, delay=10.0)
        d = KanbanDispatcher(store, runner, board)
        emitted: list[tuple[str, str]] = []
        d.on_event(lambda et, t: emitted.append((et, t.task_id)))
        await d.start()
        await asyncio.sleep(0.3)
        await d.reclaim_task("t1", reason="reassign")
        await d.stop()

        event_types = [e[0] for e in emitted]
        assert "task_reclaimed" in event_types


class TestPostExecutionStatusGuard:
    """Test that dispatcher discards results when task status changed during execution."""

    @pytest.mark.asyncio
    async def test_success_discarded_when_task_reclaimed(self) -> None:
        """If user moves task to READY during execution, success result is discarded."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task()
        task.status = TaskStatus.BACKLOG
        await store.save_task(task)

        reclaim_event = asyncio.Event()
        run_count = 0

        class _SlowRunner:
            async def run(self, t: KanbanTask) -> tuple[bool, str]:
                nonlocal run_count
                run_count += 1
                reclaim_event.set()
                await asyncio.sleep(0.5)
                return (True, "late result")

        d = KanbanDispatcher(store, _SlowRunner(), board)
        await d.start()

        stored = await store.get_task("t1")
        assert stored is not None
        stored.status = TaskStatus.READY
        await store.save_task(stored)
        d.wake()

        await reclaim_event.wait()
        reclaimed_task = await store.get_task("t1")
        assert reclaimed_task is not None
        reclaimed_task.status = TaskStatus.BACKLOG
        reclaimed_task.last_heartbeat_at = None
        await store.save_task(reclaimed_task)

        await asyncio.sleep(1.0)
        await d.stop()

        final = await store.get_task("t1")
        assert final is not None
        assert final.status == TaskStatus.BACKLOG
        assert run_count == 1

        runs = await store.list_runs("t1")
        assert len(runs) == 1
        assert runs[0].outcome == TaskRunOutcome.RECLAIMED

    @pytest.mark.asyncio
    async def test_failure_discarded_when_task_reclaimed(self) -> None:
        """If user moves task to READY during execution, failure is discarded."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task()
        task.status = TaskStatus.BACKLOG
        await store.save_task(task)

        reclaim_event = asyncio.Event()

        class _SlowFailRunner:
            async def run(self, t: KanbanTask) -> tuple[bool, str]:
                reclaim_event.set()
                await asyncio.sleep(0.5)
                return (False, "error occurred")

        d = KanbanDispatcher(store, _SlowFailRunner(), board)
        await d.start()

        stored = await store.get_task("t1")
        assert stored is not None
        stored.status = TaskStatus.READY
        await store.save_task(stored)
        d.wake()

        await reclaim_event.wait()
        reclaimed_task = await store.get_task("t1")
        assert reclaimed_task is not None
        reclaimed_task.status = TaskStatus.BACKLOG
        await store.save_task(reclaimed_task)

        await asyncio.sleep(1.0)
        await d.stop()

        final = await store.get_task("t1")
        assert final is not None
        assert final.status == TaskStatus.BACKLOG
        assert final.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_timeout_discarded_when_task_reclaimed(self) -> None:
        """If user moves task during timeout handling, timeout is discarded."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task()
        await store.save_task(task)

        class _TimeoutAfterReclaim:
            async def run(self, t: KanbanTask) -> tuple[bool, str]:
                stored = await store.get_task(t.task_id)
                if stored:
                    stored.status = TaskStatus.READY
                    await store.save_task(stored)
                raise TaskTimeoutError(
                    task_id=t.task_id, elapsed_seconds=70.0, limit_seconds=60,
                )

        d = KanbanDispatcher(store, _TimeoutAfterReclaim(), board)
        await d.start()
        await asyncio.sleep(1.0)
        await d.stop()

        final = await store.get_task("t1")
        assert final is not None
        assert final.status == TaskStatus.READY


# ---------------------------------------------------------------------------
# Manual reclaim_task method
# ---------------------------------------------------------------------------


class TestManualReclaimTask:

    @pytest.mark.asyncio
    async def test_reclaim_running_task_cancels_and_resets(self) -> None:
        """reclaim_task() cancels the executing worker and resets task to READY."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task()
        await store.save_task(task)

        started = asyncio.Event()

        class _BlockingRunner:
            async def run(self, t: KanbanTask) -> tuple[bool, str]:
                started.set()
                await asyncio.sleep(60)
                return (True, "done")

        d = KanbanDispatcher(store, _BlockingRunner(), board)
        await d.start()
        await started.wait()

        result = await d.reclaim_task("t1", reason="test reclaim")
        assert result is True

        final = await store.get_task("t1")
        assert final is not None
        assert final.status == TaskStatus.READY
        assert final.consecutive_failures == 0
        assert final.last_heartbeat_at is None
        assert final.progress_note is None

        events = await store.list_events("t1")
        reclaimed_events = [e for e in events if e.kind == TaskEventKind.RECLAIMED]
        assert len(reclaimed_events) >= 1
        assert reclaimed_events[-1].payload["manual"] is True

        runs = await store.list_runs("t1")
        assert len(runs) >= 1
        assert runs[-1].outcome == TaskRunOutcome.RECLAIMED

        await d.stop()

    @pytest.mark.asyncio
    async def test_reclaim_non_executing_task_returns_false(self) -> None:
        """reclaim_task() returns False if the task is not being executed."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.RUNNING)
        await store.save_task(task)

        d = KanbanDispatcher(store, _FakeRunner(), board)
        result = await d.reclaim_task("t1")
        assert result is False

    @pytest.mark.asyncio
    async def test_reclaim_emits_event_callback(self) -> None:
        """reclaim_task() emits 'task_reclaimed' event."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task()
        await store.save_task(task)

        started = asyncio.Event()
        emitted: list[tuple[str, str]] = []

        class _BlockingRunner:
            async def run(self, t: KanbanTask) -> tuple[bool, str]:
                started.set()
                await asyncio.sleep(60)
                return (True, "done")

        d = KanbanDispatcher(store, _BlockingRunner(), board)
        d.on_event(lambda event_type, t: emitted.append((event_type, t.task_id)))
        await d.start()
        await started.wait()

        await d.reclaim_task("t1")
        assert any(et == "task_reclaimed" and tid == "t1" for et, tid in emitted)
        await d.stop()


# ---------------------------------------------------------------------------
# Verifier integration
# ---------------------------------------------------------------------------


class TestVerifierIntegration:

    @pytest.mark.asyncio
    async def test_verification_failure_triggers_failure_path(self) -> None:
        """When verifier rejects result, task should fail."""
        from myrm_agent_harness.toolkits.kanban.types import VerificationResult

        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task()
        task.max_retries = 0
        await store.save_task(task)

        class _RejectVerifier:
            async def verify(
                self, task: KanbanTask, result: str
            ) -> VerificationResult:
                return VerificationResult(passed=False, reason="Bad output")

        d = KanbanDispatcher(
            store, _FakeRunner(succeed=True), board, verifier=_RejectVerifier()
        )
        await d.start()
        await asyncio.sleep(1.0)
        await d.stop()

        final = await store.get_task("t1")
        assert final is not None
        assert final.status == TaskStatus.FAILED

        events = await store.list_events("t1")
        vf_events = [
            e for e in events if e.kind == TaskEventKind.VERIFICATION_FAILED
        ]
        assert len(vf_events) >= 1

    @pytest.mark.asyncio
    async def test_verification_exception_triggers_failure(self) -> None:
        """When verifier raises an exception, task should fail."""
        from myrm_agent_harness.toolkits.kanban.types import VerificationResult

        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task()
        task.max_retries = 0
        await store.save_task(task)

        class _ErrorVerifier:
            async def verify(
                self, task: KanbanTask, result: str
            ) -> VerificationResult:
                raise RuntimeError("Verification service unavailable")

        d = KanbanDispatcher(
            store, _FakeRunner(succeed=True), board, verifier=_ErrorVerifier()
        )
        await d.start()
        await asyncio.sleep(1.0)
        await d.stop()

        final = await store.get_task("t1")
        assert final is not None
        assert final.status == TaskStatus.FAILED

        events = await store.list_events("t1")
        vf_events = [
            e for e in events if e.kind == TaskEventKind.VERIFICATION_FAILED
        ]
        assert len(vf_events) >= 1


# ---------------------------------------------------------------------------
# Agent self-completion via kanban_complete tool
# ---------------------------------------------------------------------------


class TestAgentSelfComplete:
    """Verify dispatcher correctly handles tasks completed by kanban_complete tool."""

    @pytest.mark.asyncio
    async def test_agent_complete_promotes_dependents(self) -> None:
        """When agent calls kanban_complete, dispatcher still promotes child tasks."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)

        parent = _make_task(task_id="parent1", status=TaskStatus.READY)
        await store.save_task(parent)

        child = _make_task(task_id="child1", status=TaskStatus.BACKLOG)
        await store.save_task(child)
        await store.add_edge("parent1", "child1")

        class _SelfCompleteRunner:
            async def run(self, task: KanbanTask) -> tuple[bool, str]:
                t = await store.get_task(task.task_id)
                assert t is not None
                t.status = TaskStatus.COMPLETED
                t.result = "Done via tool"
                t.completed_at = datetime.now(UTC)
                await store.save_task(t)
                return (True, "Done via tool")

        d = KanbanDispatcher(store, _SelfCompleteRunner(), board)
        await d.start()
        await asyncio.sleep(1.0)
        await d.stop()

        final_parent = await store.get_task("parent1")
        assert final_parent is not None
        assert final_parent.status == TaskStatus.COMPLETED

        final_child = await store.get_task("child1")
        assert final_child is not None
        assert final_child.status in (
            TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.COMPLETED,
        )

        runs = await store.list_runs("parent1")
        assert len(runs) == 1
        assert runs[0].outcome == TaskRunOutcome.COMPLETED

    @pytest.mark.asyncio
    async def test_agent_complete_run_marked_completed_not_reclaimed(self) -> None:
        """Run outcome is COMPLETED (not RECLAIMED) when agent uses kanban_complete."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        class _SelfCompleteRunner:
            async def run(self, t: KanbanTask) -> tuple[bool, str]:
                stored = await store.get_task(t.task_id)
                assert stored is not None
                stored.status = TaskStatus.COMPLETED
                stored.result = "self-completed"
                stored.completed_at = datetime.now(UTC)
                await store.save_task(stored)
                return (True, "self-completed")

        d = KanbanDispatcher(store, _SelfCompleteRunner(), board)
        await d.start()
        await asyncio.sleep(0.5)
        await d.stop()

        runs = await store.list_runs("t1")
        assert len(runs) == 1
        assert runs[0].outcome == TaskRunOutcome.COMPLETED
        assert runs[0].summary == "self-completed"


# ---------------------------------------------------------------------------
# Transient error smart backoff
# ---------------------------------------------------------------------------


from myrm_agent_harness.toolkits.kanban.dispatcher import (
    _TRANSIENT_BACKOFF_SECONDS,
    _TRANSIENT_ERROR_RE,
)
from myrm_agent_harness.toolkits.kanban.types import BlockKind


class TestTransientErrorSmartBackoff:
    """Transient errors (429/503/quota) trigger SCHEDULED block instead of
    immediate retry, giving the upstream service time to recover."""

    @pytest.mark.asyncio
    async def test_transient_429_triggers_scheduled_block(self) -> None:
        """A 429 rate-limit error should SCHEDULED-block the task."""
        store = InMemoryKanbanStore()
        board = _make_board(auto_block_failures=5)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        task.max_retries = 3
        await store.save_task(task)

        class _RateLimitRunner:
            async def run(self, t: KanbanTask) -> tuple[bool, str]:
                return (False, "429 Too Many Requests: Rate limit exceeded")

        d = KanbanDispatcher(store, _RateLimitRunner(), board)
        await d.start()
        await asyncio.sleep(0.5)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.BLOCKED
        assert updated.block_kind == BlockKind.SCHEDULED
        assert updated.scheduled_until is not None
        assert "Transient error" in (updated.blocked_reason or "")

    @pytest.mark.asyncio
    async def test_transient_503_triggers_scheduled_block(self) -> None:
        """A 503 Service Unavailable error should SCHEDULED-block the task."""
        store = InMemoryKanbanStore()
        board = _make_board(auto_block_failures=5)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        task.max_retries = 3
        await store.save_task(task)

        class _ServiceUnavailableRunner:
            async def run(self, t: KanbanTask) -> tuple[bool, str]:
                return (False, "503 Service Unavailable: server maintenance")

        d = KanbanDispatcher(store, _ServiceUnavailableRunner(), board)
        await d.start()
        await asyncio.sleep(0.5)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.BLOCKED
        assert updated.block_kind == BlockKind.SCHEDULED

    @pytest.mark.asyncio
    async def test_transient_quota_triggers_scheduled_block(self) -> None:
        """A quota-exceeded error should SCHEDULED-block the task."""
        store = InMemoryKanbanStore()
        board = _make_board(auto_block_failures=5)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        task.max_retries = 3
        await store.save_task(task)

        class _QuotaRunner:
            async def run(self, t: KanbanTask) -> tuple[bool, str]:
                return (False, "API quota exceeded for organization")

        d = KanbanDispatcher(store, _QuotaRunner(), board)
        await d.start()
        await asyncio.sleep(0.5)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.BLOCKED
        assert updated.block_kind == BlockKind.SCHEDULED

    @pytest.mark.asyncio
    async def test_non_transient_error_immediate_retry(self) -> None:
        """A non-transient error should use immediate retry (READY)."""
        store = InMemoryKanbanStore()
        board = _make_board(auto_block_failures=5)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        task.max_retries = 5
        await store.save_task(task)

        call_count = 0

        class _NormalFailRunner:
            async def run(self, t: KanbanTask) -> tuple[bool, str]:
                nonlocal call_count
                call_count += 1
                return (False, "TypeError: unexpected None value")

        d = KanbanDispatcher(store, _NormalFailRunner(), board)
        await d.start()
        await asyncio.sleep(1.0)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert call_count >= 2, "Non-transient should retry immediately"

    @pytest.mark.asyncio
    async def test_transient_backoff_event_recorded(self) -> None:
        """Transient backoff should record a BLOCKED event with transient metadata."""
        store = InMemoryKanbanStore()
        board = _make_board(auto_block_failures=5)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        task.max_retries = 3
        await store.save_task(task)

        class _RateLimitRunner:
            async def run(self, t: KanbanTask) -> tuple[bool, str]:
                return (False, "429 Too Many Requests")

        d = KanbanDispatcher(store, _RateLimitRunner(), board)
        await d.start()
        await asyncio.sleep(0.5)
        await d.stop()

        events = await store.list_events("t1")
        blocked_events = [e for e in events if e.kind == TaskEventKind.BLOCKED]
        assert len(blocked_events) >= 1
        payload = blocked_events[0].payload
        assert payload.get("transient_error") is True
        assert payload.get("block_kind") == "scheduled"
        assert "wake_at" in payload

    @pytest.mark.asyncio
    async def test_auto_block_takes_priority_when_threshold_already_reached(
        self,
    ) -> None:
        """When consecutive_failures already >= threshold before the transient
        error occurs, auto-block (HUMAN) takes priority."""
        store = InMemoryKanbanStore()
        board = _make_board(auto_block_failures=2)
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        task.max_retries = 10
        task.consecutive_failures = 1
        await store.save_task(task)

        class _RateLimitRunner:
            async def run(self, t: KanbanTask) -> tuple[bool, str]:
                return (False, "429 Rate limit exceeded")

        d = KanbanDispatcher(store, _RateLimitRunner(), board)
        await d.start()
        await asyncio.sleep(0.5)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.BLOCKED
        assert updated.block_kind == BlockKind.HUMAN
        assert updated.consecutive_failures >= 2

    def test_transient_error_regex_patterns(self) -> None:
        """Verify _TRANSIENT_ERROR_RE matches expected error patterns."""
        should_match = [
            "429 Too Many Requests: Rate limit exceeded",
            "rate limit hit for org-xxx",
            "API quota exceeded",
            "too many requests",
            "503 Service Unavailable",
            "service unavailable: try again later",
            "Server overloaded, please retry",
            "Insufficient capacity, try again",
            "rate_limit_exceeded",
            "rate-limit error",
        ]
        should_not_match = [
            "TypeError: unexpected None value",
            "SyntaxError: invalid syntax",
            "ConnectionError: DNS lookup failed",
            "FileNotFoundError: /tmp/foo",
            "IndexError: list index out of range",
            "Authentication failed: invalid API key",
        ]
        for msg in should_match:
            assert _TRANSIENT_ERROR_RE.search(msg), f"Should match: {msg!r}"
        for msg in should_not_match:
            assert not _TRANSIENT_ERROR_RE.search(msg), f"Should NOT match: {msg!r}"

    def test_transient_backoff_seconds_value(self) -> None:
        """Verify backoff duration is 15 minutes (900 seconds)."""
        assert _TRANSIENT_BACKOFF_SECONDS == 900


# ---------------------------------------------------------------------------
# cancel_execution integration
# ---------------------------------------------------------------------------


class _SlowRunner:
    """Runner that sleeps for a long duration, allowing cancellation testing."""

    def __init__(self, started: asyncio.Event) -> None:
        self.calls: list[str] = []
        self._started = started
        self.was_cancelled = False

    async def run(self, task: KanbanTask) -> tuple[bool, str]:
        self.calls.append(task.task_id)
        self._started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.was_cancelled = True
            raise
        return (True, "done")


class TestCancelExecution:
    """Integration tests for KanbanDispatcher.cancel_execution."""

    @pytest.mark.asyncio
    async def test_cancel_execution_stops_running_task(self) -> None:
        """cancel_execution terminates the asyncio.Task of a running task."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        started = asyncio.Event()
        runner = _SlowRunner(started)
        d = KanbanDispatcher(store, runner, board)
        await d.start()

        await asyncio.wait_for(started.wait(), timeout=3.0)
        assert "t1" in runner.calls

        result = await d.cancel_execution("t1")
        assert result is True
        assert runner.was_cancelled is True

        await d.stop()

    @pytest.mark.asyncio
    async def test_cancel_execution_nonexistent_task(self) -> None:
        """cancel_execution returns False for a task not being executed."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)

        d = KanbanDispatcher(store, _FakeRunner(), board)
        await d.start()

        result = await d.cancel_execution("nonexistent-task")
        assert result is False

        await d.stop()

    @pytest.mark.asyncio
    async def test_cancel_execution_already_completed(self) -> None:
        """cancel_execution returns False for a task that already finished."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        runner = _FakeRunner(succeed=True, delay=0.0)
        d = KanbanDispatcher(store, runner, board)
        await d.start()
        await asyncio.sleep(0.3)

        result = await d.cancel_execution("t1")
        assert result is False

        await d.stop()

    @pytest.mark.asyncio
    async def test_cancel_execution_does_not_change_task_status(self) -> None:
        """cancel_execution only stops execution without modifying persisted task state."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        started = asyncio.Event()
        runner = _SlowRunner(started)
        d = KanbanDispatcher(store, runner, board)
        await d.start()

        await asyncio.wait_for(started.wait(), timeout=3.0)

        persisted_before = await store.get_task("t1")
        assert persisted_before is not None
        status_before = persisted_before.status

        await d.cancel_execution("t1")

        # Task state should remain as it was (RUNNING) since cancel_execution
        # only kills the asyncio.Task, it doesn't touch the store status.
        # The caller (background_task_handler) separately calls move_task(FAILED).
        persisted_after = await store.get_task("t1")
        assert persisted_after is not None
        assert persisted_after.status == status_before

        await d.stop()

    @pytest.mark.asyncio
    async def test_cancel_execution_concurrent_double_cancel(self) -> None:
        """Calling cancel_execution twice on same task: first returns True, second False."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        started = asyncio.Event()
        runner = _SlowRunner(started)
        d = KanbanDispatcher(store, runner, board)
        await d.start()

        await asyncio.wait_for(started.wait(), timeout=3.0)

        first = await d.cancel_execution("t1")
        second = await d.cancel_execution("t1")

        assert first is True
        assert second is False

        await d.stop()

    @pytest.mark.asyncio
    async def test_cancel_execution_cleans_up_exec_tracking(self) -> None:
        """After cancel_execution, the task is removed from internal tracking."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        started = asyncio.Event()
        runner = _SlowRunner(started)
        d = KanbanDispatcher(store, runner, board)
        await d.start()

        await asyncio.wait_for(started.wait(), timeout=3.0)
        assert "t1" in d._task_id_to_exec

        await d.cancel_execution("t1")
        # _on_exec_done callback removes from tracking when task finishes
        await asyncio.sleep(0.05)
        assert "t1" not in d._task_id_to_exec

        await d.stop()
