"""Internal approval helpers for MemoryManager.


[INPUT]
- memory.types::{AnyMemory, SemanticMemory, EpisodicMemory, ProceduralMemory, PendingRecord, MemoryType} (POS: memory data models)

[OUTPUT]
- memory_to_pending: AnyMemory → PendingRecord serialization
- pending_to_memory: PendingRecord → AnyMemory deserialization

[POS]
Approval queue helpers. Handles AnyMemory ↔ PendingRecord conversion for the approval
pipeline. Internal only — not part of the public API.
"""

from __future__ import annotations

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
) -> PendingRecord:
    """Serialise an AnyMemory into a PendingRecord for the approval queue.

    ``resolution_action``/``target_memory_id`` describe what approving the record
    should do: persist it as-is (``STORE``), replace the targeted memory with it
    (``CORRECT``), or delete the targeted memory (``DELETE``).
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
    )


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
