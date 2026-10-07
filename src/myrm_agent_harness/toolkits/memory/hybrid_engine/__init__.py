# [POS]: myrm_agent_harness/toolkits/memory/hybrid_engine/__init__.py
# [INPUT]: None
# [OUTPUT]: Public exports for ZeroConfigDualDriveHybridMemoryAndGracefulDegradationSuite

"""ZeroConfigDualDriveHybridMemoryAndGracefulDegradationSuite.

Provides zero-config local SQLite FTS5 BM25 retrieval, offline semantic synonym
expansion to eliminate keyword blindness, and dual-drive RRF hybrid fusion with
seamless graceful degradation.

[INPUT]
- toolkits.memory.hybrid_engine.dual_drive_engine::DenseVectorProvider, DualDriveHybridMemoryEngine (POS:
  Orchestrates zero-config SQLite FTS5, offline synonym expansion,.)
- toolkits.memory.hybrid_engine.models::HybridEngineStats, HybridMemoryItem, HybridSearchResult,
  RetrievalMode, SynonymRule (POS: Types and models for hybrid engine.)
- toolkits.memory.hybrid_engine.sqlite_fts5_store::SqliteFts5Engine (POS: Embedded SQLite FTS5 storage and
  retrieval engine.)
- toolkits.memory.hybrid_engine.synonym_expander::OfflineSynonymExpander (POS: Zero-dependency, offline
  semantic synonym expansion engine.)

[OUTPUT]
- Re-exports: DenseVectorProvider, DualDriveHybridMemoryEngine, HybridEngineStats, HybridMemoryItem,
  HybridSearchResult, OfflineSynonymExpander, RetrievalMode, SqliteFts5Engine, SynonymRule

[POS]
ZeroConfigDualDriveHybridMemoryAndGracefulDegradationSuite.
"""

from myrm_agent_harness.toolkits.memory.hybrid_engine.dual_drive_engine import (
    DenseVectorProvider,
    DualDriveHybridMemoryEngine,
)
from myrm_agent_harness.toolkits.memory.hybrid_engine.models import (
    HybridEngineStats,
    HybridMemoryItem,
    HybridSearchResult,
    RetrievalMode,
    SynonymRule,
)
from myrm_agent_harness.toolkits.memory.hybrid_engine.sqlite_fts5_store import SqliteFts5Engine
from myrm_agent_harness.toolkits.memory.hybrid_engine.synonym_expander import OfflineSynonymExpander

__all__ = [
    "DenseVectorProvider",
    "DualDriveHybridMemoryEngine",
    "HybridEngineStats",
    "HybridMemoryItem",
    "HybridSearchResult",
    "OfflineSynonymExpander",
    "RetrievalMode",
    "SqliteFts5Engine",
    "SynonymRule",
]
