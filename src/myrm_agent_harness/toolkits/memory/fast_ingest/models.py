"""Data models for Sub-5% Latency One-Pass Fast Ingestion and Deep Distillation Engine.

[INPUT]
- External: pydantic

[OUTPUT]
- IngestStatus: Lifecycle state of ingested fast memory records.
- RawIngestTurn: Contextual representation of an individual conversational turn.
- FastCommittedRecord: Memory record committed online with zero secondary LLM call overhead.
- IngestionMetrics: Performance telemetry tracking commit latency versus forward latency.
- DistillationBatch: A batch of committed records queued for idle-time distillation.
- DistillationReport: Outcome report of asynchronous background distillation.

[POS]
Data models for Sub-5% Latency One-Pass Fast Ingestion and Deep Distillation Engine.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class IngestStatus(StrEnum):
    """Lifecycle state of ingested fast memory records."""

    COMMITTED = "committed"
    PENDING_DISTILL = "pending_distill"
    DISTILLED = "distilled"
    DROPPED = "dropped"


class RawIngestTurn(BaseModel):
    """Contextual representation of an individual conversational turn."""

    session_id: str = Field(description="Active session identifier")
    turn_id: str = Field(description="Unique turn identifier")
    user_message: str = Field(description="User prompt text")
    assistant_message: str = Field(description="Generated assistant response")
    forward_inference_ms: float = Field(
        ge=0.001,
        description="Main model forward inference duration in milliseconds",
    )
    timestamp: datetime = Field(description="Timestamp when the forward pass concluded")
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Optional auxiliary execution metadata",
    )


class FastCommittedRecord(BaseModel):
    """Memory record committed online with zero secondary LLM call overhead."""

    record_id: str = Field(description="Unique committed record identifier")
    session_id: str = Field(description="Associated session identifier")
    turn_id: str = Field(description="Originating turn identifier")
    extracted_entities: list[str] = Field(
        default_factory=list,
        description="Heuristically extracted salient entities",
    )
    extracted_facts: list[str] = Field(
        default_factory=list,
        description="Heuristically extracted factual propositions",
    )
    salience_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Preliminary information density score",
    )
    commit_latency_ms: float = Field(
        ge=0.0,
        description="Wall-clock time spent in fast ingestion commit",
    )
    status: IngestStatus = Field(
        default=IngestStatus.PENDING_DISTILL,
        description="Current distillation lifecycle state",
    )
    created_at: datetime = Field(description="Commit registration timestamp")


class IngestionMetrics(BaseModel):
    """Performance telemetry tracking commit latency versus forward latency."""

    turn_id: str = Field(description="Turn identifier")
    commit_latency_ms: float = Field(ge=0.0, description="Fast ingestion commit time in ms")
    forward_latency_ms: float = Field(gt=0.0, description="LLM forward pass time in ms")
    overhead_percentage: float = Field(
        ge=0.0,
        description="Latency overhead percentage (commit / forward * 100)",
    )
    passed_overhead_gate: bool = Field(
        description="True if overhead percentage is strictly below the target threshold",
    )


class DistillationBatch(BaseModel):
    """A batch of committed records queued for idle-time distillation."""

    batch_id: str = Field(description="Batch identifier")
    records: list[FastCommittedRecord] = Field(
        default_factory=list,
        description="Records awaiting deep distillation",
    )
    created_at: datetime = Field(description="Batch formation timestamp")


class DistillationReport(BaseModel):
    """Outcome report of asynchronous background distillation."""

    batch_id: str = Field(description="Distilled batch identifier")
    input_record_count: int = Field(ge=0, description="Total committed records ingested")
    distilled_fact_count: int = Field(ge=0, description="Total consolidated facts generated")
    consolidated_facts: list[str] = Field(
        default_factory=list,
        description="High-density synthesized facts",
    )
    deduplication_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="Ratio of deduplicated/compressed redundant facts",
    )
    duration_ms: float = Field(ge=0.0, description="Elapsed distillation runtime in ms")
