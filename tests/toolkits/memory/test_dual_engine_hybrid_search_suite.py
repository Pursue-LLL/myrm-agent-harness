"""Unit tests for dual-engine hybrid search and graceful fallback suite.

[POS]
Unit test verifying lexical sanitization, BM25 normalization, recency decay,
MMR diversity, adaptive circuit breaking, and sub-5ms graceful fallback.

[INPUT]
- asyncio, pytest
- myrm_agent_harness.toolkits.memory.hybrid_search (
    AdaptiveCircuitBreaker,
    CircuitState,
    DualEngineHybridSearcher,
    FallbackReason,
    HybridSearchHit,
    HybridSearchQuery,
    SearchMode,
    apply_mmr,
    apply_token_budget,
    bm25_to_score,
    compute_recency_decay,
    sanitize_fts_query,
  )

[OUTPUT]
- Test functions validating hybrid search suite resilience.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.hybrid_search import (
    AdaptiveCircuitBreaker,
    CircuitState,
    DualEngineHybridSearcher,
    FallbackReason,
    HybridSearchHit,
    HybridSearchQuery,
    SearchMode,
    apply_mmr,
    apply_token_budget,
    bm25_to_score,
    compute_recency_decay,
    sanitize_fts_query,
)


def test_sanitize_fts_query_and_bm25_normalization() -> None:
    """Verify rogue FTS operators are sanitized and BM25 scores are normalized."""
    # 1. Test FTS syntax sanitization
    raw_dirty = 'SELECT * FROM memory WHERE error: [SQLITE_BUSY] OR "test" (1=1)'
    sanitized = sanitize_fts_query(raw_dirty)
    assert sanitized is not None
    assert '"SELECT"' in sanitized
    assert '"SQLITE_BUSY"' in sanitized
    assert ":" not in sanitized
    assert "[" not in sanitized

    # Empty / whitespace queries
    assert sanitize_fts_query("") is None
    assert sanitize_fts_query("   --- *** ") is None

    # 2. Test BM25 rank to score normalization
    score_best = bm25_to_score(-4.5)
    score_mid = bm25_to_score(-1.0)
    score_low = bm25_to_score(-0.2)
    score_zero = bm25_to_score(0.0)

    assert 0.0 < score_low < score_mid < score_best < 1.0
    assert score_zero == 1.0  # Zero distance is maximum similarity


def test_recency_decay_and_mmr_diversity() -> None:
    """Verify temporal half-life decay, MMR redundancy reduction, and token budget."""
    now = datetime.now(UTC)
    now_ts = now.timestamp()
    iso_fresh = now.isoformat()
    iso_old = (now - timedelta(days=30)).isoformat()
    iso_ancient = (now - timedelta(days=90)).isoformat()

    # 1. Recency decay check
    decay_fresh = compute_recency_decay(iso_fresh, half_life_days=30.0, now_ts=now_ts)
    decay_old = compute_recency_decay(iso_old, half_life_days=30.0, now_ts=now_ts)
    decay_ancient = compute_recency_decay(iso_ancient, half_life_days=30.0, now_ts=now_ts)

    assert decay_fresh == 1.0
    assert pytest.approx(decay_old, abs=0.05) == 0.5
    assert decay_ancient < 0.25

    # 2. MMR diversity check
    hits = [
        HybridSearchHit(
            item_id="1",
            title="A1",
            content="Database connection timeout retry configuration",
            score=0.9,
        ),
        HybridSearchHit(
            item_id="2",
            title="A2",
            content="Database connection timeout retry parameter setting",  # Near identical
            score=0.88,
        ),
        HybridSearchHit(
            item_id="3",
            title="B1",
            content="Authentication token expiry policy and refresh mechanism",  # Distinct topic
            score=0.80,
        ),
    ]

    selected = apply_mmr(hits, lambda_param=0.6, top_k=2)
    assert len(selected) == 2
    # Item 1 is highest relevance; Item 3 should be selected next due to MMR diversity over Item 2
    assert selected[0].item_id == "1"
    assert selected[1].item_id == "3"

    # 3. Token budget check
    budget_hits = apply_token_budget(hits, max_tokens=25, chars_per_token=3.0)
    assert 1 <= len(budget_hits) <= 2


def test_circuit_breaker_tri_state_transitions() -> None:
    """Verify circuit breaker CLOSED -> OPEN -> HALF_OPEN -> CLOSED cycle."""
    breaker = AdaptiveCircuitBreaker(failure_threshold=2, recovery_timeout_seconds=0.1)
    assert breaker.state == CircuitState.CLOSED
    assert breaker.should_allow_request() is True

    # 1. Trigger failures to trip to OPEN
    breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    assert breaker.should_allow_request() is False

    # 2. Advance time past recovery timeout
    breaker._last_state_change -= 0.2  # Simulate elapsed timeout
    assert breaker.state == CircuitState.HALF_OPEN
    assert breaker.should_allow_request() is True

    # 3. Successful probe heals to CLOSED
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0


@pytest.mark.asyncio
async def test_dual_engine_parallel_hybrid_search() -> None:
    """Verify normal concurrent hybrid search fuses lexical and vector scores."""
    async def mock_fts(query: str, limit: int) -> list[HybridSearchHit]:
        return [
            HybridSearchHit(
                item_id="doc_1",
                title="Doc 1",
                content="sqlite lock issue",
                score=0.6,
                text_score=0.6,
                exact_match=True,
                created_at=datetime.now(UTC).isoformat(),
            )
        ]

    async def mock_vector(query: str, limit: int) -> list[HybridSearchHit]:
        return [
            HybridSearchHit(
                item_id="doc_1",
                title="Doc 1",
                content="sqlite lock issue",
                score=0.8,
                vector_score=0.8,
            ),
            HybridSearchHit(
                item_id="doc_2",
                title="Doc 2",
                content="concurrent transaction management",
                score=0.7,
                vector_score=0.7,
            ),
        ]

    searcher = DualEngineHybridSearcher(fts_provider=mock_fts, vector_provider=mock_vector)
    query = HybridSearchQuery(query_text="sqlite lock", top_k=5, vector_weight=0.6, text_weight=0.4)

    hits, report = await searcher.search(query)

    assert report.mode == SearchMode.HYBRID
    assert report.fallback_reason == FallbackReason.NONE
    assert len(hits) == 2
    # doc_1 combines vector (0.8 * 0.6 = 0.48) + text (0.6 * 0.4 = 0.24) = 0.72 with exact match boost
    assert hits[0].item_id == "doc_1"
    assert hits[0].score > 0.72


@pytest.mark.asyncio
async def test_graceful_fallback_on_provider_timeout_and_error() -> None:
    """Verify engine immediately falls back to FTS with calibrated threshold on timeout."""
    async def mock_fts(query: str, limit: int) -> list[HybridSearchHit]:
        return [
            HybridSearchHit(
                item_id="doc_fts",
                title="FTS hit",
                content="Local notes on SQLITE_BUSY error code",
                score=0.25,
                text_score=0.25,
                created_at=datetime.now(UTC).isoformat(),
            )
        ]

    async def mock_vector_hangs(query: str, limit: int) -> list[HybridSearchHit]:
        await asyncio.sleep(1.0)
        return []

    searcher = DualEngineHybridSearcher(fts_provider=mock_fts, vector_provider=mock_vector_hangs)
    # Query with short timeout
    query = HybridSearchQuery(
        query_text="SQLITE_BUSY",
        top_k=5,
        min_score=0.35,  # Higher than 0.25, but adaptive threshold prevents drop
        timeout_seconds=0.05,
    )

    hits, report = await searcher.search(query)

    assert report.mode == SearchMode.FALLBACK_FTS
    assert report.fallback_reason == FallbackReason.PROVIDER_TIMEOUT
    assert len(hits) == 1
    assert hits[0].item_id == "doc_fts"
    assert searcher.circuit_breaker.failure_count == 1


@pytest.mark.asyncio
async def test_unconfigured_vector_provider_fts_only() -> None:
    """Verify search executes purely in FTS_ONLY mode when no vector provider bound."""
    async def mock_fts(query: str, limit: int) -> list[HybridSearchHit]:
        return [
            HybridSearchHit(
                item_id="local_1",
                title="Local Config",
                content="Offline local environment notes",
                score=0.3,
                text_score=0.3,
            )
        ]

    searcher = DualEngineHybridSearcher(fts_provider=mock_fts, vector_provider=None)
    query = HybridSearchQuery(query_text="offline notes", top_k=5)

    hits, report = await searcher.search(query)

    assert report.mode == SearchMode.FTS_ONLY
    assert report.fallback_reason == FallbackReason.PROVIDER_UNCONFIGURED
    assert len(hits) == 1
    assert hits[0].item_id == "local_1"
