"""
[POS] src/myrm_agent_harness/core/security/outbound_ebrake_mesh/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] OutboundActionType, AudienceRiskTier, ActionBufferStatus, GhostInspectionVerdict, OutboundActionItem, EBrakeStatus, CalendarTimeSlot, CalendarNegotiationResult, OutboundEBrakeMetrics

Domain types for Outbound Irreversible Action E-Brake & Privacy-Preserving Chief of Staff Mesh Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OutboundActionType(StrEnum):
    """Categorization of irreversible external side-effect operations."""

    EMAIL_DISPATCH = "EMAIL_DISPATCH"
    IM_BROADCAST = "IM_BROADCAST"
    WEBHOOK_CALL = "WEBHOOK_CALL"
    CALENDAR_MUTATION = "CALENDAR_MUTATION"
    SOCIAL_POST = "SOCIAL_POST"


class AudienceRiskTier(StrEnum):
    """Destination audience risk classification based on domain boundaries."""

    INTERNAL_SAFE = "INTERNAL_SAFE"
    EXTERNAL_TRUSTED = "EXTERNAL_TRUSTED"
    EXTERNAL_UNTRUSTED = "EXTERNAL_UNTRUSTED"
    PROHIBITED_LEAK = "PROHIBITED_LEAK"


class ActionBufferStatus(StrEnum):
    """State transition lifecycle of an outbound operation in the grace-period buffer."""

    QUEUED_IN_GRACE_PERIOD = "QUEUED_IN_GRACE_PERIOD"
    DISPATCHED_AFTER_GRACE = "DISPATCHED_AFTER_GRACE"
    CANCELLED_BY_USER = "CANCELLED_BY_USER"
    ABORTED_BY_E_BRAKE = "ABORTED_BY_E_BRAKE"
    BLOCKED_BY_GHOST_GATE = "BLOCKED_BY_GHOST_GATE"


@dataclass(frozen=True)
class GhostInspectionVerdict:
    """Evaluation result of pre-flight shadow inspection on outbound side effects."""

    is_safe_to_queue: bool
    risk_tier: AudienceRiskTier
    tainted_tokens_detected: tuple[str, ...]
    ghost_summary: str
    diagnostic_reason: str


@dataclass(frozen=True)
class OutboundActionItem:
    """Outbound operation buffered with a visual grace-period countdown."""

    action_id: str
    task_id: str
    action_type: OutboundActionType
    destination_target: str
    payload_summary: str
    full_payload_text: str
    risk_tier: AudienceRiskTier
    enqueued_at_epoch: float
    grace_period_seconds: float
    status: ActionBufferStatus
    cancellation_reason: str | None = None


@dataclass(frozen=True)
class EBrakeStatus:
    """Global emergency brake status for interrupting all buffered outbound operations."""

    is_e_brake_active: bool
    last_triggered_at_epoch: float | None
    trigger_reason: str | None
    actions_aborted_count: int


@dataclass(frozen=True)
class CalendarTimeSlot:
    """Zero-knowledge time slot representing free/busy availability and preference."""

    slot_index: int
    start_time_iso: str
    duration_minutes: int
    is_free: bool
    preference_score: float


@dataclass(frozen=True)
class CalendarNegotiationResult:
    """Outcome of privacy-preserving multi-agent calendar scheduling negotiation."""

    negotiation_id: str
    party_a_id: str
    party_b_id: str
    matched_slots: tuple[CalendarTimeSlot, ...]
    optimal_slot: CalendarTimeSlot | None
    privacy_preserved: bool = True
    diagnostic_notes: str = ""


@dataclass
class OutboundEBrakeMetrics:
    """Cumulative operational metrics for outbound gate, e-brake, and calendar mesh."""

    inspections_total: int = 0
    blocked_by_ghost_gate_total: int = 0
    queued_in_grace_period_total: int = 0
    dispatched_total: int = 0
    cancelled_by_user_total: int = 0
    e_brake_activations_total: int = 0
    calendar_negotiations_total: int = 0
