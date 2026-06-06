"""Core BatchExecutor paths: success, failure, progress, and cancel edge cases."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from myrm_agent_harness.agent.skills.optimization.batch_executor import (
    BatchExecutor,
    PerformanceMetrics,
    RetryPolicy,
    TaskStatus,
)
from myrm_agent_harness.agent.skills.optimization.event_emitter import EventEmitter


def test_retry_policy_get_delay_caps_at_max() -> None:
    policy = RetryPolicy(initial_delay=1.0, backoff_factor=2.0, max_delay=3.0)
    assert policy.get_delay(0) == 1.0
    assert policy.get_delay(1) == 2.0
    assert policy.get_delay(2) == 3.0
    assert policy.get_delay(5) == 3.0


def test_performance_metrics_properties() -> None:
    metrics = PerformanceMetrics()
    assert metrics.average_execution_time == 0.0
    assert metrics.tasks_per_second == 0.0

    metrics.completed_tasks = 2
    metrics.total_execution_time = 4.0
    assert metrics.average_execution_time == 2.0
    assert metrics.tasks_per_second == 0.5


@pytest.mark.asyncio
async def test_submit_batch_completes_with_success_events() -> None:
    completed_payloads: list[dict[str, Any]] = []

    async def executor_fn(skill_id: str) -> dict[str, int]:
        return {"token_consumption": 7}

    emitter = EventEmitter()

    async def on_completed(_event: str, payload: dict[str, Any]) -> None:
        if payload.get("status") == "success":
            completed_payloads.append(payload)

    emitter.on("batch_task_completed", on_completed)

    executor = BatchExecutor(executor_fn=executor_fn, event_emitter=emitter)
    await executor.start_workers(num_workers=1)

    try:
        batch_id = await executor.submit_batch(["skill-a", "skill-b"])
        await asyncio.sleep(0.4)

        progress = await executor.get_batch_progress(batch_id)
        assert progress is not None
        assert progress["completed"] == 2
        assert progress["failed"] == 0
        assert progress["status"] == "completed"
        assert len(completed_payloads) == 2

        perf = await executor.get_performance_metrics()
        assert perf["completed_tasks"] == 2
        assert perf["total_token_consumption"] == 14
    finally:
        await executor.stop_workers()


async def _success_executor(_skill_id: str) -> dict[str, int]:
    return {"token_consumption": 1}


@pytest.mark.asyncio
async def test_cancel_batch_returns_false_for_unknown_or_completed() -> None:
    emitter = EventEmitter()
    executor = BatchExecutor(executor_fn=_success_executor, event_emitter=emitter)

    assert await executor.cancel_batch("batch_missing") is False

    await executor.start_workers(num_workers=1)
    try:
        batch_id = await executor.submit_batch(["skill-a"])
        await asyncio.sleep(0.3)
        assert await executor.cancel_batch(batch_id) is False
    finally:
        await executor.stop_workers()


@pytest.mark.asyncio
async def test_cancel_before_worker_processes_marks_cancelled() -> None:
    started = asyncio.Event()

    async def executor_fn(skill_id: str) -> dict[str, int]:
        started.set()
        return {"token_consumption": 1}

    emitter = EventEmitter()
    executor = BatchExecutor(executor_fn=executor_fn, event_emitter=emitter)
    await executor.start_workers(num_workers=1)

    try:
        batch_id = await executor.submit_batch(["skill-a"])
        assert await executor.cancel_batch(batch_id) is True
        await asyncio.sleep(0.3)

        task_id = executor._batches[batch_id]["task_ids"][0]
        assert executor._tasks[task_id].status == TaskStatus.CANCELLED
        assert not started.is_set()
    finally:
        await executor.stop_workers()


@pytest.mark.asyncio
async def test_task_failure_emits_failed_event_after_retries_exhausted() -> None:
    failed_payloads: list[dict[str, Any]] = []

    async def failing_fn(_skill_id: str) -> dict[str, int]:
        raise ValueError("optimization failed")

    emitter = EventEmitter()

    async def on_failed(_event: str, payload: dict[str, Any]) -> None:
        failed_payloads.append(payload)

    emitter.on("batch_task_failed", on_failed)

    executor = BatchExecutor(
        executor_fn=failing_fn,
        event_emitter=emitter,
        retry_policy=RetryPolicy(max_retries=0, initial_delay=0.01),
    )
    await executor.start_workers(num_workers=1)

    try:
        batch_id = await executor.submit_batch(["skill-a"])
        await asyncio.sleep(0.3)

        task_id = executor._batches[batch_id]["task_ids"][0]
        task = executor._tasks[task_id]
        assert task.status == TaskStatus.FAILED
        assert task.error_message == "optimization failed"
        assert len(failed_payloads) == 1
        assert failed_payloads[0]["skill_id"] == "skill-a"
    finally:
        await executor.stop_workers()


@pytest.mark.asyncio
async def test_start_workers_idempotent_when_already_running() -> None:
    emitter = EventEmitter()
    executor = BatchExecutor(executor_fn=_success_executor, event_emitter=emitter)
    await executor.start_workers(num_workers=1)
    worker_count_after_first = len(executor._workers)
    await executor.start_workers(num_workers=2)
    assert len(executor._workers) == worker_count_after_first
    await executor.stop_workers()
