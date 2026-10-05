"""Data models for Dual-Track Fact Decision and Verbatim Evidence Tracer Engine."""

from datetime import datetime

from pydantic import BaseModel, Field


class VerbatimEvidenceSlice(BaseModel):
    """Immutable verbatim conversational evidence slice anchoring factual decisions."""

    evidence_id: str = Field(description="Unique evidence slice identifier")
    session_id: str = Field(description="Session identifier from which evidence originated")
    turn_id: str = Field(description="Specific turn identifier")
    speaker: str = Field(description="Role or speaker name (user/assistant/system)")
    snippet: str = Field(description="Exact verbatim conversational transcript snippet")
    timestamp: datetime = Field(description="Timestamp when evidence occurred")
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Optional execution context (e.g., file paths, tool calls)",
    )


class FactDecisionEntry(BaseModel):
    """High-privilege compact structured fact KV with bidirectional evidence pointers."""

    fact_id: str = Field(description="Unique fact identifier")
    key: str = Field(description="Canonical state property key (e.g. 'runtime.python_version')")
    value: str = Field(description="Canonical state value (e.g. '3.13.1')")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Certainty weight")
    scope: str = Field(default="workspace", description="Target domain or workspace scope")
    evidence_ref_ids: list[str] = Field(
        default_factory=list,
        description="Pointers to VerbatimEvidenceSlice records supporting this fact",
    )
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")


class DualTrackAssembly(BaseModel):
    """Assembled dual-track prompt injection containing compact facts and lazy handles."""

    state_prompt_segment: str = Field(description="Formatted ultra-compact state KV block")
    active_fact_count: int = Field(ge=0, description="Total active facts included in state block")
    lazy_evidence_handles: list[str] = Field(
        default_factory=list,
        description="Available evidence pointers accessible for lazy drill-down",
    )
    estimated_tokens: int = Field(ge=0, description="Approximate token consumption of state segment")


class EvidenceExpansionReport(BaseModel):
    """Detailed retrospective report unrolling verbatim evidence for a specific fact."""

    fact_id: str = Field(description="Target fact identifier")
    fact_key: str = Field(description="Fact property key")
    fact_value: str = Field(description="Fact property value")
    matched_evidence_slices: list[VerbatimEvidenceSlice] = Field(
        default_factory=list,
        description="Unrolled verbatim evidence slices ordered chronologically",
    )
    synthesis_rationale: str = Field(description="Audit explanation connecting evidence to fact state")
    total_evidence_characters: int = Field(ge=0, description="Total character count of unrolled snippets")
