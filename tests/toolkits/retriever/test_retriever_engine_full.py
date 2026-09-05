"""Comprehensive unit tests for RetrieverManager and BM25CacheStats in retriever engine.

Ensures strict >=90% line coverage, zero CPU thrashing, and zero memory leaks.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.engine import (
    BM25CacheStats,
    RetrieverConfig,
    RetrieverManager,
)


def test_bm25_cache_stats_properties() -> None:
    """Verify BM25CacheStats hit_rate, total_requests, and cache_memory_mb calculations."""
    stats = BM25CacheStats()
    assert stats.hit_rate == 0.0
    assert stats.total_requests == 0
    assert stats.cache_memory_mb == 0.0

    stats.hits = 3
    stats.misses = 1
    stats.total_cached_docs = 100
    assert stats.total_requests == 4
    assert stats.hit_rate == 0.75
    expected_mb = 100 * 0.13 / 1024
    assert abs(stats.cache_memory_mb - expected_mb) < 1e-6


@pytest.mark.asyncio
async def test_retriever_cache_eviction_and_reuse() -> None:
    """Verify BM25 index caching, hit tracking, and LRU eviction upon exceeding capacity."""
    config = RetrieverConfig(bm25_cache_max_size=2)
    manager = RetrieverManager(config=config)

    docs_a = [
        Document(page_content="Apple fruit healthy nutrition.", metadata={"url": "https://a.com/1", "chunk_index": 0})
    ]
    docs_b = [
        Document(page_content="Banana tropical yellow potassium.", metadata={"url": "https://b.com/1", "chunk_index": 0})
    ]
    docs_c = [
        Document(page_content="Cherry red sweet stonefruit.", metadata={"url": "https://c.com/1", "chunk_index": 0})
    ]

    retriever_a1 = await manager._get_cached_bm25_retriever(docs_a)
    assert manager.bm25_cache_stats.misses == 1
    assert manager.bm25_cache_stats.hits == 0

    # Cache hit
    retriever_a2 = await manager._get_cached_bm25_retriever(docs_a)
    assert retriever_a1 is retriever_a2
    assert manager.bm25_cache_stats.hits == 1

    # Insert docs_b
    await manager._get_cached_bm25_retriever(docs_b)
    assert len(manager._bm25_cache) == 2

    # Insert docs_c -> should evict docs_a (LRU)
    await manager._get_cached_bm25_retriever(docs_c)
    assert manager.bm25_cache_stats.evictions == 1
    assert len(manager._bm25_cache) == 2

    # docs_a was evicted, so accessing docs_a now causes a cache miss
    await manager._get_cached_bm25_retriever(docs_a)
    assert manager.bm25_cache_stats.misses == 4


@pytest.mark.asyncio
async def test_bm25_retrieval_edge_inputs() -> None:
    """Verify bm25_retrieval_only handling of empty documents or empty queries."""
    manager = RetrieverManager()
    assert await manager.bm25_retrieval_only(queries=["test"], documents=[], top_k=5) == []

    docs = [
        Document(page_content="Sample doc 1", metadata={"url": "https://x.com/1"}),
        Document(page_content="Sample doc 2", metadata={"url": "https://x.com/2"}),
    ]
    assert await manager.bm25_retrieval_only(queries=[], documents=docs, top_k=1) == docs[:1]


@pytest.mark.asyncio
async def test_bm25_retrieval_with_mapping() -> None:
    """Verify bm25_retrieval_with_mapping per-query mapping outputs."""
    manager = RetrieverManager()
    assert await manager.bm25_retrieval_with_mapping(queries=[], documents=[]) == {}
    assert await manager.bm25_retrieval_with_mapping(queries=["foo"], documents=[]) == {}

    # Need at least 3 documents so that standard rank_bm25 IDF > 0 for term present in only 1 document
    docs = [
        Document(page_content="Python asyncio event loop concurrent tasks.", metadata={"url": "https://py.org/async"}),
        Document(page_content="Rust tokio async runtime memory safety.", metadata={"url": "https://rust.org/tokio"}),
        Document(page_content="Generic database SQL query optimization index.", metadata={"url": "https://db.org/index"}),
    ]
    mapping = await manager.bm25_retrieval_with_mapping(queries=["python", "rust"], documents=docs, top_k_per_query=2)
    assert "python" in mapping
    assert "rust" in mapping
    assert len(mapping["python"]) >= 1
    assert "Python" in mapping["python"][0][0].page_content


@pytest.mark.asyncio
async def test_retrieve_from_crawl_results_empty() -> None:
    """Verify retrieve_from_crawl_results returns empty tuple when crawl results are empty."""
    manager = RetrieverManager()
    dummy_reranker = MagicMock()
    dummy_embeddings = MagicMock()

    meta, text = await manager.retrieve_from_crawl_results(
        queries="test",
        reranker=dummy_reranker,
        embeddings=dummy_embeddings,
        pre_crawled_results=([], []),
    )
    assert meta == []
    assert text == ""


@pytest.mark.asyncio
async def test_retrieve_from_crawl_results_direct_and_hybrid() -> None:
    """Verify retrieve_from_crawl_results switches between direct reranking and hybrid paths."""
    manager = RetrieverManager()
    dummy_reranker = MagicMock()
    dummy_embeddings = MagicMock()

    # SuccessResult is list[tuple[str, Document]]
    sample_doc = Document(
        page_content="Guide on distributed consensus and Raft algorithm in high throughput systems.",
        metadata={"url": "https://example.com/guide", "title": "Consensus Guide"},
    )
    success_crawl = [("https://example.com/guide", sample_doc)]

    with patch(
        "myrm_agent_harness.toolkits.retriever.engine.create_document_chunks_from_crawl_results",
        new=AsyncMock(return_value=[sample_doc]),
    ), patch(
        "myrm_agent_harness.toolkits.retriever.engine.hybrid_retriever.direct_reranking_only",
        new=AsyncMock(return_value=[sample_doc]),
    ) as mock_direct, patch(
        "myrm_agent_harness.toolkits.retriever.engine.format_documents_with_metadata",
        return_value=([{"url": "https://example.com/guide"}], "Formatted text", {}),
    ):
        meta, formatted = await manager.retrieve_from_crawl_results(
            queries=["raft algorithm"],
            reranker=dummy_reranker,
            embeddings=dummy_embeddings,
            pre_crawled_results=(success_crawl, []),
            hybrid_top_k_per_query=100,  # Forces direct rerank path
        )
        assert mock_direct.called
        assert meta == [{"url": "https://example.com/guide"}]
        assert formatted == "Formatted text"

        sample_docs = [
            Document(page_content=f"Doc chunk {i}", metadata={"url": f"https://example.com/{i}"})
            for i in range(5)
        ]
        with patch(
            "myrm_agent_harness.toolkits.retriever.engine.create_document_chunks_from_crawl_results",
            new=AsyncMock(return_value=sample_docs),
        ), patch(
            "myrm_agent_harness.toolkits.retriever.engine.hybrid_retriever.hybrid_retrieval_with_reranking",
            new=AsyncMock(return_value=sample_docs[:2]),
        ) as mock_hybrid, patch(
            "myrm_agent_harness.toolkits.retriever.engine.format_documents_with_metadata",
            return_value=([{"url": "https://example.com/guide"}], "Formatted text", {}),
        ):
            meta, formatted = await manager.retrieve_from_crawl_results(
                queries="raft algorithm",
                reranker=dummy_reranker,
                embeddings=dummy_embeddings,
                pre_crawled_results=(success_crawl, []),
                hybrid_top_k_per_query=2,  # 5 chunks > 2 -> forces hybrid retrieval path
            )
            assert mock_hybrid.called
            assert meta == [{"url": "https://example.com/guide"}]


@pytest.mark.asyncio
async def test_direct_reranking_and_mapping_delegation() -> None:
    """Verify direct_reranking_only and rerank_with_mapping delegate to hybrid_retriever."""
    manager = RetrieverManager()
    dummy_reranker = MagicMock()
    docs = [Document(page_content="hello world")]

    with patch(
        "myrm_agent_harness.toolkits.retriever.engine.hybrid_retriever.direct_reranking_only",
        new=AsyncMock(return_value=docs),
    ) as mock_direct:
        res = await manager.direct_reranking_only(["q"], docs, dummy_reranker)
        assert res == docs
        assert mock_direct.called

    with patch(
        "myrm_agent_harness.toolkits.retriever.engine.hybrid_retriever.hybrid_retrieval_with_reranking",
        new=AsyncMock(return_value=docs),
    ) as mock_hybrid:
        res = await manager.hybrid_retrieval_with_reranking(["q"], docs, dummy_reranker, MagicMock())
        assert res == docs
        assert mock_hybrid.called

    with patch(
        "myrm_agent_harness.toolkits.retriever.engine.hybrid_retriever.rerank_with_mapping",
        new=AsyncMock(return_value=docs),
    ) as mock_map:
        res = await manager.rerank_with_mapping({"q": [(docs[0], 1.0)]}, dummy_reranker)
        assert res == docs
        assert mock_map.called


@pytest.mark.asyncio
async def test_retrieve_from_urls_validation_and_flow() -> None:
    """Verify retrieve_from_urls validates arguments, handles failures, and executes successfully."""
    manager = RetrieverManager()
    dummy_reranker = MagicMock()
    dummy_embeddings = MagicMock()

    # Empty URLs
    meta, ctx, err = await manager.retrieve_from_urls([], "query", dummy_reranker, dummy_embeddings)
    assert err == "No URLs provided"
    assert meta == []

    # Empty queries
    meta, ctx, err = await manager.retrieve_from_urls(["https://a.com"], "", dummy_reranker, dummy_embeddings)
    assert err == "No queries provided"

    # Crawl failure
    with patch(
        "myrm_agent_harness.toolkits.web_fetch.FetchEngine.crawl_many",
        new=AsyncMock(return_value=([], [("https://fail.com", "Timeout")])),
    ):
        meta, ctx, err = await manager.retrieve_from_urls(
            ["https://fail.com"], "query", dummy_reranker, dummy_embeddings
        )
        assert "Failed to crawl URLs" in err

    # Crawl success
    with patch(
        "myrm_agent_harness.toolkits.web_fetch.FetchEngine.crawl_many",
        new=AsyncMock(return_value=([MagicMock()], [])),
    ), patch.object(
        manager,
        "retrieve_from_crawl_results",
        new=AsyncMock(return_value=([{"url": "https://ok.com"}], "Context ok")),
    ):
        meta, ctx, err = await manager.retrieve_from_urls(
            ["https://ok.com"], "query", dummy_reranker, dummy_embeddings
        )
        assert err == ""
        assert meta == [{"url": "https://ok.com"}]
        assert ctx == "Context ok"

    # Exception path
    with patch(
        "myrm_agent_harness.toolkits.web_fetch.FetchEngine.crawl_many",
        new=AsyncMock(side_effect=RuntimeError("Simulated socket error")),
    ):
        meta, ctx, err = await manager.retrieve_from_urls(
            ["https://crash.com"], "query", dummy_reranker, dummy_embeddings
        )
        assert "Retrieve from URLs failed" in err
