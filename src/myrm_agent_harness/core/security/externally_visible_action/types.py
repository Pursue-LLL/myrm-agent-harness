"""Type definitions for Externally Visible Irreversible Action Static Classification Gate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ActionVisibilityScope(StrEnum):
    """Classification of action side-effect visibility boundary."""

    INTERNAL_ONLY = "INTERNAL_ONLY"  # Internal memory, file read, compute
    USER_LOCAL = "USER_LOCAL"  # Local GUI alert, ask human question
    THIRD_PARTY_VISIBLE = "THIRD_PARTY_VISIBLE"  # Leaves user view to external third-party


@dataclass(slots=True, frozen=True)
class ExternalActionClassification:
    """Security classification outcome of an action's external visibility."""

    tool_name: str
    is_third_party_visible: bool
    requires_mandatory_human_review: bool
    hide_allow_always: bool
    visibility_scope: ActionVisibilityScope
    rationale: str


@dataclass(slots=True, frozen=True)
class AuditedExternalAction:
    """Audit record capturing an outbound externally visible action attempt."""

    action_id: str
    session_id: str
    agent_id: str
    tool_name: str
    recipient_or_destination: str
    content_preview: str
    is_approved: bool
    approved_by: str | None = None
    timestamp: float = 0.0
