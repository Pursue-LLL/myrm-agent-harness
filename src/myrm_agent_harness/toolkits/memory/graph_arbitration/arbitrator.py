"""Automated fact conflict arbitration state machine with causal lineage tracking.

[INPUT]
- toolkits.memory.graph_arbitration.models::ArbitrationResult, ConflictResolutionAction, EntityRelationEdge,
  FactStatus (POS: Typed entity-graph contracts for graph arbitration: fact status, conflict resolution
  actions, entity nodes and weighted relation edges.)

[OUTPUT]
- FactConflictArbitrator: Automated fact conflict arbitration state machine with causal lineage tracking.

[POS]
Automated fact conflict arbitration state machine with causal lineage tracking.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.graph_arbitration.models import (
    ArbitrationResult,
    ConflictResolutionAction,
    EntityRelationEdge,
    FactStatus,
)


class FactConflictArbitrator:
    """Automated fact conflict arbitration state machine with causal lineage tracking.

    Resolves contradiction between incoming facts and existing active edges by
    evaluating semantic equivalence or causal recency.
    """

    @staticmethod
    def are_values_equivalent(val_a: str, val_b: str) -> bool:
        """Check whether two fact values are semantically equivalent."""
        norm_a = val_a.strip().lower()
        norm_b = val_b.strip().lower()
        return norm_a == norm_b

    @classmethod
    def arbitrate(
        cls,
        candidate_edge: EntityRelationEdge,
        existing_edges: list[EntityRelationEdge],
    ) -> tuple[ArbitrationResult, list[EntityRelationEdge]]:
        """Arbitrate conflict between candidate fact and existing active edges.

        Returns the arbitration verdict along with the updated list of edges.
        """
        conflicting_actives = [
            e
            for e in existing_edges
            if e.source_node_id == candidate_edge.source_node_id
            and e.predicate == candidate_edge.predicate
            and e.status == FactStatus.ACTIVE
        ]

        if not conflicting_actives:
            # 没有冲突，直接入库
            updated_list = [*existing_edges, candidate_edge]
            return (
                ArbitrationResult(
                    action=ConflictResolutionAction.COEXIST,
                    active_edge_id=candidate_edge.edge_id,
                    superseded_edge_ids=[],
                    explanation="No conflicting active edges found for the same predicate.",
                    confidence=1.0,
                ),
                updated_list,
            )

        # 检查是否存在等价的既有事实
        for existing in conflicting_actives:
            if cls.are_values_equivalent(
                existing.fact_value, candidate_edge.fact_value
            ):
                # 强化既有事实
                reinforced_edge = EntityRelationEdge(
                    edge_id=existing.edge_id,
                    source_node_id=existing.source_node_id,
                    target_node_id=existing.target_node_id,
                    predicate=existing.predicate,
                    fact_value=existing.fact_value,
                    base_weight=min(1.0, existing.base_weight + 0.05),
                    dynamic_weight=existing.dynamic_weight,
                    status=FactStatus.ACTIVE,
                    created_at_epoch_s=existing.created_at_epoch_s,
                    last_verified_epoch_s=max(
                        existing.last_verified_epoch_s,
                        candidate_edge.last_verified_epoch_s,
                    ),
                    access_count=existing.access_count + 1,
                    causal_superseded_by=None,
                    properties=dict(existing.properties),
                )
                updated_list = [
                    reinforced_edge if e.edge_id == existing.edge_id else e
                    for e in existing_edges
                ]
                return (
                    ArbitrationResult(
                        action=ConflictResolutionAction.REINFORCE_EXISTING,
                        active_edge_id=existing.edge_id,
                        superseded_edge_ids=[],
                        explanation=f"Fact reinforced by identical value '{candidate_edge.fact_value}'.",
                        confidence=1.0,
                    ),
                    updated_list,
                )

        # 存在互斥的事实，根据因果时间戳判定
        superseded_ids: list[str] = []
        is_candidate_newer = all(
            candidate_edge.last_verified_epoch_s >= e.last_verified_epoch_s
            for e in conflicting_actives
        )

        if is_candidate_newer:
            # 候选事实较新，覆写既有旧事实
            updated_list = []
            for e in existing_edges:
                if e in conflicting_actives:
                    superseded_ids.append(e.edge_id)
                    updated_list.append(
                        EntityRelationEdge(
                            edge_id=e.edge_id,
                            source_node_id=e.source_node_id,
                            target_node_id=e.target_node_id,
                            predicate=e.predicate,
                            fact_value=e.fact_value,
                            base_weight=e.base_weight,
                            dynamic_weight=e.dynamic_weight,
                            status=FactStatus.SUPERSEDED,
                            created_at_epoch_s=e.created_at_epoch_s,
                            last_verified_epoch_s=e.last_verified_epoch_s,
                            access_count=e.access_count,
                            causal_superseded_by=candidate_edge.edge_id,
                            properties=dict(e.properties),
                        )
                    )
                else:
                    updated_list.append(e)

            updated_list.append(candidate_edge)
            return (
                ArbitrationResult(
                    action=ConflictResolutionAction.SUPERSEDE_OLD,
                    active_edge_id=candidate_edge.edge_id,
                    superseded_edge_ids=superseded_ids,
                    explanation=(
                        f"Newer fact '{candidate_edge.fact_value}' causally superseded "
                        f"{len(superseded_ids)} older contradictory fact(s)."
                    ),
                    confidence=1.0,
                ),
                updated_list,
            )

        # 候选事实时间戳陈旧，新事实直接标记为 SUPERSEDED
        stale_candidate = EntityRelationEdge(
            edge_id=candidate_edge.edge_id,
            source_node_id=candidate_edge.source_node_id,
            target_node_id=candidate_edge.target_node_id,
            predicate=candidate_edge.predicate,
            fact_value=candidate_edge.fact_value,
            base_weight=candidate_edge.base_weight,
            dynamic_weight=candidate_edge.dynamic_weight,
            status=FactStatus.SUPERSEDED,
            created_at_epoch_s=candidate_edge.created_at_epoch_s,
            last_verified_epoch_s=candidate_edge.last_verified_epoch_s,
            access_count=candidate_edge.access_count,
            causal_superseded_by=conflicting_actives[0].edge_id,
            properties=dict(candidate_edge.properties),
        )
        updated_list = [*existing_edges, stale_candidate]
        return (
            ArbitrationResult(
                action=ConflictResolutionAction.SUPERSEDE_OLD,
                active_edge_id=conflicting_actives[0].edge_id,
                superseded_edge_ids=[candidate_edge.edge_id],
                explanation="Candidate fact was older than active fact; archived as superseded.",
                confidence=0.95,
            ),
            updated_list,
        )
