"""Independent Risk Evaluator Agent implementing risk-first dual-validation.

[INPUT]
- ActionProposal: proposed plan or operational action
- OsSecurityGuard: runtime OS security verification

[OUTPUT]
- RiskEvaluationReport: comprehensive safety score, tier classification, and approval verdict.
- HighRiskActionBlockedError: raised when high-risk proposal is blocked.

[POS]
Harness core multi-agent safety layer inspired by AutoHedge (segregated risk evaluation agent).
Ensures high-impact proposals are judged independently before execution.
"""

from __future__ import annotations

import time
import uuid

from myrm_agent_harness.core.security.risk_evaluator.os_security_guard import OsSecurityGuard
from myrm_agent_harness.core.security.risk_evaluator.types import (
    ActionProposal,
    HighRiskActionBlockedError,
    OsOperatorScanResult,
    ProposalActionType,
    RiskEvaluationReport,
    RiskEvaluationTier,
)

_DEFAULT_MAX_COST_LIMIT: float = 100.0


class IndependentRiskEvaluatorAgent:
    """Specialized evaluation agent acting as an independent risk gate."""

    def __init__(
        self,
        max_cost_limit: float = _DEFAULT_MAX_COST_LIMIT,
        strict_mode: bool = False,
    ) -> None:
        self._max_cost_limit = max_cost_limit
        self._strict_mode = strict_mode

    @property
    def max_cost_limit(self) -> float:
        """Maximum allowable financial cost ceiling."""
        return self._max_cost_limit

    def evaluate_proposal(self, proposal: ActionProposal) -> RiskEvaluationReport:
        """Compute holistic risk score across financial, blast radius, rollback, and OS vectors."""
        score: float = 0.0
        violations: list[str] = []
        recommendations: list[str] = []
        os_scan: OsOperatorScanResult | None = None

        # 1. Financial & budget limits
        if proposal.action_type == ProposalActionType.FINANCIAL_TRANSACTION:
            score += 30.0
            if proposal.estimated_cost > self._max_cost_limit:
                score += 45.0
                violations.append(
                    f"Estimated cost ${proposal.estimated_cost:.2f} exceeds threshold ${self._max_cost_limit:.2f}"
                )
                recommendations.append("Require executive financial approval before proceeding")

        # 2. Blast radius evaluation
        scope_weights = {
            "local": 5.0,
            "cluster": 25.0,
            "external": 40.0,
            "global": 60.0,
        }
        blast_score = scope_weights.get(proposal.blast_radius_scope.lower(), 15.0)
        score += blast_score
        if blast_score >= 40.0:
            violations.append(f"High blast radius scope: '{proposal.blast_radius_scope}'")
            recommendations.append("Partition target resources or reduce deployment scope")

        # 3. Rollback feasibility
        if not proposal.rollback_supported:
            score += 25.0
            violations.append("Irreversible action: rollback is not supported")
            recommendations.append("Implement automated snapshot or idempotent compensation step")

        # 4. OS runtime security scanning
        if proposal.raw_command_or_payload:
            os_scan = OsSecurityGuard.scan_command(proposal.raw_command_or_payload)
            if not os_scan.safe:
                score += 55.0
                for vuln in os_scan.detected_vulnerabilities:
                    violations.append(f"OS Security Violation: {vuln}")
                recommendations.append("Sanitize or replace high-risk shell command")

        # Clamp risk score
        score = min(100.0, max(0.0, score))

        # Determine risk tier
        if score >= 60.0 or (self._strict_mode and score >= 35.0):
            tier = RiskEvaluationTier.BLOCK_CRITICAL
            approved = False
        elif score >= 30.0:
            tier = RiskEvaluationTier.WARN_ELEVATED
            approved = True
        else:
            tier = RiskEvaluationTier.PASS_SAFE
            approved = True

        evaluation_id = f"eval_{uuid.uuid4().hex[:10]}"
        return RiskEvaluationReport(
            evaluation_id=evaluation_id,
            proposal_id=proposal.proposal_id,
            tier=tier,
            risk_score=score,
            approved=approved,
            blast_radius_score=blast_score,
            rollback_feasible=proposal.rollback_supported,
            violations=tuple(violations),
            recommendations=tuple(recommendations),
            os_scan_result=os_scan,
            evaluated_at=time.time(),
        )

    def evaluate_and_enforce(self, proposal: ActionProposal) -> RiskEvaluationReport:
        """Evaluate proposal and raise HighRiskActionBlockedError if blocked."""
        report = self.evaluate_proposal(proposal)
        if not report.approved:
            reason = "; ".join(report.violations) if report.violations else "Risk threshold exceeded"
            raise HighRiskActionBlockedError(
                proposal_id=proposal.proposal_id,
                reason=reason,
                score=report.risk_score,
            )
        return report
