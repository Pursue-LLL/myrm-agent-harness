# [POS] toolkits/memory/graph_rrf/rrf_fusion.py
# [INPUT] VectorHit, GraphHit, FusedMemoryHit, RRFConfig
# [OUTPUT] ReciprocalRankFusionEngine

"""Reciprocal Rank Fusion (RRF) Engine for multi-channel memory score unification."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.graph_rrf.types import (
    FusedMemoryHit,
    GraphHit,
    RRFConfig,
    VectorHit,
)


class ReciprocalRankFusionEngine:
    """Combines heterogeneous ranked lists using Reciprocal Rank Fusion."""

    @staticmethod
    def compute_single_score(
        rank: int, k: int = 60, weight: float = 1.0
    ) -> float:
        """Compute 1 / (k + rank) scaled by channel weight.

        rank is 1-indexed (1, 2, ...).
        """
        if rank < 1:
            rank = 1
        return float(weight / (k + rank))

    def fuse(
        self,
        vector_hits: list[VectorHit],
        graph_hits: list[GraphHit],
        config: RRFConfig | None = None,
    ) -> list[FusedMemoryHit]:
        """Fuse vector and graph hits into an unified ranked list."""
        cfg = config or RRFConfig()
        k = cfg.k
        w_vec = cfg.vector_weight
        w_graph = cfg.graph_weight

        # Index vector hits by memory_id
        vec_map: dict[str, VectorHit] = {h.memory_id: h for h in vector_hits}
        # Index graph hits by memory_id
        graph_map: dict[str, GraphHit] = {h.memory_id: h for h in graph_hits}

        all_mem_ids: set[str] = set(vec_map.keys()) | set(graph_map.keys())

        fused_items: list[FusedMemoryHit] = []

        for mem_id in all_mem_ids:
            v_hit = vec_map.get(mem_id)
            g_hit = graph_map.get(mem_id)

            vec_rank = v_hit.rank if v_hit else None
            graph_rank = g_hit.rank if g_hit else None

            v_rrf = (
                self.compute_single_score(v_hit.rank, k=k, weight=w_vec)
                if v_hit
                else 0.0
            )
            g_rrf = (
                self.compute_single_score(g_hit.rank, k=k, weight=w_graph)
                if g_hit
                else 0.0
            )
            total_score = v_rrf + g_rrf

            sources: list[str] = []
            if v_hit:
                sources.append("vector")
            if g_hit:
                sources.append("graph")

            content = ""
            if v_hit and v_hit.content:
                content = v_hit.content
            elif g_hit and g_hit.content:
                content = g_hit.content

            explanation: dict[str, str | int | float | list[str]] = {
                "vector_rrf": round(v_rrf, 6),
                "graph_rrf": round(g_rrf, 6),
                "k": k,
                "vector_weight": w_vec,
                "graph_weight": w_graph,
            }
            if g_hit:
                explanation["graph_hop"] = g_hit.hop
                explanation["graph_path"] = list(g_hit.path)

            fused_items.append(
                FusedMemoryHit(
                    memory_id=mem_id,
                    content=content,
                    fused_score=round(total_score, 6),
                    vector_rank=vec_rank,
                    graph_rank=graph_rank,
                    hit_sources=sources,
                    explanation=explanation,
                )
            )

        # Sort by fused_score descending
        fused_items.sort(key=lambda item: item.fused_score, reverse=True)

        return fused_items[: cfg.top_k]
