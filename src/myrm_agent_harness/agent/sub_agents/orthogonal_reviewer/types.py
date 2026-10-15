from enum import StrEnum

from pydantic import BaseModel, Field


class ReviewerPerspective(StrEnum):
    INTENT_ALIGNMENT = "intent_alignment"  # Reviewer A: Shared context, intent & architecture
    BLIND_CLEAN_CONTEXT = "blind_clean_context"  # Reviewer B: Zero bias, pure diff & contracts


class FindingSeverity(StrEnum):
    CRITICAL = "critical"  # Must block delivery
    WARNING = "warning"  # High recommended fix
    INFO = "info"  # Suggestion or style note


class FindingCategory(StrEnum):
    INTENT_DRIFT = "intent_drift"
    LOGIC_FLAW = "logic_flaw"
    BOUNDARY_EDGE_CASE = "boundary_edge_case"
    REGRESSION_RISK = "regression_risk"
    OVER_ENGINEERING = "over_engineering"
    TYPE_SAFETY = "type_safety"


class ArbitrationStatus(StrEnum):
    APPROVED = "approved"
    BLOCKED_AUTO_FIX = "blocked_auto_fix"
    BLOCKED_MANUAL_ESCALATION = "blocked_manual_escalation"


class ReviewFinding(BaseModel):
    finding_id: str
    reviewer: ReviewerPerspective
    severity: FindingSeverity
    category: FindingCategory
    title: str
    description: str
    file_path: str
    line_range: str = Field(default="", description="e.g. L45-L60")
    suggestion: str


class ReviewerReport(BaseModel):
    perspective: ReviewerPerspective
    findings: list[ReviewFinding] = Field(default_factory=list)
    passed: bool
    summary: str
    execution_time_ms: float = Field(ge=0.0)


class ArbitrationVerdict(BaseModel):
    session_id: str
    is_approved: bool
    status: ArbitrationStatus
    max_severity: FindingSeverity | None = None
    merged_findings: list[ReviewFinding] = Field(default_factory=list)
    deduplicated_count: int = Field(default=0, ge=0)
    auto_fix_prompts: list[str] = Field(default_factory=list)
    summary: str
