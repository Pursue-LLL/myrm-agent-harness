"""Adaptive Reciprocal Rank Fusion reranker with recency decay and importance weighting.

[INPUT]
- math, time, typing
- toolkits.memory.hybrid_engine.models::AdaptiveRrfConfig, HybridSearchResult

[OUTPUT]
- AdaptiveRrfReranker: Multi-factor RRF fusion reranker.

[POS]
Item 133 DualEngineHybridSearchAndGracefulFallbackSuite.
Blends multi-channel ranking scores from SQLite FTS5 BM25 and dense vector
similarity with Ebbinghaus memory recency half-life decay and cognitive importance multipliers.
"""

from __future__ import annotations

import math
import time

from myrm_agent_harness.toolkits.memory.hybrid_engine.models import (
    AdaptiveRrfConfig,
    HybridSearchResult,
)


class AdaptiveRrfReranker:
    """Multi-factor adaptive Reciprocal Rank Fusion reranker."""

    def __init__(self, config: AdaptiveRrfConfig | None = None) -> None:
        self._config = config or AdaptiveRrfConfig()

    @property
    def config(self) -> AdaptiveRrfConfig:
        return self._config

    def fuse_and_rerank(
        self,
        fts_hits: list[HybridSearchResult],
        vector_hits: list[HybridSearchResult],
        limit: int = 10,
        override_config: AdaptiveRrfConfig | None = None,
        now: float | None = None,
    ) -> list[HybridSearchResult]:
        """Fuse FTS and vector hits using multi-factor adaptive RRF.

        Applies:
        1. Reciprocal Rank Fusion: Score(d) = sum(weight / (k + rank))
        2. Ebbinghaus recency decay: 2 ** (-delta_t / half_life)
        3. Importance scaling: 1.0 + importance_weight * (importance - 0.5)
        """
        cfg = override_config or self._config
        current_time = time.time() if now is None else now

        raw_rrf: dict[str, float] = {}
        item_ref: dict[str, HybridSearchResult] = {}

        # 1. Accumulate FTS rankings
        for rank_idx, hit in enumerate(fts_hits, start=1):
            raw_rrf[hit.item_id] = raw_rrf.get(hit.item_id, 0.0) + (
                cfg.fts_weight / (cfg.rrf_k + rank_idx)
            )
            item_ref[hit.item_id] = hit

        # 2. Accumulate Vector rankings
        for rank_idx, hit in enumerate(vector_hits, start=1):
            raw_rrf[hit.item_id] = raw_rrf.get(hit.item_id, 0.0) + (
                cfg.vector_weight / (cfg.rrf_k + rank_idx)
            )
            if hit.item_id not in item_ref:
                item_ref[hit.item_id] = hit
            else:
                # Merge matched terms if available
                existing = item_ref[hit.item_id]
                if hit.matched_terms:
                    combined_terms = list(dict.fromkeys(existing.matched_terms + hit.matched_terms))
                    existing.matched_terms = combined_terms

        # 3. Compute multi-factor final scores
        final_scores: list[tuple[str, float, float, float]] = []
        for item_id, base_rrf in raw_rrf.items():
            hit = item_ref[item_id]
            importance = hit.importance

            # Recency factor
            if cfg.apply_recency_decay and cfg.half_life_seconds > 0:
                hit_time = hit.timestamp if hit.timestamp > 0 else current_time
                delta_t = max(0.0, current_time - hit_time)
                recency_factor = math.pow(2.0, -delta_t / cfg.half_life_seconds)
            else:
                recency_factor = 1.0

            # Importance multiplier: baseline 0.5 centered
            importance_factor = 1.0 + cfg.importance_weight * (importance - 0.5)
            if importance_factor < 0.1:
                importance_factor = 0.1

            fused_score = base_rrf * recency_factor * importance_factor
            final_scores.append((item_id, fused_score, recency_factor, importance))

        # Sort descending by fused score
        final_scores.sort(key=lambda x: x[1], reverse=True)
        top_candidates = final_scores[:limit]

        results: list[HybridSearchResult] = []
        for rank_num, (item_id, fused_score, recency_factor, importance) in enumerate(
            top_candidates, start=1
        ):
            base_hit = item_ref[item_id]
            fused_hit = HybridSearchResult(
                item_id=base_hit.item_id,
                title=base_hit.title,
                content=base_hit.content,
                score=round(fused_score, 6),
                source_channel="rrf_hybrid",
                rank=rank_num,
                matched_terms=list(base_hit.matched_terms),
                importance=importance,
                recency_factor=round(recency_factor, 4),
                is_degraded=False,
                degradation_reason="",
            )
            results.append(fused_hit)

        return results
