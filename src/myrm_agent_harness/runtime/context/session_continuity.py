"""Session continuity — LangGraph checkpoint alignment with persisted chat history.

[INPUT]
- langchain_core.messages::BaseMessage (POS: LangChain message list)
- langgraph.checkpoint.base::BaseCheckpointSaver (POS: LangGraph checkpointer)

[OUTPUT]
- resolve_thread_ids: canonical thread_id aliases for a chat session
- ContinuitySyncError: raised when checkpoint sync is incomplete
- sync_checkpoint_messages: rewrite checkpoint messages to match DB history (fail-closed)

[POS]
Framework-neutral SSOT for rewind/truncate/edit-resend checkpoint consistency.
Server loads DB history and converts to BaseMessage before calling here.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage
    from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointMetadata

logger = logging.getLogger(__name__)


class ContinuitySyncError(Exception):
    """Raised when checkpoint message sync did not complete for all thread aliases."""


def resolve_thread_ids(chat_id: str) -> tuple[str, str]:
    """Return both thread_id aliases used by the server agent runtime."""
    return chat_id, f"chat_{chat_id}"


async def sync_checkpoint_messages(
    checkpointer: BaseCheckpointSaver,
    chat_id: str,
    messages: list[BaseMessage],
) -> int:
    """Rewrite LangGraph checkpoint message channels for all session thread aliases.

    When ``messages`` is empty, checkpoint threads are deleted. Otherwise each
    thread receives an updated checkpoint whose ``messages`` channel matches
    ``messages`` while preserving other channel values when possible.

    Returns:
        Number of thread aliases successfully updated or deleted.
    """
    thread_ids = resolve_thread_ids(chat_id)
    expected = len(thread_ids)
    if not messages:
        updated = 0
        for thread_id in thread_ids:
            try:
                await checkpointer.adelete_thread(thread_id)
                updated += 1
            except Exception as exc:
                logger.warning(
                    "Failed to delete checkpoint thread %s for chat %s: %s",
                    thread_id,
                    chat_id,
                    exc,
                )
        if updated != expected:
            raise ContinuitySyncError(
                f"Deleted {updated}/{expected} checkpoint threads for chat {chat_id}",
            )
        return updated

    now_iso = datetime.now(tz=UTC).isoformat()
    checkpoint_id = str(uuid4())
    updated = 0

    for thread_id in thread_ids:
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        metadata: CheckpointMetadata = {}
        checkpoint: Checkpoint
        try:
            existing = await checkpointer.aget_tuple(config)
            if existing and existing.checkpoint:
                metadata = existing.metadata or {}
                channel_values = dict(existing.checkpoint.get("channel_values") or {})
                channel_values["messages"] = list(messages)
                prior_updated = existing.checkpoint.get("updated_channels") or []
                checkpoint = {
                    **existing.checkpoint,
                    "id": checkpoint_id,
                    "ts": now_iso,
                    "channel_values": channel_values,
                    "updated_channels": list({*prior_updated, "messages"}),
                }
            else:
                checkpoint = {
                    "v": 1,
                    "id": checkpoint_id,
                    "ts": now_iso,
                    "channel_values": {"messages": list(messages)},
                    "channel_versions": {"messages": 1},
                    "versions_seen": {},
                    "updated_channels": ["messages"],
                }
            await checkpointer.aput(config, checkpoint, metadata, {})
            updated += 1
        except Exception as exc:
            logger.warning(
                "Failed to sync checkpoint messages for thread %s (chat=%s): %s",
                thread_id,
                chat_id,
                exc,
            )
    if updated != expected:
        raise ContinuitySyncError(
            f"Synced {updated}/{expected} checkpoint threads for chat {chat_id}",
        )
    return updated
