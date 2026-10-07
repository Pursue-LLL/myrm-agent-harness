"""Data models for 5-Step Memory Diagnostic Decision Tree and Root Cause Inspector.

[INPUT]
- External: pydantic

[OUTPUT]
- DiagnosticStepKind: Categorical stage along the 5-step diagnostic decision tree.
- MemoryRootCauseKind: Standardized root causes explaining why memory was not recalled or utilized.
- DiagnosticStepResult: Evaluation outcome for an individual stage in the 5-step decision tree.
- MemoryDiagnosticProbeContext: Context input payload driving an automated memory diagnostic inspection.
- MemoryDiagnosticReport: Comprehensive diagnostic certificate with root cause and actionable remediation.

[POS]
Data models for 5-Step Memory Diagnostic Decision Tree and Root Cause Inspector.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class DiagnosticStepKind(StrEnum):
    """Categorical stage along the 5-step diagnostic decision tree."""

    STEP1_SESSION_STATE = "step1_session_state"
    STEP2_EXTRACTION_CHECK = "step2_extraction_check"
    STEP3_EXPIRATION_AUDIT = "step3_expiration_audit"
    STEP4_SCOPE_MATCHING = "step4_scope_matching"
    STEP5_BUDGET_TRUNCATION = "step5_budget_truncation"


class MemoryRootCauseKind(StrEnum):
    """Standardized root causes explaining why memory was not recalled or utilized."""

    HEALTHY = "healthy"
    SESSION_LOST = "session_lost"
    EXTRACTION_MISSED = "extraction_missed"
    FACT_EXPIRED_OR_SUPERSEDED = "fact_expired_or_superseded"
    SCOPE_MISMATCH_ISOLATED = "scope_mismatch_isolated"
    BUDGET_TRUNCATED_OR_RANK_DROPPED = "budget_truncated_or_rank_dropped"
    MODEL_ATTENTION_IGNORED = "model_attention_ignored"


class DiagnosticStepResult(BaseModel):
    """Evaluation outcome for an individual stage in the 5-step decision tree."""

    step_kind: DiagnosticStepKind = Field(description="Diagnostic stage identity")
    passed: bool = Field(description="Whether this stage verified successfully")
    diagnostic_message: str = Field(description="Diagnostic evaluation rationale")
    evidence_snippet: str | None = Field(
        default=None,
        description="Factual evidence or parameter payload inspected",
    )


class MemoryDiagnosticProbeContext(BaseModel):
    """Context input payload driving an automated memory diagnostic inspection."""

    session_id: str = Field(description="Session where memory was expected")
    query_target_entity: str = Field(description="Entity, keyword, or fact that was forgotten")
    tenant_id: str = Field(default="default_tenant", description="Active tenant boundary")
    user_id: str = Field(default="default_user", description="Active user boundary")
    project_id: str = Field(default="default_project", description="Active project boundary")
    prompt_token_budget: int = Field(
        default=2000,
        ge=100,
        description="Upper token budget allocated for context injection",
    )


class MemoryDiagnosticReport(BaseModel):
    """Comprehensive diagnostic certificate with root cause and actionable remediation."""

    diagnostic_id: str = Field(description="Unique diagnostic inspection identifier")
    session_id: str = Field(description="Evaluated session ID")
    target_entity: str = Field(description="Investigated keyword or concept")
    root_cause: MemoryRootCauseKind = Field(description="Conclusive root cause classification")
    overall_healthy: bool = Field(description="Whether the memory pipeline operated correctly")
    step_results: list[DiagnosticStepResult] = Field(
        default_factory=list,
        description="Detailed stage-by-stage verification trace",
    )
    remediation_advice: str = Field(description="Actionable fix or configuration change suggestion")
    diagnosed_at: datetime = Field(description="Timestamp of inspection completion")
