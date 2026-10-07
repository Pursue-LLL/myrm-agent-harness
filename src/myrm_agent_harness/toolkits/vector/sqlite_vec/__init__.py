"""SQLite-vec embedded vector store package.

[POS]
Embedded single-file vector storage module providing zero-daemon persistent storage,
dual-track adaptive engine, and temporal decay scoring.

[INPUT]
- .models (SqliteVecConfig, SqliteVecEngineMode, DecayedSearchResult)
- .decay (TemporalDecayScorer)
- .store (SqliteVecStore)

[OUTPUT]
- DecayedSearchResult, SqliteVecConfig, SqliteVecEngineMode, SqliteVecStore, TemporalDecayScorer
"""

from myrm_agent_harness.toolkits.vector.sqlite_vec.decay import TemporalDecayScorer
from myrm_agent_harness.toolkits.vector.sqlite_vec.models import (
    DecayedSearchResult,
    SqliteVecConfig,
    SqliteVecEngineMode,
)
from myrm_agent_harness.toolkits.vector.sqlite_vec.store import SqliteVecStore

__all__ = [
    "DecayedSearchResult",
    "SqliteVecConfig",
    "SqliteVecEngineMode",
    "SqliteVecStore",
    "TemporalDecayScorer",
]
