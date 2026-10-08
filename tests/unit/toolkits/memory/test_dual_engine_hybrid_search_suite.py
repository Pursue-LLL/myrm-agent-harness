"""Unit test suite for Item 133 DualEngineHybridSearchAndGracefulFallbackSuite.

Verifies:
1. EmbeddingCircuitBreaker state transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED/OPEN).
2. AdaptiveRrfReranker multi-factor fusion, Ebbinghaus recency decay, and importance boost.
3. DualDriveHybridMemoryEngine seamless graceful degradation from vector failure to SQLite FTS5.
4. Circuit breaker telemetry snapshot and manual control.
"""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.toolkits.memory.hybrid_engine.circuit_breaker import (
    CircuitBreakerOpenError,
    EmbeddingCircuitBreaker,
)
from myrm_agent_harness.toolkits.memory.hybrid_engine.dual_drive_engine import (
    DualDriveHybridMemoryEngine,
)
from myrm_agent_harness.toolkits.memory.hybrid_engine.models import (
    AdaptiveRrfConfig,
    CircuitBreakerConfig,
    CircuitBreakerState,
    HybridMemoryItem,
    HybridSearchResult,
    RetrievalMode,
)
from myrm_agent_harness.toolkits.memory.hybrid_engine.reranker import (
    AdaptiveRrfReranker,
)


def test_circuit_breaker_state_transitions() -> None:
    """Verify circuit breaker lifecycle, trip thresholds, and half-open probes."""
    cfg = CircuitBreakerConfig(
        failure_threshold=2,
        recovery_timeout_seconds=0.1,  # Fast probe for test
        timeout_seconds=1.0,
    )
    cb = EmbeddingCircuitBreaker(config=cfg)

    assert cb.state == CircuitBreakerState.CLOSED

    # 1. First failure keeps it closed
    def fail_func() -> str:
        raise ConnectionResetError("Provider unreachable")

    with pytest.raises(ConnectionResetError):
        cb.execute(fail_func)
    assert cb.state == CircuitBreakerState.CLOSED
    assert cb.get_stats().failure_count == 1

    # 2. Second failure trips to OPEN
    with pytest.raises(ConnectionResetError):
        cb.execute(fail_func)
    assert cb.state == CircuitBreakerState.OPEN
    assert cb.get_stats().tripped_count == 1

    # 3. Subsequent call while OPEN fails fast with CircuitBreakerOpenError
    t0 = time.perf_counter()
    with pytest.raises(CircuitBreakerOpenError):
        cb.execute(lambda: "never_called")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 5.0  # Fast-fail short circuit (< 5ms)

    # 4. Wait for recovery timeout to transition to HALF_OPEN
    time.sleep(0.12)
    assert cb.state == CircuitBreakerState.HALF_OPEN

    # 5. Successful probe in HALF_OPEN recovers to CLOSED
    result = cb.execute(lambda: "healthy_vector")
    assert result == "healthy_vector"
    assert cb.state == CircuitBreakerState.CLOSED
    assert cb.get_stats().failure_count == 0


def test_circuit_breaker_half_open_failure_re_trips() -> None:
    """Verify failed probe in HALF_OPEN immediately re-trips breaker to OPEN."""
    cfg = CircuitBreakerConfig(
        failure_threshold=1,
        recovery_timeout_seconds=0.05,
    )
    cb = EmbeddingCircuitBreaker(config=cfg)

    # Trip to OPEN
    with pytest.raises(RuntimeError):
        cb.execute(lambda: (_ for _ in ()).throw(RuntimeError("Outage")))
    assert cb.state == CircuitBreakerState.OPEN

    # Wait for HALF_OPEN
    time.sleep(0.06)
    assert cb.state == CircuitBreakerState.HALF_OPEN

    # Probe fails -> immediately re-trips to OPEN
    with pytest.raises(RuntimeError):
        cb.execute(lambda: (_ for _ in ()).throw(RuntimeError("Still dead")))
    assert cb.state == CircuitBreakerState.OPEN
    assert cb.get_stats().tripped_count == 2


def test_adaptive_rrf_reranker_multichannel_and_factors() -> None:
    """Verify RRF fusion combines FTS and Vector hits with recency and importance."""
    cfg = AdaptiveRrfConfig(
        rrf_k=10,
        fts_weight=1.0,
        vector_weight=1.0,
        importance_weight=0.5,
        half_life_seconds=100.0,
        apply_recency_decay=True,
    )
    reranker = AdaptiveRrfReranker(config=cfg)

    current_t = 1000.0
    # Document 1: Hit by both FTS (rank 1) and Vector (rank 1), fresh (t=1000), normal importance (0.5)
    doc1_fts = HybridSearchResult(
        item_id="doc1",
        title="Doc 1",
        content="Dual hit content",
        score=1.0,
        source_channel="fts",
        rank=1,
        importance=0.5,
        timestamp=current_t,
    )
    doc1_vec = HybridSearchResult(
        item_id="doc1",
        title="Doc 1",
        content="Dual hit content",
        score=0.9,
        source_channel="vector",
        rank=1,
        importance=0.5,
        timestamp=current_t,
    )

    # Document 2: Hit by FTS only (rank 2), high importance (1.0), fresh
    doc2_fts = HybridSearchResult(
        item_id="doc2",
        title="Doc 2",
        content="High importance FTS only",
        score=0.8,
        source_channel="fts",
        rank=2,
        importance=1.0,
        timestamp=current_t,
    )

    # Document 3: Hit by Vector (rank 2), low importance (0.1), stale (t=700, 3 half-lives old)
    doc3_vec = HybridSearchResult(
        item_id="doc3",
        title="Doc 3",
        content="Stale vector hit",
        score=0.85,
        source_channel="vector",
        rank=2,
        importance=0.1,
        timestamp=current_t - 300.0,
    )

    results = reranker.fuse_and_rerank(
        fts_hits=[doc1_fts, doc2_fts],
        vector_hits=[doc1_vec, doc3_vec],
        limit=5,
        now=current_t,
    )

    assert len(results) == 3
    # doc1 is dual hit + fresh, must be rank 1
    assert results[0].item_id == "doc1"
    assert results[0].source_channel == "rrf_hybrid"
    assert results[0].rank == 1

    # doc2 has importance boost (1.0 + 0.5 * 0.5 = 1.25)
    # doc3 has recency decay (2^-3 = 0.125) and low importance (1.0 - 0.2 = 0.8)
    assert results[1].item_id == "doc2"
    assert results[2].item_id == "doc3"
    assert results[2].recency_factor < 0.2


def test_dual_drive_engine_hybrid_search_and_graceful_degradation() -> None:
    """Verify dual drive engine graceful fallback from vector failure to FTS5."""
    engine = DualDriveHybridMemoryEngine(
        circuit_breaker_config=CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=0.1)
    )

    # Insert items
    now = time.time()
    item1 = HybridMemoryItem(
        item_id="m1",
        title="PostgreSQL Optimization",
        content="Tuning vacuum and work_mem buffer settings.",
        tags=["database", "performance"],
        importance=0.8,
        timestamp=now,
    )
    item2 = HybridMemoryItem(
        item_id="m2",
        title="Redis Caching Patterns",
        content="Cache-aside and write-through cache patterns.",
        tags=["database", "cache"],
        importance=0.6,
        timestamp=now - 50.0,
    )
    engine.insert_item(item1)
    engine.insert_item(item2)

    # Scenario 1: No vector provider injected -> FTS_ONLY mode
    hits, mode = engine.search("database", limit=5)
    assert mode == RetrievalMode.FTS_ONLY
    assert len(hits) == 2

    # Scenario 2: Inject healthy vector provider -> HYBRID_RRF mode
    def mock_vector_provider(query: str, limit: int) -> list[HybridSearchResult]:
        return [
            HybridSearchResult(
                item_id="m1",
                title="PostgreSQL Optimization",
                content="Tuning vacuum and work_mem buffer settings.",
                score=0.92,
                source_channel="vector",
                rank=1,
                importance=0.8,
                timestamp=now,
            )
        ]

    engine.set_dense_vector_provider(mock_vector_provider)
    hits, mode = engine.search("database", limit=5)
    assert mode == RetrievalMode.HYBRID_RRF
    assert len(hits) == 2
    assert hits[0].source_channel == "rrf_hybrid"
    assert hits[0].item_id == "m1"

    # Scenario 3: Provider raises exception -> Graceful fallback to DEGRADED_FALLBACK
    call_count = 0

    def flaky_vector_provider(query: str, limit: int) -> list[HybridSearchResult]:
        nonlocal call_count
        call_count += 1
        raise TimeoutError("Vector embedding RPC timeout")

    engine.set_dense_vector_provider(flaky_vector_provider)
    hits, mode = engine.search("database", limit=5)
    assert mode == RetrievalMode.DEGRADED_FALLBACK
    assert len(hits) == 2
    assert hits[0].is_degraded is True
    assert "Vector embedding RPC timeout" in hits[0].degradation_reason
    assert hits[0].source_channel == "fts_degraded"

    # Second failure trips circuit breaker
    hits, mode = engine.search("database", limit=5)
    assert mode == RetrievalMode.DEGRADED_FALLBACK
    stats = engine.get_stats()
    assert stats.circuit_breaker.state == CircuitBreakerState.OPEN
    assert stats.active_mode == RetrievalMode.DEGRADED_FALLBACK

    # Subsequent search fast-fails vector without invoking flaky provider again
    prior_calls = call_count
    hits, mode = engine.search("database", limit=5)
    assert call_count == prior_calls  # No further provider invocations
    assert mode == RetrievalMode.DEGRADED_FALLBACK

    # Scenario 4: Reset circuit breaker and restore healthy provider
    engine.reset_circuit_breaker()
    engine.set_dense_vector_provider(mock_vector_provider)
    hits, mode = engine.search("database", limit=5)
    assert mode == RetrievalMode.HYBRID_RRF
    assert hits[0].is_degraded is False

    engine.close()


def test_manual_trip_and_stats_telemetry() -> None:
    """Verify manual trip, reset, and stats snapshot."""
    engine = DualDriveHybridMemoryEngine()
    stats = engine.get_stats()
    assert stats.circuit_breaker.state == CircuitBreakerState.CLOSED

    engine.trip_circuit_breaker(reason="Disaster simulation test")
    stats = engine.get_stats()
    assert stats.circuit_breaker.state == CircuitBreakerState.OPEN
    assert stats.circuit_breaker.tripped_count == 1
    assert stats.active_mode == RetrievalMode.DEGRADED_FALLBACK

    engine.reset_circuit_breaker()
    stats = engine.get_stats()
    assert stats.circuit_breaker.state == CircuitBreakerState.CLOSED

    engine.close()
