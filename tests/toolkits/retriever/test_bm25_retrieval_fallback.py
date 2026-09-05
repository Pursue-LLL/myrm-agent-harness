"""Unit tests for RetrieverManager BM25 zero recall unconditional fallback."""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.engine import RetrieverManager


@pytest.mark.asyncio
async def test_bm25_retrieval_only_zero_recall_fallback_unconditional() -> None:
    """Verify that BM25 zero recall unconditionally triggers fallback to original top_k.

    Tests both mixed language and monolingual zero-match lexical scenarios.
    """
    manager = RetrieverManager()
    docs = [
        Document(page_content="苹果 香蕉 橘子 水果大集合", metadata={"url": "https://example.com/fruit1"}),
        Document(page_content="西瓜 葡萄 草莓 盛夏果实", metadata={"url": "https://example.com/fruit2"}),
        Document(page_content="电脑 键盘 鼠标 硬件设备", metadata={"url": "https://example.com/hardware"}),
    ]

    # Monolingual zero-match query (Chinese query vs fruit/hardware docs, no overlapping tokens)
    res_mono = await manager.bm25_retrieval_only(
        queries=["空间折叠 引力波 奇点"],
        documents=docs,
        top_k=2,
    )
    # Must fallback to docs[:2], NOT return empty list!
    assert len(res_mono) == 2
    assert res_mono[0].metadata["url"] == "https://example.com/fruit1"
    assert res_mono[1].metadata["url"] == "https://example.com/fruit2"

    # Mixed language zero-match query (Mixed query where BM25 has 0 hits)
    res_mixed = await manager.bm25_retrieval_only(
        queries=["Kubernetes Pod CRD 控制器原理"],
        documents=docs,
        top_k=1,
    )
    assert len(res_mixed) == 1
    assert res_mixed[0].metadata["url"] == "https://example.com/fruit1"
