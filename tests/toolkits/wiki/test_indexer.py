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
    embedding.embed_batch.side_effect = lambda chunks: [[0.1, 0.2, 0.3] for _ in chunks]
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


@pytest.mark.asyncio
async def test_sidecar_indexing_and_search(wiki_structure):
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert_sidecar("work/project-a", level=0, content="Project A architecture summary.")
    await indexer.upsert_sidecar("work/project-a", level=1, content="Project A detailed design overview.")

    # Sidecar-only content should not pollute concept search.
    concept_hits = await indexer.search("architecture")
    assert concept_hits == []

    sidecar_hits = await indexer.search_sidecars("architecture", limit=5)
    assert len(sidecar_hits) >= 1
    assert sidecar_hits[0][0] == "work/project-a"
    assert sidecar_hits[0][1] in (0, 1)

    abstract = indexer.get_sidecar_truth("work/project-a", level=0)
    overview = indexer.get_sidecar_truth("work/project-a", level=1)
    assert abstract is not None and "architecture" in abstract.lower()
    assert overview is not None and "overview" in overview.lower()


@pytest.mark.asyncio
async def test_sidecar_delete_single(wiki_structure):
    """delete_sidecar removes one level while keeping the other."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert_sidecar("lang/python", level=0, content="Python overview.")
    await indexer.upsert_sidecar("lang/python", level=1, content="Python detailed.")

    await indexer.delete_sidecar("lang/python", level=0)

    assert indexer.get_sidecar_truth("lang/python", level=0) is None
    assert indexer.get_sidecar_truth("lang/python", level=1) is not None


@pytest.mark.asyncio
async def test_sidecar_delete_all(wiki_structure):
    """delete_all_sidecars removes all sidecar entries without touching concepts."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert("RegularConcept", "## Compiled Truth\nConcept content.")
    await indexer.upsert_sidecar("dir-a", level=0, content="Dir A abstract.")
    await indexer.upsert_sidecar("dir-b", level=1, content="Dir B overview.")

    await indexer.delete_all_sidecars()

    assert indexer.get_sidecar_truth("dir-a", level=0) is None
    assert indexer.get_sidecar_truth("dir-b", level=1) is None
    assert indexer.get_truth("RegularConcept") is not None


@pytest.mark.asyncio
async def test_sidecar_search_empty_query(wiki_structure):
    """search_sidecars returns empty for blank queries."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert_sidecar("data", level=0, content="Data science.")
    result = await indexer.search_sidecars("", limit=5)
    assert result == []

    result2 = await indexer.search_sidecars("   ", limit=5)
    assert result2 == []


@pytest.mark.asyncio
async def test_sidecar_search_invalid_levels(wiki_structure):
    """search_sidecars returns empty when no valid levels are given."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert_sidecar("data", level=0, content="Data science.")
    result = await indexer.search_sidecars("data", levels=(99,), limit=5)
    assert result == []


@pytest.mark.asyncio
async def test_sidecar_root_directory(wiki_structure):
    """Root directory (empty string) sidecars work correctly."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert_sidecar("", level=0, content="Root abstract.")
    await indexer.upsert_sidecar("", level=1, content="Root overview.")

    assert indexer.get_sidecar_truth("", level=0) is not None
    assert "root" in indexer.get_sidecar_truth("", level=0).lower()

    hits = await indexer.search_sidecars("root", limit=5)
    root_dirs = [dir_path for dir_path, _, _ in hits]
    assert "" in root_dirs


@pytest.mark.asyncio
async def test_sidecar_upsert_invalid_level(wiki_structure):
    """upsert_sidecar raises ValueError for unsupported levels."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    with pytest.raises(ValueError, match="Unsupported sidecar level"):
        await indexer.upsert_sidecar("data", level=5, content="Bad level.")


@pytest.mark.asyncio
async def test_sidecar_upsert_empty_content_fallback(wiki_structure):
    """upsert_sidecar uses fallback text for empty content."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert_sidecar("empty", level=0, content="   ")
    truth = indexer.get_sidecar_truth("empty", level=0)
    assert truth is not None
    assert "no validated knowledge" in truth.lower()


@pytest.mark.asyncio
async def test_sidecar_overwrite_updates_content(wiki_structure):
    """Upserting same sidecar replaces previous content."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert_sidecar("versioned", level=0, content="Version 1.")
    assert "version 1" in indexer.get_sidecar_truth("versioned", level=0).lower()

    await indexer.upsert_sidecar("versioned", level=0, content="Version 2.")
    truth = indexer.get_sidecar_truth("versioned", level=0)
    assert "version 2" in truth.lower()
    assert "version 1" not in truth.lower()


def test_normalize_dir_path():
    """Static helpers preserve semantics for various path formats."""
    from myrm_agent_harness.toolkits.wiki.retrieval.sidecar_index import SidecarIndexMixin

    assert SidecarIndexMixin._normalize_dir_path("work/project") == "work/project"
    assert SidecarIndexMixin._normalize_dir_path("/work/project/") == "work/project"
    assert SidecarIndexMixin._normalize_dir_path("  work\\project  ") == "work/project"
    assert SidecarIndexMixin._normalize_dir_path("") == ""
    assert SidecarIndexMixin._normalize_dir_path("   ") == ""


def test_concept_dir_path():
    from myrm_agent_harness.toolkits.wiki.retrieval.sidecar_index import SidecarIndexMixin

    assert SidecarIndexMixin._concept_dir_path("work/project/item") == "work/project"
    assert SidecarIndexMixin._concept_dir_path("single") == ""
    assert SidecarIndexMixin._concept_dir_path("a/b/c/d") == "a/b/c"


def test_decode_sidecar_entry_id_roundtrip():
    from myrm_agent_harness.toolkits.wiki.retrieval.sidecar_index import SidecarIndexMixin

    mixin = SidecarIndexMixin()
    for dir_path in ("", "work/project", "deep/nested/path"):
        for level in (0, 1):
            entry_id = mixin._sidecar_entry_id(dir_path, level)
            decoded = SidecarIndexMixin._decode_sidecar_entry_id(entry_id)
            assert decoded is not None
            assert decoded[0] == SidecarIndexMixin._normalize_dir_path(dir_path)
            assert decoded[1] == level


def test_decode_sidecar_entry_id_invalid():
    from myrm_agent_harness.toolkits.wiki.retrieval.sidecar_index import SidecarIndexMixin

    assert SidecarIndexMixin._decode_sidecar_entry_id("not-a-sidecar") is None
    assert SidecarIndexMixin._decode_sidecar_entry_id("__sidecar__:L9:bad") is None
    assert SidecarIndexMixin._decode_sidecar_entry_id("__sidecar__:") is None


@pytest.mark.asyncio
async def test_sidecar_hybrid_upsert_and_search(wiki_structure, mock_vector_store, mock_embedding):
    """Sidecar upsert and search work correctly in hybrid (FTS5+vector) mode."""
    config = WikiConfig(enable_hybrid_search=True)
    indexer = WikiIndexer(wiki_structure, config, vector_store=mock_vector_store, embedding=mock_embedding)

    await indexer.upsert_sidecar("lang/go", level=0, content="Go language concurrency model.")

    mock_embedding.embed.assert_awaited()
    mock_vector_store.upsert.assert_awaited()

    upsert_call = mock_vector_store.upsert.call_args
    doc = upsert_call[0][1][0]
    assert doc.metadata["entry_type"] == "sidecar"
    assert doc.metadata["level"] == "L0"
    assert doc.metadata["dir_path"] == "lang/go"


@pytest.mark.asyncio
async def test_sidecar_hybrid_delete_cleans_vector(wiki_structure, mock_vector_store, mock_embedding):
    """delete_sidecar removes entry from vector store in hybrid mode."""
    config = WikiConfig(enable_hybrid_search=True)
    indexer = WikiIndexer(wiki_structure, config, vector_store=mock_vector_store, embedding=mock_embedding)

    await indexer.upsert_sidecar("lang/go", level=0, content="Go language.")
    await indexer.delete_sidecar("lang/go", level=0)

    mock_vector_store.delete.assert_awaited()
    assert indexer.get_sidecar_truth("lang/go", level=0) is None


@pytest.mark.asyncio
async def test_sidecar_search_single_level_filter(wiki_structure):
    """search_sidecars respects levels parameter to filter L0 or L1 only."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert_sidecar("data", level=0, content="Data science abstract.")
    await indexer.upsert_sidecar("data", level=1, content="Data science overview.")

    l0_hits = await indexer.search_sidecars("data science", levels=(0,), limit=5)
    for _, level, _ in l0_hits:
        assert level == 0, f"Expected only L0 results, got L{level}"

    l1_hits = await indexer.search_sidecars("data science", levels=(1,), limit=5)
    for _, level, _ in l1_hits:
        assert level == 1, f"Expected only L1 results, got L{level}"


@pytest.mark.asyncio
async def test_sidecar_delete_then_search(wiki_structure):
    """After deleting a sidecar, search should not return that directory."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert_sidecar("deleted-dir", level=0, content="This will be deleted.")
    hits_before = await indexer.search_sidecars("deleted", limit=5)
    assert any(d == "deleted-dir" for d, _, _ in hits_before)

    await indexer.delete_sidecar("deleted-dir", level=0)
    hits_after = await indexer.search_sidecars("deleted", limit=5)
    assert not any(d == "deleted-dir" for d, _, _ in hits_after)


@pytest.mark.asyncio
async def test_sidecar_deep_nested_directory(wiki_structure):
    """Sidecars work correctly for deeply nested directory paths."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    deep_path = "research/ml/transformers/attention"
    await indexer.upsert_sidecar(deep_path, level=0, content="Attention mechanism research.")

    truth = indexer.get_sidecar_truth(deep_path, level=0)
    assert truth is not None
    assert "attention" in truth.lower()

    hits = await indexer.search_sidecars("attention mechanism", limit=5)
    dirs = [d for d, _, _ in hits]
    assert deep_path in dirs


@pytest.mark.asyncio
async def test_sidecar_hybrid_embedding_failure_graceful(wiki_structure, mock_vector_store, mock_embedding):
    """Sidecar upsert handles embedding failure gracefully in hybrid mode."""
    config = WikiConfig(enable_hybrid_search=True)
    mock_embedding.embed_batch.side_effect = RuntimeError("Embedding service down")
    indexer = WikiIndexer(wiki_structure, config, vector_store=mock_vector_store, embedding=mock_embedding)

    await indexer.upsert_sidecar("fail-dir", level=0, content="Content that fails embedding.")

    truth = indexer.get_sidecar_truth("fail-dir", level=0)
    assert truth is not None, "FTS5 upsert should succeed even if embedding fails"
    mock_vector_store.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_sidecar_concept_search_isolation_with_shared_keywords(wiki_structure):
    """Sidecar and concept using identical keywords stay isolated in search."""
    config = WikiConfig(enable_hybrid_search=False)
    indexer = WikiIndexer(wiki_structure, config)

    await indexer.upsert("kubernetes", "## Compiled Truth\nKubernetes container orchestration platform.")
    await indexer.upsert_sidecar("infra", level=0, content="Kubernetes cluster management.")

    concept_results = await indexer.search("kubernetes", limit=10)
    for name, _ in concept_results:
        assert not name.startswith("__sidecar__"), f"Sidecar leaked: {name}"
    assert any(name == "kubernetes" for name, _ in concept_results)

    sidecar_results = await indexer.search_sidecars("kubernetes", limit=10)
    assert any(d == "infra" for d, _, _ in sidecar_results)
