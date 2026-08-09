"""Tests for the task-level human approval gate (IN_REVIEW state machine).

Covers: require_approval routing on verified success, approve → COMPLETED +
dependent promotion, reject → READY with reason echo, idempotency, CAS
(concurrent approve resolves once), retry budget reset on reject, and the
review-history section surfaced in the worker context.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from myrm_agent_harness.toolkits.kanban.dispatcher import KanbanDispatcher
from myrm_agent_harness.toolkits.kanban.stores import InMemoryKanbanStore
from myrm_agent_harness.toolkits.kanban.types import (
    BoardSettings,
    KanbanBoard,
    KanbanTask,
    TaskEventKind,
    TaskPriority,
    TaskStatus,
    VerificationResult,
)


class _PassVerifier:
    """Verifier that always accepts the produced result."""

    async def verify(self, task: KanbanTask, result: str) -> VerificationResult:
        return VerificationResult(passed=True, reason="ok")


class _FakeRunner:
    """Minimal TaskRunner that records calls and succeeds immediately."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, task: KanbanTask) -> tuple[bool, str]:
        self.calls.append(task.task_id)
        return (True, "work done")


def _make_board() -> KanbanBoard:
    return KanbanBoard(
        board_id="b1",
        name="Test",
        settings=BoardSettings(
            max_concurrent_tasks=3,
            heartbeat_interval_seconds=10,
            zombie_timeout_seconds=120,
        ),
    )


def _make_task(
    task_id: str = "t1",
    *,
    status: TaskStatus = TaskStatus.READY,
    require_approval: bool = False,
) -> KanbanTask:
    return KanbanTask(
        task_id=task_id,
        board_id="b1",
        title=f"Task {task_id}",
        status=status,
        priority=TaskPriority.NORMAL,
        require_approval=require_approval,
    )


class TestApprovalGate:

    @pytest.mark.asyncio
    async def test_require_approval_lands_in_in_review_not_completed(self) -> None:
        """A verified success on a require_approval task stops at IN_REVIEW."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(require_approval=True)
        await store.save_task(task)

        events: list[tuple[str, str]] = []
        d = KanbanDispatcher(store, _FakeRunner(), board, verifier=_PassVerifier())
        d.on_event(lambda etype, t: events.append((etype, t.task_id)))
        await d.start()
        await asyncio.sleep(0.4)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.IN_REVIEW
        assert updated.result == "work done"

        kinds = {e.kind for e in await store.list_events("t1")}
        assert TaskEventKind.REVIEW_REQUESTED in kinds
        assert TaskEventKind.COMPLETED not in kinds
        assert ("task_review_requested", "t1") in events

    @pytest.mark.asyncio
    async def test_without_require_approval_skips_review(self) -> None:
        """A regular task still completes immediately (zero behavior change)."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(require_approval=False)
        await store.save_task(task)

        d = KanbanDispatcher(store, _FakeRunner(), board, verifier=_PassVerifier())
        await d.start()
        await asyncio.sleep(0.4)
        await d.stop()

        updated = await store.get_task("t1")
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_approve_promotes_to_completed_and_releases_dependents(self) -> None:
        """approve_task() completes the task and promotes child tasks."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        parent = _make_task(task_id="parent", status=TaskStatus.IN_REVIEW, require_approval=True)
        parent.result = "built & tested"
        await store.save_task(parent)
        child = _make_task(task_id="child", status=TaskStatus.BACKLOG)
        await store.save_task(child)
        await store.add_edge("parent", "child")

        d = KanbanDispatcher(store, _FakeRunner(), board, verifier=_PassVerifier())

        approved = await d.approve_task("parent", approver="alice")
        assert approved is not None
        assert approved.status == TaskStatus.COMPLETED
        assert approved.completed_at is not None

        updated_child = await store.get_task("child")
        assert updated_child is not None
        assert updated_child.status == TaskStatus.READY

        kinds = {e.kind for e in await store.list_events("parent")}
        assert TaskEventKind.APPROVED in kinds
        approved_event = next(e for e in await store.list_events("parent") if e.kind == TaskEventKind.APPROVED)
        assert approved_event.payload == {"approver": "alice"}

    @pytest.mark.asyncio
    async def test_reject_sends_back_to_ready_with_reason(self) -> None:
        """reject_task() sends the task back to READY and echoes the reason."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.IN_REVIEW, require_approval=True)
        task.result = "draft answer"
        await store.save_task(task)

        d = KanbanDispatcher(store, _FakeRunner(), board, verifier=_PassVerifier())

        rejected = await d.reject_task("t1", reason="needs source citations", approver="bob")
        assert rejected is not None
        assert rejected.status == TaskStatus.READY
        assert rejected.error == "needs source citations"
        assert rejected.completed_at is None

        kinds = {e.kind for e in await store.list_events("t1")}
        assert TaskEventKind.REJECTED in kinds
        rejected_event = next(e for e in await store.list_events("t1") if e.kind == TaskEventKind.REJECTED)
        assert rejected_event.payload["reason"] == "needs source citations"
        assert rejected_event.payload["approver"] == "bob"

    @pytest.mark.asyncio
    async def test_approve_reject_are_idempotent_outside_in_review(self) -> None:
        """approve/reject on a non-IN_REVIEW task are safe no-ops."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.COMPLETED)
        await store.save_task(task)

        d = KanbanDispatcher(store, _FakeRunner(), board, verifier=_PassVerifier())
        result = await d.approve_task("t1")
        assert result is not None
        assert result.status == TaskStatus.COMPLETED

        result = await d.reject_task("t1", reason="nope")
        assert result is not None
        assert result.status == TaskStatus.COMPLETED

        kinds = {e.kind for e in await store.list_events("t1")}
        assert TaskEventKind.APPROVED not in kinds
        assert TaskEventKind.REJECTED not in kinds

    @pytest.mark.asyncio
    async def test_reject_then_rerun_lands_in_review_again(self) -> None:
        """After rejection, re-dispatch goes through the approval gate again."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(require_approval=True)
        await store.save_task(task)

        d = KanbanDispatcher(store, _FakeRunner(), board, verifier=_PassVerifier())
        await d.start()
        await asyncio.sleep(0.4)

        current = await store.get_task("t1")
        assert current is not None
        assert current.status == TaskStatus.IN_REVIEW

        await d.reject_task("t1", reason="redo it")

        requeued = await store.get_task("t1")
        assert requeued is not None
        assert requeued.status == TaskStatus.READY

        d.wake()
        await asyncio.sleep(0.4)
        await d.stop()

        again = await store.get_task("t1")
        assert again is not None
        assert again.status == TaskStatus.IN_REVIEW
        assert len(await store.list_runs("t1")) >= 2

    @pytest.mark.asyncio
    async def test_reject_resets_retry_budget(self) -> None:
        """Rejection grants a fresh retry budget for the rework attempt."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.IN_REVIEW, require_approval=True)
        task.retry_count = 2
        task.consecutive_failures = 2
        await store.save_task(task)

        d = KanbanDispatcher(store, _FakeRunner(), board, verifier=_PassVerifier())
        rejected = await d.reject_task("t1", reason="rework")

        assert rejected is not None
        assert rejected.status == TaskStatus.READY
        assert rejected.retry_count == 0
        assert rejected.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_concurrent_approve_succeeds_exactly_once(self) -> None:
        """Two concurrent approve calls produce a single APPROVED event (CAS)."""
        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(task_id="parent", status=TaskStatus.IN_REVIEW, require_approval=True)
        task.result = "built & tested"
        await store.save_task(task)

        d = KanbanDispatcher(store, _FakeRunner(), board, verifier=_PassVerifier())
        _, _ = await asyncio.gather(
            d.approve_task("parent", approver="alice"),
            d.approve_task("parent", approver="bob"),
        )

        events = [e for e in await store.list_events("parent") if e.kind == TaskEventKind.APPROVED]
        assert len(events) == 1


class TestReviewHistoryInContext:

    @pytest.mark.asyncio
    async def test_rejected_reason_appears_in_worker_context(self) -> None:
        """The worker context surfaces prior rejection reasons for adaptation."""
        from myrm_agent_harness.toolkits.kanban.context_builder import build_task_context

        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY, require_approval=True)
        await store.save_task(task)

        d = KanbanDispatcher(store, _FakeRunner(), board, verifier=_PassVerifier())
        await d.start()
        await asyncio.sleep(0.4)
        await d.reject_task("t1", reason="add unit tests")
        await d.stop()

        context = await build_task_context(store, "t1")
        assert "## Review history" in context
        assert "add unit tests" in context

    @pytest.mark.asyncio
    async def test_review_history_omitted_when_no_review(self) -> None:
        """A task with no review events has no Review history section."""
        from myrm_agent_harness.toolkits.kanban.context_builder import build_task_context

        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)
        task = _make_task(status=TaskStatus.READY)
        await store.save_task(task)

        context = await build_task_context(store, "t1")
        assert "## Review history" not in context


class TestOrchestratorAddTask:

    @pytest.mark.asyncio
    async def test_add_task_supports_require_approval(self) -> None:
        """kanban_add_task accepts require_approval and persists it."""
        from myrm_agent_harness.toolkits.kanban._orchestrator_tools import build_orchestrator_tools

        store = InMemoryKanbanStore()
        board = _make_board()
        await store.save_board(board)

        tools = build_orchestrator_tools(store, None, default_board_id="b1")
        add_task = next(t for t in tools if t.name == "kanban_add_task")
        result = json.loads(await add_task.ainvoke({"title": "deploy to prod", "require_approval": True}))

        assert result["status"] == "added"
        task = await store.get_task(result["task"]["task_id"])
        assert task is not None
        assert task.require_approval is True
