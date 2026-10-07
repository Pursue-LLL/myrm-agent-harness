"""Verification module for goal completion logic.

[INPUT]
- .gatekeeper::VerificationGatekeeper (POS: Orchestrator)
- .base::VerificationResult, AggregatedVerificationResult (POS: Result types)

[OUTPUT]
- VerificationGatekeeper
- VerificationResult
- AggregatedVerificationResult

[POS]
Exports verification entry points for use in goal_agent_tools.
"""

from myrm_agent_harness.agent.goals.verification.base import (
    AggregatedVerificationResult,
    ReviewComment,
    ReviewSeverity,
    VerificationResult,
)
from myrm_agent_harness.agent.goals.verification.fault_attribution import (
    FaultAttribution,
    FaultCategory,
    FaultClassificationResult,
    FaultKind,
    classify_execution_fault,
    classify_fault,
)
from myrm_agent_harness.agent.goals.verification.gatekeeper import (
    VerificationGatekeeper,
)
from myrm_agent_harness.agent.goals.verification.handoff_verification_gate import (
    HandoffVerificationGate,
)
from myrm_agent_harness.agent.goals.verification.handoff_verification_types import (
    HandoffVerificationIssue,
    HandoffVerificationResult,
    VerificationSeverity as HandoffVerificationSeverity,
)
from myrm_agent_harness.agent.goals.verification.security import (
    SecurityScanCriterion,
)

__all__ = [
    "AggregatedVerificationResult",
    "FaultAttribution",
    "FaultCategory",
    "FaultClassificationResult",
    "FaultKind",
    "HandoffVerificationGate",
    "HandoffVerificationIssue",
    "HandoffVerificationResult",
    "HandoffVerificationSeverity",
    "ReviewComment",
    "ReviewSeverity",
    "SecurityScanCriterion",
    "VerificationGatekeeper",
    "VerificationResult",
    "classify_execution_fault",
    "classify_fault",
]
