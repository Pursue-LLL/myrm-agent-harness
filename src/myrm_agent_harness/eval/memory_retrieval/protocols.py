"""Memory Retrieval Eval — types and adapter protocol.

[INPUT]
None

[OUTPUT]
- MemoryRetrievalEvalCase: single retrieval eval question
- MemoryRetrievalCaseResult: per-case scored result
- MemoryRetrievalEvalSummary: aggregate results with per-category breakdown
- MemoryRetrievalAdapter: protocol for pluggable memory backends

[POS]
Defines the type system and adapter protocol for memory retrieval
quality evaluation. Framework-only — no business-layer dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class MemoryRetrievalEvalCase:
    """A single retrieval evaluation question."""

    id: str
    category: str
    query: str
    gold_ids: list[str]
    language: str = "en"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryRetrievalCaseResult:
    """Scored result for a single eval case."""

    case_id: str
    category: str
    retrieved_ids: list[str]
    gold_ids: set[str]
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    ndcg_at_10: float = 0.0
    mrr_score: float = 0.0
    precision_at_5: float = 0.0
    hit_at_5: float = 0.0
    latency_ms: float = 0.0


@dataclass(slots=True)
class MemoryRetrievalCategorySummary:
    """Aggregate metrics for one category."""

    category: str
    count: int = 0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    ndcg_at_10: float = 0.0
    mrr_score: float = 0.0
    precision_at_5: float = 0.0
    hit_at_5: float = 0.0


@dataclass(slots=True)
class MemoryRetrievalEvalSummary:
    """Full evaluation summary with per-category breakdown."""

    total_cases: int = 0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    ndcg_at_10: float = 0.0
    mrr_score: float = 0.0
    precision_at_5: float = 0.0
    hit_at_5: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    by_category: list[MemoryRetrievalCategorySummary] = field(default_factory=list)
    case_results: list[MemoryRetrievalCaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Export as JSON-serializable dict."""
        return {
            "total_cases": self.total_cases,
            "recall_at_5": round(self.recall_at_5, 4),
            "recall_at_10": round(self.recall_at_10, 4),
            "ndcg_at_10": round(self.ndcg_at_10, 4),
            "mrr": round(self.mrr_score, 4),
            "precision_at_5": round(self.precision_at_5, 4),
            "hit_at_5": round(self.hit_at_5, 4),
            "latency_p50_ms": round(self.latency_p50_ms, 2),
            "latency_p95_ms": round(self.latency_p95_ms, 2),
            "by_category": [
                {
                    "category": c.category,
                    "count": c.count,
                    "recall_at_5": round(c.recall_at_5, 4),
                    "recall_at_10": round(c.recall_at_10, 4),
                    "ndcg_at_10": round(c.ndcg_at_10, 4),
                    "mrr": round(c.mrr_score, 4),
                }
                for c in self.by_category
            ],
        }


@runtime_checkable
class MemoryRetrievalAdapter(Protocol):
    """Protocol for pluggable memory retrieval backends.

    Business layer implements this to bridge the eval framework
    with actual memory storage and retrieval.
    """

    async def ingest(self, memory_id: str, content: str, *, category: str = "", language: str = "en") -> None:
        """Store a memory entry for later retrieval."""
        ...

    async def query(self, query_text: str, top_k: int = 10) -> list[str]:
        """Retrieve top-K memory IDs ranked by relevance."""
        ...

    async def clear(self) -> None:
        """Remove all ingested benchmark memories."""
        ...
