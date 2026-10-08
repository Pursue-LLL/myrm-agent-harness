"""Type definitions for Untrusted Webhook Prompt Injection Defense and Toolset Demotion.

[INPUT]
- None.

[OUTPUT]
- OriginTaint, ApprovalCardStatus, AdminApprovalCard, DemotionPolicy
- DemotedToolAccessDeniedError, WebhookSecurityError

[POS]
- Harness core security module inspired by Hermes Agent message gateway.
- Enforces HMAC sender trust decoupling: treats third-party webhook payloads as tainted,
  strips destructive tools, and gates dangerous executions behind admin approval cards.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ApprovalCardStatus(StrEnum):
    """Lifecycle status of an interactive admin approval card."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class OriginTaint:
    """Taint metadata decoupling HMAC verification from content trustworthiness."""

    is_untrusted_external_content: bool
    origin_source: str  # e.g. "github_pr", "gitlab_issue", "public_webhook"
    sender_identity: str
    received_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class AdminApprovalCard:
    """Approval card generated when a tainted agent requires elevated tool execution."""

    card_id: str
    task_id: str
    origin_source: str
    requested_tool: str
    tool_arguments: dict[str, str | int | float | bool | list[str]]
    risk_reason: str
    status: ApprovalCardStatus = ApprovalCardStatus.PENDING
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 300.0)


@dataclass(frozen=True, slots=True)
class DemotionPolicy:
    """Policy defining allowable safe tools versus forbidden high-risk tools for tainted sessions."""

    safe_read_only_tools: frozenset[str] = frozenset({
        "web_search",
        "web_extract",
        "file_read",
        "code_analyze",
        "clarify",
        "vision_analyze",
    })
    forbidden_high_risk_tools: frozenset[str] = frozenset({
        "bash_code_execute",
        "file_write",
        "db_mutate",
        "terminal_spawn",
        "delete_file",
        "run_command",
    })


class WebhookSecurityError(Exception):
    """Base exception for webhook security and prompt injection defense."""


class DemotedToolAccessDeniedError(WebhookSecurityError):
    """Raised when an untrusted/tainted session attempts to invoke a demoted tool without approval."""

    def __init__(self, tool_name: str, origin_source: str, card_id: str | None = None) -> None:
        msg = (
            f"Execution of tool '{tool_name}' blocked: Session is marked as untrusted external content "
            f"from '{origin_source}'. High-risk execution requires explicit human admin approval."
        )
        if card_id:
            msg += f" (Approval card generated: {card_id})"
        super().__init__(msg)
        self.tool_name = tool_name
        self.origin_source = origin_source
        self.card_id = card_id
