"""Public API for HITL Approval Fail-Closed Safety Gate & Non-Bypassable Guard Suite.

[INPUT]
- Package import declarations.

[OUTPUT]
- Exported classes, enums, exceptions, and pipelines.

[POS]
- Harness core security module package entrypoint.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.hitl_fail_closed.pipeline import (
    HitlApprovalPipeline,
)
from myrm_agent_harness.core.security.hitl_fail_closed.secondary_guard import (
    NonBypassableSecondaryGuard,
)
from myrm_agent_harness.core.security.hitl_fail_closed.types import (
    ApprovalDecision,
    ApprovalRequestPayload,
    FailClosedReason,
    HitlExecutionPipelineVerdict,
    HitlFailClosedError,
    SecondaryGuardVerdict,
    SecondaryGuardViolationError,
)

__all__ = [
    "ApprovalDecision",
    "ApprovalRequestPayload",
    "FailClosedReason",
    "HitlApprovalPipeline",
    "HitlExecutionPipelineVerdict",
    "HitlFailClosedError",
    "NonBypassableSecondaryGuard",
    "SecondaryGuardVerdict",
    "SecondaryGuardViolationError",
]
