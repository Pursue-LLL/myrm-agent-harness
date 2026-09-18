"""Checkpoint read access — the single place that knows the checkpoint payload shape.

[INPUT]
- langgraph.checkpoint.base::BaseCheckpointSaver (``aget()`` returns a dict-typed Checkpoint)

[OUTPUT]
- read_checkpoint_messages: raw ``channel_values["messages"]`` payload for a thread
  (empty list when the checkpointer, the checkpoint, or the channel is unavailable).

[POS]
Read-side counterpart to factory.py, which owns checkpointer creation and cleanup.
The langgraph ``Checkpoint`` payload is a TypedDict, so it is a plain ``dict`` at
runtime: field access must go through mapping lookups. Centralizing that here keeps
every consumer (context-budget breakdown, checkpoint-state extraction) from
re-deriving it and silently degrading to empty results.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)


async def read_checkpoint_messages(
    checkpointer: object | None,
    thread_id: str,
) -> list[object]:
    """Read the raw messages channel of ``thread_id``'s checkpoint.

    Returns an empty list when there is no checkpointer, no checkpoint for the
    thread, or an unreadable payload. Read failures are logged and degrade to an
    empty result rather than aborting the agent run.

    The payload is returned untyped; callers narrow to ``BaseMessage`` or
    serialize it, because each consumer needs a different projection.
    """
    if checkpointer is None or not callable(getattr(checkpointer, "aget", None)):
        return []

    config = {"configurable": {"thread_id": thread_id}}
    try:
        checkpoint = await checkpointer.aget(config)  # type: ignore[attr-defined]
    except Exception:
        logger.warning(
            "Failed to read checkpoint for thread %s", thread_id, exc_info=True
        )
        return []

    if not isinstance(checkpoint, Mapping):
        return []

    channel_values = checkpoint.get("channel_values")
    if not isinstance(channel_values, Mapping):
        return []

    messages = channel_values.get("messages")
    return list(messages) if isinstance(messages, list) else []
