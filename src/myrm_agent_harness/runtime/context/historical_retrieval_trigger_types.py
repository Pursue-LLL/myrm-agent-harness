"""Types and models for historical retrieval trigger.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- HeuristicAnomalyKind: Categorization of execution anomalies that trigger historical retrieval heuristics.
- ToolExecutionFeedback: Execution outcome feedback from a tool call used by the heuristic trigger.
- HeuristicTriggerResult: Output produced when evaluating tool failure state against retrieval heuristics.

[POS]
Types and models for historical retrieval trigger.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class HeuristicAnomalyKind(StrEnum):
    """Categorization of execution anomalies that trigger historical retrieval heuristics."""

    CONSECUTIVE_ERRORS = "consecutive_errors"
    PARAMETER_MISSING = "parameter_missing"
    AUTH_CREDENTIAL_MISSING = "auth_credential_missing"
    CONFIG_NOT_FOUND = "config_not_found"
    REPEATED_DISQUALIFIED_ATTEMPT = "repeated_disqualified_attempt"


class ToolExecutionFeedback(BaseModel):
    """Execution outcome feedback from a tool call used by the heuristic trigger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str = Field(description="Name of the executed tool")
    success: bool = Field(description="Whether tool execution succeeded")
    error_message: str | None = Field(default=None, description="Error message or exception text if failed")


class HeuristicTriggerResult(BaseModel):
    """Output produced when evaluating tool failure state against retrieval heuristics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    triggered: bool = Field(default=False, description="Whether heuristic retrieval recommendation is activated")
    consecutive_failures: int = Field(default=0, ge=0, description="Number of sequential failures recorded")
    matched_anomaly_kind: HeuristicAnomalyKind | None = Field(
        default=None, description="Category of anomaly activating the hint"
    )
    suggested_query_terms: list[str] = Field(
        default_factory=list, description="Extracted keywords suggested for search_session_archive"
    )
    system_hint_block: str | None = Field(
        default=None, description="Structured prompt injection block advising archive search"
    )
    message: str = Field(default="", description="Diagnostic status message")
