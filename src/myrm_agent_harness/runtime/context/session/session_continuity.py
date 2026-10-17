"""Session continuity — the checkpoint threads of a chat session.

[INPUT]
- langgraph.checkpoint.base::BaseCheckpointSaver (POS: LangGraph checkpointer)

[OUTPUT]
- HISTORY_MODE_CONTEXT_KEY: run-context key a caller sets to declare who owns the thread
- HistoryMode: ``append`` | ``continue`` | ``replace``
- resolve_thread_ids: canonical thread_id aliases for a chat session
- CheckpointClearError: raised when a chat's checkpoint threads were not all deleted
- clear_checkpoint_threads: delete every checkpoint thread of a chat session (fail-closed)

[POS]
Framework-neutral SSOT for what a chat session's checkpoint threads are called and how they are
dropped. The persisted chat history is the authority on what was said; a thread that no longer
matches it is cleared here, and the next run rebuilds it from that history. ``HistoryMode`` is how
a caller tells a run which of the two owns the conversation (resolved in
``agent/_internals/turn_history.py``): ``continue`` extends the thread and sends only the new
message, ``replace`` clears the thread and rebuilds it from the caller's history, ``append`` (the
default) feeds the caller's history on top of whatever the thread holds.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)

HISTORY_MODE_CONTEXT_KEY = "history_mode"

HistoryMode = Literal["append", "continue", "replace"]


class CheckpointClearError(Exception):
    """Raised when not every checkpoint thread alias of a chat was deleted."""


def resolve_thread_ids(chat_id: str) -> tuple[str, str]:
    """Return both thread_id aliases used by the server agent runtime."""
    return chat_id, f"chat_{chat_id}"


async def clear_checkpoint_threads(checkpointer: BaseCheckpointSaver[str], chat_id: str) -> int:
    """Delete the checkpoint threads of every session alias of ``chat_id``.

    Every alias is attempted even when an earlier one fails, so one broken thread never leaves
    the others stale.

    Returns:
        Number of thread aliases deleted.

    Raises:
        CheckpointClearError: not every alias could be deleted.
    """
    thread_ids = resolve_thread_ids(chat_id)
    deleted = 0
    for thread_id in thread_ids:
        try:
            await checkpointer.adelete_thread(thread_id)
            deleted += 1
        except Exception as exc:
            logger.warning(
                "Failed to delete checkpoint thread %s for chat %s: %s",
                thread_id,
                chat_id,
                exc,
            )
    if deleted != len(thread_ids):
        raise CheckpointClearError(f"Deleted {deleted}/{len(thread_ids)} checkpoint threads for chat {chat_id}")
    return deleted
