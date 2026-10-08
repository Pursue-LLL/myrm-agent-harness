"""
[POS] src/myrm_agent_harness/core/security/scoped_approval/risk_gate_router.py
[INPUT] types
[OUTPUT] RiskTieredGateRouter
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .types import (
    ActionRiskTier,
    ApprovalGrantLease,
    GateDecision,
    RiskEvaluationRequest,
    RiskEvaluationResult,
)

logger = logging.getLogger(__name__)


class RiskTieredGateRouter:
    """Routes execution requests through risk classification policies and approval lease validations."""

    def __init__(
        self,
        deny_tools: tuple[str, ...] = ("rm_rf", "format_disk", "dump_system_secrets"),
        always_allow_tools: tuple[str, ...] = ("echo", "get_current_time", "read_clock"),
        always_ask_tools: tuple[str, ...] = ("transfer_funds", "send_external_email", "execute_sql_ddl"),
        auto_allow_low_risk_write: bool = False,
    ) -> None:
        self._deny_tools = {t.strip().lower() for t in deny_tools}
        self._always_allow_tools = {t.strip().lower() for t in always_allow_tools}
        self._always_ask_tools = {t.strip().lower() for t in always_ask_tools}
        self._auto_allow_low_risk_write = auto_allow_low_risk_write

    def evaluate(
        self,
        request: RiskEvaluationRequest,
        active_lease: ApprovalGrantLease | None = None,
    ) -> RiskEvaluationResult:
        """Resolve access control decision according to risk tiering, blacklist, and lease redemption."""
        tool_clean = request.tool_name.strip().lower()

        # 1. Hard Denial Blacklist
        if tool_clean in self._deny_tools:
            return RiskEvaluationResult(
                decision=GateDecision.DENY,
                reason=f"Tool '{request.tool_name}' is in the hard-denial blacklist",
                matched_grant_id=None,
                risk_tier=request.risk_tier,
                requires_hitl_prompt=False,
            )

        # 2. Active Approval Lease Redemption
        if active_lease is not None:
            return RiskEvaluationResult(
                decision=GateDecision.ALLOW,
                reason=(
                    f"Execution granted under active {active_lease.scope.value} lease "
                    f"'{active_lease.grant_id}'"
                ),
                matched_grant_id=active_lease.grant_id,
                risk_tier=request.risk_tier,
                requires_hitl_prompt=False,
            )

        # 3. Always-Ask Tool Constraint
        if tool_clean in self._always_ask_tools:
            return RiskEvaluationResult(
                decision=GateDecision.ASK,
                reason=f"Tool '{request.tool_name}' mandates human-in-the-loop confirmation",
                matched_grant_id=None,
                risk_tier=request.risk_tier,
                requires_hitl_prompt=True,
            )

        # 4. Always-Allow Whitelist
        if tool_clean in self._always_allow_tools:
            return RiskEvaluationResult(
                decision=GateDecision.ALLOW,
                reason=f"Tool '{request.tool_name}' configured for always-allow pass-through",
                matched_grant_id=None,
                risk_tier=request.risk_tier,
                requires_hitl_prompt=False,
            )

        # 5. Risk-Tiered Automated Resolution
        if request.risk_tier == ActionRiskTier.READ_ONLY:
            return RiskEvaluationResult(
                decision=GateDecision.ALLOW,
                reason="Read-only operation permitted silently with telemetry audit",
                matched_grant_id=None,
                risk_tier=request.risk_tier,
                requires_hitl_prompt=False,
            )

        if request.risk_tier == ActionRiskTier.LOW_RISK_WRITE:
            if self._auto_allow_low_risk_write:
                return RiskEvaluationResult(
                    decision=GateDecision.ALLOW,
                    reason="Low-risk write permitted under relaxed tiering policy",
                    matched_grant_id=None,
                    risk_tier=request.risk_tier,
                    requires_hitl_prompt=False,
                )
            return RiskEvaluationResult(
                decision=GateDecision.ASK,
                reason="Low-risk write operation requires human-in-the-loop confirmation",
                matched_grant_id=None,
                risk_tier=request.risk_tier,
                requires_hitl_prompt=True,
            )

        # High-risk writes and irreversible egress actions always mandate confirmation
        return RiskEvaluationResult(
            decision=GateDecision.ASK,
            reason=(
                f"Operation classified as '{request.risk_tier.value}' mandates human approval"
            ),
            matched_grant_id=None,
            risk_tier=request.risk_tier,
            requires_hitl_prompt=True,
        )
