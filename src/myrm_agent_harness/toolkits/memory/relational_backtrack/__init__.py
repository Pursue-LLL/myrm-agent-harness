# [POS]: src/myrm_agent_harness/toolkits/memory/relational_backtrack/__init__.py
# [INPUT]: models.py, synonym_normalizer.py, triplet_store.py, backtrack_engine.py
# [OUTPUT]: Public facade for TemporalRelationalAnchorAndCrossSessionEntityBacktrackingSuite

"""Temporal relational anchor and cross-session entity backtracking suite.

Solves the classic causal backtracking blind spot ('eat hotpot' ↔ 'have da-bin-lo with client')
by anchoring structured entity-action triplets with synonym normalization and verbatim quotes.
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
