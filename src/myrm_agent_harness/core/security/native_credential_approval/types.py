"""Type definitions and data structures for Native Credential Approvals and Precise Message Links.

[INPUT]
- Credential request attributes, conversation sequence coordinates, and approval decisions.

[OUTPUT]
- Immutable ask specifications, precise navigation links, and audit records.

[POS]
- Core domain models for QM #1502 native credential approval and session message linking.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ApprovalDecision(StrEnum):
    """Decision mode for credential access approval."""

    ONCE = "once"  # Allow single-turn access
    STANDING = "standing"  # Allow persistent access for current session
    DENY = "deny"  # Reject request


class CredentialAskStatus(StrEnum):
    """Lifecycle status of a native credential access request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class MessageSequenceRef:
    """Exact coordinate linking a credential ask to a conversation message."""

    session_id: str
    message_id: str
    sequence_number: int  # Exact monotonic turn or message sequence index
    turn_index: int | None = None


@dataclass(frozen=True)
class PreciseMessageLink:
    """Standardized navigation deep link targeting a specific message in the UI transcript."""

    path: str  # e.g., "/chat/sess-123"
    sequence_number: int
    message_id: str
    deep_link_url: str  # e.g., "/chat/sess-123?seq=42&msg=msg-999"


@dataclass(frozen=True)
class CredentialAsk:
    """Native credential access approval request with contextual message link."""

    ask_id: str
    credential_id: str
    service_name: str
    account_label: str
    requester_id: str  # Agent or tool identifier requesting access
    owner_id: str  # User / principal who owns the credential and can approve
    purpose: str  # Justification presented to human approver
    message_ref: MessageSequenceRef
    deep_link: PreciseMessageLink
    status: CredentialAskStatus
    decision_mode: ApprovalDecision | None = None
    decided_by: str | None = None
    decision_note: str | None = None
    created_at_iso: str = ""
    decided_at_iso: str | None = None


@dataclass(frozen=True)
class ApprovalAuditRecord:
    """Immutable audit entry generated when a credential ask is decided."""

    audit_id: str
    ask_id: str
    credential_id: str
    service_name: str
    actor_id: str
    decision: ApprovalDecision
    target_session_id: str
    sequence_number: int
    timestamp_iso: str
    note: str = ""
