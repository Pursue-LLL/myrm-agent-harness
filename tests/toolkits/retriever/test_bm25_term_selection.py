"""Tests for IDF-aware BM25 query term selection."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.retriever.bm25 import (
    select_selective_bm25_tokens,
)
from myrm_agent_harness.toolkits.retriever.bm25_retrieval import (
    BM25Retriever,
    bm25_retrieval,
)


class TestBm25TermSelection:
    """Unit tests for select_selective_bm25_tokens."""

    def test_short_query_untouched(self) -> None:
        tokens = ["database", "lock", "timeout"]
        idf = {"database": 0.5, "lock": 1.2, "timeout": 2.1}
        result = select_selective_bm25_tokens(tokens, idf, doc_count=20, max_terms=5)
        assert result == tokens

    def test_empty_tokens(self) -> None:
        assert select_selective_bm25_tokens([], {"a": 1.0}, doc_count=10) == []

    def test_cold_start_small_corpus_preserves_order(self) -> None:
        # Less than min_corpus_docs (default 5): should fallback to head truncation without sorting by skewed idf
        tokens = [f"t{i}" for i in range(20)]
        idf = {f"t{i}": float(i) for i in range(20)}
        result = select_selective_bm25_tokens(tokens, idf, doc_count=3, max_terms=10, min_corpus_docs=5)
        assert len(result) == 10
        assert result == tokens[:10]

    def test_prunes_low_idf_common_words_pure_idf(self) -> None:
        # High IDF = rare / specific; Low IDF = ubiquitous / noise (with protect_leading_terms=0)
        tokens = ["the", "error", "occurred", "in", "sqlite_wal_checkpoint", "during", "transaction"]
        idf = {
            "the": 0.05,
            "error": 0.2,
            "occurred": 0.3,
            "in": 0.08,
            "sqlite_wal_checkpoint": 3.8,
            "during": 0.15,
            "transaction": 1.9,
        }
        # Keep top 3 tokens without leading protection
        selected = select_selective_bm25_tokens(
            tokens, idf, doc_count=50, max_terms=3, protect_leading_terms=0
        )
        assert len(selected) == 3
        # Should keep sqlite_wal_checkpoint (3.8), transaction (1.9), occurred (0.3)
        assert "sqlite_wal_checkpoint" in selected
        assert "transaction" in selected
        assert "occurred" in selected
        # Relative order from original tokens must be preserved
        assert selected == ["occurred", "sqlite_wal_checkpoint", "transaction"]

    def test_protect_leading_terms_intent(self) -> None:
        # By default protect_leading_terms=2: the first 2 words are unconditionally retained for intent
        tokens = ["how", "to", "fix", "memory_leak", "in", "qdrant_vector_store"]
        idf = {
            "how": 0.05,
            "to": 0.01,
            "fix": 0.1,
            "memory_leak": 2.8,
            "in": 0.02,
            "qdrant_vector_store": 4.1,
        }
        # max_terms=4: 2 leading tokens ("how", "to") + top 2 high-IDF ("qdrant_vector_store", "memory_leak")
        selected = select_selective_bm25_tokens(tokens, idf, doc_count=30, max_terms=4)
        assert len(selected) == 4
        assert selected == ["how", "to", "memory_leak", "qdrant_vector_store"]

    def test_unseen_tokens_lower_priority_than_discriminative_words(self) -> None:
        # In sparse matching, an unseen typo shouldn't displace in-corpus discriminative words
        tokens = ["explain", "issue", "novel_unseen_x199", "another", "specific_term"]
        idf = {
            "explain": 0.1,
            "issue": 0.2,
            "another": 0.15,
            "specific_term": 2.5,
        }
        # With protect_leading_terms=0, specific_term and issue are preferred over unseen token
        selected = select_selective_bm25_tokens(
            tokens, idf, doc_count=20, max_terms=2, protect_leading_terms=0
        )
        assert len(selected) == 2
        assert "specific_term" in selected
        assert "issue" in selected

    def test_all_unseen_tokens_graceful_retention(self) -> None:
        # If all tokens are unseen, head truncation ensures graceful degradation
        tokens = ["unseen_a", "unseen_b", "unseen_c", "unseen_d"]
        selected = select_selective_bm25_tokens(tokens, {}, doc_count=20, max_terms=2)
        assert selected == ["unseen_a", "unseen_b"]


class TestBm25RetrieverIntegration:
    """Integration tests for BM25Retriever with term selection enabled."""

    def test_retriever_search_with_long_query(self) -> None:
        docs = [
            "Python asyncio event loop exception handling and task cancellation in coroutine",
            "SQLite database locked operational error during busy handler timeout and WAL journal checkpoint",
            "FastAPI request dependency injection and Pydantic schema validation pipeline",
            "Docker container sandbox volume mount permissions and resource constraints",
            "PostgreSQL connection pool max overflow and transaction isolation level",
            "Redis cache eviction LRU policy memory limit key expiry ttl",
        ]
        retriever = BM25Retriever(docs)

        # Long query with many generic words + specific sqlite wal words
        long_query = (
            "can you please tell me what is the reason for sqlite database locked operational error "
            "during busy handler timeout when we have concurrent read and write operations in wal journal checkpoint"
        )

        results = retriever.search(long_query, top_k=3, max_query_terms=6)
        assert len(results) > 0
        top_idx, top_score = results[0]
        # Document 1 (SQLite) should be ranked highest despite long verbose query
        assert top_idx == 1
        assert top_score > 0.0

    def test_one_shot_bm25_retrieval_wrapper(self) -> None:
        docs = [
            "Alpha architecture doc and design system",
            "Beta backend implementation and database connection",
            "Gamma gateway routing and reverse proxy",
            "Delta deployment pipeline and continuous delivery",
            "Epsilon embedding model and vector search",
        ]
        results = bm25_retrieval(
            docs,
            "find information about Delta deployment pipeline and continuous delivery",
            top_k=2,
            max_query_terms=6,
        )
        assert len(results) > 0
        assert results[0][0] == 3  # Delta deployment
