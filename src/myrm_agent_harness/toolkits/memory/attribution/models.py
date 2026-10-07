"""Data models for Full-Lifecycle Memory Attribution and Explainable Traceability Matrix.

[INPUT]
- External: pydantic

[OUTPUT]
- FilterDiscardReason: Categorical rationale explaining why candidate memory was discarded.
- CandidateRecallItem: Memory entry initially retrieved from stores before post-filtering.
- DiscardedRecallItem: Memory candidate rejected during deduplication, scope filtering, or budgeting.
- InjectedContextItem: Surviving memory formatted and injected into prompt context.
- ModelCitationItem: Memory explicitly referenced or relied upon in the model output.
- AttributionGraphNode: Visual graph node representing an entity in the memory lifecycle.
- AttributionGraphEdge: Directed relationship link between lifecycle nodes.
- AttributionGraphPayload: Graph structure formatted for frontend observability visualization.
- MemoryAttributionTrace: Single-trace end-to-end memory lifecycle record penetrating query to citation.
- FourDimensionHealthReport: Production health evaluation matrix across four governance dimensions.

[POS]
Data models for Full-Lifecycle Memory Attribution and Explainable Traceability Matrix.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class FilterDiscardReason(StrEnum):
    """Categorical rationale explaining why candidate memory was discarded."""

    LOW_RELEVANCE = "low_relevance"
    DUPLICATE = "duplicate"
    SCOPE_MISMATCH = "scope_mismatch"
    BUDGET_TRUNCATED = "budget_truncated"
    EXPIRED = "expired"
    POLICY_BLOCKED = "policy_blocked"


class CandidateRecallItem(BaseModel):
    """Memory entry initially retrieved from stores before post-filtering."""

    memory_id: str = Field(description="Unique retrieved memory identifier")
    score: float = Field(ge=0.0, le=1.0, description="Raw relevance or similarity score")
    content_preview: str = Field(description="Concise excerpt of memory content")
    source_namespace: str = Field(description="Originating namespace or store partition")
    retrieved_at: datetime = Field(description="Timestamp when recalled")


class DiscardedRecallItem(BaseModel):
    """Memory candidate rejected during deduplication, scope filtering, or budgeting."""

    memory_id: str = Field(description="Identifier of discarded memory candidate")
    discard_reason: FilterDiscardReason = Field(description="Formal rejection cause")
    rationale: str = Field(description="Diagnostic explanation for rejection")
    stage: str = Field(default="filter", description="Processing stage where rejection occurred")


class InjectedContextItem(BaseModel):
    """Surviving memory formatted and injected into prompt context."""

    memory_id: str = Field(description="Injected memory identifier")
    token_count: int = Field(ge=0, description="Tokens consumed in prompt")
    position_index: int = Field(ge=0, description="Placement index within context block")
    formatted_preview: str = Field(description="Textual snippet as rendered to the model")


class ModelCitationItem(BaseModel):
    """Memory explicitly referenced or relied upon in the model output."""

    memory_id: str = Field(description="Cited memory identifier")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Attribution confidence")
    citation_snippet: str = Field(description="Generated sentence or clause citing this memory")
    supported_fact: str | None = Field(default=None, description="Underlying claim corroborated")


class AttributionGraphNode(BaseModel):
    """Visual graph node representing an entity in the memory lifecycle."""

    node_id: str = Field(description="Unique graph node identifier")
    node_type: str = Field(description="Category: query, candidate, discarded, injected, cited")
    label: str = Field(description="Display label")
    details: str = Field(description="Detailed contextual information")


class AttributionGraphEdge(BaseModel):
    """Directed relationship link between lifecycle nodes."""

    source: str = Field(description="Originating node ID")
    target: str = Field(description="Destination node ID")
    relation: str = Field(description="Edge semantic type (e.g., 'recalled', 'filtered', 'cited')")


class AttributionGraphPayload(BaseModel):
    """Graph structure formatted for frontend observability visualization."""

    nodes: list[AttributionGraphNode] = Field(default_factory=list)
    edges: list[AttributionGraphEdge] = Field(default_factory=list)


class MemoryAttributionTrace(BaseModel):
    """Single-trace end-to-end memory lifecycle record penetrating query to citation."""

    trace_id: str = Field(description="Unique end-to-end trace identifier")
    session_id: str = Field(description="Executing conversation or task session ID")
    query_text: str = Field(description="User prompt or tool query driving recall")
    candidate_recalls: list[CandidateRecallItem] = Field(
        default_factory=list,
        description="All candidates fetched in the recall stage",
    )
    discarded_items: list[DiscardedRecallItem] = Field(
        default_factory=list,
        description="Items filtered out with explicit rationales",
    )
    prompt_injections: list[InjectedContextItem] = Field(
        default_factory=list,
        description="Surviving items successfully injected into prompt",
    )
    model_citations: list[ModelCitationItem] = Field(
        default_factory=list,
        description="Memories demonstrably cited in final response",
    )
    duration_ms: float = Field(default=0.0, ge=0.0, description="Total pipeline processing latency")
    is_finalized: bool = Field(default=False, description="Whether the trace lifecycle has closed")
    created_at: datetime = Field(description="Trace initiation timestamp")


class FourDimensionHealthReport(BaseModel):
    """Production health evaluation matrix across four governance dimensions."""

    total_traces_analyzed: int = Field(ge=0, description="Count of evaluated traces")
    recall_quality_score: float = Field(ge=0.0, le=1.0, description="Recall precision & retention")
    task_outcome_adoption_rate: float = Field(
        ge=0.0,
        le=1.0,
        description="Ratio of injected memories actually cited",
    )
    cost_overhead_token_ratio: float = Field(
        ge=0.0,
        description="Average tokens injected per cited memory",
    )
    safety_governance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Ratio of safe/authorized memory handling without violations",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Actionable diagnostic improvement suggestions",
    )
