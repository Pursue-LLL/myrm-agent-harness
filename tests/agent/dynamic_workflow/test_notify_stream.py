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
