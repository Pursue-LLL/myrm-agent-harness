"""Unit tests for dual-track RRF fusion and chunk_filter safety fallback."""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.engine import RetrieverManager
from myrm_agent_harness.toolkits.retriever.preprocessing.chunk_filter import ChunkFilter


@pytest.mark.asyncio
async def test_dual_track_rrf_preserves_anchor_authority_and_consensus() -> None:
    """Verify dual-track RRF protects engine anchor ranking while boosting cross-query consensus."""
    manager = RetrieverManager()
    docs = [
        Document(
            page_content="Official Kubernetes documentation about pod eviction and allocatable memory constraints.",
            metadata={"title": "K8s Official Docs", "url": "https://kubernetes.io/docs/concepts/scheduling-eviction/"},
        ),
        Document(
            page_content="CNCF technical article explaining production guidelines for kubelet eviction thresholds.",
            metadata={"title": "CNCF Best Practices", "url": "https://cncf.io/blog/kubelet-eviction-production"},
        ),
        Document(
            page_content="Eviction threshold eviction threshold eviction threshold keyword spam blog guide hacks.",
            metadata={"title": "Spammy Aggregator", "url": "https://spammy-seo-aggregator.xyz/post/1234"},
        ),
    ]

    queries = ["kubelet eviction thresholds", "pod allocatable memory"]
    results = await manager.bm25_retrieval_only(queries=queries, documents=docs, top_k=2)

    assert len(results) == 2
    # Official docs must maintain top 1 rank due to anchor track weighting
    assert results[0].metadata["title"] == "K8s Official Docs"
    assert results[1].metadata["title"] == "CNCF Best Practices"


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
