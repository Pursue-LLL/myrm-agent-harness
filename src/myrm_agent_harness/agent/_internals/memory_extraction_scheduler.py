"""Per-chat coalescing for background memory auto-extraction tasks.

[INPUT]
- agent.skill_agent.context::track_background_task

[OUTPUT]
- schedule_chat_memory_extraction: cancel superseded in-flight extraction for the same chat and run the latest.

[POS]
Prevents overlapping auto_extract_memories runs when users send turns faster than extraction completes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from myrm_agent_harness.agent.skill_agent.context import track_background_task

logger = logging.getLogger(__name__)

_chat_extract_tasks: dict[str, asyncio.Task[None]] = {}


def schedule_chat_memory_extraction(
    chat_id: str | None,
    run_extraction: Callable[[], Awaitable[None]],
) -> None:
    normalized = (chat_id or "").strip()
    if not normalized:
        return

    previous = _chat_extract_tasks.get(normalized)
    if previous is not None and not previous.done():
        previous.cancel()

    async def _runner() -> None:
        try:
            await run_extraction()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Background memory extraction failed for chat %s: %s", normalized, exc)

    task = asyncio.create_task(_runner(), name=f"memory_extract_{normalized[:24]}")
    _chat_extract_tasks[normalized] = task
    track_background_task(task)
