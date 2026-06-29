"""Memory domain session post-processing — unified post-session task runner.

[INPUT]
- asyncio (POS: concurrent task execution)

[OUTPUT]
- SessionCleanupTask: Callable type alias for post-session hooks.
- run_session_post_process: Runs registered cleanup tasks concurrently.

[POS]
Single entry point for memory-domain background work after a conversation
session ends (proactive extraction, correction propagation, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

logger = logging.getLogger(__name__)

SessionCleanupTask = Callable[[Sequence[dict[str, str]], str | None], Awaitable[None]]


async def run_session_post_process(
    tasks: Sequence[SessionCleanupTask],
    messages: Sequence[dict[str, str]],
    chat_id: str | None,
) -> None:
    """Run all post-session tasks concurrently; failures are logged, not raised."""
    if not tasks:
        return

    results = await asyncio.gather(
        *(task(messages, chat_id) for task in tasks),
        return_exceptions=True,
    )
    for idx, result in enumerate(results):
        if isinstance(result, BaseException):
            logger.warning("Session post-process task %d failed: %s", idx, result)
