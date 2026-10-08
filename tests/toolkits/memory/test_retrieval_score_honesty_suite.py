"""Unit tests for retrieval score honesty: raw similarity vs ranking score decoupling (Item 142).

[INPUT]:
- myrm_agent_harness.toolkits.memory.types::{MemorySearchResult, SemanticMemory, MemoryType}
- myrm_agent_harness.toolkits.memory.retriever::MemoryRetriever
- myrm_agent_harness.toolkits.memory.config::RetrievalConfig

[OUTPUT]:
- Rigorous test coverage for raw_score retention, max-pooling across variants,
  zero-score fidelity, two-tier threshold admission guard, and backward compatibility.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.config import RetrievalConfig
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever
from myrm_agent_harness.toolkits.memory.types import (
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)


def _make_candidate(
    mid: str,
    content: str,
    score: float,
    raw_score: float | None = None,
) -> MemorySearchResult:
    """Helper to create a MemorySearchResult candidate with optional raw_score."""
    mem = SemanticMemory(id=mid, content=content)
    data: dict[str, object] = {
        "memory": mem,
        "score": score,
        "memory_type": MemoryType.SEMANTIC,
    }
    if raw_score is not None:
        data["raw_score"] = raw_score
    return MemorySearchResult(**data)  # type: ignore[arg-type]


def test_single_query_score_honesty_and_defaults() -> None:
    """In single query path without boost/fusion, raw_score defaults to input score and matches ranking_score."""
    retriever = MemoryRetriever(config=RetrievalConfig(min_relevance_score=0.0))
    cand_a = _make_candidate("a", "Alpha content", 0.85)
    cand_b = _make_candidate("b", "Beta content", 0.40)

    results = retriever.rank([cand_a, cand_b], query="Alpha")
    assert len(results) == 2

    top = results[0]
    assert top.id == "a"
    assert top.raw_score == pytest.approx(0.85, rel=1e-3)
    assert top.raw_similarity == pytest.approx(0.85, rel=1e-3)
    assert top.ranking_score == pytest.approx(1.0, rel=1e-3)  # Top ranked normalized to 1.0
    assert top.score == top.ranking_score


def test_multi_query_max_pooling_retains_highest_raw_score() -> None:
    """When the same candidate appears across multiple variants, retain the highest raw score seen."""
    retriever = MemoryRetriever(config=RetrievalConfig(rrf_k=60, min_relevance_score=0.0))

    # Candidate 'doc_1' has varying raw similarities across three query variants: 0.42, 0.91, 0.55
    variant_1 = [_make_candidate("doc_1", "Target document", score=0.42, raw_score=0.42)]
    variant_2 = [_make_candidate("doc_1", "Target document", score=0.91, raw_score=0.91)]
    variant_3 = [_make_candidate("doc_1", "Target document", score=0.55, raw_score=0.55)]

    fused = retriever.fuse([variant_1, variant_2, variant_3], query="Target document")
    assert len(fused) == 1

    result = fused[0]
    assert result.id == "doc_1"
    # Even though RRF fused score is relative, raw_score must faithfully preserve 0.91 (highest seen)
    assert result.raw_score == pytest.approx(0.91, rel=1e-3)
    assert result.raw_similarity == pytest.approx(0.91, rel=1e-3)
    assert result.recall_debug is not None
    assert result.recall_debug.raw_score == pytest.approx(0.91, rel=1e-3)


def test_zero_raw_score_fidelity_under_recency_and_rrf() -> None:
    """A raw similarity of 0.0 must be preserved honestly and not distorted by normalization."""
    retriever = MemoryRetriever(config=RetrievalConfig(min_relevance_score=0.0))
    cand_zero = _make_candidate("zero_cand", "Zero similarity item", score=0.0, raw_score=0.0)

    results = retriever.rank([cand_zero], query="Unrelated search")
    assert len(results) == 1
    assert results[0].raw_score == 0.0
    assert results[0].raw_similarity == 0.0


def test_two_tier_admission_threshold_filters_raw_noise_without_rrf_kill() -> None:
    """Similarity threshold filters based on raw_score and does not kill RRF scores (ADR-090 Finding B)."""
    # Configure similarity_threshold = 0.50
    config = RetrievalConfig(rrf_k=60, min_relevance_score=0.0, raw_similarity_threshold=0.50)
    retriever = MemoryRetriever(config=config)

    # Variant returns doc_high (raw 0.85) and doc_low (raw 0.20)
    c_high = _make_candidate("high", "High relevance doc", score=0.85, raw_score=0.85)
    c_low = _make_candidate("low", "Low relevance noise", score=0.20, raw_score=0.20)

    fused = retriever.fuse([[c_high, c_low]], query="High relevance")
    assert len(fused) == 1
    assert fused[0].id == "high"
    assert fused[0].raw_score == pytest.approx(0.85, rel=1e-3)

    # RRF score is tiny (1/61 approx 0.01639), but it is NOT killed by similarity_threshold
    assert fused[0].ranking_score == pytest.approx(1.0, rel=1e-3)


def test_two_tier_admission_threshold_top1_fallback() -> None:
    """When all candidates fall below raw_similarity_threshold, preserve the best candidate (top-1 fallback)."""
    config = RetrievalConfig(rrf_k=60, min_relevance_score=0.0, raw_similarity_threshold=0.70)
    retriever = MemoryRetriever(config=config)

    c1 = _make_candidate("c1", "Candidate 1", score=0.40, raw_score=0.40)
    c2 = _make_candidate("c2", "Candidate 2", score=0.60, raw_score=0.60)

    # Both 0.40 and 0.60 are below 0.70, but top-1 fallback preserves c2
    fused = retriever.fuse([[c1, c2]], query="Test query")
    assert len(fused) == 1
    assert fused[0].id == "c2"
    assert fused[0].raw_score == pytest.approx(0.60, rel=1e-3)


def test_serialization_and_backward_compatibility() -> None:
    """MemorySearchResult.model_dump() must contain score, raw_score, raw_similarity, and ranking_score."""
    cand = _make_candidate("test_id", "Compatibility test", score=0.75, raw_score=0.75)
    dumped = cand.model_dump()

    assert dumped["score"] == 0.75
    assert dumped["raw_score"] == 0.75
    assert dumped["raw_similarity"] == 0.75
    assert dumped["ranking_score"] == 0.75
