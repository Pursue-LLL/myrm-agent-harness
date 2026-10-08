"""Type definitions for Headless Agent Interactive Approval, Webhook Relay, and Hold-Resume Conduit.

[POS] src/myrm_agent_harness/core/security/headless_interactive_approval/types.py
[INPUT] enum, dataclasses
[OUTPUT] ApprovalHoldStatus, RiskActionDescriptor, ApprovalHoldTicket, WebhookRelayPayload, StreamHoldChunk
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ApprovalHoldStatus(StrEnum):
    """Lifecycle state of an action execution hold ticket."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TIMED_OUT = "TIMED_OUT"


@dataclass(slots=True, frozen=True)
class RiskActionDescriptor:
    """Action requested by the agent that exceeds autonomous thresholds."""

    action_id: str
    tool_name: str
    command_or_target: str
    risk_level: str  # CRITICAL, HIGH, MEDIUM
    justification: str


@dataclass(slots=True, frozen=True)
class ApprovalHoldTicket:
    """Ephemeral transactional ticket representing a suspended execution state."""

    tx_id: str
    session_id: str
    action: RiskActionDescriptor
    status: ApprovalHoldStatus
    shortlink_url: str
    created_at: float
    expires_at: float
    operator_decision_notes: str | None = None
    decided_by: str | None = None
    decided_at: float | None = None


@dataclass(slots=True, frozen=True)
class WebhookRelayPayload:
    """Outbound payload sent to external notification channels (Telegram, Feishu, Desktop)."""

    tx_id: str
    session_id: str
    tool_name: str
    command_or_target: str
    risk_level: str
    approval_shortlink: str
    expires_in_seconds: int
    custom_metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class StreamHoldChunk:
    """Markdown formatted chunk injected into streaming reasoning or thinking buffer."""

    tx_id: str
    inject_markdown: str
    is_resumed: bool
    status: ApprovalHoldStatus
