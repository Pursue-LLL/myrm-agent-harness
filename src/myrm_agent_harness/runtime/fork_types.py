"""Conversation fork types and structures.

 Self-update prompt: Once updated, must sync:
1. This file's INPUT/OUTPUT/POS comments

[INPUT]

[OUTPUT]
- ForkInfo: Fork relationship metadata (parent_thread_id, fork_checkpoint_id, fork_message_index)

[POS]
Defines data structures for conversation forking feature. Used by business layer
to track fork relationships and by frontend to display fork lineage.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ForkInfo:
    """Conversation fork metadata.

    Tracks relationship between parent conversation and forked conversation.
    Immutable to prevent accidental modification of fork history.

    Attributes:
        parent_thread_id: Parent conversation thread ID (LangGraph thread_id)
        parent_chat_id: Parent conversation chat ID (business layer ID)
        fork_checkpoint_id: Checkpoint ID that was forked from
        fork_message_index: Message index where fork occurred (0-based, for UI)

    Example:
        >>> fork_info = ForkInfo(
        ...     parent_thread_id="thread-123",
        ...     parent_chat_id="chat-123",
        ...     fork_checkpoint_id="checkpoint-abc",
        ...     fork_message_index=5,
        ... )
        >>> print(f"Forked from message #{fork_info.fork_message_index}")

    """

    parent_thread_id: str
    parent_chat_id: str
    fork_checkpoint_id: str
    fork_message_index: int
