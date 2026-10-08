"""Types and data structures for headless task continuation and mobile approval relay.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ClientAttachmentState: Attachment state of the client front-end (Desktop/Web).
- HeadlessExecutionPhase: Lifecycle phase of asynchronous headless execution in the sandbox.
- RelayChannelKind: Supported push relay channels for mobile human-in-the-loop.
- ApprovalDecisionKind: Operator decision for a suspended action.
- RiskLevel: Risk tier for the pending action requiring confirmation.
- MobileApprovalRelayCard: Tamper-evident mobile approval card payload dispatched to remote channels.
- MobileApprovalDecisionPayload: Incoming approval decision callback from mobile device.
- ApprovalRelayReceipt: Cryptographic audit receipt after decision is validated and applied.
- ReconnectionSyncManifest: Manifest synchronizing headless task state when desktop client reconnects.

[POS]
Types and data structures for headless task continuation and mobile approval relay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ClientAttachmentState(str, Enum):
    """Attachment state of the client front-end (Desktop/Web)."""

    ATTACHED = "attached"
    DETACHED_HEADLESS = "detached_headless"
    RECONNECTING = "reconnecting"


class HeadlessExecutionPhase(str, Enum):
    """Lifecycle phase of asynchronous headless execution in the sandbox."""

    IDLE = "idle"
    RUNNING_HEADLESS = "running_headless"
    AWAITING_MOBILE_APPROVAL = "awaiting_mobile_approval"
    RESUMED_ACTIVE = "resumed_active"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class RelayChannelKind(str, Enum):
    """Supported push relay channels for mobile human-in-the-loop."""

    TELEGRAM = "telegram"
    WEBPUSH = "webpush"
    WECHAT_WORK = "wechat_work"
    GENERIC_WEBHOOK = "generic_webhook"


class ApprovalDecisionKind(str, Enum):
    """Operator decision for a suspended action."""

    APPROVE = "approve"
    REJECT = "reject"
    CONDITIONAL_ALLOW = "conditional_allow"


class RiskLevel(str, Enum):
    """Risk tier for the pending action requiring confirmation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class MobileApprovalRelayCard:
    """Tamper-evident mobile approval card payload dispatched to remote channels."""

    request_id: str
    task_id: str
    session_id: str
    action_summary: str
    risk_level: RiskLevel
    created_at_iso: str
    expires_at_iso: str
    auth_token_digest: str
    channels_supported: list[RelayChannelKind] = field(default_factory=list)
    payload_preview: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MobileApprovalDecisionPayload:
    """Incoming approval decision callback from mobile device."""

    decision_id: str
    request_id: str
    decision: ApprovalDecisionKind
    operator_id: str
    decision_reason: str
    signature_proof: str


@dataclass(frozen=True)
class ApprovalRelayReceipt:
    """Cryptographic audit receipt after decision is validated and applied."""

    receipt_id: str
    request_id: str
    decision: ApprovalDecisionKind
    operator_id: str
    applied_at_iso: str
    latency_seconds: float
    is_expired: bool
    status_message: str


@dataclass(frozen=True)
class ReconnectionSyncManifest:
    """Manifest synchronizing headless task state when desktop client reconnects."""

    task_id: str
    session_id: str
    detached_at_iso: str
    reconnected_at_iso: str
    detached_duration_seconds: float
    execution_phase: HeadlessExecutionPhase
    approval_events_count: int
    receipts: list[ApprovalRelayReceipt]
    incremental_output_lines: list[str]
    resume_ready: bool
