"""
[POS] src/myrm_agent_harness/core/security/target_scope_boundary/facade.py
[INPUT] logging, typing, .types, .scope_contract_validator, .egress_boundary_interceptor
[OUTPUT] StrictTargetScopeBoundarySuite

Unified facade for Strict Target Scope Authorization & Egress Boundary Suite.
Coordinates Rules of Engagement (ROE) contract enforcement, kernel/proxy egress interception,
and emergency kill-switch circuit breaker.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .egress_boundary_interceptor import DynamicEgressBoundaryInterceptor
from .scope_contract_validator import TargetScopeContractValidator
from .types import (
    ScopeVerdict,
    ScopeVerificationResult,
    TargetScopeContract,
    TargetScopeMetrics,
)

logger = logging.getLogger(__name__)


class StrictTargetScopeBoundarySuite:
    """Unified security suite safeguarding target authorization scopes and preventing out-of-scope egress."""

    def __init__(
        self,
        validator: TargetScopeContractValidator | None = None,
        interceptor: DynamicEgressBoundaryInterceptor | None = None,
    ) -> None:
        self._validator = validator or TargetScopeContractValidator()
        self._interceptor = interceptor or DynamicEgressBoundaryInterceptor(validator=self._validator)
        self._metrics = TargetScopeMetrics()

    @property
    def metrics(self) -> TargetScopeMetrics:
        """Retrieve cumulative metrics."""
        return self._metrics

    def set_active_contract(self, contract: TargetScopeContract | None) -> None:
        """Configure active Rules of Engagement scope contract."""
        self._interceptor.set_active_contract(contract)

    def get_active_contract(self) -> TargetScopeContract | None:
        """Retrieve active ROE contract."""
        return self._interceptor.get_active_contract()

    def activate_kill_switch(self) -> None:
        """Activate emergency kill-switch to immediately halt all external scanner egress."""
        self._interceptor.activate_emergency_kill_switch()
        self._metrics.kill_switch_activations_total += 1

    def reset_kill_switch(self) -> None:
        """Reset emergency kill-switch to resume authorized scoped scans."""
        self._interceptor.reset_emergency_kill_switch()

    def is_kill_switch_active(self) -> bool:
        """Check if emergency kill-switch is engaged."""
        return self._interceptor.is_kill_switch_active()

    def verify_target(
        self,
        target_host: str,
        resolved_ip: str | None = None,
    ) -> ScopeVerificationResult:
        """Verify destination target against active scope rules and emergency breakers."""
        self._metrics.scope_checks_total += 1
        result = self._interceptor.verify_egress_target(target_host=target_host, resolved_ip=resolved_ip)

        if result.verdict == ScopeVerdict.IN_SCOPE_ALLOWED:
            self._metrics.in_scope_allowed_total += 1
        else:
            self._metrics.out_of_scope_blocked_total += 1
            if result.verdict == ScopeVerdict.CLOUD_METADATA_PROHIBITED:
                self._metrics.metadata_probes_blocked_total += 1

        return result
