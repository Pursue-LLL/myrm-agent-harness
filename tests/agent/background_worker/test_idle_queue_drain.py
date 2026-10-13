"""Idle queue behaviour against the real SQLite registry: global queue, draining, recovery, cancellation."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.background_worker import idle_tasks
from myrm_agent_harness.agent.background_worker.idle_tasks import register_idle_task_handler, run_pending_idle_tasks
from myrm_agent_harness.agent.background_worker.registry import GLOBAL_SESSION_ID, IdleTaskRecord, IdleTaskRegistry
from myrm_agent_harness.runtime.cognitive_clock.signals import get_global_pause_signal
from myrm_agent_harness.runtime.maintenance.protocols import CapacityDenial, CapacityTicket

_SESSION = "chat_1"
_TYPES = ("probe_a", "probe_b", "probe_global")


@pytest.fixture
def registry(tmp_path: Path) -> IdleTaskRegistry:
    return IdleTaskRegistry(str(tmp_path / "idle.db"))


@pytest.fixture(autouse=True)
def _runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    scheduler = AsyncMock()
    scheduler.report_outcome = MagicMock()
    scheduler.request_capacity.return_value = CapacityTicket(ticket_id="t", task_type="probe")
    monkeypatch.setattr(idle_tasks, "get_maintenance_scheduler", lambda: scheduler)
    monkeypatch.setattr(idle_tasks, "get_event_bus", lambda: MagicMock())
    monkeypatch.setattr(idle_tasks.asyncio, "sleep", AsyncMock())
    yield
    for task_type in _TYPES:
        idle_tasks._idle_task_handlers.pop(task_type, None)


def _record_handler(ran: list[str]) -> AsyncMock:
    async def handler(task: IdleTaskRecord, session_id: str) -> dict[str, object]:
        ran.append(task.task_type)
        return {}

    return AsyncMock(side_effect=handler)


@pytest.mark.asyncio
async def test_one_window_drains_session_and_global_queues(registry: IdleTaskRegistry) -> None:
    ran: list[str] = []
    for task_type in _TYPES:
        register_idle_task_handler(task_type, _record_handler(ran))
    await registry.enqueue(_SESSION, "probe_a", {})
    await registry.enqueue(_SESSION, "probe_b", {})
    await registry.enqueue(GLOBAL_SESSION_ID, "probe_global", {})
    await registry.enqueue("chat_other", "probe_a", {})

    await run_pending_idle_tasks(_SESSION, registry)

    assert sorted(ran) == ["probe_a", "probe_b", "probe_global"]
    assert await registry.acquire_next(_SESSION) is None
    # Another chat's task is never claimed by this window.
    assert (await registry.acquire_next("chat_other")).task_type == "probe_a"


@pytest.mark.asyncio
async def test_failed_task_does_not_block_the_rest_and_is_not_retried(registry: IdleTaskRegistry) -> None:
    ran: list[str] = []
    register_idle_task_handler("probe_a", AsyncMock(side_effect=RuntimeError("boom")))
    register_idle_task_handler("probe_b", _record_handler(ran))
    await registry.enqueue(_SESSION, "probe_a", {})
    await registry.enqueue(_SESSION, "probe_b", {})

    await run_pending_idle_tasks(_SESSION, registry)

    assert ran == ["probe_b"]
    assert await registry.acquire_next(_SESSION) is None


@pytest.mark.asyncio
async def test_cancelled_window_returns_the_running_task_to_the_queue(registry: IdleTaskRegistry) -> None:
    started = asyncio.Event()

    async def hang(task: IdleTaskRecord, session_id: str) -> dict[str, object]:
        started.set()
        await asyncio.Event().wait()
        return {}

    register_idle_task_handler("probe_a", hang)
    await registry.enqueue(_SESSION, "probe_a", {})

    window = asyncio.create_task(run_pending_idle_tasks(_SESSION, registry))
    await asyncio.wait_for(started.wait(), timeout=5)
    window.cancel()
    with pytest.raises(asyncio.CancelledError):
        await window

    assert (await registry.acquire_next(_SESSION)).task_type == "probe_a"


@pytest.mark.asyncio
async def test_running_rows_left_by_a_crash_are_recovered_on_init(tmp_path: Path) -> None:
    db_path = str(tmp_path / "idle.db")
    crashed = IdleTaskRegistry(db_path)
    await crashed.enqueue(_SESSION, "probe_a", {})
    assert (await crashed.acquire_next(_SESSION)) is not None

    restarted = IdleTaskRegistry(db_path)
    await restarted.init_db()

    assert (await restarted.acquire_next(_SESSION)).task_type == "probe_a"


@pytest.mark.asyncio
async def test_registry_completion_and_error_marks_persist(registry: IdleTaskRegistry) -> None:
    await registry.enqueue(_SESSION, "probe_a", {})
    await registry.enqueue(_SESSION, "probe_b", {})
    first = await registry.acquire_next(_SESSION)
    second = await registry.acquire_next(_SESSION)

    await registry.mark_completed(first.id)
    await registry.mark_error(second.id)

    assert await registry.acquire_next(_SESSION) is None
    # A finished task type may be enqueued again (dedup only covers pending/running rows).
    await registry.enqueue(_SESSION, "probe_a", {})
    assert (await registry.acquire_next(_SESSION)).task_type == "probe_a"


@pytest.mark.asyncio
async def test_window_is_bounded(registry: IdleTaskRegistry, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(idle_tasks, "_MAX_TASKS_PER_IDLE_WINDOW", 1)
    ran: list[str] = []
    register_idle_task_handler("probe_a", _record_handler(ran))
    register_idle_task_handler("probe_b", _record_handler(ran))
    await registry.enqueue(_SESSION, "probe_a", {})
    await registry.enqueue(_SESSION, "probe_b", {})

    await run_pending_idle_tasks(_SESSION, registry)

    assert len(ran) == 1
    assert (await registry.acquire_next(_SESSION)) is not None


@pytest.mark.asyncio
async def test_drained_queue_asks_for_no_retry(registry: IdleTaskRegistry) -> None:
    register_idle_task_handler("probe_a", _record_handler([]))
    await registry.enqueue(_SESSION, "probe_a", {})

    assert await run_pending_idle_tasks(_SESSION, registry) is None


@pytest.mark.asyncio
async def test_user_activity_pause_leaves_the_queue_intact_and_asks_for_a_retry(
    registry: IdleTaskRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[str] = []
    register_idle_task_handler("probe_a", _record_handler(ran))
    await registry.enqueue(_SESSION, "probe_a", {})
    pause_signal = get_global_pause_signal()
    pause_signal.request_pause("typing")
    try:
        assert await run_pending_idle_tasks(_SESSION, registry) == idle_tasks.DEFERRED_RETRY_SECONDS
        assert ran == []

        pause_signal.clear()
        assert await run_pending_idle_tasks(_SESSION, registry) is None
        assert ran == ["probe_a"]
    finally:
        pause_signal.clear()


@pytest.mark.asyncio
async def test_capacity_denial_requeues_the_task_and_asks_for_a_retry(
    registry: IdleTaskRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    denying = AsyncMock()
    denying.request_capacity.return_value = CapacityDenial(reason="overloaded", retry_after_seconds=60.0)
    monkeypatch.setattr(idle_tasks, "get_maintenance_scheduler", lambda: denying)
    ran: list[str] = []
    register_idle_task_handler("probe_a", _record_handler(ran))
    await registry.enqueue(_SESSION, "probe_a", {})

    assert await run_pending_idle_tasks(_SESSION, registry) == idle_tasks.DEFERRED_RETRY_SECONDS
    assert ran == []
    assert await registry.has_pending(_SESSION) is True


@pytest.mark.asyncio
async def test_exhausted_window_asks_for_a_retry_while_work_remains(
    registry: IdleTaskRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(idle_tasks, "_MAX_TASKS_PER_IDLE_WINDOW", 1)
    register_idle_task_handler("probe_a", _record_handler([]))
    register_idle_task_handler("probe_b", _record_handler([]))
    await registry.enqueue(_SESSION, "probe_a", {})
    await registry.enqueue(_SESSION, "probe_b", {})

    assert await run_pending_idle_tasks(_SESSION, registry) == idle_tasks.DEFERRED_RETRY_SECONDS
    assert await run_pending_idle_tasks(_SESSION, registry) is None
