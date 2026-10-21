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


def test_rrf_deterministic_tie_breaker_multi_hit_priority(retriever: MemoryRetriever) -> None:
    """RRF tie-breaking: identical scores must prioritize items hit by MORE sources."""
    ts = datetime.now(UTC)
    # Item A is hit by Stream 0 (rank 1) and Stream 1 (rank 1)
    # Item B is hit by Stream 0 only (rank 0)
    # With rrf_k=60:
    # Item B score = 1 / (60 + 0 + 1) = 1/61 = 0.01639344...
    # If we construct two items with identical boosted score, multi-hit must win.
    conv_a = ConversationMemory(id="conv_a", content="Multi hit candidate", raw_exchange="...", timestamp=ts)
    conv_b = ConversationMemory(id="conv_b", content="Single hit candidate", raw_exchange="...", timestamp=ts)

    # Let's craft scores such that mid A has hit_count=2, mid B has hit_count=1
    # We can pass custom result lists
    stream_vector = [
        MemorySearchResult(memory=conv_a, score=0.8, memory_type=MemoryType.CONVERSATION),
        MemorySearchResult(memory=conv_b, score=0.8, memory_type=MemoryType.CONVERSATION),
    ]
    stream_fts = [
        MemorySearchResult(memory=conv_a, score=0.8, memory_type=MemoryType.CONVERSATION),
    ]

    fused = retriever.fuse(
        [stream_vector, stream_fts],
        limit=10,
        query="",
        source_names=["vector", "fts"],
    )

    # conv_a is hit by 2 streams, conv_b by 1 stream. conv_a must be ranked #0
    assert len(fused) == 2
    assert fused[0].memory.id == "conv_a"
    assert fused[1].memory.id == "conv_b"

    # Verify recall_debug trace metadata
    trace_a = fused[0].recall_debug
    assert trace_a is not None
    assert trace_a.hit_count == 2
    assert len(trace_a.hit_sources) == 2
    assert trace_a.hit_sources[0].source == "vector"
    assert trace_a.hit_sources[1].source == "fts"

    trace_b = fused[1].recall_debug
    assert trace_b is not None
    assert trace_b.hit_count == 1
    assert len(trace_b.hit_sources) == 1
    assert trace_b.hit_sources[0].source == "vector"


def test_rrf_deterministic_tie_breaker_id_alphabetical(retriever: MemoryRetriever) -> None:
    """When scores AND hit counts are identical, sort strictly by ID alphabetically ascending."""
    ts = datetime.now(UTC)
    # conv_z and conv_a with exact same rank in single stream
    conv_z = ConversationMemory(id="conv_z", content="Content Z", raw_exchange="...", timestamp=ts)
    conv_a = ConversationMemory(id="conv_a", content="Content A", raw_exchange="...", timestamp=ts)

    # Both are at rank 0 in separate single-item streams
    stream_1 = [MemorySearchResult(memory=conv_z, score=0.9, memory_type=MemoryType.CONVERSATION)]
    stream_2 = [MemorySearchResult(memory=conv_a, score=0.9, memory_type=MemoryType.CONVERSATION)]

    # Both receive identical 1.0 / (60 + 0 + 1) RRF score, both hit_count=1
    fused = retriever.fuse([stream_1, stream_2], limit=10, query="")
    assert len(fused) == 2

    # Alphabetical order: 'conv_a' must strictly precede 'conv_z'
    assert fused[0].memory.id == "conv_a"
    assert fused[1].memory.id == "conv_z"
    assert fused[0].recall_debug is not None
    assert fused[0].recall_debug.tie_break_rank == 0
    assert fused[1].recall_debug is not None
    assert fused[1].recall_debug.tie_break_rank == 1


def test_rrf_repeated_runs_zero_jitter(retriever: MemoryRetriever) -> None:
    """Validate 100% deterministic ranking across 50 repeated executions without flapping."""
    ts = datetime.now(UTC)
    candidates = [
        ConversationMemory(id=f"cand_{i:02d}", content=f"Memory {i}", raw_exchange="...", timestamp=ts)
        for i in range(20)
    ]

    list_0 = [MemorySearchResult(memory=c, score=0.8, memory_type=MemoryType.CONVERSATION) for c in candidates[:15]]
    list_1 = [MemorySearchResult(memory=c, score=0.8, memory_type=MemoryType.CONVERSATION) for c in candidates[5:]]

    first_run_ids = [r.memory.id for r in retriever.fuse([list_0, list_1], limit=10, query="")]

    for _ in range(50):
        run_ids = [r.memory.id for r in retriever.fuse([list_0, list_1], limit=10, query="")]
        assert run_ids == first_run_ids, "RRF fusion order flapped! Order must be 100% deterministic."

