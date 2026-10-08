"""Dual-engine hybrid search and graceful fallback package.

[POS]
Embedded retrieval package providing parallel SQLite FTS5 lexical recall,
vector similarity merging, adaptive circuit breaking, recency decay, and MMR.

[INPUT]
- .models (CircuitState, FallbackReason, HybridSearchHit, HybridSearchQuery, HybridSearchReport, SearchMode)
- .circuit_breaker (AdaptiveCircuitBreaker)
- .ranker (apply_mmr, apply_token_budget, bm25_to_score, compute_recency_decay, sanitize_fts_query)
- .engine (DualEngineHybridSearcher)

[OUTPUT]
- AdaptiveCircuitBreaker, CircuitState, DualEngineHybridSearcher, FallbackReason
- HybridSearchHit, HybridSearchQuery, HybridSearchReport, SearchMode
- apply_mmr, apply_token_budget, bm25_to_score, compute_recency_decay, sanitize_fts_query
"""

from myrm_agent_harness.toolkits.memory.hybrid_search.circuit_breaker import (
    AdaptiveCircuitBreaker,
)
from myrm_agent_harness.toolkits.memory.hybrid_search.engine import (
    DualEngineHybridSearcher,
)
from myrm_agent_harness.toolkits.memory.hybrid_search.models import (
    CircuitState,
    FallbackReason,
    HybridSearchHit,
    HybridSearchQuery,
    HybridSearchReport,
    SearchMode,
)
from myrm_agent_harness.toolkits.memory.hybrid_search.ranker import (
    apply_mmr,
    apply_token_budget,
    bm25_to_score,
    compute_recency_decay,
    sanitize_fts_query,
)

__all__ = [
    "AdaptiveCircuitBreaker",
    "CircuitState",
    "DualEngineHybridSearcher",
    "FallbackReason",
    "HybridSearchHit",
    "HybridSearchQuery",
    "HybridSearchReport",
    "SearchMode",
    "apply_mmr",
    "apply_token_budget",
    "bm25_to_score",
    "compute_recency_decay",
    "sanitize_fts_query",
]
