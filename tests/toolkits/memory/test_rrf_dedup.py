"""Test RRF deduplication for dual-channel conversation search.

Ensures that when raw_embedding and summary_embedding queries return
the same document ID, RRF correctly fuses the scores without duplicating
results.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory.config import RetrievalConfig
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever
from myrm_agent_harness.toolkits.memory.types import ConversationMemory, MemorySearchResult, MemoryType


@pytest.fixture
def retriever() -> MemoryRetriever:
    config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0, min_relevance_score=0.0)
    return MemoryRetriever(config)


def test_rrf_dedup_same_id(retriever: MemoryRetriever) -> None:
    """RRF should fuse scores for same document ID, not duplicate."""
    conv = ConversationMemory(
        id="conv_123",
        content="Discussion about Python performance",
        raw_exchange="User: How to optimize Python?\nAI: Use caching.",
        timestamp=datetime.now(UTC),
    )

    raw_result = MemorySearchResult(memory=conv, score=0.9, memory_type=MemoryType.CONVERSATION)
    summary_result = MemorySearchResult(memory=conv, score=0.8, memory_type=MemoryType.CONVERSATION)

    fused = retriever.fuse([[raw_result], [summary_result]], limit=10, query="")

    assert len(fused) == 1, f"Expected 1 result, got {len(fused)}"
    assert fused[0].memory.id == "conv_123"
    assert 0.8 <= fused[0].score <= 1.0


def test_rrf_dedup_different_ids(retriever: MemoryRetriever) -> None:
    """RRF should preserve different document IDs."""
    ts = datetime.now(UTC)
    conv1 = ConversationMemory(id="conv_123", content="Python performance", raw_exchange="...", timestamp=ts)
    conv2 = ConversationMemory(id="conv_456", content="JavaScript async", raw_exchange="...", timestamp=ts)

    raw_result = MemorySearchResult(memory=conv1, score=0.9, memory_type=MemoryType.CONVERSATION)
    summary_result = MemorySearchResult(memory=conv2, score=0.8, memory_type=MemoryType.CONVERSATION)

    fused = retriever.fuse([[raw_result], [summary_result]], limit=10, query="")

    assert len(fused) == 2
    ids = {r.memory.id for r in fused}
    assert ids == {"conv_123", "conv_456"}


def test_rrf_dedup_partial_overlap(retriever: MemoryRetriever) -> None:
    """RRF should handle partial overlap (some same, some different IDs)."""
    ts = datetime.now(UTC)
    conv_shared = ConversationMemory(id="conv_999", content="Shared topic", raw_exchange="...", timestamp=ts)
    conv_unique1 = ConversationMemory(id="conv_111", content="Unique A", raw_exchange="...", timestamp=ts)
    conv_unique2 = ConversationMemory(id="conv_222", content="Unique B", raw_exchange="...", timestamp=ts)

    raw_results = [
        MemorySearchResult(memory=conv_shared, score=0.95, memory_type=MemoryType.CONVERSATION),
        MemorySearchResult(memory=conv_unique1, score=0.85, memory_type=MemoryType.CONVERSATION),
    ]
    summary_results = [
        MemorySearchResult(memory=conv_shared, score=0.90, memory_type=MemoryType.CONVERSATION),
        MemorySearchResult(memory=conv_unique2, score=0.80, memory_type=MemoryType.CONVERSATION),
    ]

    fused = retriever.fuse([raw_results, summary_results], limit=10, query="")

    assert len(fused) == 3
    ids = {r.memory.id for r in fused}
    assert ids == {"conv_999", "conv_111", "conv_222"}

    shared_result = next(r for r in fused if r.memory.id == "conv_999")
    assert 0.90 <= shared_result.score <= 1.0


def test_rrf_dedup_limit_enforcement(retriever: MemoryRetriever) -> None:
    """RRF should respect limit parameter after deduplication."""
    ts = datetime.now(UTC)
    convs = [
        ConversationMemory(id=f"conv_{i}", content=f"Topic {i}", raw_exchange="...", timestamp=ts) for i in range(10)
    ]

    raw_results = [
        MemorySearchResult(memory=c, score=0.9 - i * 0.05, memory_type=MemoryType.CONVERSATION)
        for i, c in enumerate(convs[:7])
    ]
    summary_results = [
        MemorySearchResult(memory=c, score=0.85 - i * 0.05, memory_type=MemoryType.CONVERSATION)
        for i, c in enumerate(convs[4:])
    ]

    fused = retriever.fuse([raw_results, summary_results], limit=5, query="")

    assert len(fused) == 5
