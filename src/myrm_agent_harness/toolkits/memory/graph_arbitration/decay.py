"""Dynamic edge weight decay and frequency reinforcement operator.

[INPUT]
- toolkits.memory.graph_arbitration.models::EntityRelationEdge, FactStatus (POS: Typed entity-graph
  contracts for graph arbitration: fact status, conflict resolution actions, entity nodes and weighted
  relation edges.)

[OUTPUT]
- TemporalEdgeDecayCalculator: Dynamic edge weight decay and frequency reinforcement operator.

[POS]
Dynamic edge weight decay and frequency reinforcement operator.
"""

from __future__ import annotations

import math
from typing import Final

from myrm_agent_harness.toolkits.memory.graph_arbitration.models import (
    EntityRelationEdge,
    FactStatus,
)

DEFAULT_HALF_LIFE_DAYS: Final[float] = 14.0
MIN_WEIGHT_THRESHOLD: Final[float] = 0.10
SECONDS_PER_DAY: Final[float] = 86400.0


class TemporalEdgeDecayCalculator:
    """Dynamic edge weight decay and frequency reinforcement operator.

    Adapted from graphiti dynamic edge weighting with half-life exponential decay
    and access frequency reinforcement.
    """

    @staticmethod
    def calculate_temporal_decay(
        last_verified_epoch_s: float,
        current_epoch_s: float,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    ) -> float:
        """Calculate exponential temporal decay multiplier based on elapsed time."""
        delta_s = max(0.0, current_epoch_s - last_verified_epoch_s)
        half_life_s = max(1.0, half_life_days * SECONDS_PER_DAY)
        decay_constant = math.log(2.0) / half_life_s
        return math.exp(-decay_constant * delta_s)

    @staticmethod
    def calculate_frequency_boost(access_count: int) -> float:
        """Calculate logarithmic frequency reinforcement gain."""
        count = max(1, access_count)
        return min(1.0, math.log2(1.0 + count) * 0.25)

    @classmethod
    def compute_dynamic_weight(
        cls,
        edge: EntityRelationEdge,
        current_epoch_s: float,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    ) -> float:
        """Derive combined dynamic weight from temporal decay and access frequency."""
        temporal_factor = cls.calculate_temporal_decay(
            edge.last_verified_epoch_s, current_epoch_s, half_life_days
        )
        frequency_factor = cls.calculate_frequency_boost(edge.access_count)

        combined = edge.base_weight * (
            temporal_factor * 0.70 + frequency_factor * 0.30
        )
        return max(0.05, min(1.0, combined))

    @classmethod
    def apply_decay_to_edge(
        cls,
        edge: EntityRelationEdge,
        current_epoch_s: float,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    ) -> EntityRelationEdge:
        """Recalculate dynamic weight and transition to ARCHIVED if below threshold."""
        new_weight = cls.compute_dynamic_weight(
            edge, current_epoch_s, half_life_days
        )
        new_status = edge.status
        if edge.status == FactStatus.ACTIVE and new_weight < MIN_WEIGHT_THRESHOLD:
            new_status = FactStatus.ARCHIVED

        return EntityRelationEdge(
            edge_id=edge.edge_id,
            source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id,
            predicate=edge.predicate,
            fact_value=edge.fact_value,
            base_weight=edge.base_weight,
            dynamic_weight=round(new_weight, 4),
            status=new_status,
            created_at_epoch_s=edge.created_at_epoch_s,
            last_verified_epoch_s=edge.last_verified_epoch_s,
            access_count=edge.access_count,
            causal_superseded_by=edge.causal_superseded_by,
            properties=dict(edge.properties),
        )
