"""Types and models for Negative Decision Ledger and Anti-Regression Protection.

Part of Item 129: NegativeDecisionAndRejectionReasonLedger.
Provides models for recording failed/rejected attempts, structural rejection rationale,
and pre-flight anti-regression plan interception.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- FailureRootCauseKind: Categorization of why a proposed approach failed or was disqualified.
- NegativeDecisionEntry: Immutable entry recording a failed or rejected solution attempt.
- AntiRegressionInterceptionResult: Result of pre-flight plan check against negative decisions ledger.

[POS]
Types and models for Negative Decision Ledger and Anti-Regression Protection.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FailureRootCauseKind(StrEnum):
    """Categorization of why a proposed approach failed or was disqualified."""

    COMPILATION_ERROR = "compilation_error"
    RUNTIME_EXCEPTION = "runtime_exception"
    SECURITY_VIOLATION = "security_violation"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    USER_EXPLICIT_REJECTION = "user_explicit_rejection"
    DEPENDENCY_INCOMPATIBLE = "dependency_incompatible"


class NegativeDecisionEntry(BaseModel):
    """Immutable entry recording a failed or rejected solution attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_id: str = Field(description="Unique entry identifier")
    session_id: str = Field(description="Originating session identifier")
    attempted_solution: str = Field(description="Summary of the failed or rejected approach")
    root_cause_kind: FailureRootCauseKind = Field(description="Root cause classification")
    rejection_reason: str = Field(description="Specific technical rationale why it failed or was rejected")
    associated_files: list[str] = Field(default_factory=list, description="Target files associated with failure")
    disqualified_patterns: list[str] = Field(
        default_factory=list,
        description="Forbidden tokens, flags, or library names that must not be reintroduced",
    )
    tried_turn: int = Field(ge=0, description="Dialogue turn index where this approach was attempted")
    timestamp_iso: str = Field(description="ISO-8601 recording timestamp")


class AntiRegressionInterceptionResult(BaseModel):
    """Result of pre-flight plan check against negative decisions ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_blocked: bool = Field(description="True if proposed plan matches a known disqualified solution")
    matched_entry: NegativeDecisionEntry | None = Field(default=None, description="Disqualifying ledger entry")
    reason: str = Field(default="", description="Explanatory reason why plan is intercepted")
    alternative_suggestion: str = Field(default="", description="Guidance to select viable alternatives")
