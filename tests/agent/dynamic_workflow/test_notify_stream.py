"""Unit tests for notify_stream concurrent drain."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.agent.dynamic_workflow.notify_stream import (
    iter_notify_events_while_task_runs,
)


@pytest.mark.asyncio
async def test_events_yielded_before_task_completes() -> None:
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

    async def slow_task() -> str:
        await asyncio.sleep(0.05)
        await queue.put({"type": "status", "step_key": "workflow_stage", "data": {"message": "late"}})
        await asyncio.sleep(0.05)
        return "done"

    task = asyncio.create_task(slow_task())
    await queue.put({"type": "status", "step_key": "workflow_stage", "data": {"message": "early"}})

    events: list[dict[str, object]] = []
    async for event in iter_notify_events_while_task_runs(queue, task):
        events.append(event)

    assert await task == "done"
    messages = [e["data"]["message"] for e in events if isinstance(e.get("data"), dict)]
    assert messages == ["early", "late"]


@pytest.mark.asyncio
async def test_cancel_token_interrupts_silent_script() -> None:
    """Cancellation must not wait for the script to emit a notify event.

    A silent long-running script (pure computation, blocked I/O) never puts
    anything on the queue. Draining with a bare ``FIRST_COMPLETED`` wait would
    block forever on the queue getter, so the Stop button appeared dead.
    """

    class _Token:
        def __init__(self) -> None:
            self.is_cancelled = False

    token = _Token()
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    cancelled_at: list[float] = []

    async def silent_task() -> str:
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled_at.append(loop.time() - started)
            raise
        return "never"

    task = asyncio.create_task(silent_task())
    events: list[dict[str, object]] = []

    async def _cancel_soon() -> None:
        await asyncio.sleep(0.1)
        token.is_cancelled = True

    canceller = asyncio.create_task(_cancel_soon())
    started = asyncio.get_running_loop().time()
    async for event in iter_notify_events_while_task_runs(queue, task, cancel_token=token):
        events.append(event)
    elapsed = asyncio.get_running_loop().time() - started
    await canceller

    assert task.cancelled()
    assert cancelled_at, "the in-flight task should have been cancelled"
    assert elapsed < 2.0, f"cancellation took {elapsed:.2f}s; should be sub-second"
    assert events == []
