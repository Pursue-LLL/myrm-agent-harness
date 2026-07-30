"""Tests for wiki vs memory write boundary helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory
from myrm_agent_harness.toolkits.memory.wiki_memory_boundary import (
    WIKI_MEMORY_SAVE_MAX_CHARS,
    WIKI_MEMORY_SAVE_MIN_HEADINGS,
    filter_wiki_document_vector_memories,
    get_wiki_memory_save_rejection_count,
    looks_like_wiki_document,
    record_wiki_memory_save_rejection,
    reset_wiki_memory_save_rejection_count,
)


def test_looks_like_wiki_document_by_length() -> None:
    assert not looks_like_wiki_document("short fact")
    assert looks_like_wiki_document("a" * WIKI_MEMORY_SAVE_MAX_CHARS)


def test_looks_like_wiki_document_by_headings() -> None:
    two_headings = "## Section 1\nBody\n## Section 2\nBody"
    assert not looks_like_wiki_document(two_headings)
    content = "\n".join(f"## Section {idx}\nBody {idx}" for idx in range(WIKI_MEMORY_SAVE_MIN_HEADINGS))
    assert looks_like_wiki_document(content)
    assert not looks_like_wiki_document("## One heading only")


def test_rejection_counter() -> None:
    reset_wiki_memory_save_rejection_count()
    assert get_wiki_memory_save_rejection_count() == 0
    assert record_wiki_memory_save_rejection() == 1
    assert get_wiki_memory_save_rejection_count() == 1
    reset_wiki_memory_save_rejection_count()


def test_filter_drops_long_semantic_when_enabled() -> None:
    long_semantic = SemanticMemory(content="x" * WIKI_MEMORY_SAVE_MAX_CHARS)
    short_semantic = SemanticMemory(content="User prefers tea")
    kept, dropped = filter_wiki_document_vector_memories(
        [long_semantic, short_semantic],
        enabled=True,
    )
    assert dropped == 1
    assert kept == [short_semantic]


def test_filter_keeps_all_when_disabled() -> None:
    long_semantic = SemanticMemory(content="x" * WIKI_MEMORY_SAVE_MAX_CHARS)
    kept, dropped = filter_wiki_document_vector_memories([long_semantic], enabled=False)
    assert dropped == 0
    assert kept == [long_semantic]


def test_filter_drops_long_episodic_only() -> None:
    long_event = EpisodicMemory(content="e" * WIKI_MEMORY_SAVE_MAX_CHARS, event_type="user_action")
    kept, dropped = filter_wiki_document_vector_memories([long_event], enabled=True)
    assert dropped == 1
    assert kept == []


@pytest.mark.asyncio
async def test_persist_extracted_memories_applies_wiki_filter() -> None:
    from myrm_agent_harness.agent._internals.memory_extraction import persist_extracted_memories

    long_semantic = SemanticMemory(content="x" * WIKI_MEMORY_SAVE_MAX_CHARS)
    short_semantic = SemanticMemory(content="User prefers tea")

    mock_manager = MagicMock()
    mock_manager.store_batch = AsyncMock(return_value=[short_semantic])

    with patch(
        "myrm_agent_harness.toolkits.memory.strategies.extractor.MemoryExtractor"
    ) as mock_cls:
        mock_extractor = MagicMock()
        mock_extractor.to_concrete_memories.return_value = [long_semantic, short_semantic]
        mock_cls.return_value = mock_extractor

        count = await persist_extracted_memories(
            [MagicMock()],
            mock_manager,
            "chat-1",
            wiki_boundary_enabled=True,
        )

    assert count == 1
    stored_batch = mock_manager.store_batch.call_args[0][0]
    assert stored_batch == [short_semantic]
