"""Type definitions for Independent Risk Evaluator Agent and OS Security Scanner.

[INPUT]
None.

[OUTPUT]
- ProposalActionType, RiskEvaluationTier
- ActionProposal, RiskEvaluationReport, OsOperatorScanResult
- RiskEvaluationError, HighRiskActionBlockedError

[POS]
Harness core security subsystem providing multi-agent independent risk checks (AutoHedge inspired)
and OS-level safe operator scanning (ECC inspired).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ProposalActionType(StrEnum):
    """Categorization of proposed operational actions."""

    FINANCIAL_TRANSACTION = "financial_transaction"
    SYSTEM_OPERATION = "system_operation"
    DATA_MUTATION = "data_mutation"
    NETWORK_OUTBOUND = "network_outbound"
    COMPUTE_INTENSIVE = "compute_intensive"


class RiskEvaluationTier(StrEnum):
    """Graded risk severity tiers."""

    PASS_SAFE = "pass_safe"
    WARN_ELEVATED = "warn_elevated"
    BLOCK_CRITICAL = "block_critical"


@dataclass(frozen=True, slots=True)
class ActionProposal:
    """Action plan proposal submitted by a planner agent before execution."""

    proposal_id: str
    action_type: ProposalActionType
    title: str
    description: str
    estimated_cost: float = 0.0
    blast_radius_scope: str = "local"  # local, cluster, external, global
    rollback_supported: bool = True
    raw_command_or_payload: str | None = None
    target_resources: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class OsOperatorScanResult:
    """Outcome of OS-level AST and pattern vulnerability scanning."""

    safe: bool
    command_signature: str
    detected_vulnerabilities: tuple[str, ...] = ()
    blocked_patterns: tuple[str, ...] = ()
    scanned_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class RiskEvaluationReport:
    """Comprehensive verdict produced by the Independent Risk Evaluator Agent."""

    evaluation_id: str
    proposal_id: str
    tier: RiskEvaluationTier
    risk_score: float  # 0.0 (safe) to 100.0 (critical danger)
    approved: bool
    blast_radius_score: float
    rollback_feasible: bool
    violations: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    os_scan_result: OsOperatorScanResult | None = None
    evaluated_at: float = field(default_factory=time.time)


class RiskEvaluationError(Exception):
    """Base error for risk evaluation operations."""


class HighRiskActionBlockedError(RiskEvaluationError):
    """Raised when an action proposal fails independent risk assessment."""

    def __init__(self, proposal_id: str, reason: str, score: float) -> None:
        super().__init__(f"Action proposal '{proposal_id}' blocked by Risk Evaluator (score {score:.1f}): {reason}")
        self.proposal_id = proposal_id
        self.reason = reason
        self.score = score
