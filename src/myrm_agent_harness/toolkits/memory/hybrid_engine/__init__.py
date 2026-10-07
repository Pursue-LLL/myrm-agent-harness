# [POS]: myrm_agent_harness/toolkits/memory/hybrid_engine/__init__.py
# [INPUT]: None
# [OUTPUT]: Public exports for ZeroConfigDualDriveHybridMemoryAndGracefulDegradationSuite

"""ZeroConfigDualDriveHybridMemoryAndGracefulDegradationSuite.

Provides zero-config local SQLite FTS5 BM25 retrieval, offline semantic synonym
expansion to eliminate keyword blindness, and dual-drive RRF hybrid fusion with
seamless graceful degradation.
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
