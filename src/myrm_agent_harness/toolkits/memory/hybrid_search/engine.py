"""Dual-engine hybrid searcher orchestrating parallel retrieval and graceful fallback.

[POS]
Orchestration engine coordinating SQLite FTS5 lexical recall, embedding vector
similarity, circuit-breaking resilience, adaptive threshold calibration, and MMR re-ranking.

[INPUT]
- asyncio, time
- collections.abc.Awaitable, collections.abc.Callable
- .models (CircuitState, FallbackReason, HybridSearchHit, HybridSearchQuery, HybridSearchReport, SearchMode)
- .circuit_breaker (AdaptiveCircuitBreaker)
- .ranker (apply_mmr, apply_token_budget, compute_recency_decay)

[OUTPUT]
- DualEngineHybridSearcher
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from myrm_agent_harness.toolkits.memory.hybrid_search.circuit_breaker import (
    AdaptiveCircuitBreaker,
)
from myrm_agent_harness.toolkits.memory.hybrid_search.models import (
    FallbackReason,
    HybridSearchHit,
    HybridSearchQuery,
    HybridSearchReport,
    SearchMode,
)
from myrm_agent_harness.toolkits.memory.hybrid_search.ranker import (
    apply_mmr,
    apply_token_budget,
    compute_recency_decay,
)

FtsProviderFunc = Callable[[str, int], Awaitable[list[HybridSearchHit]]]
VectorProviderFunc = Callable[[str, int], Awaitable[list[HybridSearchHit]]]


class DualEngineHybridSearcher:
    """Coordinates dual FTS5 and vector retrieval with fault-tolerant circuit breaking."""

    def __init__(
        self,
        fts_provider: FtsProviderFunc,
        vector_provider: VectorProviderFunc | None = None,
        circuit_breaker: AdaptiveCircuitBreaker | None = None,
    ) -> None:
        """Initialize hybrid searcher with retrieval providers and circuit breaker."""
        self._fts_provider = fts_provider
        self._vector_provider = vector_provider
        self._circuit_breaker = circuit_breaker or AdaptiveCircuitBreaker()

    @property
    def circuit_breaker(self) -> AdaptiveCircuitBreaker:
        """Access underlying circuit breaker."""
        return self._circuit_breaker

    async def search(
        self, query: HybridSearchQuery
    ) -> tuple[list[HybridSearchHit], HybridSearchReport]:
        """Execute parallel hybrid retrieval with automatic fallback and reranking."""
        start_time = time.perf_counter()
        fts_start = time.perf_counter()
        fts_hits: list[HybridSearchHit] = []
        vector_hits: list[HybridSearchHit] = []
        fts_latency_ms = 0.0
        vector_latency_ms = 0.0

        fallback_reason = FallbackReason.NONE
        effective_mode = SearchMode.HYBRID

        candidate_k = max(query.top_k * 4, 20)

        # 1. Determine vector capability and circuit status
        vector_permitted = False
        if self._vector_provider is None:
            effective_mode = SearchMode.FTS_ONLY
            fallback_reason = FallbackReason.PROVIDER_UNCONFIGURED
        elif not self._circuit_breaker.should_allow_request():
            effective_mode = SearchMode.FALLBACK_FTS
            fallback_reason = FallbackReason.CIRCUIT_OPEN
        else:
            vector_permitted = True

        # 2. Parallel or isolated retrieval
        if vector_permitted and self._vector_provider is not None:
            async def _run_vector() -> list[HybridSearchHit]:
                v_provider = self._vector_provider
                assert v_provider is not None
                return await v_provider(query.query_text, candidate_k)

            v_start = time.perf_counter()
            fts_task = asyncio.create_task(self._fts_provider(query.query_text, candidate_k))
            vector_task = asyncio.create_task(_run_vector())

            # Wait for FTS
            fts_hits = await fts_task
            fts_latency_ms = (time.perf_counter() - fts_start) * 1000.0

            # Guard vector call with strict timeout
            try:
                vector_hits = await asyncio.wait_for(vector_task, timeout=query.timeout_seconds)
                vector_latency_ms = (time.perf_counter() - v_start) * 1000.0
                self._circuit_breaker.record_success()
            except TimeoutError:
                vector_latency_ms = (time.perf_counter() - v_start) * 1000.0
                self._circuit_breaker.record_failure()
                effective_mode = SearchMode.FALLBACK_FTS
                fallback_reason = FallbackReason.PROVIDER_TIMEOUT
                vector_hits = []
            except Exception:
                vector_latency_ms = (time.perf_counter() - v_start) * 1000.0
                self._circuit_breaker.record_failure()
                effective_mode = SearchMode.FALLBACK_FTS
                fallback_reason = FallbackReason.PROVIDER_ERROR
                vector_hits = []
        else:
            # FTS only path
            fts_hits = await self._fts_provider(query.query_text, candidate_k)
            fts_latency_ms = (time.perf_counter() - fts_start) * 1000.0

        # 3. Fuse scores and apply adaptive threshold
        merged_map: dict[str, HybridSearchHit] = {}

        # Merge vector hits
        for vh in vector_hits:
            vh.score = vh.vector_score * query.vector_weight
            merged_map[vh.item_id] = vh

        # Merge or add FTS hits
        for fh in fts_hits:
            if fh.item_id in merged_map:
                existing = merged_map[fh.item_id]
                existing.text_score = fh.text_score
                existing.exact_match = fh.exact_match
                # Combined weighted score
                existing.score = (
                    query.vector_weight * existing.vector_score
                    + query.text_weight * fh.text_score
                )
            else:
                if effective_mode in (SearchMode.FALLBACK_FTS, SearchMode.FTS_ONLY):
                    fh.score = fh.text_score
                else:
                    fh.score = query.text_weight * fh.text_score
                merged_map[fh.item_id] = fh

        # 4. Multi-factor re-ranking: temporal decay + importance + exact phrase boost
        fused_hits: list[HybridSearchHit] = []
        for hit in merged_map.values():
            decay = compute_recency_decay(
                hit.created_at, half_life_days=query.recency_half_life_days
            )
            exact_boost = query.exact_phrase_boost if hit.exact_match else 1.0
            importance_boost = max(0.2, query.importance_multiplier)

            # Unified mathematical score form
            hit.score = hit.score * decay * importance_boost * exact_boost
            fused_hits.append(hit)

        # 5. Adaptive threshold calibration
        if effective_mode in (SearchMode.FALLBACK_FTS, SearchMode.FTS_ONLY):
            # Scale down threshold to prevent filtering out all results during fallback
            effective_min_score = min(query.min_score * 0.4, 0.10)
        else:
            effective_min_score = query.min_score

        qualified_hits = [h for h in fused_hits if h.score >= effective_min_score]
        qualified_hits.sort(key=lambda x: x.score, reverse=True)

        # 6. Diversity re-ranking (MMR)
        diverse_hits = apply_mmr(
            qualified_hits,
            lambda_param=query.mmr_lambda,
            top_k=query.top_k,
        )

        # 7. Context token budget enforcement
        final_hits = apply_token_budget(diverse_hits, max_tokens=query.max_tokens)

        total_latency_ms = (time.perf_counter() - start_time) * 1000.0

        report = HybridSearchReport(
            query_text=query.query_text,
            mode=effective_mode,
            fallback_reason=fallback_reason,
            total_hits=len(final_hits),
            total_latency_ms=round(total_latency_ms, 2),
            vector_latency_ms=round(vector_latency_ms, 2),
            fts_latency_ms=round(fts_latency_ms, 2),
            circuit_state=self._circuit_breaker.state,
        )

        return final_hits, report
