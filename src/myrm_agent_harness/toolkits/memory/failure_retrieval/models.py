# [POS]: myrm_agent_harness.toolkits.memory.failure_retrieval.models
# [INPUT]: None (Standard library & Pydantic)
# [OUTPUT]: FailureOutcomeType, ErrorFingerprint, HistoricalResolutionEntry, FailureRetrievalResult, FailureTriggerConfig

"""Domain models for failure-triggered historical session retrieval.

P0 delivery for Item 109 in topic_01 memory roadmap.
Enables automated retrieval of historical solutions or cautionary failures
when an agent encounters an execution or tool failure.

[INPUT]
- Third-party: pydantic

[OUTPUT]
- FailureOutcomeType: Categorical outcome of a historical session attempt.
- ErrorFingerprint: Normalized fingerprint of an error extracted from an execution failure.
- HistoricalResolutionEntry: Indexed solution or cautionary lesson from a past session.
- FailureRetrievalResult: Dual-track retrieval result returning both solutions and cautionary failures.
- FailureTriggerConfig: Runtime configuration for failure-triggered historical session retrieval.

[POS]
Domain models for failure-triggered historical session retrieval.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class FailureOutcomeType(StrEnum):
    """Categorical outcome of a historical session attempt."""

    SUCCESSFUL_RESOLUTION = "successful_resolution"
    CAUTIONARY_FAILURE = "cautionary_failure"


class ErrorFingerprint(BaseModel):
    """Normalized fingerprint of an error extracted from an execution failure."""

    error_type: str = Field(description="Exception or failure class name (e.g. ConnectionResetError, PermissionDenied)")
    tool_name: str = Field(default="", description="Name of tool that triggered failure if applicable")
    normalized_pattern: str = Field(description="Cleaned, scrubbed error signature with dynamic IDs/timestamps removed")
    exit_code: int | None = Field(default=None, description="Command exit code if shell execution")
    context_tags: list[str] = Field(default_factory=list, description="Categorical tags (e.g. network, auth, database)")


class HistoricalResolutionEntry(BaseModel):
    """Indexed solution or cautionary lesson from a past session."""

    entry_id: str = Field(description="Unique index identifier")
    session_id: str = Field(description="Historical session identifier where fix was applied")
    turn_index: int = Field(default=0, description="Turn index containing the direct resolution")
    error_signature: str = Field(description="Error signature or pattern matched")
    outcome_type: FailureOutcomeType = Field(description="Successful fix vs dead-end failure")
    solution_snippet: str = Field(description="Concrete command, code patch, or workaround applied")
    explanation: str = Field(default="", description="Why this fix resolved the issue or why this path failed")
    confidence: float = Field(default=1.0, description="Confidence score between 0.0 and 1.0")
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class FailureRetrievalResult(BaseModel):
    """Dual-track retrieval result returning both solutions and cautionary failures."""

    query_fingerprint: ErrorFingerprint = Field(description="Input error fingerprint searched")
    total_matched: int = Field(default=0, description="Total historical records matched")
    successful_resolutions: list[HistoricalResolutionEntry] = Field(
        default_factory=list, description="Historical solutions that successfully resolved this error"
    )
    cautionary_failures: list[HistoricalResolutionEntry] = Field(
        default_factory=list, description="Historical attempts that failed, warning agent away from dead ends"
    )
    suggested_action: str = Field(default="", description="Synthesized recommendation or workaround")


class FailureTriggerConfig(BaseModel):
    """Runtime configuration for failure-triggered historical session retrieval."""

    enabled: bool = Field(default=True, description="Whether failure-triggered retrieval is active")
    auto_trigger_on_error: bool = Field(default=True, description="Whether to automatically search history without user prompt")
    max_matches: int = Field(default=3, description="Maximum historical resolutions to return")
    min_similarity_threshold: float = Field(default=0.6, description="Minimum keyword/pattern match threshold")
    include_cautionary_failures: bool = Field(default=True, description="Whether to also return cautionary dead-end lessons")
