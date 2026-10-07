"""Semantic entity normalization and cross-session alias resolution operator.

[INPUT]
- toolkits.memory.graph_arbitration.models::EntityNode, EntityRelationEdge (POS: Typed entity-graph
  contracts for graph arbitration: fact status, conflict resolution actions, entity nodes and weighted
  relation edges.)

[OUTPUT]
- EntityDisambiguator: Semantic entity normalization and cross-session alias resolution operator.

[POS]
Semantic entity normalization and cross-session alias resolution operator.
"""

from __future__ import annotations

import re
from typing import Final

from myrm_agent_harness.toolkits.memory.graph_arbitration.models import (
    EntityNode,
    EntityRelationEdge,
)

PUNCTUATION_RE: Final[re.Pattern[str]] = re.compile(r"[^\w\s]", re.UNICODE)
WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"[\s\-_]+", re.UNICODE)


class EntityDisambiguator:
    """Semantic entity normalization and cross-session alias resolution operator.

    Prevents graph fragmentation by aligning surface forms to canonical entities.
    """

    @staticmethod
    def normalize_name(name: str) -> str:
        """Derive standard lexical fingerprint from surface entity name."""
        cleaned = PUNCTUATION_RE.sub(" ", name.strip().lower())
        collapsed = WHITESPACE_RE.sub("_", cleaned.strip())
        return collapsed.strip("_")

    @staticmethod
    def alphanumeric_fingerprint(name: str) -> str:
        """Derive stripped alphanumeric lowercase fingerprint for fuzzy variant matching."""
        return re.sub(r"[^a-z0-9]", "", name.lower())

    @classmethod
    def find_canonical_match(
        cls, candidate_name: str, existing_nodes: list[EntityNode]
    ) -> EntityNode | None:
        """Find an existing canonical entity by matching normalized name or aliases."""
        target_fp = cls.normalize_name(candidate_name)
        target_alpha = cls.alphanumeric_fingerprint(candidate_name)
        if not target_fp and not target_alpha:
            return None

        for node in existing_nodes:
            if cls.normalize_name(node.canonical_name) == target_fp or (
                target_alpha and cls.alphanumeric_fingerprint(node.canonical_name) == target_alpha
            ):
                return node
            for alias in node.aliases:
                if cls.normalize_name(alias) == target_fp or (
                    target_alpha and cls.alphanumeric_fingerprint(alias) == target_alpha
                ):
                    return node

        return None

    @classmethod
    def merge_entities(
        cls,
        primary_node: EntityNode,
        secondary_node: EntityNode,
        edges: list[EntityRelationEdge],
    ) -> tuple[EntityNode, list[EntityRelationEdge]]:
        """Merge a secondary duplicate entity into the primary node and retarget edges."""
        merged_aliases = set(primary_node.aliases)
        merged_aliases.update(secondary_node.aliases)
        merged_aliases.add(secondary_node.canonical_name)
        merged_aliases.discard(primary_node.canonical_name)

        updated_primary = EntityNode(
            node_id=primary_node.node_id,
            canonical_name=primary_node.canonical_name,
            aliases=sorted(merged_aliases),
            entity_type=primary_node.entity_type,
            description=primary_node.description or secondary_node.description,
            created_at_epoch_s=min(
                primary_node.created_at_epoch_s, secondary_node.created_at_epoch_s
            ),
            last_accessed_epoch_s=max(
                primary_node.last_accessed_epoch_s,
                secondary_node.last_accessed_epoch_s,
            ),
        )

        sec_id = secondary_node.node_id
        pri_id = primary_node.node_id
        retargeted_edges: list[EntityRelationEdge] = []

        for edge in edges:
            needs_update = False
            src = edge.source_node_id
            tgt = edge.target_node_id

            if src == sec_id:
                src = pri_id
                needs_update = True
            if tgt == sec_id:
                tgt = pri_id
                needs_update = True

            if needs_update:
                retargeted_edges.append(
                    EntityRelationEdge(
                        edge_id=edge.edge_id,
                        source_node_id=src,
                        target_node_id=tgt,
                        predicate=edge.predicate,
                        fact_value=edge.fact_value,
                        base_weight=edge.base_weight,
                        dynamic_weight=edge.dynamic_weight,
                        status=edge.status,
                        created_at_epoch_s=edge.created_at_epoch_s,
                        last_verified_epoch_s=edge.last_verified_epoch_s,
                        access_count=edge.access_count,
                        causal_superseded_by=edge.causal_superseded_by,
                        properties=dict(edge.properties),
                    )
                )
            else:
                retargeted_edges.append(edge)

        return updated_primary, retargeted_edges
