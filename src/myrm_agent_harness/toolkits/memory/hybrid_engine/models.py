"""Types and models for hybrid engine.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- RetrievalMode: Operational mode for dual-drive hybrid memory retrieval.
- HybridMemoryItem: Persistent memory unit stored in local SQLite FTS5 table.
- HybridSearchResult: Ranked hit produced by FTS5, dense vector, or RRF hybrid fusion.
- SynonymRule: Synonym cluster mapping primary keyword to related semantic expressions.
- HybridEngineStats: Operational telemetry and status snapshot of the hybrid engine.

[POS]
Types and models for hybrid engine.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class RetrievalMode(StrEnum):
    """Operational mode for dual-drive hybrid memory retrieval."""

    FTS_ONLY = "fts_only"                      # Pure zero-config local SQLite FTS5 BM25
    DENSE_ONLY = "dense_only"                  # Dense vector embedding semantic retrieval
    HYBRID_RRF = "hybrid_rrf"                  # Dual-drive Reciprocal Rank Fusion (FTS5 + Vector)
    DEGRADED_FALLBACK = "degraded_fallback"    # Graceful degradation to local FTS5 on vector failure


@dataclass(slots=True)
class HybridMemoryItem:
    """Persistent memory unit stored in local SQLite FTS5 table."""

    item_id: str
    content: str
    title: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)
    created_at: str = ""


@dataclass(slots=True)
class HybridSearchResult:
    """Ranked hit produced by FTS5, dense vector, or RRF hybrid fusion."""

    item_id: str
    content: str
    title: str
    score: float
    source_channel: str                       # e.g., "fts", "vector", "rrf_hybrid", "fts_degraded"
    rank: int = 1
    matched_terms: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SynonymRule:
    """Synonym cluster mapping primary keyword to related semantic expressions."""

    primary_term: str
    synonyms: list[str] = field(default_factory=list)


@dataclass(slots=True)
class HybridEngineStats:
    """Operational telemetry and status snapshot of the hybrid engine."""

    total_items: int
    synonym_terms_count: int
    dense_vector_available: bool
    active_mode: RetrievalMode
    db_path: str
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
