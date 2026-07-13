"""Integration test: full search → bump_access_counts → vector upsert chain.

No mock on bump_access_counts — exercises the real fire-and-forget path.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._manager import MemoryManager
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemorySearchResult,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
)


def _build_manager(*, search_results: list[MemorySearchResult]) -> tuple[MemoryManager, AsyncMock, AsyncMock]:
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    relational = AsyncMock()
    embedding = AsyncMock()
    manager = MemoryManager(
        config, user_id="u1", vector=vector, relational=relational, embedding=embedding
    )
    mock_search_svc = AsyncMock()
    mock_search_svc.search.return_value = search_results
    manager._search_service = mock_search_svc
    return manager, vector, relational


@pytest.mark.asyncio
async def test_full_chain_semantic_access_count_persisted():
    """search() → real bump_access_counts → vector.upsert called with updated memory."""
    mem = SemanticMemory(id="s1", content="user likes coffee", metadata={}, access_count=5)
    result = MemorySearchResult(memory=mem, score=0.9, memory_type=MemoryType.SEMANTIC)
    manager, vector, _ = _build_manager(search_results=[result])

    await manager.search("coffee preference")
    await asyncio.sleep(0.1)

    assert mem.access_count == 6
    assert mem.last_accessed_at is not None
    assert vector.upsert.await_count == 1
    upsert_args = vector.upsert.call_args[0]
    assert "semantic" in upsert_args[0]


@pytest.mark.asyncio
async def test_full_chain_episodic_access_count_persisted():
    """Episodic memory access count bump through real chain."""
    mem = EpisodicMemory(id="e1", content="user asked about weather", metadata={}, access_count=0)
    result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.EPISODIC)
    manager, vector, _ = _build_manager(search_results=[result])

    await manager.search("weather event")
    await asyncio.sleep(0.1)

    assert mem.access_count == 1
    assert vector.upsert.await_count == 1
    upsert_args = vector.upsert.call_args[0]
    assert "episodic" in upsert_args[0]


@pytest.mark.asyncio
async def test_full_chain_procedural_access_count_persisted():
    """Procedural memory access count bump through relational store."""
    mem = ProceduralMemory(
        id="p1", content="always respond in Chinese", trigger="any message", action="respond in zh",
        source="agent_self", access_count=3,
    )
    result = MemorySearchResult(memory=mem, score=0.7, memory_type=MemoryType.PROCEDURAL)
    manager, _, relational = _build_manager(search_results=[result])

    await manager.search("language preference")
    await asyncio.sleep(0.1)

    assert mem.access_count == 4
    assert mem.last_accessed_at is not None
    relational.update_rule.assert_awaited_once_with(mem.id, mem)


@pytest.mark.asyncio
async def test_full_chain_track_access_false_no_side_effects():
    """track_access=False must not produce any write side effects."""
    mem = SemanticMemory(id="s1", content="data", metadata={}, access_count=0)
    result = MemorySearchResult(memory=mem, score=0.9, memory_type=MemoryType.SEMANTIC)
    manager, vector, relational = _build_manager(search_results=[result])

    await manager.search("data", track_access=False)
    await asyncio.sleep(0.1)

    assert mem.access_count == 0
    vector.upsert.assert_not_awaited()
    relational.update_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_chain_mixed_results_all_types_tracked():
    """Mixed results: each type gets its access_count bumped correctly."""
    sem = SemanticMemory(id="s1", content="fact", metadata={}, access_count=0)
    epi = EpisodicMemory(id="e1", content="event", metadata={}, access_count=2)
    proc = ProceduralMemory(
        id="p1", content="rule", trigger="t", action="a", source="agent_self", access_count=10
    )
    results = [
        MemorySearchResult(memory=sem, score=0.9, memory_type=MemoryType.SEMANTIC),
        MemorySearchResult(memory=epi, score=0.8, memory_type=MemoryType.EPISODIC),
        MemorySearchResult(memory=proc, score=0.7, memory_type=MemoryType.PROCEDURAL),
    ]
    manager, vector, relational = _build_manager(search_results=results)

    await manager.search("mixed query")
    await asyncio.sleep(0.1)

    assert sem.access_count == 1
    assert epi.access_count == 3
    assert proc.access_count == 11
    assert vector.upsert.await_count == 2
    relational.update_rule.assert_awaited_once()


@pytest.mark.asyncio
async def test_full_chain_no_vector_store_does_not_crash():
    """When vector store is None, track_access=True should gracefully skip."""
    config = MemoryConfig(embedding_model="test")
    embedding = AsyncMock()
    manager = MemoryManager(config, user_id="u1", vector=None, embedding=embedding)
    mock_search_svc = AsyncMock()
    mem = SemanticMemory(id="s1", content="test", metadata={})
    mock_search_svc.search.return_value = [
        MemorySearchResult(memory=mem, score=0.9, memory_type=MemoryType.SEMANTIC)
    ]
    manager._search_service = mock_search_svc

    results = await manager.search("test", track_access=True)
    await asyncio.sleep(0.1)

    assert len(results) == 1
    assert mem.access_count == 0


@pytest.mark.asyncio
async def test_full_chain_concurrent_searches():
    """Concurrent searches on same memory should not crash (eventual consistency)."""
    mem = SemanticMemory(id="s1", content="shared memory", metadata={}, access_count=0)
    result = MemorySearchResult(memory=mem, score=0.9, memory_type=MemoryType.SEMANTIC)
    manager, vector, _ = _build_manager(search_results=[result])

    await asyncio.gather(
        manager.search("query1"),
        manager.search("query2"),
        manager.search("query3"),
    )
    await asyncio.sleep(0.2)

    assert mem.access_count == 3
    assert vector.upsert.await_count == 3


@pytest.mark.asyncio
async def test_full_chain_large_result_set():
    """Large result set (limit=10) should batch upsert correctly."""
    memories = [
        SemanticMemory(id=f"s{i}", content=f"fact {i}", metadata={}, access_count=0)
        for i in range(10)
    ]
    results = [
        MemorySearchResult(memory=m, score=0.9 - i * 0.05, memory_type=MemoryType.SEMANTIC)
        for i, m in enumerate(memories)
    ]
    manager, vector, _ = _build_manager(search_results=results)

    await manager.search("broad query")
    await asyncio.sleep(0.1)

    for m in memories:
        assert m.access_count == 1
    assert vector.upsert.await_count == 1
    upsert_docs = vector.upsert.call_args[0][1]
    assert len(upsert_docs) == 10
