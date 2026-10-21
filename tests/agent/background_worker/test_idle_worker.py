import asyncio

import pytest

from myrm_agent_harness.agent.background_worker import idle_worker
from myrm_agent_harness.agent.background_worker.idle_worker import _idle_tasks, cancel_idle_task, schedule_idle_task


async def _finish(session_id: str) -> None:
    """Wait for the session's scheduled worker to end, whatever the host load."""
    task = _idle_tasks.get(session_id)
    if task is not None:
        await asyncio.wait({task}, timeout=10)


@pytest.fixture(autouse=True)
def clear_tasks():
    _idle_tasks.clear()
    yield
    for task in _idle_tasks.values():
        if not task.done():
            task.cancel()
    _idle_tasks.clear()


@pytest.mark.asyncio
async def test_schedule_idle_task():
    callback_called = False

    async def my_callback():
        nonlocal callback_called
        callback_called = True

    schedule_idle_task("test_session", my_callback, delay_seconds=0.1)

    assert "test_session" in _idle_tasks

    await _finish("test_session")

    assert callback_called is True
    assert "test_session" not in _idle_tasks


@pytest.mark.asyncio
async def test_cancel_idle_task():
    callback_called = False

    async def my_callback():
        nonlocal callback_called
        callback_called = True

    schedule_idle_task("test_session", my_callback, delay_seconds=0.1)
    assert "test_session" in _idle_tasks

    # Cancel immediately
    cancel_idle_task("test_session")

    # Wait for duration
    await asyncio.sleep(0.15)

    assert callback_called is False
    assert "test_session" not in _idle_tasks


@pytest.mark.asyncio
async def test_reschedule_idle_task():
    callback_calls = 0

    async def my_callback():
        nonlocal callback_calls
        callback_calls += 1

    schedule_idle_task("test_session", my_callback, delay_seconds=0.1)

    # Reschedule before the first one fires
    schedule_idle_task("test_session", my_callback, delay_seconds=0.1)

    await _finish("test_session")

    # It should only be called once because the first one was cancelled
    assert callback_calls == 1


@pytest.mark.asyncio
async def test_exception_in_callback():
    async def my_callback():
        raise RuntimeError("Oops")

    schedule_idle_task("test_session", my_callback, delay_seconds=0.01)

    # The exception must be caught and logged, not crash the loop.
    await _finish("test_session")

    assert "test_session" not in _idle_tasks


@pytest.mark.asyncio
async def test_callback_returning_a_delay_is_called_again_until_it_finishes():
    results: list[float | None] = [0.01, 0.01, None]
    calls = 0

    async def deferring_callback() -> float | None:
        nonlocal calls
        calls += 1
        return results.pop(0)

    schedule_idle_task("test_session", deferring_callback, delay_seconds=0.01)
    await _finish("test_session")

    assert calls == 3
    assert "test_session" not in _idle_tasks


@pytest.mark.asyncio
async def test_a_callback_that_always_defers_is_retried_a_bounded_number_of_times(monkeypatch):
    monkeypatch.setattr(idle_worker, "_MAX_RETRIES", 2)
    calls = 0

    async def always_deferring() -> float | None:
        nonlocal calls
        calls += 1
        return 0.01

    schedule_idle_task("test_session", always_deferring, delay_seconds=0.01)
    await _finish("test_session")

    assert calls == 3  # first run plus two retries
    assert "test_session" not in _idle_tasks


@pytest.mark.asyncio
async def test_new_activity_cancels_a_pending_retry():
    calls = 0
    first_call = asyncio.Event()

    async def deferring_callback() -> float | None:
        nonlocal calls
        calls += 1
        first_call.set()
        return 0.2

    schedule_idle_task("test_session", deferring_callback, delay_seconds=0.01)
    await asyncio.wait_for(first_call.wait(), timeout=10)
    task = _idle_tasks["test_session"]

    cancel_idle_task("test_session")
    await asyncio.wait({task}, timeout=10)

    assert task.done()
    assert calls == 1
