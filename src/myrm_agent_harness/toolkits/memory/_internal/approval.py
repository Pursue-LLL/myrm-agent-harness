"""Internal approval helpers for MemoryManager.


[INPUT]
- memory.types::{AnyMemory, SemanticMemory, EpisodicMemory, ProceduralMemory, PendingRecord, MemoryType} (POS: memory data models)
- memory._internal.storage::InvalidPendingEditError (POS: memory error hierarchy)

[OUTPUT]
- memory_to_pending: AnyMemory → PendingRecord serialization
- pending_to_memory: PendingRecord → AnyMemory deserialization
- apply_edited_content: reviewer-edited wording applied to a PendingRecord

[POS]
Approval queue helpers. Handles AnyMemory ↔ PendingRecord conversion for the approval
pipeline. Internal only — not part of the public API.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory._internal.storage import InvalidPendingEditError
from myrm_agent_harness.toolkits.memory.types import (
    AnyMemory,
    ConversationMemory,
    EpisodicMemory,
    MemoryType,
    PendingRecord,
    PendingResolutionAction,
    ProceduralMemory,
    SemanticMemory,
)


def memory_to_pending(
    memory: AnyMemory,
    *,
    resolution_action: PendingResolutionAction = PendingResolutionAction.STORE,
    target_memory_id: str | None = None,
    target_content: str | None = None,
) -> PendingRecord:
    """Serialise an AnyMemory into a PendingRecord for the approval queue.

    ``resolution_action``/``target_memory_id`` describe what approving the record
    should do: persist it as-is (``STORE``), replace the targeted memory with it
    (``CORRECT``), or retire the targeted memory (``DELETE``). ``target_content``
    is the reviewed memory's content, kept so the approval surface can show the
    user exactly which memory will be replaced or removed.
    """
    data = memory.model_dump(exclude={"embedding"}, mode="json")
    return PendingRecord(
        id=memory.id,
        memory_type=MemoryType(memory.memory_type),
        content=memory.content,
        memory_data=data,
        source_chat_id=getattr(memory, "source_chat_id", None),
        source_message_id=getattr(memory, "source_message_id", None),
        resolution_action=resolution_action,
        target_memory_id=target_memory_id,
        target_content=target_content,
    )


def apply_edited_content(record: PendingRecord, edited_content: str) -> PendingRecord:
    """Return ``record`` carrying the reviewer's reworded text.

    Both ``content`` (used by ``CORRECT``) and ``memory_data["content"]`` (used to
    rebuild the memory for ``STORE``) are updated so every approval path persists
    the same wording. Profile entries and ``DELETE`` proposals persist no free
    text, so an edit there is an error rather than a silently dropped change.

    Raises:
        InvalidPendingEditError: the edit is blank or the proposal has no editable text.
    """
    content = edited_content.strip()
    if not content:
        raise InvalidPendingEditError("Edited content must not be empty")
    if record.memory_type == MemoryType.PROFILE or record.resolution_action == PendingResolutionAction.DELETE:
        raise InvalidPendingEditError("This proposal has no editable content")
    if content == record.content:
        return record
    return record.model_copy(update={"content": content, "memory_data": {**record.memory_data, "content": content}})


def pending_to_memory(record: PendingRecord) -> AnyMemory:
    """Reconstruct an AnyMemory from a PendingRecord."""
    data = dict(record.memory_data)
    mt = record.memory_type
    if mt == MemoryType.SEMANTIC:
        return SemanticMemory(**data)
    if mt == MemoryType.EPISODIC:
        return EpisodicMemory(**data)
    if mt == MemoryType.PROCEDURAL:
        return ProceduralMemory(**data)
    if mt == MemoryType.CONVERSATION:
        return ConversationMemory(**data)
    raise ValueError(f"Cannot reconstruct memory from type: {mt}")
