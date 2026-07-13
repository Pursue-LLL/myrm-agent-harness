from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import bump_access_counts
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemorySearchResult,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
)


@pytest.mark.asyncio
async def test_bump_access_counts_semantic_and_episodic():
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()

    mem1 = SemanticMemory(id="sem1", content="test", metadata={})
    mem2 = EpisodicMemory(id="epi1", content="test", metadata={})

    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.SEMANTIC)
    res2 = MemorySearchResult(memory=mem2, score=0.8, memory_type=MemoryType.EPISODIC)

    await bump_access_counts([res1, res2], vector, config)

    assert mem1.access_count == 1
    assert mem2.access_count == 1
    assert mem1.last_accessed_at is not None
    assert mem2.last_accessed_at is not None
    assert vector.upsert.call_count == 2


@pytest.mark.asyncio
async def test_bump_access_counts_procedural_with_relational():
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    relational = AsyncMock()

    proc_mem = ProceduralMemory(
        id="proc1", content="Always use TypeScript", trigger="new file", action="use .ts", source="agent_self"
    )
    res = MemorySearchResult(memory=proc_mem, score=0.85, memory_type=MemoryType.PROCEDURAL)

    await bump_access_counts([res], vector, config, relational=relational)

    assert proc_mem.access_count == 1
    assert proc_mem.last_accessed_at is not None
    relational.update_rule.assert_awaited_once_with(proc_mem.id, proc_mem)


@pytest.mark.asyncio
async def test_bump_access_counts_procedural_without_relational():
    """ProceduralMemory should be skipped when relational store is not available."""
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()

    proc_mem = ProceduralMemory(
        id="proc1", content="rule", trigger="t", action="a", source="agent_self"
    )
    res = MemorySearchResult(memory=proc_mem, score=0.85, memory_type=MemoryType.PROCEDURAL)

    await bump_access_counts([res], vector, config, relational=None)

    assert proc_mem.access_count == 0


@pytest.mark.asyncio
async def test_bump_access_counts_mixed_types():
    """All memory types tracked in a single call."""
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    relational = AsyncMock()

    sem = SemanticMemory(id="s1", content="fact", metadata={})
    epi = EpisodicMemory(id="e1", content="event", metadata={})
    proc = ProceduralMemory(id="p1", content="rule", trigger="t", action="a", source="agent_self")

    results = [
        MemorySearchResult(memory=sem, score=0.9, memory_type=MemoryType.SEMANTIC),
        MemorySearchResult(memory=epi, score=0.8, memory_type=MemoryType.EPISODIC),
        MemorySearchResult(memory=proc, score=0.7, memory_type=MemoryType.PROCEDURAL),
    ]

    await bump_access_counts(results, vector, config, relational=relational)

    assert sem.access_count == 1
    assert epi.access_count == 1
    assert proc.access_count == 1
    assert vector.upsert.call_count == 2
    relational.update_rule.assert_awaited_once()


@pytest.mark.asyncio
async def test_bump_access_counts_error_non_fatal():
    """Errors should be caught and not propagate."""
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    vector.upsert.side_effect = Exception("Upsert error")

    mem1 = SemanticMemory(id="sem1", content="test", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.SEMANTIC)

    await bump_access_counts([res1], vector, config)

    assert mem1.access_count == 1


@pytest.mark.asyncio
async def test_bump_access_counts_idempotent_increment():
    """Multiple calls should accumulate access_count."""
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()

    mem = SemanticMemory(id="sem1", content="test", metadata={})
    res = MemorySearchResult(memory=mem, score=0.9, memory_type=MemoryType.SEMANTIC)

    await bump_access_counts([res], vector, config)
    await bump_access_counts([res], vector, config)
    await bump_access_counts([res], vector, config)

    assert mem.access_count == 3


@pytest.mark.asyncio
async def test_bump_access_counts_procedural_update_rule_error():
    """ProceduralMemory update_rule failure should not propagate."""
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    relational = AsyncMock()
    relational.update_rule.side_effect = Exception("DB connection lost")

    proc_mem = ProceduralMemory(
        id="proc1", content="rule", trigger="t", action="a", source="agent_self"
    )
    res = MemorySearchResult(memory=proc_mem, score=0.85, memory_type=MemoryType.PROCEDURAL)

    await bump_access_counts([res], vector, config, relational=relational)

    assert proc_mem.access_count == 1
    assert proc_mem.last_accessed_at is not None
    relational.update_rule.assert_awaited_once()
