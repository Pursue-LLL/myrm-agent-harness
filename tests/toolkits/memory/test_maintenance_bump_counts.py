from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import bump_access_counts
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, MemorySearchResult, MemoryType, SemanticMemory


@pytest.mark.asyncio
async def test_bump_access_counts():
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()

    mem1 = SemanticMemory(id="sem1", content="test", metadata={})
    mem2 = EpisodicMemory(id="epi1", content="test", metadata={})

    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.SEMANTIC)
    res2 = MemorySearchResult(memory=mem2, score=0.8, memory_type=MemoryType.EPISODIC)

    await bump_access_counts([res1, res2], vector, config)

    assert mem1.access_count == 1
    assert mem2.access_count == 1
    assert vector.upsert.call_count == 2

@pytest.mark.asyncio
async def test_bump_access_counts_error():
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()

    mem1 = SemanticMemory(id="sem1", content="test", metadata={})
    res1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.SEMANTIC)

    vector.upsert.side_effect = Exception("Upsert error")

    # Should not raise exception
    await bump_access_counts([res1], vector, config)

    assert mem1.access_count == 1
    assert vector.upsert.call_count == 1
