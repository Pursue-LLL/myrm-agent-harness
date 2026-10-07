"""Dual-Channel Knowledge Graph and Vector Retriever using Reciprocal Rank Fusion.

[INPUT]
- toolkits.memory.graph_rrf.graph_store::SQLiteGraphMemoryStore (POS: Lightweight SQLite-backed Knowledge
  Graph Store for relational long-term memory.)
- toolkits.memory.graph_rrf.rrf_fusion::ReciprocalRankFusionEngine (POS: Reciprocal Rank Fusion (RRF) Engine
  for multi-channel memory score unification.)
- toolkits.memory.graph_rrf.types::FusedMemoryHit, GraphHit, RRFConfig, VectorHit (POS: Data models and
  contract types for Knowledge Graph and Vector RRF Fusion Memory Engine.)

[OUTPUT]
- DualChannelRRFRetriever: Orchestrates dual-channel vector + graph search and fuses ranks via RRF.

[POS]
Dual-Channel Knowledge Graph and Vector Retriever using Reciprocal Rank Fusion.
"""

from __future__ import annotations

from collections.abc import Callable

from myrm_agent_harness.toolkits.memory.graph_rrf.graph_store import (
    SQLiteGraphMemoryStore,
)
from myrm_agent_harness.toolkits.memory.graph_rrf.rrf_fusion import (
    ReciprocalRankFusionEngine,
)
from myrm_agent_harness.toolkits.memory.graph_rrf.types import (
    FusedMemoryHit,
    GraphHit,
    RRFConfig,
    VectorHit,
)

VectorSearchFn = Callable[[str, int], list[VectorHit]]


class DualChannelRRFRetriever:
    """Orchestrates dual-channel vector + graph search and fuses ranks via RRF."""

    def __init__(
        self,
        graph_store: SQLiteGraphMemoryStore,
        vector_search_fn: VectorSearchFn | None = None,
        config: RRFConfig | None = None,
    ) -> None:
        self.graph_store = graph_store
        self.vector_search_fn = vector_search_fn
        self.config = config or RRFConfig()
        self._fusion_engine = ReciprocalRankFusionEngine()

    def extract_seeds_from_query(self, query: str) -> list[str]:
        """Scan registered nodes to find entity names present in query text."""
        if not query:
            return []
        q_lower = query.lower()
        matched_ids: list[str] = []
        cursor = self.graph_store._conn.execute(
            "SELECT id, name FROM memory_graph_nodes"
        )
        for row in cursor.fetchall():
            node_id = str(row["id"])
            node_name = str(row["name"]).strip().lower()
            if node_name and node_name in q_lower:
                matched_ids.append(node_id)
        return matched_ids

    def search_graph_channel(
        self, seed_entity_ids: list[str], max_hops: int = 2
    ) -> list[GraphHit]:
        """Traverse knowledge graph from seeds and rank associated memories by distance."""
        if not seed_entity_ids:
            return []

        traversal = self.graph_store.traverse(
            seed_entity_ids=seed_entity_ids, max_hops=max_hops
        )

        # Map each reached node to its shortest hop distance
        node_hops: dict[str, int] = {}
        for s_id in seed_entity_ids:
            node_hops[s_id] = 0

        for path in traversal.paths:
            prev_tgt_hop = node_hops.get(path.target_id, 999)
            node_hops[path.target_id] = min(prev_tgt_hop, path.depth)

        # For each memory, find all linked entities and calculate shortest hop
        mem_shortest_hop: dict[str, int] = {}
        mem_primary_entity: dict[str, str] = {}
        mem_paths: dict[str, list[str]] = {}

        for n_id, hop in node_hops.items():
            assoc_mems = self.graph_store.get_associated_memories([n_id])
            for mem_id in assoc_mems:
                curr_hop = mem_shortest_hop.get(mem_id, 999)
                if hop < curr_hop:
                    mem_shortest_hop[mem_id] = hop
                    mem_primary_entity[mem_id] = n_id

        # Collect paths related to seed to primary entity
        for path in traversal.paths:
            for mem_id, e_id in mem_primary_entity.items():
                if path.target_id == e_id or path.source_id == e_id:
                    path_desc = f"{path.source_id}->({path.relation_type})->{path.target_id}"
                    if mem_id not in mem_paths:
                        mem_paths[mem_id] = []
                    if path_desc not in mem_paths[mem_id]:
                        mem_paths[mem_id].append(path_desc)

        hits: list[GraphHit] = []
        for mem_id, hop in mem_shortest_hop.items():
            # Graph relevance score decays with hop distance: 1.0 / (hop + 1)
            raw_score = 1.0 / (hop + 1.0)
            content = self.graph_store.get_memory_content(mem_id)
            hits.append(
                GraphHit(
                    memory_id=mem_id,
                    entity_id=mem_primary_entity.get(mem_id, ""),
                    content=content,
                    hop=hop,
                    path=mem_paths.get(mem_id, []),
                    score=raw_score,
                    rank=0,  # will be assigned below
                )
            )

        # Rank hits: lowest hop first, then higher score
        hits.sort(key=lambda h: (h.hop, -h.score))
        ranked_hits: list[GraphHit] = []
        for idx, h in enumerate(hits, start=1):
            ranked_hits.append(
                GraphHit(
                    memory_id=h.memory_id,
                    entity_id=h.entity_id,
                    content=h.content,
                    hop=h.hop,
                    path=h.path,
                    score=h.score,
                    rank=idx,
                )
            )
        return ranked_hits

    def search(
        self,
        query: str,
        seed_entity_ids: list[str] | None = None,
        seed_entity_names: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[FusedMemoryHit]:
        """Execute dual-channel search and fuse candidate ranks via RRF."""
        eff_top_k = top_k or self.config.top_k
        eff_config = RRFConfig(
            k=self.config.k,
            vector_weight=self.config.vector_weight,
            graph_weight=self.config.graph_weight,
            max_graph_hops=self.config.max_graph_hops,
            top_k=eff_top_k,
            max_nodes_visited=self.config.max_nodes_visited,
        )

        # 1. Resolve seed entity IDs
        active_seed_ids: list[str] = []
        if seed_entity_ids:
            active_seed_ids.extend(seed_entity_ids)
        if seed_entity_names:
            for name in seed_entity_names:
                node = self.graph_store.find_node_by_name(name)
                if node and node.id not in active_seed_ids:
                    active_seed_ids.append(node.id)

        # Fallback to lexical extraction from query if no seeds provided
        if not active_seed_ids:
            active_seed_ids = self.extract_seeds_from_query(query)

        # 2. Vector Channel
        vector_hits: list[VectorHit] = []
        if self.vector_search_fn:
            vector_hits = self.vector_search_fn(query, eff_top_k * 2)

        # 3. Knowledge Graph Channel
        graph_hits = self.search_graph_channel(
            active_seed_ids, max_hops=eff_config.max_graph_hops
        )

        # 4. Reciprocal Rank Fusion
        return self._fusion_engine.fuse(
            vector_hits=vector_hits,
            graph_hits=graph_hits,
            config=eff_config,
        )
