"""[POS]: src/myrm_agent_harness/toolkits/memory/four_tier_fts/__init__.py
[INPUT]: Submodule exports for four_tier_fts models, fts engine, and dream compactor.
[OUTPUT]: Public symbols for the four-tier persistent memory and SQLite FTS5 suite.
"""

from .dream_compactor import FourTierDreamCompactor
from .fts_engine import SqliteFts5MemoryEngine
from .models import (
    DreamCompactionReport,
    FourTierMemoryItem,
    FtsSearchResult,
    MemoryScope,
)

__all__ = [
    "DreamCompactionReport",
    "FourTierDreamCompactor",
    "FourTierMemoryItem",
    "FtsSearchResult",
    "MemoryScope",
    "SqliteFts5MemoryEngine",
]
