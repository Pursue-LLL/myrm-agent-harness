"""Read tracking for context files.

Records a file access whenever a context file is read inside an agent session, so the
cleanup pass keeps files that are still being used.

[INPUT]
- runtime.paths.execution_paths::is_context_path (POS: Whether a path lies under the context root.)
- agent.context_management.infra.session_lock::get_current_chat_id (POS: Chat id of the running session.)
- runtime.context.file_access_tracker::get_file_access_tracker (POS: Shared access tracker.)

[OUTPUT]
- track_context_file_access_if_needed: Record a read of a context file for the current session.

[POS]
Bridge from file readers to the context file access tracker.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING

from myrm_agent_harness.runtime.paths.execution_paths import is_context_path

if TYPE_CHECKING:
    from myrm_agent_harness.runtime.context.file_access_tracker import FileAccessTracker

logger = logging.getLogger(__name__)

# Cached function references to avoid repeated imports
_cached_get_current_chat_id: Callable[[], str | None] | None = None
_cached_get_file_access_tracker: Callable[[], Coroutine[None, None, FileAccessTracker]] | None = None


async def track_context_file_access_if_needed(file_path: str) -> None:
    """Track context file access if in agent session context.

    Automatically records file access to FileAccessTracker when:
    1. File is a context file (in /persistent/.context/)
    2. Currently in an agent session (has session_id)

    Args:
        file_path: File path to potentially track

    Note:
        Fails silently if tracking is not available or not in session context.
        This ensures file operations work even without tracking infrastructure.

    """
    global _cached_get_current_chat_id, _cached_get_file_access_tracker

    if not is_context_path(file_path):
        return

    try:
        # Lazy import and cache
        if _cached_get_current_chat_id is None:
            from myrm_agent_harness.agent.context_management.infra.session_lock import (
                get_current_chat_id,
            )

            _cached_get_current_chat_id = get_current_chat_id

        chat_id = _cached_get_current_chat_id()
        if not chat_id:
            return

        if _cached_get_file_access_tracker is None:
            from myrm_agent_harness.runtime.context.file_access_tracker import (
                get_file_access_tracker,
            )

            _cached_get_file_access_tracker = get_file_access_tracker

        tracker = await _cached_get_file_access_tracker()
        await tracker.record_access(file_path, session_id=chat_id)
    except Exception as exc:
        logger.debug(f"Failed to track context file access for {file_path}: {exc}")
