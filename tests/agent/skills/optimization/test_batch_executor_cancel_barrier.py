"""Tests for BatchExecutor cancellation barrier on in-flight tasks."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from myrm_agent_harness.agent.skills.optimization.batch_executor import BatchExecutor, TaskStatus
from myrm_agent_harness.agent.skills.optimization.event_emitter import EventEmitter


@pytest.mark.asyncio
async def test_cancel_discards_in_flight_task_after_executor_returns() -> None:
    started = asyncio.Event()
    release_executor = asyncio.Event()
    optimization_writes: list[str] = []
    completed_events: list[str] = []

    async def executor_fn(skill_id: str) -> dict[str, Any]:
        optimization_writes.append(skill_id)
        started.set()
        await release_executor.wait()
        return {"token_consumption": 5}

    emitter = EventEmitter()

    async def on_task_completed(_event: str, payload: dict[str, Any]) -> None:
        if payload.get("status") == "success":
            completed_events.append(payload["skill_id"])

    emitter.on("batch_task_completed", on_task_completed)

    executor = BatchExecutor(executor_fn=executor_fn, event_emitter=emitter)
    await executor.start_workers(num_workers=1)

    try:
        batch_id = await executor.submit_batch(["skill-a"])
        await asyncio.wait_for(started.wait(), timeout=2.0)
        assert await executor.cancel_batch(batch_id) is True
        release_executor.set()
        await asyncio.sleep(0.3)

        task_id = executor._batches[batch_id]["task_ids"][0]
        task = executor._tasks[task_id]
        assert task.status == TaskStatus.CANCELLED
        assert optimization_writes == ["skill-a"]
        assert completed_events == []
    finally:
        await executor.stop_workers()
