"""Regression tests for positive-IDF BM25 scoring.

``rank_bm25``'s stock IDF goes negative for terms present in more than half of the
documents and is then floored at ``epsilon * average_idf``, which collapses to zero
on small corpora. The sparse channel then scored a matching term as irrelevant and
silently returned nothing, so memory recall reported "no such memory" even though the
fact was stored. These tests pin the positive-IDF behaviour that fixes it.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.retriever.bm25_retrieval import (
    BM25Retriever,
    preprocess_text,
)

# The exact one-document shape that previously produced a silent empty channel.
_SINGLE_DOC = "我最喜欢的颜色是深海蓝，我有一只叫'奥利奥'的猫。"

# Mirrors the CJK corpus shape used by test_cjk_recall_quality.
_FIVE_DOCS = [
    "机器学习模型部署方案讨论",
    "深度学习训练优化技巧总结",
    "数据预处理管道设计文档",
    "前端React组件重构计划",
    "Python自动化测试框架搭建",
]


class TestPositiveIdfWeights:
    """apply_positive_idf must leave no zero or negative weight behind."""

    def test_all_weights_are_strictly_positive_for_single_document_corpus(self) -> None:
        retriever = BM25Retriever([_SINGLE_DOC])
        assert retriever.bm25 is not None
        assert all(weight > 0 for weight in retriever.bm25.idf.values())

    def test_weight_decreases_as_document_frequency_grows(self) -> None:
        retriever = BM25Retriever(_FIVE_DOCS)
        assert retriever.bm25 is not None
        idf = retriever.bm25.idf
        shared = idf["学习"]  # bigram shared by two documents
        unique = idf["部署"]  # discriminative to a single document
        assert unique > shared > 0

    def test_zero_document_corpus_is_a_noop(self) -> None:
        retriever = BM25Retriever(["", "   "])
        assert retriever.bm25 is None


class TestSingleDocumentRecall:
    """A one-memory library must still recall on the discriminative query term."""

    def test_partial_name_query_recalls_the_only_document(self) -> None:
        retriever = BM25Retriever([_SINGLE_DOC])
        for query in ("奥利奥", "奥利", "猫", "我的猫叫什么名字", "深海蓝", "颜色"):
            hits = retriever.search(query, top_k=5, only_relevant=True)
            assert hits, f"query {query!r} lost recall on a single-document corpus"
            assert hits[0][0] == 0
            assert hits[0][1] > 0

    def test_unrelated_query_still_returns_nothing(self) -> None:
        retriever = BM25Retriever([_SINGLE_DOC])
        assert retriever.search("量子物理", top_k=5, only_relevant=True) == []

    def test_query_terms_absent_from_corpus_never_match(self) -> None:
        retriever = BM25Retriever([_SINGLE_DOC])
        assert retriever.search("区块链", top_k=5, only_relevant=True) == []


class TestMultiDocumentRankingUnchanged:
    """The fix must not disturb intended multi-document ranking."""

    def test_partial_match_still_ranks_source_document_first(self) -> None:
        retriever = BM25Retriever(_FIVE_DOCS)
        hits = retriever.search("模型部署", top_k=5, only_relevant=True)
        assert hits
        assert hits[0][0] == 0

    def test_tokenization_boundary_is_unchanged(self) -> None:
        assert "奥利" in preprocess_text("奥利奥")
