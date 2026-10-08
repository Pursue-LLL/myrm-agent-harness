"""Orchestrates zero-config SQLite FTS5, offline synonym expansion, adaptive RRF fusion, and circuit breaker.

[INPUT]
- collections.abc.Callable, logging, pathlib.Path
- toolkits.memory.hybrid_engine.circuit_breaker::EmbeddingCircuitBreaker
- toolkits.memory.hybrid_engine.models::AdaptiveRrfConfig, CircuitBreakerConfig, CircuitBreakerState,
  HybridEngineStats, HybridMemoryItem, HybridSearchResult, RetrievalMode
- toolkits.memory.hybrid_engine.reranker::AdaptiveRrfReranker
- toolkits.memory.hybrid_engine.sqlite_fts5_store::SqliteFts5Engine
- toolkits.memory.hybrid_engine.synonym_expander::OfflineSynonymExpander

[OUTPUT]
- DenseVectorProvider: Type alias for dense vector retrieval callable.
- DualDriveHybridMemoryEngine: Orchestrates hybrid retrieval and graceful circuit-breaker fallback.

[POS]
Item 133 DualEngineHybridSearchAndGracefulFallbackSuite.
Unified orchestrator for FTS5, semantic synonym expansion, dense vector embeddings,
Ebbinghaus recency decay, cognitive importance weighting, and circuit-breaker degradation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from myrm_agent_harness.toolkits.memory.hybrid_engine.circuit_breaker import EmbeddingCircuitBreaker
from myrm_agent_harness.toolkits.memory.hybrid_engine.models import (
    AdaptiveRrfConfig,
    CircuitBreakerConfig,
    CircuitBreakerState,
    HybridEngineStats,
    HybridMemoryItem,
    HybridSearchResult,
    RetrievalMode,
)
from myrm_agent_harness.toolkits.memory.hybrid_engine.reranker import AdaptiveRrfReranker
from myrm_agent_harness.toolkits.memory.hybrid_engine.sqlite_fts5_store import SqliteFts5Engine
from myrm_agent_harness.toolkits.memory.hybrid_engine.synonym_expander import OfflineSynonymExpander

logger = logging.getLogger(__name__)

DenseVectorProvider = Callable[[str, int], list[HybridSearchResult]]


class DualDriveHybridMemoryEngine:
    """Orchestrates zero-config SQLite FTS5, offline synonym expansion,

    dense vector embedding retrieval, adaptive RRF multi-factor reranking,
    and circuit-breaker protected zero-crash graceful degradation.
    """

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        dense_vector_provider: DenseVectorProvider | None = None,
        rrf_k: int = 60,
        circuit_breaker_config: CircuitBreakerConfig | None = None,
        adaptive_rrf_config: AdaptiveRrfConfig | None = None,
    ) -> None:
        self._fts_engine = SqliteFts5Engine(db_path=db_path)
        self._synonym_expander = OfflineSynonymExpander()
        self._vector_provider = dense_vector_provider
        self._circuit_breaker = EmbeddingCircuitBreaker(circuit_breaker_config)
        rrf_cfg = adaptive_rrf_config or AdaptiveRrfConfig(rrf_k=rrf_k)
        self._reranker = AdaptiveRrfReranker(rrf_cfg)

    @property
    def fts_engine(self) -> SqliteFts5Engine:
        return self._fts_engine

    @property
    def synonym_expander(self) -> OfflineSynonymExpander:
        return self._synonym_expander

    @property
    def circuit_breaker(self) -> EmbeddingCircuitBreaker:
        return self._circuit_breaker

    @property
    def reranker(self) -> AdaptiveRrfReranker:
        return self._reranker

    def set_dense_vector_provider(self, provider: DenseVectorProvider | None) -> None:
        """Inject or remove dense vector provider at runtime."""
        self._vector_provider = provider

    def trip_circuit_breaker(self, reason: str = "manual") -> None:
        """Force trip the embedding circuit breaker for disaster testing."""
        self._circuit_breaker.trip(reason=reason)

    def reset_circuit_breaker(self) -> None:
        """Force reset the embedding circuit breaker to normal CLOSED state."""
        self._circuit_breaker.reset()

    def insert_item(self, item: HybridMemoryItem) -> None:
        """Store item in the local FTS5 engine."""
        self._fts_engine.insert_or_replace_item(item)

    def delete_item(self, item_id: str) -> bool:
        """Delete item by ID."""
        return self._fts_engine.delete_item(item_id)

    def get_item(self, item_id: str) -> HybridMemoryItem | None:
        """Retrieve stored item by ID."""
        return self._fts_engine.get_item(item_id)

    def search(
        self,
        query: str,
        limit: int = 10,
        enable_vector: bool = True,
        override_rrf_config: AdaptiveRrfConfig | None = None,
    ) -> tuple[list[HybridSearchResult], RetrievalMode]:
        """Execute dual-drive search with automatic synonym expansion, circuit-breaker

        vector retrieval, adaptive multi-factor RRF reranking, and zero-crash degradation.
        """
        if not query.strip():
            return [], RetrievalMode.FTS_ONLY

        # 1. Expand query using offline semantic synonym graph and search FTS5
        fts5_expr, expanded_terms = self._synonym_expander.expand_query(query)
        fts_hits = self._fts_engine.search_fts(fts5_expr, limit=limit * 2) if fts5_expr else []
        for hit in fts_hits:
            hit.matched_terms = list(expanded_terms)

        # 2. Vector retrieval guarded by circuit breaker
        use_vector = bool(enable_vector and self._vector_provider is not None)
        vector_hits: list[HybridSearchResult] = []
        is_degraded = False
        degradation_reason = ""

        if use_vector and self._vector_provider:
            try:
                provider_fn = self._vector_provider
                vector_hits = self._circuit_breaker.execute(lambda: provider_fn(query, limit * 2))
            except Exception as ex:
                logger.warning(
                    "Dense vector retrieval tripped or failed (%s). Gracefully falling back to FTS5.",
                    ex,
                )
                is_degraded = True
                degradation_reason = str(ex)
                vector_hits = []

        # 3. Decision routing for degradation or pure FTS
        if not use_vector or is_degraded:
            active_mode = RetrievalMode.DEGRADED_FALLBACK if is_degraded else RetrievalMode.FTS_ONLY
            if is_degraded:
                for h in fts_hits:
                    h.source_channel = "fts_degraded"
                    h.is_degraded = True
                    h.degradation_reason = degradation_reason
            return fts_hits[:limit], active_mode

        if not fts_hits and not vector_hits:
            return [], RetrievalMode.HYBRID_RRF

        # 4. Adaptive RRF multi-factor reranking
        fused_results = self._reranker.fuse_and_rerank(
            fts_hits=fts_hits,
            vector_hits=vector_hits,
            limit=limit,
            override_config=override_rrf_config,
        )
        return fused_results, RetrievalMode.HYBRID_RRF

    def get_stats(self) -> HybridEngineStats:
        """Produce operational snapshot of the hybrid engine and circuit breaker."""
        cb_stats = self._circuit_breaker.get_stats()
        vector_available = self._vector_provider is not None
        if cb_stats.state == CircuitBreakerState.OPEN:
            active_mode = RetrievalMode.DEGRADED_FALLBACK
        elif vector_available:
            active_mode = RetrievalMode.HYBRID_RRF
        else:
            active_mode = RetrievalMode.FTS_ONLY

        return HybridEngineStats(
            total_items=self._fts_engine.count_items(),
            synonym_terms_count=self._synonym_expander.total_terms(),
            dense_vector_available=vector_available,
            active_mode=active_mode,
            db_path=self._fts_engine.db_path,
            circuit_breaker=cb_stats,
        )

    def close(self) -> None:
        """Close underlying database resources."""
        self._fts_engine.close()
