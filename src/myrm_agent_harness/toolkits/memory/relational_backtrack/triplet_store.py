"""In-memory structured index for entity-action-temporal triplets.

[INPUT]
- toolkits.memory.relational_backtrack.models::EntityTypeKind, TemporalRelationTriplet (POS: Types and models
  for relational backtrack.)

[OUTPUT]
- TemporalTripletStore: In-memory structured index for entity-action-temporal triplets.

[POS]
In-memory structured index for entity-action-temporal triplets.
"""

# [POS]: src/myrm_agent_harness/toolkits/memory/relational_backtrack/triplet_store.py
# [INPUT]: models.py (TemporalRelationTriplet, EntityTypeKind)
# [OUTPUT]: TemporalTripletStore

from __future__ import annotations

import logging
from collections import defaultdict

from myrm_agent_harness.toolkits.memory.relational_backtrack.models import (
    EntityTypeKind,
    TemporalRelationTriplet,
)

logger = logging.getLogger(__name__)


class TemporalTripletStore:
    """In-memory structured index for entity-action-temporal triplets.

    Provides high-speed inverted indexes mapping actions and entity types
    to temporal relations, enabling deterministic cross-session back-lookup.
    """

    def __init__(self) -> None:
        self._triplets: dict[str, TemporalRelationTriplet] = {}
        # action -> set of triplet_ids
        self._action_index: dict[str, set[str]] = defaultdict(set)
        # entity_type -> set of triplet_ids
        self._entity_type_index: dict[EntityTypeKind, set[str]] = defaultdict(set)
        # session_id -> set of triplet_ids
        self._session_index: dict[str, set[str]] = defaultdict(set)

    def record_triplet(self, triplet: TemporalRelationTriplet) -> TemporalRelationTriplet:
        """Store a temporal relation triplet and update inverted indexes."""
        self._triplets[triplet.triplet_id] = triplet

        # Index canonical action
        canon_action = triplet.predicate_action.strip().lower()
        self._action_index[canon_action].add(triplet.triplet_id)

        # Index all action synonyms attached to the triplet
        for syn in triplet.action_synonyms:
            clean_syn = syn.strip().lower()
            if clean_syn:
                self._action_index[clean_syn].add(triplet.triplet_id)

        # Index entity type and session scope
        self._entity_type_index[triplet.target_entity_type].add(triplet.triplet_id)
        if triplet.session_id:
            self._session_index[triplet.session_id].add(triplet.triplet_id)

        logger.debug(
            "Recorded temporal triplet %s: %s -> %s (%s)",
            triplet.triplet_id,
            triplet.predicate_action,
            triplet.target_entity,
            triplet.temporal_anchor,
        )
        return triplet

    def get_triplet(self, triplet_id: str) -> TemporalRelationTriplet | None:
        """Retrieve a specific triplet by its unique identifier."""
        return self._triplets.get(triplet_id)

    def find_candidates(
        self,
        candidate_actions: list[str],
        entity_type: EntityTypeKind | None = None,
        session_id_scope: str | None = None,
    ) -> list[TemporalRelationTriplet]:
        """Query matching triplets across candidate action representations and constraints."""
        matched_ids: set[str] = set()

        for action_term in candidate_actions:
            clean_term = action_term.strip().lower()
            if clean_term in self._action_index:
                matched_ids.update(self._action_index[clean_term])

        results: list[TemporalRelationTriplet] = []
        for tid in matched_ids:
            triplet = self._triplets.get(tid)
            if triplet is None:
                continue

            if entity_type is not None and triplet.target_entity_type != entity_type:
                continue

            if session_id_scope is not None and triplet.session_id != session_id_scope:
                continue

            results.append(triplet)

        # Order chronologically descending by temporal_anchor / created_at
        results.sort(
            key=lambda t: (t.temporal_anchor, t.created_at),
            reverse=True,
        )
        return results

    def list_all(self) -> list[TemporalRelationTriplet]:
        """Return all triplets in chronological descending order."""
        items = list(self._triplets.values())
        items.sort(key=lambda t: (t.temporal_anchor, t.created_at), reverse=True)
        return items

    def clear(self) -> None:
        """Clear all stored triplets and index structures."""
        self._triplets.clear()
        self._action_index.clear()
        self._entity_type_index.clear()
        self._session_index.clear()
