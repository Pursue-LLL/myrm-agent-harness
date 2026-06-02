from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument
from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


@pytest.fixture
def wiki_structure(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_vector_store():
    store = AsyncMock()
    store.collection_exists.return_value = False
    store.create_collection = AsyncMock()
    store.ensure_collection = AsyncMock()
    store.upsert = AsyncMock()
    store.search = AsyncMock()
    return store


@pytest.fixture
def mock_embedding():
    embedding = AsyncMock()
    embedding.embed.return_value = [0.1, 0.2, 0.3]
    return embedding


@pytest.mark.asyncio
async def test_indexer_upsert_fts5_only(wiki_structure):
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert(
        "Test Concept", "---\ntags: [test]\n---\n## Compiled Truth\nThis is a truth.\n## Timeline\nTimeline event."
    )

    # Verify FTS5
    truth = indexer.get_truth("Test Concept")
    assert truth is not None
    assert "This is a truth." in truth
    assert "---\ntags: [test]\n---\n" in truth

    results = await indexer.search("truth")
    assert len(results) == 1
    assert results[0][0] == "Test Concept"


@pytest.mark.asyncio
async def test_indexer_hybrid_upsert_and_search(wiki_structure, mock_vector_store, mock_embedding):
    config = WikiConfig(enable_hybrid_search=True)
    indexer = WikiIndexer(wiki_structure, config, vector_store=mock_vector_store, embedding=mock_embedding)

    await indexer.upsert("Vector Concept", "## Compiled Truth\nVector knowledge.")

    # Verify FTS5
    truth = indexer.get_truth("Vector Concept")
    assert truth is not None
    assert "Vector knowledge." in truth

    # Verify VectorStore upsert
    mock_embedding.embed.assert_awaited()
    mock_vector_store.upsert.assert_awaited()

    # Setup search mock
    mock_vector_store.search.return_value = [
        SearchResult(
            document=VectorDocument(id="vector-id", content="", vector=[], metadata={"concept_name": "Vector Concept"}),
            score=0.9,
        )
    ]

    results = await indexer.search("Vector")
    assert len(results) == 1
    assert results[0][0] == "Vector Concept"
