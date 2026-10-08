"""Data models for dual-engine hybrid search and graceful fallback.

[POS]
Data structures, query specifications, search results, circuit states,
and telemetry diagnostics for dual FTS5 and vector retrieval.

[INPUT]
- dataclasses.dataclass, dataclasses.field
- datetime.UTC, datetime.datetime
- enum.StrEnum
- typing.Literal

[OUTPUT]
- SearchMode, FallbackReason, CircuitState
- HybridSearchHit, HybridSearchQuery, HybridSearchReport
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class SearchMode(StrEnum):
    """Operational mode under which search executed."""

    HYBRID = "hybrid"
    VECTOR_ONLY = "vector_only"
    FTS_ONLY = "fts_only"
    FALLBACK_FTS = "fallback_fts"


class FallbackReason(StrEnum):
    """Reason code when vector search falls back to FTS."""

    NONE = "none"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_ERROR = "provider_error"
    PROVIDER_UNCONFIGURED = "provider_unconfigured"
    CIRCUIT_OPEN = "circuit_open"


class CircuitState(StrEnum):
    """Tri-state circuit breaker phase."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(slots=True)
class HybridSearchHit:
    """Individual retrieval hit combining lexical and vector relevance signals."""

    item_id: str
    title: str
    content: str
    score: float
    vector_score: float = 0.0
    text_score: float = 0.0
    exact_match: bool = False
    source_path: str = ""
    created_at: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class HybridSearchQuery:
    """Query parameters driving dual-engine retrieval and reranking."""

    query_text: str
    top_k: int = 5
    min_score: float = 0.25
    vector_weight: float = 0.65
    text_weight: float = 0.35
    recency_half_life_days: float = 30.0
    importance_multiplier: float = 1.0
    mmr_lambda: float = 0.7
    timeout_seconds: float = 2.0
    max_tokens: int | None = 2000
    exact_phrase_boost: float = 1.3


@dataclass(slots=True)
class HybridSearchReport:
    """Execution telemetry report capturing latency, modes, and circuit state."""

    query_text: str
    mode: SearchMode
    fallback_reason: FallbackReason
    total_hits: int
    total_latency_ms: float
    vector_latency_ms: float = 0.0
    fts_latency_ms: float = 0.0
    circuit_state: CircuitState = CircuitState.CLOSED
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
