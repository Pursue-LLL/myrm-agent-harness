"""Types for skill memory provenance tracing and batch learning namespace isolation.

[INPUT]
- datetime::{UTC, datetime}
- uuid::{uuid4}
- pydantic::{BaseModel, Field}

[OUTPUT]
- ToolExecutionTrace: Granular record of a physical tool execution serving as concrete evidence
- ExtractionProvenanceLink: Bi-directional link from extracted skill back to raw turn and tool traces
- NamespacedMemoryRef: Deterministically partitioned memory reference preventing ID collision
- BatchLearnItem: Input specification for batch learning with scope attribution
- BatchLearnResult: Outcome of namespaced batch memory compilation

[POS]
Data structures and value objects for skill extraction provenance and batch learning isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field


class ToolExecutionTrace(BaseModel):
    """Forensic record of a tool execution serving as concrete physical evidence."""

    tool_name: str = Field(description="Name of the executed tool (e.g. bash, search, git)")
    tool_call_id: str | None = Field(default=None, description="Unique call ID from the model")
    input_args_summary: str = Field(default="", description="Sanitized summary of input parameters")
    output_evidence_snippet: str = Field(
        default="", description="Sanitized factual output snippet proving execution outcome"
    )
    status: str = Field(default="success", description="Outcome status (e.g. success, failure)")
    duration_ms: float = Field(default=0.0, ge=0.0, description="Execution duration in milliseconds")


class ExtractionProvenanceLink(BaseModel):
    """Bi-directional provenance link anchoring extracted skill patterns to concrete context."""

    link_id: str = Field(
        default_factory=lambda: f"prov_{uuid4().hex[:12]}",
        description="Unique identifier of this provenance link anchor",
    )
    conversation_id: str = Field(description="Source conversation identifier")
    turn_index: int | None = Field(default=None, ge=0, description="Turn index within the conversation")
    trigger_prompt_snippet: str = Field(description="User prompt or intent trigger that prompted the turn")
    tool_traces: list[ToolExecutionTrace] = Field(
        default_factory=list, description="Ordered physical tool executions providing evidence"
    )
    counterexample_snippet: str | None = Field(
        default=None, description="Optional contrastive counterexample or pitfall observed"
    )
    confidence_score: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Confidence in this extraction provenance"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when this provenance link was sealed",
    )


class NamespacedMemoryRef(BaseModel):
    """Deterministically partitioned memory identifier preventing cross-scope collision."""

    namespaced_id: str = Field(description="Fully-qualified namespaced ID (namespace::scope::raw_id)")
    namespace: str = Field(description="Target primary namespace (e.g. 'agent:coder', 'global')")
    scope_level: str = Field(description="Scope level (e.g. 'agent', 'shared', 'conversation')")
    raw_id: str = Field(description="Original unnamespaced memory identifier")


class BatchLearnItem(BaseModel):
    """Individual item submitted for batch extraction and learning."""

    raw_id: str = Field(description="Caller-provided memory identifier")
    content: str = Field(description="Fact, skill pattern, or rule text")
    namespace: str = Field(description="Target namespace (e.g. 'agent:dev', 'global')")
    scope_level: str = Field(default="agent", description="Target scope classification ('agent', 'shared')")
    provenance_link: ExtractionProvenanceLink | None = Field(
        default=None, description="Optional evidentiary provenance trace link"
    )


class BatchLearnResult(BaseModel):
    """Summary of namespaced batch learning isolation."""

    total_items: int = Field(ge=0, description="Total items processed in the batch")
    namespaced_items: list[NamespacedMemoryRef] = Field(
        default_factory=list, description="All partitioned items with guaranteed unique IDs"
    )
    has_provenance_count: int = Field(
        default=0, ge=0, description="Number of items equipped with evidentiary provenance links"
    )
