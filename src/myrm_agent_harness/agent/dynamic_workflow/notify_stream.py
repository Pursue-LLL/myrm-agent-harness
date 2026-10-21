"""Live notify queue draining while a background asyncio task runs.

[INPUT]
- asyncio.Queue (POS: DW PTC notify event buffer.)

[OUTPUT]
- iter_notify_events_while_task_runs: yields queued events during task execution
- drain_notify_queue_nowait: non-blocking flush helper

[POS]
Keeps Dynamic Workflow engine lean by isolating concurrent queue-drain logic
from orchestration flow in __init__.py.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

_CANCEL_POLL_SECONDS = 0.2
"""Cancel-token poll cadence while a script emits no notify events.

A bare ``FIRST_COMPLETED`` wait blocks on the queue getter for as long as the
script stays silent, so the Stop button could not interrupt compute-only or
blocked-I/O scripts. Polling bounds the reaction time without spinning.
"""


async def drain_notify_queue_nowait(
    notify_queue: asyncio.Queue[dict[str, object]],
) -> list[dict[str, object]]:
    drained: list[dict[str, object]] = []
    while True:
        try:
            drained.append(notify_queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return drained


async def iter_notify_events_while_task_runs(
    notify_queue: asyncio.Queue[dict[str, object]],
    task: asyncio.Task[object],
    cancel_token: object | None = None,
) -> AsyncIterator[dict[str, object]]:
    """Yield notify events as they arrive while ``task`` is still running.

    Cancellation is checked on a fixed poll interval in addition to event arrival,
    so a silent script can still be stopped promptly.
    """
    queue_get_task: asyncio.Task[dict[str, object]] | None = None
    try:
        while not task.done():
            if cancel_token and getattr(cancel_token, "is_cancelled", False):
                task.cancel()
                break
            if queue_get_task is None or queue_get_task.done():
                queue_get_task = asyncio.create_task(notify_queue.get())
            done, _pending = await asyncio.wait(
                {task, queue_get_task},
                timeout=_CANCEL_POLL_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if queue_get_task in done:
                yield queue_get_task.result()
                queue_get_task = None
    finally:
        if queue_get_task is not None and not queue_get_task.done():
            queue_get_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await queue_get_task
        for event in await drain_notify_queue_nowait(notify_queue):
            yield event


__all__ = ["drain_notify_queue_nowait", "iter_notify_events_while_task_runs"]
