"""Async tool dispatcher with support for non-blocking execution and sync-wait opt-out.

Implements the SyncWaitToolOptOut protocol to guarantee wait/yield tools remain
strictly synchronous, preventing speculative reasoning before wait-results arrive.

[INPUT]
- __future__
- asyncio
- contextlib
- time
- uuid
- collections

[OUTPUT]
- AsyncToolDispatcher

[POS]
Async tool dispatcher with support for non-blocking execution and sync-wait opt-out.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Callable, Coroutine

from .async_tool_types import (
    AsyncToolMetadata,
    ToolCompletedEvent,
    ToolExecutionMode,
    ToolFutureHandle,
    ToolJobResult,
    ToolJobStatus,
)


class AsyncToolDispatcher:
    """Dispatches tool executions in synchronous or non-blocking asynchronous modes."""

    def __init__(self) -> None:
        self._tool_metadata: dict[str, AsyncToolMetadata] = {}
        self._running_tasks: dict[str, asyncio.Task[ToolJobResult]] = {}
        self._job_results: dict[str, ToolJobResult] = {}
        self._event_listeners: list[Callable[[ToolCompletedEvent], None]] = []
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register built-in meta tools with mandatory sync wait opt-out."""
        # Yielding or waiting tools MUST NEVER be async-deferred
        self.register_tool(
            AsyncToolMetadata(
                tool_name="await_job",
                supports_async=False,
                default_mode=ToolExecutionMode.SYNC_WAIT_OPTOUT,
                is_wait_or_yield_tool=True,
            )
        )
        self.register_tool(
            AsyncToolMetadata(
                tool_name="sessions_yield",
                supports_async=False,
                default_mode=ToolExecutionMode.SYNC_WAIT_OPTOUT,
                is_wait_or_yield_tool=True,
            )
        )

    def register_tool(self, metadata: AsyncToolMetadata) -> None:
        """Register capability descriptor and execution rules for a tool."""
        self._tool_metadata[metadata.tool_name] = metadata

    def add_completion_listener(self, listener: Callable[[ToolCompletedEvent], None]) -> None:
        """Register a callback invoked when an asynchronous background job completes."""
        self._event_listeners.append(listener)

    def is_sync_wait_optout(self, tool_name: str) -> bool:
        """Return True if tool is designated as a synchronous wait/yield tool."""
        meta = self._tool_metadata.get(tool_name)
        if meta is None:
            return False
        return not meta.supports_async or meta.is_wait_or_yield_tool

    async def submit_tool_call(
        self,
        tool_name: str,
        func: Callable[..., Coroutine[object, object, str] | str],
        *args: object,
        async_mode: bool = False,
        estimated_duration_s: float | None = None,
        **kwargs: object,
    ) -> ToolFutureHandle | ToolJobResult:
        """Dispatch a tool call.

        If async_mode is requested and tool supports async, returns a ToolFutureHandle immediately.
        If tool opts out (e.g., await_job or sessions_yield), executes synchronously regardless.
        """
        task_id = f"job_{uuid.uuid4().hex[:8]}"
        meta = self._tool_metadata.get(tool_name)

        # Enforce SyncWaitToolOptOut invariant: wait/yield tools must block synchronously
        if self.is_sync_wait_optout(tool_name):
            start_t = time.time()
            return await self._execute_sync(task_id, tool_name, func, start_t, *args, **kwargs)

        if not async_mode:
            start_t = time.time()
            return await self._execute_sync(task_id, tool_name, func, start_t, *args, **kwargs)

        # Async non-blocking dispatch
        est_duration = (
            estimated_duration_s
            if estimated_duration_s is not None
            else (meta.default_estimated_duration_s if meta else 5.0)
        )

        handle = ToolFutureHandle(
            task_id=task_id,
            tool_name=tool_name,
            status=ToolJobStatus.RUNNING,
            estimated_duration_s=est_duration,
            submitted_at=time.time(),
        )

        task = asyncio.create_task(
            self._run_async_worker(task_id, tool_name, func, *args, **kwargs)
        )
        self._running_tasks[task_id] = task
        return handle

    async def await_job(self, task_id: str, timeout_s: float = 30.0) -> ToolJobResult:
        """Explicitly await completion of an asynchronous background job."""
        if task_id in self._job_results:
            return self._job_results[task_id]

        task = self._running_tasks.get(task_id)
        if task is None:
            return ToolJobResult(
                task_id=task_id,
                tool_name="unknown",
                status=ToolJobStatus.FAILED,
                error_msg=f"Job ID '{task_id}' not found in active or completed jobs.",
            )

        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
        except TimeoutError:
            return ToolJobResult(
                task_id=task_id,
                tool_name="timeout_job",
                status=ToolJobStatus.TIMED_OUT,
                error_msg=f"Job '{task_id}' timed out after {timeout_s}s.",
            )

    def poll_job_status(self, task_id: str) -> ToolJobStatus:
        """Poll the current lifecycle status of a tool job without blocking."""
        if task_id in self._job_results:
            return self._job_results[task_id].status
        if task_id in self._running_tasks:
            return ToolJobStatus.RUNNING
        return ToolJobStatus.FAILED

    def cancel_job(self, task_id: str) -> bool:
        """Cancel a running background job."""
        task = self._running_tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            self._job_results[task_id] = ToolJobResult(
                task_id=task_id,
                tool_name="cancelled_job",
                status=ToolJobStatus.CANCELLED,
                error_msg="Job was cancelled by request.",
            )
            return True
        return False

    async def dispose_all(self) -> int:
        """Cancel and drain all in-flight asynchronous tasks upon session teardown."""
        cancelled_count = 0
        for task in list(self._running_tasks.values()):
            if not task.done():
                task.cancel()
                cancelled_count += 1

        if self._running_tasks:
            await asyncio.gather(*self._running_tasks.values(), return_exceptions=True)
            self._running_tasks.clear()

        return cancelled_count

    async def _execute_sync(
        self,
        task_id: str,
        tool_name: str,
        func: Callable[..., Coroutine[object, object, str] | str],
        start_t: float,
        *args: object,
        **kwargs: object,
    ) -> ToolJobResult:
        """Execute a tool synchronously and capture terminal results."""
        try:
            raw_res = func(*args, **kwargs)
            if asyncio.iscoroutine(raw_res):
                val = await raw_res
            else:
                val = str(raw_res)

            res = ToolJobResult(
                task_id=task_id,
                tool_name=tool_name,
                status=ToolJobStatus.COMPLETED,
                return_value=str(val),
                duration_s=time.time() - start_t,
            )
        except Exception as exc:
            res = ToolJobResult(
                task_id=task_id,
                tool_name=tool_name,
                status=ToolJobStatus.FAILED,
                error_msg=str(exc),
                duration_s=time.time() - start_t,
            )

        self._job_results[task_id] = res
        return res

    async def _run_async_worker(
        self,
        task_id: str,
        tool_name: str,
        func: Callable[..., Coroutine[object, object, str] | str],
        *args: object,
        **kwargs: object,
    ) -> ToolJobResult:
        """Worker executing the tool in background and broadcasting completion event."""
        start_t = time.time()
        res = await self._execute_sync(task_id, tool_name, func, start_t, *args, **kwargs)

        self._running_tasks.pop(task_id, None)

        event = ToolCompletedEvent(
            task_id=task_id,
            tool_name=tool_name,
            result=res,
            event_timestamp=time.time(),
        )

        for listener in self._event_listeners:
            with contextlib.suppress(Exception):
                # Listener failures must never crash the dispatcher worker
                listener(event)

        return res
