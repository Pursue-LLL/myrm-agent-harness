"""Domain models and data structures for quadruple parallel retrieval and reasoner suite.

[INPUT]
- None (Standard library dataclasses, enums, and typing)

[OUTPUT]
- RetrievalChannelKind: Parallel recall channel identifiers.
- ReasonerDecisionKind: Semantic reasoner decision types.
- ParsedTaskGoal: Pre-retrieval deconstructed task goal and constraints.
- ChannelRecallHit: Hit retrieved from an individual channel.
- UnifiedCandidateHit: Deduplicated candidate merged across channels.
- RerankedMemoryHit: Final reranked memory item equipped with reasoner audit rationale.
- QuadrupleRetrievalReport: Comprehensive end-to-end report of the quadruple retrieval pass.
- QueryIntentType: Enumerated retrieval intent classifications.
- RetrievalChannelType: Alias for RetrievalChannelKind.
- TaskGoal: Alias for ParsedTaskGoal.
- CandidateMemoryItem: Channel recall candidate model.
- HarmonizedMemoryItem: Harmonized memory model.
- HarmonizedRecallResult: End-to-end outcome report model.

[POS]
Domain models and contracts for goal-driven quadruple retrieval and reasoner suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class RetrievalChannelKind(StrEnum):
    """Parallel memory recall channel types."""

    GRAPH = "graph"
    VECTOR = "vector"
    LEXICAL = "lexical"
    METADATA = "metadata"

    # Aliases
    GRAPH_TOPOLOGY = "graph"
    DENSE_VECTOR = "vector"
    LEXICAL_BM25 = "lexical"
    METADATA_EXACT = "metadata"


RetrievalChannelType = RetrievalChannelKind


class ReasonerDecisionKind(StrEnum):
    """Semantic reasoner decision during reranking."""

    KEEP = "keep"
    SUPPRESS = "suppress"
    BOOST = "boost"
    PENALIZE_STALE = "penalize_stale"


class QueryIntentType(StrEnum):
    """Classification of the primary retrieval intent."""

    FACTUAL = "factual"
    PROCEDURAL = "procedural"
    PREFERENCE = "preference"
    EPISODIC = "episodic"
    GENERAL_EXPLORATION = "general_exploration"
    TECHNICAL_STANDARD = "technical_standard"


@dataclass(slots=True)
class ParsedTaskGoal:
    """Pre-retrieval decomposed intent and constraint container."""

    goal_id: str
    original_query: str
    explicit_intent: str
    target_entities: list[str] = field(default_factory=list)
    extracted_keywords: list[str] = field(default_factory=list)
    metadata_filters: dict[str, str] = field(default_factory=dict)
    temporal_constraints: str | None = None
    confidence: float = 1.0
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    @property
    def intent_type(self) -> QueryIntentType:
        """Normalized QueryIntentType enum."""
        try:
            return QueryIntentType(self.explicit_intent)
        except ValueError:
            return QueryIntentType.GENERAL_EXPLORATION

    @property
    def raw_query(self) -> str:
        """Alias for original_query."""
        return self.original_query

    @property
    def temporal_constraint(self) -> str | None:
        """Alias for temporal_constraints."""
        return self.temporal_constraints

    @property
    def filter_criteria(self) -> dict[str, str]:
        """Alias for metadata_filters."""
        return self.metadata_filters


TaskGoal = ParsedTaskGoal


@dataclass(slots=True)
class ChannelRecallHit:
    """Single recalled candidate memory item from an individual channel."""

    memory_id: str
    content: str
    channel: RetrievalChannelKind
    raw_score: float
    confidence: float = 1.0
    metadata: dict[str, str] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


CandidateMemoryItem = ChannelRecallHit


@dataclass(slots=True)
class UnifiedCandidateHit:
    """Deduplicated candidate fused across multiple channels."""

    memory_id: str
    content: str
    channels_hit: list[RetrievalChannelKind]
    fused_score: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class RerankedMemoryHit:
    """Final memory hit refined and ordered by the semantic reasoner."""

    memory_id: str
    content: str
    final_rank: int
    final_score: float
    channels_hit: list[RetrievalChannelKind]
    reasoner_decision: ReasonerDecisionKind
    rationale: str
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def item_id(self) -> str:
        return self.memory_id

    @property
    def rank(self) -> int:
        return self.final_rank

    @property
    def contributing_channels(self) -> list[RetrievalChannelKind]:
        return self.channels_hit

    @property
    def subject(self) -> str:
        return self.metadata.get("subject", "")

    @property
    def rrf_score(self) -> float:
        return self.final_score


HarmonizedMemoryItem = RerankedMemoryHit


@dataclass(slots=True)
class QuadrupleRetrievalReport:
    """Comprehensive end-to-end report of a quadruple retrieval pass."""

    query: str
    parsed_goal: ParsedTaskGoal
    channel_hits_count: dict[str, int]
    fused_candidates_count: int
    final_hits: list[RerankedMemoryHit]
    latency_ms: float
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    @property
    def goal(self) -> ParsedTaskGoal:
        return self.parsed_goal

    @property
    def top_k_items(self) -> list[RerankedMemoryHit]:
        return self.final_hits

    @property
    def execution_time_ms(self) -> float:
        return self.latency_ms

    @property
    def total_candidates_analyzed(self) -> int:
        return self.fused_candidates_count

    @property
    def degraded_channels(self) -> list[RetrievalChannelKind]:
        return []


HarmonizedRecallResult = QuadrupleRetrievalReport
