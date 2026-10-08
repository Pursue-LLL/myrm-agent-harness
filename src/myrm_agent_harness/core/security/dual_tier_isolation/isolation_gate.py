"""Dual-Tier Physical Isolation Gate enforcing strict Control/Data plane separation.

[INPUT]
- Raw API keys, target access planes, requested user/tenant contexts, and operation scopes.

[OUTPUT]
- AccessEvaluationVerdict with definitive isolation permissions and audit rationale.

[POS]
- Harness core security gate preventing administrative data snooping and user privilege escalation.
"""

from __future__ import annotations

import uuid

from myrm_agent_harness.core.security.dual_tier_isolation.key_vault import (
    DualTierKeyVault,
)
from myrm_agent_harness.core.security.dual_tier_isolation.types import (
    AccessEvaluationVerdict,
    AccessPlane,
    IsolationVerdict,
    KeyTier,
)


class DualTierIsolationGate:
    """Evaluates operations against the dual-tier control/data plane security boundary."""

    def __init__(self, key_vault: DualTierKeyVault | None = None) -> None:
        self._vault = key_vault or DualTierKeyVault()

    @property
    def vault(self) -> DualTierKeyVault:
        """Access underlying key vault."""
        return self._vault

    def evaluate_access(
        self,
        raw_key: str,
        requested_plane: AccessPlane,
        target_user_id: str | None = None,
        target_tenant_id: str | None = None,
        requested_scope: str = "",
    ) -> AccessEvaluationVerdict:
        """Enforce strict physical isolation between management and tenant data operations."""
        audit_id = f"iso-{uuid.uuid4().hex[:12]}"

        record = self._vault.lookup_raw_key(raw_key)
        if record is None:
            return AccessEvaluationVerdict(
                verdict=IsolationVerdict.BLOCKED_INVALID_KEY,
                is_permitted=False,
                effective_tier=None,
                user_id=None,
                tenant_id=None,
                audit_id=audit_id,
                message="Authentication failed: invalid or unknown API key.",
            )

        if record.is_revoked:
            return AccessEvaluationVerdict(
                verdict=IsolationVerdict.BLOCKED_REVOKED_KEY,
                is_permitted=False,
                effective_tier=record.tier,
                user_id=record.user_id,
                tenant_id=record.tenant_id,
                audit_id=audit_id,
                message="Access denied: API key has been revoked.",
            )

        # Tier 1: Root Admin Key Enforcement
        if record.tier == KeyTier.ROOT_ADMIN:
            if requested_plane == AccessPlane.DATA_PLANE:
                return AccessEvaluationVerdict(
                    verdict=IsolationVerdict.BLOCKED_DATA_PLANE_VIOLATION,
                    is_permitted=False,
                    effective_tier=KeyTier.ROOT_ADMIN,
                    user_id=None,
                    tenant_id=None,
                    audit_id=audit_id,
                    message="Dual-tier violation: Root Admin API keys are strictly forbidden from "
                    "directly accessing private tenant memories or data plane contexts.",
                )

            return AccessEvaluationVerdict(
                verdict=IsolationVerdict.PERMITTED,
                is_permitted=True,
                effective_tier=KeyTier.ROOT_ADMIN,
                user_id=None,
                tenant_id=None,
                audit_id=audit_id,
                message="Control-plane administrative operation authorized for Root Admin key.",
            )

        # Tier 2: Derived User Key Enforcement
        if record.tier == KeyTier.DERIVED_USER:
            if requested_plane == AccessPlane.CONTROL_PLANE:
                return AccessEvaluationVerdict(
                    verdict=IsolationVerdict.BLOCKED_CONTROL_PLANE_VIOLATION,
                    is_permitted=False,
                    effective_tier=KeyTier.DERIVED_USER,
                    user_id=record.user_id,
                    tenant_id=record.tenant_id,
                    audit_id=audit_id,
                    message="Dual-tier violation: User API keys cannot access control-plane "
                    "management, host infrastructure, or sandbox scheduling operations.",
                )

            # Data-plane access: check tenant and user boundary
            if target_user_id and target_user_id != record.user_id:
                return AccessEvaluationVerdict(
                    verdict=IsolationVerdict.BLOCKED_CROSS_TENANT_BREACH,
                    is_permitted=False,
                    effective_tier=KeyTier.DERIVED_USER,
                    user_id=record.user_id,
                    tenant_id=record.tenant_id,
                    audit_id=audit_id,
                    message=f"Cross-tenant breach prevented: API key bound to user '{record.user_id}' "
                    f"attempted to access target user '{target_user_id}' context.",
                )

            if target_tenant_id and record.tenant_id and target_tenant_id != record.tenant_id:
                return AccessEvaluationVerdict(
                    verdict=IsolationVerdict.BLOCKED_CROSS_TENANT_BREACH,
                    is_permitted=False,
                    effective_tier=KeyTier.DERIVED_USER,
                    user_id=record.user_id,
                    tenant_id=record.tenant_id,
                    audit_id=audit_id,
                    message=f"Cross-tenant breach prevented: API key bound to tenant '{record.tenant_id}' "
                    f"attempted to access target tenant '{target_tenant_id}' context.",
                )

            return AccessEvaluationVerdict(
                verdict=IsolationVerdict.PERMITTED,
                is_permitted=True,
                effective_tier=KeyTier.DERIVED_USER,
                user_id=record.user_id,
                tenant_id=record.tenant_id,
                audit_id=audit_id,
                message="Data-plane tenant interaction authorized within bound scope.",
            )

        return AccessEvaluationVerdict(
            verdict=IsolationVerdict.BLOCKED_INVALID_KEY,
            is_permitted=False,
            effective_tier=None,
            user_id=None,
            tenant_id=None,
            audit_id=audit_id,
            message="Unhandled key tier encountered.",
        )
