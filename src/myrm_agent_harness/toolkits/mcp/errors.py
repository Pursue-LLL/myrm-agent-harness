"""MCP error handling utilities.

MCP SDK (anyio-based) uses cancel scopes that can leak ``CancelledError``
on timeout or connection failure.  Since ``CancelledError`` is a
``BaseException``, it escapes ``except Exception`` handlers and can crash
the agent loop.

This module provides helpers to distinguish SDK-leaked cancellations from
genuine task cancellations (e.g. user /stop).

[INPUT]
- (none)

[OUTPUT]
- reraise_if_genuine_cancel: Re-raise *exc* if the current task was genuinely cancelled.

[POS]
MCP error handling utilities.
"""

from __future__ import annotations

import asyncio


def reraise_if_genuine_cancel(exc: asyncio.CancelledError) -> None:
    """Re-raise *exc* if the current task was genuinely cancelled.

    Call inside an ``except asyncio.CancelledError`` block.  Returns
    normally when the cancellation originated from an MCP SDK cancel-scope
    leak (safe to convert into a graceful error).  Re-raises when the
    task itself was cancelled externally (e.g. user /stop command).

    Uses ``Task.cancelling()`` (Python 3.11+) to detect external
    cancellation requests.
    """
    task = asyncio.current_task()
    if task is not None and task.cancelling() > 0:
        raise exc
