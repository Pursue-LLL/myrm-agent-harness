"""Tests for the approval queue serialisation helpers.

Locks the ``AnyMemory <-> PendingRecord`` contract, including the
``resolution_action``/``target_memory_id``/``target_content`` metadata that the
approval dispatcher and the review UI depend on.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory._internal.approval import (
    apply_edited_content,
    memory_to_pending,
    pending_to_memory,
)
from myrm_agent_harness.toolkits.memory.types import (
    ConversationMemory,
    EpisodicMemory,
    MemoryType,
    PendingRecord,
    PendingResolutionAction,
    ProceduralMemory,
    SemanticMemory,
)


def test_memory_to_pending_defaults_to_store() -> None:
    memory = SemanticMemory(id="mem-1", content="User prefers Rust", confidence=0.8)

    record = memory_to_pending(memory)

    assert record.id == "mem-1"
    assert record.memory_type == MemoryType.SEMANTIC
    assert record.content == "User prefers Rust"
    assert record.resolution_action == PendingResolutionAction.STORE
    assert record.target_memory_id is None
    assert record.target_content is None
    # Embeddings are large and never needed for approval reconstruction.
    assert "embedding" not in record.memory_data


def test_memory_to_pending_carries_correction_target() -> None:
    memory = SemanticMemory(id="mem-2", content="User now works at Google")

    record = memory_to_pending(
        memory,
        resolution_action=PendingResolutionAction.CORRECT,
        target_memory_id="mem-old",
        target_content="User works at ByteDance",
    )

    assert record.resolution_action == PendingResolutionAction.CORRECT
    assert record.target_memory_id == "mem-old"
    assert record.target_content == "User works at ByteDance"


def test_pending_to_memory_round_trips_semantic() -> None:
    original = SemanticMemory(id="mem-3", content="fact", confidence=0.7, importance=0.4)

    restored = pending_to_memory(memory_to_pending(original))

    assert isinstance(restored, SemanticMemory)
    assert restored.id == original.id
    assert restored.content == original.content
    assert restored.confidence == original.confidence


def test_pending_to_memory_rejects_unsupported_type() -> None:
    record = PendingRecord(
        id="p-1",
        memory_type=MemoryType.PROFILE,
        content="timezone: UTC",
        memory_data={},
    )

    with pytest.raises(ValueError, match="Cannot reconstruct memory from type"):
        pending_to_memory(record)


def test_pending_to_memory_reconstructs_episodic() -> None:
    record = PendingRecord(
        id="e-1",
        memory_type=MemoryType.EPISODIC,
        content="User fixed a login bug",
        memory_data={"content": "User fixed a login bug"},
    )

    restored = pending_to_memory(record)

    assert isinstance(restored, EpisodicMemory)
    assert restored.content == "User fixed a login bug"


def test_pending_to_memory_reconstructs_procedural() -> None:
    record = PendingRecord(
        id="pr-1",
        memory_type=MemoryType.PROCEDURAL,
        content="Always run tests before commit",
        memory_data={"trigger": "before commit", "action": "run tests"},
    )

    restored = pending_to_memory(record)

    assert isinstance(restored, ProceduralMemory)
    assert restored.action == "run tests"


def test_pending_to_memory_reconstructs_conversation() -> None:
    record = PendingRecord(
        id="c-1",
        memory_type=MemoryType.CONVERSATION,
        content="hello there",
        memory_data={"content": "hello there", "raw_exchange": "user: hi"},
    )

    restored = pending_to_memory(record)

    assert isinstance(restored, ConversationMemory)
    assert restored.content == "hello there"


def test_apply_edited_content_updates_content_and_rebuild_source() -> None:
    record = memory_to_pending(SemanticMemory(id="mem-1", content="Original"))

    edited = apply_edited_content(record, "  Reworded  ")

    assert edited.content == "Reworded"
    assert edited.memory_data["content"] == "Reworded"
    assert pending_to_memory(edited).content == "Reworded"
    # The queued record itself is never mutated.
    assert record.content == "Original"


def test_apply_edited_content_unchanged_text_returns_same_record() -> None:
    record = memory_to_pending(SemanticMemory(id="mem-1", content="Original"))

    assert apply_edited_content(record, " Original ") is record


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_apply_edited_content_rejects_blank(blank: str) -> None:
    record = memory_to_pending(SemanticMemory(id="mem-1", content="Original"))

    with pytest.raises(ValueError, match="must not be empty"):
        apply_edited_content(record, blank)


def test_apply_edited_content_rejects_proposals_without_text() -> None:
    forget = memory_to_pending(
        SemanticMemory(id="mem-1", content="Stale"),
        resolution_action=PendingResolutionAction.DELETE,
        target_memory_id="mem-old",
    )
    profile = PendingRecord(
        id="p-1", memory_type=MemoryType.PROFILE, content="tz: UTC", memory_data={"key": "tz", "value": "UTC"}
    )

    for record in (forget, profile):
        with pytest.raises(ValueError, match="no editable content"):
            apply_edited_content(record, "anything")
