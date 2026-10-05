from __future__ import annotations

import time
import uuid

from myrm_agent_harness.toolkits.memory.graph_arbitration.arbitrator import (
    FactConflictArbitrator,
)
from myrm_agent_harness.toolkits.memory.graph_arbitration.decay import (
    DEFAULT_HALF_LIFE_DAYS,
    TemporalEdgeDecayCalculator,
)
from myrm_agent_harness.toolkits.memory.graph_arbitration.disambiguation import (
    EntityDisambiguator,
)
from myrm_agent_harness.toolkits.memory.graph_arbitration.models import (
    ArbitrationResult,
    EntityNode,
    EntityRelationEdge,
    FactStatus,
)


class HierarchicalEntityGraphEngine:
    """Unified engine for dynamic edge weighting, entity disambiguation, and conflict arbitration.

    Provides a clean facade over entity graph ingestion, decay calculations,
    automated conflict superseding, and active fact queries.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, EntityNode] = {}
        self._edges: list[EntityRelationEdge] = []

    @property
    def nodes_count(self) -> int:
        return len(self._nodes)

    @property
    def edges_count(self) -> int:
        return len(self._edges)

    def upsert_entity(
        self,
        name: str,
        aliases: list[str] | None = None,
        entity_type: str = "general",
        description: str = "",
        current_epoch_s: float | None = None,
    ) -> EntityNode:
        """Resolve or register a canonical entity node across sessions."""
        now_s = current_epoch_s if current_epoch_s is not None else time.time()
        alias_list = aliases or []

        matched = EntityDisambiguator.find_canonical_match(
            name, list(self._nodes.values())
        )
        if matched:
            merged_aliases = set(matched.aliases)
            merged_aliases.update(alias_list)
            if name != matched.canonical_name:
                merged_aliases.add(name)

            updated = EntityNode(
                node_id=matched.node_id,
                canonical_name=matched.canonical_name,
                aliases=sorted(merged_aliases),
                entity_type=matched.entity_type or entity_type,
                description=matched.description or description,
                created_at_epoch_s=matched.created_at_epoch_s,
                last_accessed_epoch_s=now_s,
            )
            self._nodes[matched.node_id] = updated
            return updated

        new_id = f"node_{uuid.uuid4().hex[:12]}"
        new_node = EntityNode(
            node_id=new_id,
            canonical_name=name,
            aliases=sorted(set(alias_list)),
            entity_type=entity_type,
            description=description,
            created_at_epoch_s=now_s,
            last_accessed_epoch_s=now_s,
        )
        self._nodes[new_id] = new_node
        return new_node

    def add_fact(
        self,
        source_name: str,
        predicate: str,
        fact_value: str,
        target_name: str = "global",
        base_weight: float = 1.0,
        current_epoch_s: float | None = None,
    ) -> ArbitrationResult:
        """Add a candidate fact relation, arbitrating conflicts with older facts."""
        now_s = current_epoch_s if current_epoch_s is not None else time.time()

        src_node = self.upsert_entity(source_name, current_epoch_s=now_s)
        tgt_node = self.upsert_entity(target_name, current_epoch_s=now_s)

        candidate_edge = EntityRelationEdge(
            edge_id=f"edge_{uuid.uuid4().hex[:12]}",
            source_node_id=src_node.node_id,
            target_node_id=tgt_node.node_id,
            predicate=predicate.strip().lower(),
            fact_value=fact_value.strip(),
            base_weight=base_weight,
            dynamic_weight=base_weight,
            status=FactStatus.ACTIVE,
            created_at_epoch_s=now_s,
            last_verified_epoch_s=now_s,
            access_count=1,
            causal_superseded_by=None,
        )

        result, updated_edges = FactConflictArbitrator.arbitrate(
            candidate_edge, self._edges
        )
        self._edges = updated_edges
        return result

    def decay_graph(
        self,
        current_epoch_s: float,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    ) -> int:
        """Apply temporal and access frequency decay to all relations."""
        archived_count = 0
        new_edges: list[EntityRelationEdge] = []
        for edge in self._edges:
            decayed = TemporalEdgeDecayCalculator.apply_decay_to_edge(
                edge, current_epoch_s, half_life_days
            )
            if decayed.status == FactStatus.ARCHIVED and edge.status != FactStatus.ARCHIVED:
                archived_count += 1
            new_edges.append(decayed)

        self._edges = new_edges
        return archived_count

    def query_active_facts(
        self, source_name: str, min_weight: float = 0.20
    ) -> list[EntityRelationEdge]:
        """Query active and relevant facts for a given entity, sorted by dynamic weight."""
        matched = EntityDisambiguator.find_canonical_match(
            source_name, list(self._nodes.values())
        )
        if not matched:
            return []

        active_edges = [
            e
            for e in self._edges
            if e.source_node_id == matched.node_id
            and e.status == FactStatus.ACTIVE
            and e.dynamic_weight >= min_weight
        ]
        return sorted(active_edges, key=lambda e: e.dynamic_weight, reverse=True)

    def get_fact_lineage(
        self, source_name: str, predicate: str
    ) -> list[EntityRelationEdge]:
        """Retrieve full historical evolution lineage for a specific fact predicate."""
        matched = EntityDisambiguator.find_canonical_match(
            source_name, list(self._nodes.values())
        )
        if not matched:
            return []

        norm_pred = predicate.strip().lower()
        lineage = [
            e
            for e in self._edges
            if e.source_node_id == matched.node_id and e.predicate == norm_pred
        ]
        return sorted(lineage, key=lambda e: e.created_at_epoch_s)
