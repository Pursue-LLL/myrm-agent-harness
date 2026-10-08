"""Types and models for zero-config dual-drive hybrid memory engine.

[INPUT]
- dataclasses, datetime, enum, time, typing

[OUTPUT]
- RetrievalMode, CircuitBreakerState, CircuitBreakerConfig, CircuitBreakerStats
- AdaptiveRrfConfig, HybridMemoryItem, HybridSearchResult, SynonymRule, HybridEngineStats

[POS]
Item 133 DualEngineHybridSearchAndGracefulFallbackSuite.
Strictly typed data contracts for adaptive RRF fusion, recency decay,
importance weighting, and embedding circuit breaker telemetry.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class RetrievalMode(StrEnum):
    """Operational mode for dual-drive hybrid memory retrieval."""

    FTS_ONLY = "fts_only"                      # Pure zero-config local SQLite FTS5 BM25
    DENSE_ONLY = "dense_only"                  # Dense vector embedding semantic retrieval
    HYBRID_RRF = "hybrid_rrf"                  # Dual-drive Adaptive Reciprocal Rank Fusion
    DEGRADED_FALLBACK = "degraded_fallback"    # Graceful degradation to local FTS5 on vector failure


class CircuitBreakerState(StrEnum):
    """State of embedding circuit breaker."""

    CLOSED = "closed"          # Normal operation: vector retrieval active
    OPEN = "open"              # Breaker tripped: fast circuit break to FTS5
    HALF_OPEN = "half_open"    # Recovery probe: testing vector backend


@dataclass(slots=True)
class CircuitBreakerConfig:
    """Configuration for embedding provider circuit breaker."""

    failure_threshold: int = 3
    recovery_timeout_seconds: float = 30.0
    timeout_seconds: float = 2.0


@dataclass(slots=True)
class CircuitBreakerStats:
    """Telemetry metrics snapshot of circuit breaker."""

    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    failure_count: int = 0
    consecutive_successes: int = 0
    last_failure_time: float = 0.0
    last_state_change: float = field(default_factory=time.time)
    tripped_count: int = 0


@dataclass(slots=True)
class AdaptiveRrfConfig:
    """Configuration parameters for multi-factor Adaptive RRF."""

    rrf_k: int = 60
    fts_weight: float = 1.0
    vector_weight: float = 1.0
    importance_weight: float = 0.3
    half_life_seconds: float = 86400.0  # 1 day default half-life
    apply_recency_decay: bool = True


@dataclass(slots=True)
class HybridMemoryItem:
    """Persistent memory unit stored in local SQLite FTS5 table."""

    item_id: str
    content: str
    title: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)
    created_at: str = ""
    importance: float = 0.5
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class HybridSearchResult:
    """Ranked hit produced by FTS5, dense vector, or adaptive RRF hybrid fusion."""

    item_id: str
    content: str
    title: str
    score: float
    source_channel: str                       # e.g., "fts", "vector", "rrf_hybrid", "fts_degraded"
    rank: int = 1
    matched_terms: list[str] = field(default_factory=list)
    importance: float = 0.5
    recency_factor: float = 1.0
    is_degraded: bool = False
    degradation_reason: str = ""
    timestamp: float = 0.0


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
    circuit_breaker: CircuitBreakerStats = field(default_factory=CircuitBreakerStats)
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
