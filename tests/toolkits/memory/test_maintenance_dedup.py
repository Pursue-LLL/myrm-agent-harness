from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import dedup_semantics
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


@pytest.mark.asyncio
async def test_dedup_semantics_no_duplicates():
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    embedding = AsyncMock()
    embedding.embed_documents.return_value = [[0.1]]
    cache = AsyncMock()

    mem1 = SemanticMemory(id="doc1", content="test", metadata={"status": "active"})
    vector.search.return_value = []

    result = await dedup_semantics([mem1], vector, embedding, config, cache)

    assert len(result) == 1
    assert result[0].id == "doc1"

@pytest.mark.asyncio
async def test_dedup_semantics_with_duplicates():
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    embedding = AsyncMock()
    embedding.embed_documents.return_value = [[0.1]]
    cache = AsyncMock()

    mem1 = SemanticMemory(id="doc1", content="test", metadata={"status": "active"})
    doc2 = VectorDocument(id="doc2", content="test", metadata={"status": "active"}, embedding=[0.1])

    # Mock search to return doc2 as a duplicate of mem1
    vector.search.return_value = [(doc2, 0.96)]

    result = await dedup_semantics([mem1], vector, embedding, config, cache)

    assert len(result) == 0

@pytest.mark.asyncio
async def test_dedup_semantics_error():
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    embedding = AsyncMock()
    embedding.embed_documents.return_value = [[0.1]]
    cache = AsyncMock()

    mem1 = SemanticMemory(id="doc1", content="test", metadata={"status": "active"})

    vector.search.side_effect = Exception("Search error")

    result = await dedup_semantics([mem1], vector, embedding, config, cache)

    # In case of error, it should probably return the original memory
    assert len(result) == 1
    assert result[0].id == "doc1"
