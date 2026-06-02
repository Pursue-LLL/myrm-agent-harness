"""Session activity loading for context lifecycle management.

Queries checkpointer thread store to identify active sessions,
enabling session-aware file cleanup strategies.

[INPUT]
- toolkits.browser.checkpoint::ThreadStoreProtocol (POS: Task-level checkpoint/resume module for the browser toolkit. Fully reuses LangGraph Checkpointer's persistence capabilities, only saves incrementally when Session Vault state changes, supports automatic recovery of incomplete tasks on startup with parallel pre-warming.)

[OUTPUT]
- load_session_activity_async: Load active session IDs from checkpointer thread store (a...
- load_session_activity: Load active session IDs from checkpointer thread store.

[POS]
Session activity loading for context lifecycle management.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..checkpoint_protocol import CheckpointerProtocol

logger = logging.getLogger(__name__)


async def load_session_activity_async(
    threshold: datetime,
    checkpointer: CheckpointerProtocol | None = None,
) -> set[str]:
    """Load active session IDs from checkpointer thread store (async version).

    Args:
        threshold: Only return sessions active after this timestamp
        checkpointer: Optional checkpointer instance (injected by business layer).
                      If None, returns empty set (fallback to file-based cleanup).

    Returns:
        Set of active session IDs (thread_ids)

    Note:
        Uses dependency injection pattern for checkpointer access.
        Returns empty set when checkpointer unavailable.

    """
    if checkpointer is None:
        return set()

    try:
        if not hasattr(checkpointer, "thread_store"):
            return set()

        from myrm_agent_harness.toolkits.browser.checkpoint import ThreadStoreProtocol

        thread_store: ThreadStoreProtocol = checkpointer.thread_store

        active_threads = await thread_store.find_active_threads(max_age_hours=None)
        active_ids = {record.thread_id for record in active_threads if record.last_active_at >= threshold}

        return active_ids
    except Exception as exc:
        logger.debug(f"Failed to load session activity (async): {exc}")
        return set()


def load_session_activity(
    threshold: datetime,
    checkpointer: CheckpointerProtocol | None = None,
) -> set[str]:
    """Load active session IDs from checkpointer thread store.

    Args:
        threshold: Only return sessions active after this timestamp
        checkpointer: Optional checkpointer instance (injected by business layer).
                      If None, returns empty set (fallback to file-based cleanup).

    Returns:
        Set of active session IDs (thread_ids)

    Note:
        Synchronous wrapper for session activity loading.
        Returns empty set when checkpointer unavailable or error occurs.

    """
    if checkpointer is None:
        return set()

    try:
        import asyncio

        async def _query_active_sessions() -> set[str]:
            try:
                if not hasattr(checkpointer, "thread_store"):
                    return set()

                from myrm_agent_harness.toolkits.browser.checkpoint import ThreadStore

                thread_store: ThreadStore = checkpointer.thread_store

                active_threads = await thread_store.find_active_threads(max_age_hours=None)
                active_ids = {record.thread_id for record in active_threads if record.last_active_at >= threshold}

                return active_ids
            except Exception as exc:
                logger.debug(f"Failed to query active sessions: {exc}")
                return set()

        # Handle both sync and async contexts safely
        try:
            asyncio.get_running_loop()
            return set()
        except RuntimeError:
            return asyncio.run(_query_active_sessions())
    except Exception as exc:
        logger.debug(f"Failed to load session activity (sync): {exc}")
        return set()
