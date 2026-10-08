"""Types and schemas for Tracing Redaction and Sensitive Data Policy."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class ExecutionPathType(StrEnum):
    """Execution path where a trace or telemetry span was captured."""

    SUCCESS = "success"
    ERROR = "error"
    STREAMING = "streaming"
    RETRY = "retry"
    RESUME = "resume"


class TracingOptOutMode(StrEnum):
    """Opt-out handling mode for tracing and telemetry."""

    ALLOW_TRACING = "allow_tracing"
    REDACT_MANDATORY = "redact_mandatory"
    DROP_TRACE = "drop_trace"


class TraceSpanInput(BaseModel):
    """Payload representing an incoming trace span before sanitization."""

    model_config = ConfigDict(frozen=True)

    trace_id: str = Field(..., description="Unique trace session identifier")
    span_id: str = Field(..., description="Unique span identifier")
    path_type: ExecutionPathType = Field(..., description="Execution path origin")
    payload: dict[str, object] = Field(
        default_factory=dict, description="Arbitrary span payload data"
    )
    raw_error: str | None = Field(
        default=None, description="Raw error or stack trace message if present"
    )
    opt_out_requested: bool = Field(
        default=False,
        description="Whether the user or tenant requested tracing opt-out",
    )


class RedactedTraceSpan(BaseModel):
    """Sanitized trace span complying with sensitive-data policy."""

    model_config = ConfigDict(frozen=True)

    trace_id: str
    span_id: str
    path_type: ExecutionPathType
    sanitized_payload: dict[str, object]
    sanitized_error: str | None = None
    is_dropped: bool = False
    redaction_count: int = 0
    policy_applied: str = Field(default="standard_redaction")
