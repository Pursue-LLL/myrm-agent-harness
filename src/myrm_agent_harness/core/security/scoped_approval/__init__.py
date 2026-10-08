"""
[POS] src/myrm_agent_harness/core/security/scoped_approval/__init__.py
Scoped Approval Grant and Risk-Tiered Gate Suite.
Exports domain types, lease engine, risk gate router, and facade.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .facade import ScopedApprovalGateFacade
from .lease_engine import ScopedGrantLeaseEngine
from .risk_gate_router import RiskTieredGateRouter
from .types import (
    ActionRiskTier,
    ApprovalGrantLease,
    GateDecision,
    GrantScope,
    GrantUsageRecord,
    RiskEvaluationRequest,
    RiskEvaluationResult,
    ScopedApprovalMetrics,
)

__all__ = [
    "ActionRiskTier",
    "ApprovalGrantLease",
    "GateDecision",
    "GrantScope",
    "GrantUsageRecord",
    "RiskEvaluationRequest",
    "RiskEvaluationResult",
    "RiskTieredGateRouter",
    "ScopedApprovalGateFacade",
    "ScopedApprovalMetrics",
    "ScopedGrantLeaseEngine",
]
