"""Message-level working memory marks metadata contract and inspection primitives.

Provides fine-grained semantic categorization (hints, scratchpads, raw tool outputs,
pinned rules, trap shields) to decouple memory storage from compression strategies.

[INPUT]
- langchain_core.messages::BaseMessage (POS: message contract)

[OUTPUT]
- WorkingMemoryMark: StrEnum of standard mark names
- IMMUNE_MARKS: frozenset of marks protected from eviction
- get_message_marks, with_message_marks, has_message_marks, is_eviction_immune

[POS]
Core memory abstraction layer for message metadata tags, aligned with AgentScope MemoryBase
contract while maintaining zero-LLM overhead and Prompt Cache safety.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage


class WorkingMemoryMark(StrEnum):
    """Standard marks used across working memory and context management pipelines."""

    HINT = "hint"  # Transient single-turn guidance/reflection (evicted after turn)
    SCRATCHPAD = "scratchpad"  # Intermediate working notes/drafts (evicted when subtask resolves)
    TOOL_RAW_OUTPUT = "tool_raw_output"  # High-volume raw tool results (offloaded & compacted)
    PINNED = "pinned"  # Critical business constraints/rules (immune from eviction/summarization)
    TRAP_SHIELD = "trap_shield"  # Error avoidance rules (immune from eviction)


IMMUNE_MARKS: frozenset[str] = frozenset(
    {
        WorkingMemoryMark.PINNED.value,
        WorkingMemoryMark.TRAP_SHIELD.value,
        "keep",
        "pinned",
        "trap_shield",
    }
)

MARKS_METADATA_KEY = "marks"


def get_message_marks(message: BaseMessage) -> set[str]:
    """Extract semantic marks set from a message's additional_kwargs."""
    if not hasattr(message, "additional_kwargs") or not isinstance(message.additional_kwargs, dict):
        return set()
    raw_marks = message.additional_kwargs.get(MARKS_METADATA_KEY)
    if isinstance(raw_marks, (set, list, tuple)):
        return {str(m) for m in raw_marks if m}
    if isinstance(raw_marks, str) and raw_marks:
        return {raw_marks}
    return set()


def with_message_marks(message: BaseMessage, *marks: str | WorkingMemoryMark) -> BaseMessage:
    """Return message with specified marks merged into its additional_kwargs (in-place & returned)."""
    if not hasattr(message, "additional_kwargs") or not isinstance(message.additional_kwargs, dict):
        message.additional_kwargs = {}

    current_marks = get_message_marks(message)
    for m in marks:
        val = m.value if isinstance(m, WorkingMemoryMark) else str(m)
        if val:
            current_marks.add(val)

    message.additional_kwargs[MARKS_METADATA_KEY] = sorted(current_marks)
    return message


def has_message_marks(message: BaseMessage, *marks: str | WorkingMemoryMark) -> bool:
    """Check if message carries any of the specified marks."""
    if not marks:
        return False
    msg_marks = get_message_marks(message)
    target_values = {m.value if isinstance(m, WorkingMemoryMark) else str(m) for m in marks}
    return bool(msg_marks & target_values)


def is_eviction_immune(message: BaseMessage) -> bool:
    """Check if message is strictly immune from selective eviction or destructive compaction."""
    msg_marks = get_message_marks(message)
    return bool(msg_marks & IMMUNE_MARKS)
