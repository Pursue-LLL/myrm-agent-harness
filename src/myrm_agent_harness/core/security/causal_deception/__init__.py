"""Causal Deception Defense & Mechanism Probe Package.

Grounds agent assertions in objective tool execution traces to prevent deceptive
fabrication and sycophantic reporting (arXiv:2609.04166).
"""

from myrm_agent_harness.core.security.causal_deception.guard import (
    CausalConsistencyGuard,
)
from myrm_agent_harness.core.security.causal_deception.matrix import (
    CommitmentExecutionReportMatrix,
)
from myrm_agent_harness.core.security.causal_deception.probe import (
    AudienceAsymmetryProbe,
)
from myrm_agent_harness.core.security.causal_deception.types import (
    CausalAuditReport,
    CausalDeceptionError,
    ClaimStatus,
    CommitmentItem,
    CommitmentType,
    CounterfactualProbeResult,
    DeceptiveFabricationDetectedError,
    ExecutionTraceItem,
    InvarianceVerdict,
    InvarianceViolation,
    PhantomExecutionError,
    PostReportClaim,
    TechnicalProficiency,
)

__all__ = [
    "AudienceAsymmetryProbe",
    "CausalAuditReport",
    "CausalConsistencyGuard",
    "CausalDeceptionError",
    "ClaimStatus",
    "CommitmentExecutionReportMatrix",
    "CommitmentItem",
    "CommitmentType",
    "CounterfactualProbeResult",
    "DeceptiveFabricationDetectedError",
    "ExecutionTraceItem",
    "InvarianceVerdict",
    "InvarianceViolation",
    "PhantomExecutionError",
    "PostReportClaim",
    "TechnicalProficiency",
]
