"""
[INPUT]: Raw span attributes, execution durations, active skill context tags, and span statuses.
[OUTPUT]: Strongly typed domain models for active skill span telemetry and aggregated performance metrics.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/active_skill_telemetry/models.py
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class SkillSpanRecord(BaseModel):
    """Telemetry record for an execution span correlated with the currently active skill."""

    span_id: str = Field(...)
    trace_id: str = Field(...)
    name: str = Field(...)
    active_skill: Optional[str] = Field(default=None, description="Active skill bound via ContextVar")
    duration_ms: float = Field(..., ge=0.0)
    status: str = Field(default="ok", description="'ok' or 'error'")
    attributes: Dict[str, str] = Field(default_factory=dict)
    timestamp_ms: int = Field(...)


class SkillTelemetryAggregation(BaseModel):
    """Aggregated latency and throughput metrics partitioned by active skill."""

    skill_name: str = Field(...)
    total_spans: int = Field(default=0, ge=0)
    error_spans: int = Field(default=0, ge=0)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_duration_ms: float = Field(default=0.0, ge=0.0)
    p95_duration_ms: float = Field(default=0.0, ge=0.0)


class ActiveSkillTelemetryReport(BaseModel):
    """Full observability report summarizing active skill spans and unattributed baseline executions."""

    total_spans_recorded: int = Field(default=0, ge=0)
    skills_count: int = Field(default=0, ge=0)
    skill_aggregations: List[SkillTelemetryAggregation] = Field(default_factory=list)
    unattributed_spans_count: int = Field(default=0, ge=0)
    timestamp_ms: int = Field(...)
