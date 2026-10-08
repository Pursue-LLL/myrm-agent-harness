"""Native Credential Approvals and Precise Conversation Message Links module.

[INPUT]
- Credential access asks, decision commands, and sequence coordinates.

[OUTPUT]
- Managed CredentialAsk states, immutable ApprovalAuditRecord logs, and verified permissions.

[POS]
- Harness security subsystem for native credential approvals (#1502).
"""

from __future__ import annotations

from .approval_manager import NativeCredentialApprovalManager
from .link_generator import MessageLinkGenerator
from .types import (
    ApprovalAuditRecord,
    ApprovalDecision,
    CredentialAsk,
    CredentialAskStatus,
    MessageSequenceRef,
    PreciseMessageLink,
)

__all__ = [
    "ApprovalAuditRecord",
    "ApprovalDecision",
    "CredentialAsk",
    "CredentialAskStatus",
    "MessageLinkGenerator",
    "MessageSequenceRef",
    "NativeCredentialApprovalManager",
    "PreciseMessageLink",
]
