"""Unit tests for pure BM25 multi-query RRF reranking and chunk_filter safety fallback."""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.engine import RetrieverManager
from myrm_agent_harness.toolkits.retriever.preprocessing.chunk_filter import ChunkFilter


@pytest.mark.asyncio
async def test_bm25_multi_query_relevance_reranking() -> None:
    """Verify BM25 reranks candidate pool based purely on keyword relevance and consensus."""
    manager = RetrieverManager()
    docs = [
        Document(
            page_content="Welcome to our cloud platform homepage. We provide best-in-class solutions.",
            metadata={"title": "Cloud Vendor Landing Page", "url": "https://example.com/home"},
        ),
        Document(
            page_content="Detailed guide on PostgreSQL sequence overflow and BIGINT migration strategies.",
            metadata={"title": "Postgres Sequence Deep Dive", "url": "https://example.com/postgres-overflow"},
        ),
        Document(
            page_content="Troubleshooting database primary key sequence exhaustion in PostgreSQL production.",
            metadata={"title": "Production Fix Guide", "url": "https://example.com/troubleshoot-sequence"},
        ),
    ]

    queries = ["postgresql sequence overflow", "primary key exhaustion"]
    results = await manager.bm25_retrieval_only(queries=queries, documents=docs, top_k=2)

    assert len(results) == 2
    # Generic landing page with 0 query keywords must be naturally dropped out of top 2
    titles = [r.metadata["title"] for r in results]
    assert "Cloud Vendor Landing Page" not in titles
    assert "Postgres Sequence Deep Dive" in titles
    assert "Production Fix Guide" in titles


@pytest.mark.asyncio
async def test_bm25_retrieval_only_zero_match_fallback() -> None:
    """Verify bm25_retrieval_only falls back safely to original order when all queries have zero matches."""
    manager = RetrieverManager()
    docs = [
        Document(
            page_content="Python asyncio event loop guide.",
            metadata={"title": "Asyncio Doc 1", "url": "https://example.com/asyncio-1"},
        ),
        Document(
            page_content="Python asyncio tasks and futures.",
            metadata={"title": "Asyncio Doc 2", "url": "https://example.com/asyncio-2"},
        ),
    ]

    # Queries completely unrelated to docs
    queries = ["量子力学 波粒二象性", "天体物理学 恒星演化"]
    results = await manager.bm25_retrieval_only(queries=queries, documents=docs, top_k=1)

    assert len(results) == 1
    # Safe fallback to original order
    assert results[0].metadata["title"] == "Asyncio Doc 1"


@pytest.mark.asyncio
async def test_chunk_filter_zero_recall_and_cross_language_bounded_fallback() -> None:
    """Verify ChunkFilter fallback never exceeds max_retained_chunks and never returns empty for valid chunks."""
    filter_instance = ChunkFilter(
        long_doc_threshold=100,
        bm25_topk_ratio=2,
        max_retained_chunks=3,
        min_retained_chunks=1,
    )

    # 10 chunks created from a long document
    long_doc_text = "Detailed documentation chapter paragraph. " * 30
    doc = Document(page_content=long_doc_text, metadata={"url": "https://example.com/spec"})

    # Monolingual zero-match queries
    filtered = await filter_instance.filter_chunks_by_relevance(
        url="https://example.com/spec",
        document=doc,
        queries=["量子力学 宇宙膨胀 黑洞"],
    )

    # Must be bounded by max_retained_chunks (3), NOT 0 and NOT 10!
    assert 0 < len(filtered) <= 3
