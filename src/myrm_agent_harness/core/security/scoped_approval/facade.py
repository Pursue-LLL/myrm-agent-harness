"""
[POS] src/myrm_agent_harness/core/security/scoped_approval/facade.py
[INPUT] time, types, lease_engine, risk_gate_router
[OUTPUT] ScopedApprovalGateFacade
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time

from .lease_engine import ScopedGrantLeaseEngine
from .risk_gate_router import RiskTieredGateRouter
from .types import (
    ApprovalGrantLease,
    GateDecision,
    GrantScope,
    GrantUsageRecord,
    RiskEvaluationRequest,
    RiskEvaluationResult,
    ScopedApprovalMetrics,
)


class ScopedApprovalGateFacade:
    """Unified facade orchestrating scoped approval grants, risk-tiered gating, and audit ledgers."""

    def __init__(
        self,
        lease_engine: ScopedGrantLeaseEngine | None = None,
        gate_router: RiskTieredGateRouter | None = None,
    ) -> None:
        self._lease_engine = lease_engine or ScopedGrantLeaseEngine()
        self._gate_router = gate_router or RiskTieredGateRouter()
        self._metrics = ScopedApprovalMetrics()

    @property
    def metrics(self) -> ScopedApprovalMetrics:
        """Operational telemetry counters."""
        return self._metrics

    def issue_grant(
        self,
        tool_name: str,
        scope: GrantScope,
        agent_id: str,
        session_id: str,
        task_id: str | None = None,
        current_time: float | None = None,
        ttl_seconds: float | None = None,
    ) -> ApprovalGrantLease:
        """Issue a new scoped approval lease voucher."""
        lease = self._lease_engine.issue_grant(
            tool_name=tool_name,
            scope=scope,
            agent_id=agent_id,
            session_id=session_id,
            task_id=task_id,
            current_time=current_time,
            ttl_seconds=ttl_seconds,
        )
        self._metrics.grants_issued_total += 1
        return lease

    def evaluate_and_process(
        self,
        request: RiskEvaluationRequest,
        current_time: float | None = None,
    ) -> RiskEvaluationResult:
        """Evaluate invocation against risk tiers and active leases, updating metrics and ledger."""
        now = time.time() if current_time is None else current_time
        self._metrics.evaluations_total += 1

        active_lease = self._lease_engine.find_active_grant(
            tool_name=request.tool_name,
            agent_id=request.agent_id,
            session_id=request.session_id,
            task_id=request.task_id,
            current_time=now,
        )

        res = self._gate_router.evaluate(request=request, active_lease=active_lease)

        if res.decision == GateDecision.ALLOW:
            self._metrics.silent_allows_total += 1
            if active_lease is not None:
                self._lease_engine.redeem_grant(
                    grant_id=active_lease.grant_id,
                    tool_name=request.tool_name,
                    agent_id=request.agent_id,
                    session_id=request.session_id,
                    task_id=request.task_id,
                    current_time=now,
                )
                self._metrics.grant_redemptions_total += 1
        elif res.decision == GateDecision.ASK:
            self._metrics.asks_required_total += 1
        elif res.decision == GateDecision.DENY:
            self._metrics.denials_total += 1

        return res

    def revoke_grant(self, grant_id: str) -> bool:
        """Revoke an active approval lease."""
        success = self._lease_engine.revoke_grant(grant_id)
        if success:
            self._metrics.grants_revoked_total += 1
        return success

    def revoke_all(
        self, agent_id: str | None = None, session_id: str | None = None
    ) -> int:
        """Revoke all matching active approval leases."""
        count = self._lease_engine.revoke_all(agent_id=agent_id, session_id=session_id)
        self._metrics.grants_revoked_total += count
        return count

    def list_active_grants(
        self, current_time: float | None = None
    ) -> tuple[ApprovalGrantLease, ...]:
        """Fetch all currently active leases."""
        return self._lease_engine.list_active_grants(current_time=current_time)

    def get_audit_ledger(self) -> tuple[GrantUsageRecord, ...]:
        """Fetch redemption audit trail."""
        return self._lease_engine.get_audit_ledger()
