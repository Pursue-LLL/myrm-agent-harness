"""
[POS] src/myrm_agent_harness/core/security/autonomous_signing_airgap/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] SigningDecisionStatus, TransactionPayload, SigningQuotaConfig, SigningEvaluationVerdict, WalletAirgapMetrics
Domain types for Headless Autonomous Signing Sandbox & Keyring Airgap Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SigningDecisionStatus(StrEnum):
    """Evaluation verdict for autonomous wallet/signing requests."""

    SILENT_AUTHORIZED = "SILENT_AUTHORIZED"
    REQUIRE_HITL_STEP_UP = "REQUIRE_HITL_STEP_UP"
    REJECTED_QUOTA_EXCEEDED = "REJECTED_QUOTA_EXCEEDED"
    REJECTED_UNTRUSTED_RECIPIENT = "REJECTED_UNTRUSTED_RECIPIENT"
    FROZEN_BY_KILL_SWITCH = "FROZEN_BY_KILL_SWITCH"


@dataclass(frozen=True)
class TransactionPayload:
    """Structured transaction payload submitted for airgapped signing."""

    tx_id: str
    recipient: str
    amount: float
    currency: str
    chain_or_network: str
    call_data_summary: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SigningQuotaConfig:
    """Security rules governing headless transaction signing thresholds."""

    single_tx_limit: float = 100.0
    daily_cumulative_limit: float = 500.0
    trusted_recipients: tuple[str, ...] = ()


@dataclass(frozen=True)
class SigningEvaluationVerdict:
    """Verdict rendered by the airgap sandbox and quota guard."""

    decision: SigningDecisionStatus
    is_approved_to_sign: bool
    signature_token: str | None
    diagnostic_reason: str
    tx_id: str
    remaining_daily_allowance: float


@dataclass
class WalletAirgapMetrics:
    """Operational metrics for autonomous signing delegate and airgap sandbox."""

    evaluations_total: int = 0
    silent_signed_total: int = 0
    hitl_stepped_up_total: int = 0
    rejected_quota_total: int = 0
    rejected_untrusted_total: int = 0
    kill_switch_blocked_total: int = 0
