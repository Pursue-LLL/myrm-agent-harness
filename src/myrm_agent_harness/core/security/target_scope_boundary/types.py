"""
[POS] src/myrm_agent_harness/core/security/target_scope_boundary/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] ScopeVerdict, TargetScopeContract, ScopeVerificationResult, TargetScopeMetrics

Domain types for Strict Target Scope Authorization & Egress Boundary Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ScopeVerdict(StrEnum):
    """Enforcement evaluation outcome for a destination target."""

    IN_SCOPE_ALLOWED = "IN_SCOPE_ALLOWED"
    OUT_OF_SCOPE_BLOCKED = "OUT_OF_SCOPE_BLOCKED"
    CLOUD_METADATA_PROHIBITED = "CLOUD_METADATA_PROHIBITED"
    EMERGENCY_KILL_SWITCH_ACTIVE = "EMERGENCY_KILL_SWITCH_ACTIVE"
    UNAUTHORIZED_IP_BLOCKED = "UNAUTHORIZED_IP_BLOCKED"


@dataclass(frozen=True)
class TargetScopeContract:
    """Rules of Engagement (ROE) contract defining strictly permitted target parameters."""

    contract_id: str
    engagement_name: str
    authorized_domains: tuple[str, ...]
    authorized_cidrs: tuple[str, ...]
    prohibited_targets: tuple[str, ...]
    signed_by: str
    signature_hash: str
    is_active: bool = True


@dataclass(frozen=True)
class ScopeVerificationResult:
    """Outcome of verifying outbound connection destination against active ROE contract."""

    is_allowed: bool
    verdict: ScopeVerdict
    target_host: str
    resolved_ip: str | None
    diagnostic_reason: str
    contract_id: str | None


@dataclass
class TargetScopeMetrics:
    """Cumulative operational metrics for target scope authorization and egress boundaries."""

    scope_checks_total: int = 0
    in_scope_allowed_total: int = 0
    out_of_scope_blocked_total: int = 0
    metadata_probes_blocked_total: int = 0
    kill_switch_activations_total: int = 0
