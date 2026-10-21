"""Tests for manual retry of FAILED kanban tasks.

Covers: the reset set and optional description, the audit trail, guard on
non-FAILED/missing tasks, double-submit idempotency under real interleaving (including
a worker claiming the task right after the move), and the dispatcher entry point
(emit once, wake, re-run to completion).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.kanban.dispatcher import KanbanDispatcher
from myrm_agent_harness.toolkits.kanban.retry import retry_failed_task
from myrm_agent_harness.toolkits.kanban.stores import InMemoryKanbanStore
from myrm_agent_harness.toolkits.kanban.types import (
    BoardSettings,
    KanbanBoard,
    KanbanTask,
    TaskEvent,
    TaskEventKind,
    TaskStatus,
)


class _FakeRunner:
    """Minimal TaskRunner that records calls and succeeds immediately."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, task: KanbanTask) -> tuple[bool, str]:
        self.calls.append(task.task_id)
        return (True, "work done")


class _RacingStore(InMemoryKanbanStore):
    """Forces the worst interleaving of two concurrent retries.

    Every read yields to the event loop after taking its snapshot, so both retries
    observe FAILED before either has written anything. Once
    ``arm()`` is called, the second save is held back until ``release_second_save``
    is set, i.e. until a worker has already claimed the task.
    """

    def __init__(self) -> None:
        super().__init__()
        self.release_second_save = asyncio.Event()
        self._saves_since_armed: int | None = None

    def arm(self) -> None:
        self._saves_since_armed = 0

    async def get_task(self, task_id: str) -> KanbanTask | None:
        snapshot = await super().get_task(task_id)
        await asyncio.sleep(0)
        return snapshot

    async def save_task(self, task: KanbanTask) -> KanbanTask:
        if self._saves_since_armed is not None:
            self._saves_since_armed += 1
            if self._saves_since_armed == 2:
                await self.release_second_save.wait()
        return await super().save_task(task)


def _make_board() -> KanbanBoard:
    return KanbanBoard(
        board_id="b1",
        name="Test",
        settings=BoardSettings(max_concurrent_tasks=3, heartbeat_interval_seconds=10, zombie_timeout_seconds=120),
    )


async def _seed(
    status: TaskStatus = TaskStatus.FAILED, store: InMemoryKanbanStore | None = None
) -> InMemoryKanbanStore:
    store = store or InMemoryKanbanStore()
    await store.save_board(_make_board())
    task = KanbanTask(task_id="t1", board_id="b1", title="Task t1", description="original", status=status)
    if status == TaskStatus.FAILED:
        task.error = "boom"
        task.retry_count = 3
        task.consecutive_failures = 3
        task.block_cycle_count = 2
        task.completed_at = datetime.now(UTC)
        task.progress_note = "stuck at step 2"
    await store.save_task(task)
    return store


async def _retry_events(store: InMemoryKanbanStore) -> list[TaskEvent]:
    return [e for e in await store.list_events("t1") if e.kind == TaskEventKind.RETRYING]


class TestRetryFailedTask:
    @pytest.mark.asyncio
    async def test_resets_status_and_budget_and_records_audit_event(self) -> None:
        store = await _seed()

        outcome = await retry_failed_task(store, "t1", reason="  fixed env  ", source="human")

        assert outcome.applied is True
        assert outcome.task is not None
        assert outcome.task.status == TaskStatus.READY
        persisted = await store.get_task("t1")
        assert persisted is not None
        assert persisted.status == TaskStatus.READY
        assert persisted.error == ""
        assert persisted.retry_count == 0
        assert persisted.consecutive_failures == 0
        assert persisted.block_cycle_count == 0
        assert persisted.completed_at is None
        assert persisted.progress_note is None
        assert persisted.description == "original"
        events = await _retry_events(store)
        assert len(events) == 1
        assert events[0].payload == {"from": "failed", "to": "ready", "source": "human", "reason": "fixed env"}

    @pytest.mark.asyncio
    async def test_new_description_replaces_original(self) -> None:
        store = await _seed()

        outcome = await retry_failed_task(store, "t1", description="  use API v2  ", source="orchestrator")

        assert outcome.task is not None
        assert outcome.task.description == "use API v2"
        persisted = await store.get_task("t1")
        assert persisted is not None
        assert persisted.description == "use API v2"

    @pytest.mark.asyncio
    async def test_blank_reason_and_description_are_ignored(self) -> None:
        store = await _seed()

        outcome = await retry_failed_task(store, "t1", description="   ", reason="  ", source="orchestrator")

        assert outcome.task is not None
        assert outcome.task.description == "original"
        events = await _retry_events(store)
        assert events[0].payload == {"from": "failed", "to": "ready", "source": "orchestrator"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [s for s in TaskStatus if s != TaskStatus.FAILED])
    async def test_non_failed_is_idempotent_noop(self, status: TaskStatus) -> None:
        store = await _seed(status)

        outcome = await retry_failed_task(store, "t1", description="x", source="human")

        assert outcome.applied is False
        assert outcome.task is not None
        assert outcome.task.status == status
        assert outcome.task.description == "original"
        assert await _retry_events(store) == []

    @pytest.mark.asyncio
    async def test_missing_task(self) -> None:
        store = await _seed()

        outcome = await retry_failed_task(store, "missing", source="human")

        assert outcome.applied is False
        assert outcome.task is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("child_status", [TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.COMPLETED])
    async def test_downstream_the_failure_already_released_is_left_alone(self, child_status: TaskStatus) -> None:
        store = await _seed()
        await store.save_task(
            KanbanTask(task_id="t2", board_id="b1", title="Task t2", description="downstream", status=child_status)
        )
        await store.add_edge("t1", "t2")
        events_before = [e.kind for e in await store.list_events("t2")]

        outcome = await retry_failed_task(store, "t1", source="human")

        assert outcome.applied is True
        child = await store.get_task("t2")
        assert child is not None
        assert child.status == child_status
        assert [e.kind for e in await store.list_events("t2")] == events_before

    @pytest.mark.asyncio
    async def test_double_submit_applies_once_and_never_clobbers_a_claim(self) -> None:
        """A worker claims the task the moment it is READY; the loser must not revert it to FAILED."""
        store = _RacingStore()
        await _seed(store=store)
        store.arm()

        async def claimer() -> None:
            while not await store.claim_task("t1", "worker-1"):
                await asyncio.sleep(0)
            store.release_second_save.set()

        async with asyncio.timeout(5):
            first, second, _ = await asyncio.gather(
                retry_failed_task(store, "t1", source="human"),
                retry_failed_task(store, "t1", source="human"),
                claimer(),
            )

        assert sorted([first.applied, second.applied]) == [False, True]
        assert len(await _retry_events(store)) == 1
        task = await store.get_task("t1")
        assert task is not None
        assert task.status == TaskStatus.RUNNING


class TestDispatcherRetryTask:
    @pytest.mark.asyncio
    async def test_emits_once_and_second_call_is_noop(self) -> None:
        store = await _seed()
        dispatcher = KanbanDispatcher(store, _FakeRunner(), _make_board())
        emitted: list[tuple[str, str]] = []
        dispatcher.on_event(lambda event_type, task: emitted.append((event_type, task.task_id)))

        first = await dispatcher.retry_task("t1")
        second = await dispatcher.retry_task("t1")

        assert first.applied is True
        assert second.applied is False
        assert emitted == [("task_retrying", "t1")]

    @pytest.mark.asyncio
    async def test_retried_task_is_picked_up_and_completed(self) -> None:
        store = await _seed()
        runner = _FakeRunner()
        dispatcher = KanbanDispatcher(store, runner, _make_board())
        await dispatcher.start()
        await asyncio.sleep(0.2)
        assert runner.calls == []  # FAILED is never scheduled on its own

        await dispatcher.retry_task("t1", description="use API v2", reason="fixed env")
        await asyncio.sleep(0.4)
        await dispatcher.stop()

        assert runner.calls == ["t1"]
        task = await store.get_task("t1")
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.description == "use API v2"
