"""Idle Task Worker for scheduling background tasks when agent is inactive.

[INPUT]
- (none)

[OUTPUT]
- cancel_idle_task: Cancel any pending idle task for the given session.
- schedule_idle_task: Run a callback once the session has been idle, repeating while it asks to be retried

[POS]
Idle Task Worker for scheduling background tasks when agent is inactive.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_idle_tasks: dict[str, asyncio.Task[None]] = {}

# Bounds how often a deferring callback is retried so a permanently blocked queue cannot spin forever.
_MAX_RETRIES = 10


def cancel_idle_task(session_id: str) -> None:
    """Cancel any pending idle task for the given session."""
    task = _idle_tasks.pop(session_id, None)
    if task and not task.done():
        task.cancel()
        logger.debug("Cancelled existing idle task for session %s.", session_id)


def schedule_idle_task(
    session_id: str, callback: Callable[[], Awaitable[float | None]], delay_seconds: float = 600
) -> None:
    """Schedule a background task to run after the session has been idle.

    Args:
        session_id: Unique identifier for the conversation session.
        callback: Async function to execute when the idle period expires. Returning a number of
            seconds asks to be called again after that delay (work was deferred); ``None`` finishes.
        delay_seconds: Seconds to wait before executing (default 10 minutes).
    """
    cancel_idle_task(session_id)

    async def _worker() -> None:
        try:
            delay = delay_seconds
            for _ in range(1 + _MAX_RETRIES):
                await asyncio.sleep(delay)
                logger.info("Idle time reached for session %s. Starting background task.", session_id)
                retry_after = await callback()
                if retry_after is None:
                    break
                delay = retry_after
        except asyncio.CancelledError:
            logger.debug("Idle task for session %s cancelled (activity resumed).", session_id)
        except Exception as e:
            logger.error("Error in idle task for session %s: %s", session_id, e, exc_info=True)
        finally:
            if _idle_tasks.get(session_id) is current_task:
                _idle_tasks.pop(session_id, None)

    current_task = asyncio.create_task(_worker())
    _idle_tasks[session_id] = current_task
    logger.debug("Scheduled idle task for session %s in %s seconds.", session_id, delay_seconds)
