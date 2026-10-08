"""Temporal relational anchor and cross-session entity backtracking suite.

Solves the classic causal backtracking blind spot ('eat hotpot' ↔ 'have da-bin-lo with client')
by anchoring structured entity-action triplets with synonym normalization and verbatim quotes.

[INPUT]
- toolkits.memory.relational_backtrack.backtrack_engine::CrossSessionBacktrackEngine (POS: Core backtracking
  engine for cross-session entity and temporal causal recall.)
- toolkits.memory.relational_backtrack.models::EntityTypeKind, RelationalBacktrackHit,
  RelationalBacktrackQuery, RelationalBacktrackResult, TemporalRelationTriplet (POS: Types and models for
  relational backtrack.)
- toolkits.memory.relational_backtrack.synonym_normalizer::ActionSynonymNormalizer (POS: Action synonym
  normalization and dialect mapping engine.)
- toolkits.memory.relational_backtrack.triplet_store::TemporalTripletStore (POS: In-memory structured index
  for entity-action-temporal triplets.)

[OUTPUT]
- Re-exports: ActionSynonymNormalizer, CrossSessionBacktrackEngine, EntityTypeKind, RelationalBacktrackHit,
  RelationalBacktrackQuery, RelationalBacktrackResult, TemporalRelationTriplet, TemporalTripletStore

[POS]
Temporal relational anchor and cross-session entity backtracking suite.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.relational_backtrack.backtrack_engine import (
    CrossSessionBacktrackEngine,
)
from myrm_agent_harness.toolkits.memory.relational_backtrack.models import (
    EntityTypeKind,
    RelationalBacktrackHit,
    RelationalBacktrackQuery,
    RelationalBacktrackResult,
    TemporalRelationTriplet,
)
from myrm_agent_harness.toolkits.memory.relational_backtrack.synonym_normalizer import (
    ActionSynonymNormalizer,
)
from myrm_agent_harness.toolkits.memory.relational_backtrack.triplet_store import (
    TemporalTripletStore,
)

__all__ = [
    "ActionSynonymNormalizer",
    "CrossSessionBacktrackEngine",
    "EntityTypeKind",
    "RelationalBacktrackHit",
    "RelationalBacktrackQuery",
    "RelationalBacktrackResult",
    "TemporalRelationTriplet",
    "TemporalTripletStore",
]
