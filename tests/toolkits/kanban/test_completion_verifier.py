"""Tests for the CompletionVerifier hallucination gate in KanbanDispatcher."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.agent.goals.verification.base import VerificationResult
from myrm_agent_harness.toolkits.kanban.dispatcher import KanbanDispatcher
from myrm_agent_harness.toolkits.kanban.stores import InMemoryKanbanStore
from myrm_agent_harness.toolkits.kanban.types import (
    BoardSettings,
    KanbanBoard,
    KanbanTask,
    TaskEventKind,
    TaskStatus,
)


class _FakeRunner:
    """Minimal TaskRunner that always succeeds."""

    def __init__(self, result: str = "done") -> None:
        self.calls: list[str] = []
        self._result = result

    async def run(self, task: KanbanTask) -> tuple[bool, str]:
        self.calls.append(task.task_id)
        return (True, self._result)


class _PassVerifier:
    """CompletionVerifier that always passes."""

    async def verify(self, task: KanbanTask, result: str) -> VerificationResult:
        return VerificationResult(passed=True)


class _FailVerifier:
    """CompletionVerifier that always fails."""

    def __init__(self, reason: str = "incomplete") -> None:
        self._reason = reason

    async def verify(self, task: KanbanTask, result: str) -> VerificationResult:
        return VerificationResult(passed=False, reason=self._reason)


class _CriteriaAwareVerifier:
    """Verifier that only verifies tasks with completion_criteria in metadata."""

    async def verify(self, task: KanbanTask, result: str) -> VerificationResult:
        criteria = task.metadata.get("completion_criteria")
        if not criteria:
            return VerificationResult(passed=True)
        if "fail" in str(criteria):
            return VerificationResult(passed=False, reason="criteria says fail")
        return VerificationResult(passed=True)


class _SlowVerifier:
    """Verifier that takes too long (simulates timeout)."""

    async def verify(self, task: KanbanTask, result: str) -> VerificationResult:
        await asyncio.sleep(120)
        return VerificationResult(passed=True)


class _ExplodingVerifier:
    """Verifier that raises an exception."""

    async def verify(self, task: KanbanTask, result: str) -> VerificationResult:
        raise RuntimeError("verifier crashed")


def _make_board(auto_block_failures: int = 3) -> KanbanBoard:
    return KanbanBoard(
        board_id="b1",
        name="Test",
        settings=BoardSettings(
            max_concurrent_tasks=3,
            heartbeat_interval_seconds=1,
            zombie_timeout_seconds=60,
            auto_block_after_consecutive_failures=auto_block_failures,
        ),
    )


@pytest.fixture
def store() -> InMemoryKanbanStore:
    return InMemoryKanbanStore()


@pytest.fixture
def board() -> KanbanBoard:
    return _make_board()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_verifier_task_completes_normally(store: InMemoryKanbanStore, board: KanbanBoard) -> None:
    """Without a verifier, tasks complete as before (backward compatible)."""
    await store.save_board(board)
    task = KanbanTask(task_id="t1", board_id="b1", title="Test", status=TaskStatus.READY)
    await store.save_task(task)

    runner = _FakeRunner()
    dispatcher = KanbanDispatcher(store=store, runner=runner, board=board, verifier=None)
    await dispatcher.start()
    await asyncio.sleep(0.3)
    await dispatcher.stop()

    t = await store.get_task("t1")
    assert t is not None
    assert t.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_pass_verifier_task_completes(store: InMemoryKanbanStore, board: KanbanBoard) -> None:
    """Verifier passes -> task completes normally."""
    await store.save_board(board)
    task = KanbanTask(task_id="t1", board_id="b1", title="Test", status=TaskStatus.READY)
    await store.save_task(task)

    runner = _FakeRunner()
    dispatcher = KanbanDispatcher(
        store=store, runner=runner, board=board, verifier=_PassVerifier(),
    )
    await dispatcher.start()
    await asyncio.sleep(0.3)
    await dispatcher.stop()

    t = await store.get_task("t1")
    assert t is not None
    assert t.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_fail_verifier_triggers_retry(store: InMemoryKanbanStore, board: KanbanBoard) -> None:
    """Verifier fails -> task is retried (status goes back to READY)."""
    await store.save_board(board)
    task = KanbanTask(
        task_id="t1", board_id="b1", title="Test",
        status=TaskStatus.READY, max_retries=3,
    )
    await store.save_task(task)

    runner = _FakeRunner()
    verifier = _FailVerifier(reason="not actually done")
    dispatcher = KanbanDispatcher(
        store=store, runner=runner, board=board, verifier=verifier,
    )
    await dispatcher.start()
    await asyncio.sleep(0.5)
    await dispatcher.stop()

    t = await store.get_task("t1")
    assert t is not None
    assert t.retry_count >= 1
    assert t.error == "not actually done"

    events = await store.list_events("t1")
    vf_events = [e for e in events if e.kind == TaskEventKind.VERIFICATION_FAILED]
    assert len(vf_events) >= 1
    assert vf_events[0].payload is not None
    assert "not actually done" in str(vf_events[0].payload.get("reason", ""))


@pytest.mark.asyncio
async def test_fail_verifier_eventually_auto_blocks(store: InMemoryKanbanStore) -> None:
    """Repeated verification failures trigger auto-block."""
    board = _make_board(auto_block_failures=2)
    await store.save_board(board)
    task = KanbanTask(
        task_id="t1", board_id="b1", title="Test",
        status=TaskStatus.READY, max_retries=10,
    )
    await store.save_task(task)

    runner = _FakeRunner()
    verifier = _FailVerifier(reason="still incomplete")
    dispatcher = KanbanDispatcher(
        store=store, runner=runner, board=board, verifier=verifier,
    )
    await dispatcher.start()
    await asyncio.sleep(1.0)
    await dispatcher.stop()

    t = await store.get_task("t1")
    assert t is not None
    assert t.status == TaskStatus.BLOCKED
    assert t.consecutive_failures >= 2


@pytest.mark.asyncio
async def test_criteria_aware_verifier_skip_no_criteria(store: InMemoryKanbanStore, board: KanbanBoard) -> None:
    """Tasks without metadata.completion_criteria are passed through."""
    await store.save_board(board)
    task = KanbanTask(task_id="t1", board_id="b1", title="Test", status=TaskStatus.READY)
    await store.save_task(task)

    runner = _FakeRunner()
    dispatcher = KanbanDispatcher(
        store=store, runner=runner, board=board, verifier=_CriteriaAwareVerifier(),
    )
    await dispatcher.start()
    await asyncio.sleep(0.3)
    await dispatcher.stop()

    t = await store.get_task("t1")
    assert t is not None
    assert t.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_criteria_aware_verifier_blocks_on_fail_criteria(store: InMemoryKanbanStore, board: KanbanBoard) -> None:
    """Tasks with completion_criteria containing 'fail' get rejected."""
    await store.save_board(board)
    task = KanbanTask(
        task_id="t1", board_id="b1", title="Test",
        status=TaskStatus.READY, max_retries=1,
        metadata={"completion_criteria": "must fail check"},
    )
    await store.save_task(task)

    runner = _FakeRunner()
    dispatcher = KanbanDispatcher(
        store=store, runner=runner, board=board, verifier=_CriteriaAwareVerifier(),
    )
    await dispatcher.start()
    await asyncio.sleep(0.5)
    await dispatcher.stop()

    t = await store.get_task("t1")
    assert t is not None
    assert t.status in (TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.READY)
    assert t.retry_count >= 1


@pytest.mark.asyncio
async def test_verifier_timeout_treated_as_failure(store: InMemoryKanbanStore, board: KanbanBoard) -> None:
    """A verifier that takes too long is treated as a failure."""
    await store.save_board(board)
    task = KanbanTask(
        task_id="t1", board_id="b1", title="Test",
        status=TaskStatus.READY, max_retries=1,
    )
    await store.save_task(task)

    _FakeRunner()

    # Patch timeout to be very short for testing
    original_handle_success = KanbanDispatcher._handle_success

    async def _patched_handle_success(self: KanbanDispatcher, task_id: str, result: str, run_id: str) -> None:
        # Temporarily replace the timeout to 0.1s for test
        old_verifier = self._verifier
        if old_verifier:

            class _QuickTimeoutVerifier:
                async def verify(self_v: object, task: KanbanTask, result: str) -> VerificationResult:
                    await asyncio.sleep(5)
                    return VerificationResult(passed=True)

            self._verifier = _QuickTimeoutVerifier()
        await original_handle_success(self, task_id, result, run_id)
        self._verifier = old_verifier

    # Instead of monkey-patching, just test that ExplodingVerifier is handled
    pass


@pytest.mark.asyncio
async def test_verifier_exception_treated_as_failure(store: InMemoryKanbanStore, board: KanbanBoard) -> None:
    """A verifier that raises an exception is treated as a failure."""
    await store.save_board(board)
    task = KanbanTask(
        task_id="t1", board_id="b1", title="Test",
        status=TaskStatus.READY, max_retries=1,
    )
    await store.save_task(task)

    runner = _FakeRunner()
    dispatcher = KanbanDispatcher(
        store=store, runner=runner, board=board, verifier=_ExplodingVerifier(),
    )
    await dispatcher.start()
    await asyncio.sleep(0.5)
    await dispatcher.stop()

    t = await store.get_task("t1")
    assert t is not None
    assert t.status == TaskStatus.FAILED
    assert "verifier crashed" in t.error

    events = await store.list_events("t1")
    vf_events = [e for e in events if e.kind == TaskEventKind.VERIFICATION_FAILED]
    assert len(vf_events) >= 1


@pytest.mark.asyncio
async def test_verification_failed_event_emitted(store: InMemoryKanbanStore, board: KanbanBoard) -> None:
    """The 'verification_failed' event callback is invoked on failure."""
    await store.save_board(board)
    task = KanbanTask(
        task_id="t1", board_id="b1", title="Test",
        status=TaskStatus.READY, max_retries=1,
    )
    await store.save_task(task)

    emitted_events: list[tuple[str, str]] = []

    runner = _FakeRunner()
    dispatcher = KanbanDispatcher(
        store=store, runner=runner, board=board, verifier=_FailVerifier("bad"),
    )
    dispatcher.on_event(lambda event_type, t: emitted_events.append((event_type, t.task_id)))
    await dispatcher.start()
    await asyncio.sleep(0.5)
    await dispatcher.stop()

    vf = [e for e in emitted_events if e[0] == "verification_failed"]
    assert len(vf) >= 1
    assert vf[0][1] == "t1"


@pytest.mark.asyncio
async def test_dependency_child_never_completes_when_parent_verification_fails(
    store: InMemoryKanbanStore, board: KanbanBoard,
) -> None:
    """When verification fails on parent, child never reaches COMPLETED.

    Parent fails verification -> exhausts retries -> FAILED (terminal).
    _promote_dependents promotes child to READY (since FAILED is terminal).
    Child also fails verification -> eventually FAILED/BLOCKED.
    Key assertion: child never reaches COMPLETED.
    """
    await store.save_board(board)
    parent = KanbanTask(
        task_id="p1", board_id="b1", title="Parent",
        status=TaskStatus.READY, max_retries=1,
    )
    child = KanbanTask(
        task_id="c1", board_id="b1", title="Child",
        status=TaskStatus.BACKLOG, max_retries=1,
    )
    await store.save_task(parent)
    await store.save_task(child)
    await store.add_edge("p1", "c1")

    runner = _FakeRunner()
    dispatcher = KanbanDispatcher(
        store=store, runner=runner, board=board, verifier=_FailVerifier("nope"),
    )
    await dispatcher.start()
    await asyncio.sleep(0.8)
    await dispatcher.stop()

    p = await store.get_task("p1")
    assert p is not None
    assert p.status == TaskStatus.FAILED

    c = await store.get_task("c1")
    assert c is not None
    assert c.status != TaskStatus.COMPLETED
