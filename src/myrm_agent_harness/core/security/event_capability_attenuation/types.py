"""
[POS] src/myrm_agent_harness/core/security/event_capability_attenuation/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] EventTrustScopeEnum, ApprovalTicketStatusEnum, TicketRiskLevelEnum, ChannelNotificationTarget, ApprovalTicket, EventPayloadDescriptor, AttenuationRule, CapabilityAttenuationMetrics

Data structures and specifications for Event-Triggered Capability Attenuation
and Multi-Channel Unattended Async Approval Bridge Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class EventTrustScopeEnum(StrEnum):
    """Execution context trust scope."""

    USER_INTERACTIVE = "USER_INTERACTIVE"
    LOW_TRUST_EVENT_SCOPE = "LOW_TRUST_EVENT_SCOPE"
    ISOLATED_QUARANTINE = "ISOLATED_QUARANTINE"


class ApprovalTicketStatusEnum(StrEnum):
    """Lifecycle status for unattended asynchronous approval tickets."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class TicketRiskLevelEnum(StrEnum):
    """Risk severity classification for requested write actions."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class ChannelNotificationTarget:
    """Target messaging platform channel destination for out-of-band notification."""

    channel_type: str  # e.g. "feishu", "telegram", "wechat_work", "desktop"
    target_id: str
    recipient_name: str | None = None


@dataclass(frozen=True)
class EventPayloadDescriptor:
    """Descriptor of an incoming event triggering agent execution."""

    event_id: str
    source_name: str
    event_type: str
    timestamp: float
    raw_payload_bytes: bytes
    signature: str | None = None
    is_verified: bool = False


@dataclass(frozen=True)
class ApprovalTicket:
    """Digital approval ticket generated when an attenuated agent attempts high-risk action."""

    ticket_id: str
    session_id: str
    requested_tool: str
    risk_level: TicketRiskLevelEnum
    action_description: str
    diff_payload: str
    created_at: float
    expires_at: float
    status: ApprovalTicketStatusEnum = ApprovalTicketStatusEnum.PENDING
    decided_by: str | None = None
    decision_reason: str | None = None
    notification_channels: tuple[ChannelNotificationTarget, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AttenuationRule:
    """Rule determining which tools are blocked or require approval under LOW_TRUST_EVENT_SCOPE."""

    blocked_tools: tuple[str, ...] = (
        "shell_exec",
        "rm_rf",
        "git_push",
        "send_email",
        "drop_database",
        "deploy_production",
    )
    read_only_allowed_tools: tuple[str, ...] = (
        "file_read",
        "grep_search",
        "list_dir",
        "git_diff",
        "static_code_analysis",
        "web_fetch_readonly",
    )


@dataclass
class CapabilityAttenuationMetrics:
    """Cumulative operational metrics for event attenuation and async approval bridge."""

    total_events_received: int = 0
    verified_events_count: int = 0
    rejected_signature_events: int = 0
    attenuated_executions_count: int = 0
    tickets_created: int = 0
    tickets_approved: int = 0
    tickets_rejected: int = 0
    tickets_expired: int = 0
