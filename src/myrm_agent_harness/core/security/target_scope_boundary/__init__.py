"""
[POS] src/myrm_agent_harness/core/security/target_scope_boundary/__init__.py
[INPUT] .types, .scope_contract_validator, .egress_boundary_interceptor, .facade
[OUTPUT] StrictTargetScopeBoundarySuite, ScopeVerdict, TargetScopeContract, etc.

Export interface for Strict Target Scope Authorization & Egress Boundary Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .egress_boundary_interceptor import DynamicEgressBoundaryInterceptor
from .facade import StrictTargetScopeBoundarySuite
from .scope_contract_validator import TargetScopeContractValidator
from .types import (
    ScopeVerdict,
    ScopeVerificationResult,
    TargetScopeContract,
    TargetScopeMetrics,
)

__all__ = [
    "DynamicEgressBoundaryInterceptor",
    "ScopeVerdict",
    "ScopeVerificationResult",
    "StrictTargetScopeBoundarySuite",
    "TargetScopeContract",
    "TargetScopeContractValidator",
    "TargetScopeMetrics",
]
