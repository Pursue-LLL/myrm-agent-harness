"""Unit tests for Async Non-Blocking Tool Calling and Overlapped Inference Suite."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.runtime.async_tool_calling import (
    AsyncToolDispatcher,
    AsyncToolMetadata,
    OverlappedInferenceCoordinator,
    ToolExecutionMode,
    ToolFutureHandle,
    ToolJobResult,
    ToolJobStatus,
)


@pytest.mark.asyncio
async def test_sync_tool_dispatch() -> None:
    """Verify that synchronous tools execute immediately and return terminal ToolJobResult."""
    dispatcher = AsyncToolDispatcher()

    def calc_sync(a: int, b: int) -> str:
        return str(a + b)

    res = await dispatcher.submit_tool_call("calc", calc_sync, 10, 20, async_mode=False)
    assert isinstance(res, ToolJobResult)
    assert res.is_success is True
    assert res.return_value == "30"
    assert res.status == ToolJobStatus.COMPLETED


@pytest.mark.asyncio
async def test_async_tool_dispatch_and_overlapped_inference() -> None:
    """Verify non-blocking async tool call returns ToolFutureHandle immediately."""
    dispatcher = AsyncToolDispatcher()
    dispatcher.register_tool(
        AsyncToolMetadata(
            tool_name="long_download",
            supports_async=True,
            default_mode=ToolExecutionMode.ASYNC_FUTURE,
            default_estimated_duration_s=2.0,
        )
    )

    async def mock_download(url: str) -> str:
        await asyncio.sleep(0.05)
        return f"Downloaded {url} (200 OK)"

    handle = await dispatcher.submit_tool_call(
        "long_download",
        mock_download,
        "https://example.com/asset.zip",
        async_mode=True,
    )

    # Invariant: Must return future handle immediately without blocking caller
    assert isinstance(handle, ToolFutureHandle)
    assert handle.tool_name == "long_download"
    assert handle.status == ToolJobStatus.RUNNING

    # Caller can execute independent work concurrently
    poll_status = dispatcher.poll_job_status(handle.task_id)
    assert poll_status in (ToolJobStatus.RUNNING, ToolJobStatus.COMPLETED)

    # Await completion
    result = await dispatcher.await_job(handle.task_id, timeout_s=1.0)
    assert result.is_success is True
    assert "Downloaded https://example.com/asset.zip" in result.return_value

    await dispatcher.dispose_all()


@pytest.mark.asyncio
async def test_sync_wait_tool_optout_contract() -> None:
    """Verify that yield and wait tools strictly opt out of async deferral (openclaw #166876)."""
    dispatcher = AsyncToolDispatcher()

    # sessions_yield is registered by default as sync wait optout
    assert dispatcher.is_sync_wait_optout("sessions_yield") is True
    assert dispatcher.is_sync_wait_optout("await_job") is True

    yield_called = False

    async def mock_sessions_yield(reason: str) -> str:
        nonlocal yield_called
        yield_called = True
        return f"Yielded control: {reason}"

    # Even with async_mode=True requested, dispatcher must force synchronous blocking
    result = await dispatcher.submit_tool_call(
        "sessions_yield",
        mock_sessions_yield,
        "Waiting for user input",
        async_mode=True,  # Call site attempts to make it async
    )

    # CRITICAL INVARIANT: Yield tool must NOT return a future handle!
    assert isinstance(result, ToolJobResult)
    assert result.is_success is True
    assert yield_called is True
    assert "Yielded control" in result.return_value

    await dispatcher.dispose_all()


@pytest.mark.asyncio
async def test_await_job_and_timeout() -> None:
    """Verify await_job behavior on slow tasks triggering timeout."""
    dispatcher = AsyncToolDispatcher()

    async def very_slow_task() -> str:
        await asyncio.sleep(0.5)
        return "Finished slow task"

    handle = await dispatcher.submit_tool_call(
        "slow_op",
        very_slow_task,
        async_mode=True,
    )
    assert isinstance(handle, ToolFutureHandle)

    # Await with short timeout (0.01s)
    res = await dispatcher.await_job(handle.task_id, timeout_s=0.01)
    assert res.status == ToolJobStatus.TIMED_OUT
    assert "timed out" in res.error_msg

    await dispatcher.dispose_all()


@pytest.mark.asyncio
async def test_overlapped_inference_coordinator_drain_and_markdown() -> None:
    """Verify coordinator tracks active futures, drains ready events at step boundaries, and formats markdown."""
    dispatcher = AsyncToolDispatcher()
    coordinator = OverlappedInferenceCoordinator(dispatcher)

    async def quick_task(task_name: str) -> str:
        await asyncio.sleep(0.02)
        return f"Success: {task_name}"

    handle = await dispatcher.submit_tool_call(
        "quick_op",
        quick_task,
        "data_prep",
        async_mode=True,
    )
    assert isinstance(handle, ToolFutureHandle)
    coordinator.track_future(handle)

    # Verify active handle tracked in markdown card
    md_running = coordinator.render_async_pipeline_markdown()
    assert "### ⚡ 异步非阻塞工具调用与前瞻重叠推理调度看板" in md_running
    assert "quick_op" in md_running

    # Wait for completion
    await dispatcher.await_job(handle.task_id, timeout_s=1.0)

    # Events drained at inference boundary
    events = coordinator.drain_ready_events()
    assert len(events) == 1
    assert events[0].task_id == handle.task_id
    assert events[0].result.return_value == "Success: data_prep"

    # Queue should now be empty after drain
    assert len(coordinator.drain_ready_events()) == 0

    await dispatcher.dispose_all()


@pytest.mark.asyncio
async def test_dispose_all_cancellation() -> None:
    """Verify dispose_all properly terminates running asynchronous tasks without leaving zombies."""
    dispatcher = AsyncToolDispatcher()

    async def infinite_job() -> str:
        while True:
            await asyncio.sleep(0.1)

    handle = await dispatcher.submit_tool_call("infinite", infinite_job, async_mode=True)
    assert isinstance(handle, ToolFutureHandle)

    cancelled = await dispatcher.dispose_all()
    assert cancelled == 1
