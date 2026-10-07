# [POS]: myrm_agent_harness/toolkits/memory/hybrid_engine/dual_drive_engine.py
# [INPUT]: SqliteFts5Engine, OfflineSynonymExpander, optional DenseVectorProvider callback
# [OUTPUT]: DualDriveHybridMemoryEngine facade with RRF fusion and graceful degradation

import logging
from collections.abc import Callable
from pathlib import Path

from myrm_agent_harness.toolkits.memory.hybrid_engine.models import (
    HybridEngineStats,
    HybridMemoryItem,
    HybridSearchResult,
    RetrievalMode,
)
from myrm_agent_harness.toolkits.memory.hybrid_engine.sqlite_fts5_store import SqliteFts5Engine
from myrm_agent_harness.toolkits.memory.hybrid_engine.synonym_expander import OfflineSynonymExpander

logger = logging.getLogger(__name__)

DenseVectorProvider = Callable[[str, int], list[HybridSearchResult]]


class DualDriveHybridMemoryEngine:
    """Orchestrates zero-config SQLite FTS5, offline synonym expansion,

    optional dense vector embedding search, and Reciprocal Rank Fusion (RRF)
    with seamless graceful degradation.
    """

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        dense_vector_provider: DenseVectorProvider | None = None,
        rrf_k: int = 60,
    ) -> None:
        self._fts_engine = SqliteFts5Engine(db_path=db_path)
        self._synonym_expander = OfflineSynonymExpander()
        self._vector_provider = dense_vector_provider
        self._rrf_k = rrf_k

    @property
    def fts_engine(self) -> SqliteFts5Engine:
        return self._fts_engine

    @property
    def synonym_expander(self) -> OfflineSynonymExpander:
        return self._synonym_expander

    def set_dense_vector_provider(self, provider: DenseVectorProvider | None) -> None:
        """Inject or remove dense vector provider at runtime."""
        self._vector_provider = provider

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
    ) -> tuple[list[HybridSearchResult], RetrievalMode]:
        """Execute dual-drive search with automatic synonym expansion, RRF fusion,

        and zero-crash graceful degradation.
        """
        if not query.strip():
            return [], RetrievalMode.FTS_ONLY

        # 1. Expand query using offline semantic synonym graph
        fts5_expr, expanded_terms = self._synonym_expander.expand_query(query)
        fts_hits = self._fts_engine.search_fts(fts5_expr, limit=limit * 2) if fts5_expr else []
        for hit in fts_hits:
            hit.matched_terms = list(expanded_terms)

        # 2. Check dense vector availability
        use_vector = bool(enable_vector and self._vector_provider is not None)
        vector_hits: list[HybridSearchResult] = []
        is_degraded = False

        if use_vector and self._vector_provider:
            try:
                vector_hits = self._vector_provider(query, limit * 2)
            except Exception as ex:
                logger.warning(
                    "Dense vector retrieval failed or timed out (%s). Falling back gracefully to pure FTS5.",
                    ex,
                )
                is_degraded = True
                vector_hits = []

        # 3. Decision routing and RRF Fusion
        if not use_vector or is_degraded:
            active_mode = RetrievalMode.DEGRADED_FALLBACK if is_degraded else RetrievalMode.FTS_ONLY
            # Annotate channel if degraded
            if is_degraded:
                for h in fts_hits:
                    h.source_channel = "fts_degraded"
            return fts_hits[:limit], active_mode

        if not fts_hits and not vector_hits:
            return [], RetrievalMode.HYBRID_RRF

        # 4. Reciprocal Rank Fusion: Score(d) = sum(1 / (k + rank))
        rrf_scores: dict[str, float] = {}
        items_map: dict[str, HybridSearchResult] = {}

        # Process FTS ranks (weight: 1.0)
        for r_idx, hit in enumerate(fts_hits, start=1):
            cid = hit.item_id
            items_map[cid] = hit
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (self._rrf_k + r_idx))

        # Process Vector ranks (weight: 1.0)
        for r_idx, hit in enumerate(vector_hits, start=1):
            cid = hit.item_id
            if cid not in items_map:
                items_map[cid] = hit
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (self._rrf_k + r_idx))

        # Sort by final fused RRF score descending
        sorted_ids = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)[:limit]

        fused_results: list[HybridSearchResult] = []
        for rank_num, cid in enumerate(sorted_ids, start=1):
            base_hit = items_map[cid]
            fused_hit = HybridSearchResult(
                item_id=base_hit.item_id,
                title=base_hit.title,
                content=base_hit.content,
                score=round(rrf_scores[cid], 5),
                source_channel="rrf_hybrid",
                rank=rank_num,
                matched_terms=base_hit.matched_terms,
            )
            fused_results.append(fused_hit)

        return fused_results, RetrievalMode.HYBRID_RRF

    def get_stats(self) -> HybridEngineStats:
        """Produce operational snapshot of the hybrid engine."""
        vector_available = self._vector_provider is not None
        active_mode = RetrievalMode.HYBRID_RRF if vector_available else RetrievalMode.FTS_ONLY
        return HybridEngineStats(
            total_items=self._fts_engine.count_items(),
            synonym_terms_count=self._synonym_expander.total_terms(),
            dense_vector_available=vector_available,
            active_mode=active_mode,
            db_path=self._fts_engine.db_path,
        )

    def close(self) -> None:
        """Close underlying database resources."""
        self._fts_engine.close()
