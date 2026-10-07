"""Types and models for handoff verification.

[INPUT]
- runtime.context.session_handoff_continuation_types::StructuredHandoffMemo (POS: Types and models for
  Session Handoff and Clean Window Continuation.)

[OUTPUT]
- VerificationSeverity: Severity of a detected handoff discrepancy.
- HandoffVerificationIssue: Detailed discrepancy found during adversarial handoff inspection.
- HandoffVerificationResult: Result of adversarial verification on a StructuredHandoffMemo.

[POS]
Types and models for handoff verification.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from myrm_agent_harness.runtime.context.session_handoff_continuation_types import (
    StructuredHandoffMemo,
)


class VerificationSeverity(StrEnum):
    """Severity of a detected handoff discrepancy."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class HandoffVerificationIssue(BaseModel):
    """Detailed discrepancy found during adversarial handoff inspection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: VerificationSeverity = Field(description="Severity classification")
    issue_type: str = Field(
        description="Category of the discrepancy (e.g., missing_constraint, missing_negative_decision)"
    )
    description: str = Field(description="Detailed explanation of the discrepancy")
    offending_item: str = Field(description="The specific constraint or pattern that was omitted")


class HandoffVerificationResult(BaseModel):
    """Result of adversarial verification on a StructuredHandoffMemo."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool = Field(description="Whether the handoff memo passed all adversarial checks")
    fidelity_score: float = Field(ge=0.0, le=1.0, description="Completeness and fidelity ratio between 0.0 and 1.0")
    issues: list[HandoffVerificationIssue] = Field(default_factory=list, description="List of identified issues")
    missing_constraints: list[str] = Field(default_factory=list, description="User constraints absent in the memo")
    missing_negative_decisions: list[str] = Field(
        default_factory=list, description="Disqualified approaches absent in the memo"
    )
    is_rectified: bool = Field(default=False, description="Whether self-healing auto-rectification was applied")
    rectified_memo: StructuredHandoffMemo | None = Field(
        default=None, description="Self-healed memo with missing constraints and negative decisions appended"
    )
