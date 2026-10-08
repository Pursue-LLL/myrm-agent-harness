"""
[POS] src/myrm_agent_harness/core/security/data_sovereignty_watchdog/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] SovereigntySealLevel, SovereigntySealManifest, ProactivityValueLevel, SubIntrusiveNotificationCard, HighStakesActionType, HighStakesConsentTicket, DataSovereigntyWatchdogMetrics

Data structures and specifications for Private Sandbox Data Sovereignty & Sub-Intrusive Proactivity Watchdog Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SovereigntySealLevel(StrEnum):
    """Enforceable storage isolation guarantee."""

    LOCAL_AIRGAPPED = "LOCAL_AIRGAPPED"
    PRIVATE_SANDBOX_VOLUME = "PRIVATE_SANDBOX_VOLUME"
    VERIFIED_ENCRYPTED = "VERIFIED_ENCRYPTED"


class ProactivityValueLevel(StrEnum):
    """Filter level for proactive suggestions."""

    TRIVIAL_NOISE = "TRIVIAL_NOISE"
    MODERATE_SUGGESTION = "MODERATE_SUGGESTION"
    HIGH_VALUE_ALERT = "HIGH_VALUE_ALERT"
    CRITICAL_DEADLINE = "CRITICAL_DEADLINE"


class HighStakesActionType(StrEnum):
    """High-stakes financial or account mutation action requiring mandatory human consent."""

    SUBSCRIPTION_CANCEL = "SUBSCRIPTION_CANCEL"
    REFUND_DISPUTE = "REFUND_DISPUTE"
    PAYMENT_METHOD_UPDATE = "PAYMENT_METHOD_UPDATE"
    BALANCE_TRANSFER = "BALANCE_TRANSFER"


@dataclass(frozen=True)
class SovereigntySealManifest:
    """Immutable proof that financial receipts and email tokens remain strictly within private sandbox."""

    seal_id: str
    storage_target: str
    seal_level: SovereigntySealLevel
    central_cloud_zero_retention: bool
    volume_mount_path: str
    created_at: float
    checksum: str


@dataclass(frozen=True)
class SubIntrusiveNotificationCard:
    """Non-intrusive notification card emitted only when value surpasses anti-annoyance thresholds."""

    card_id: str
    title: str
    potential_savings_cents: int
    deadline_epoch: float | None
    value_level: ProactivityValueLevel
    is_suppressed: bool
    message: str
    service_name: str


@dataclass(frozen=True)
class HighStakesConsentTicket:
    """One-time ticket locking an automated financial/account mutation until human approval."""

    ticket_id: str
    action_type: HighStakesActionType
    service_name: str
    financial_impact_cents: int
    payload_summary: str
    is_approved: bool = False
    is_denied: bool = False
    created_at: float = 0.0


@dataclass
class DataSovereigntyWatchdogMetrics:
    """Cumulative operational metrics for data sovereignty and sub-intrusive guardrail operations."""

    sovereignty_seals_issued_total: int = 0
    proactive_scans_total: int = 0
    noise_suppressed_total: int = 0
    high_value_alerts_emitted_total: int = 0
    high_stakes_actions_blocked_total: int = 0
    high_stakes_consents_approved_total: int = 0
    high_stakes_consents_denied_total: int = 0
