"""Types and models for append-only session event sourcing and deterministic context replaying."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class SessionEventKind(str, Enum):
    """Classification of immutable session ledger events."""

    USER_PROMPT = "user_prompt"
    SYSTEM_DIRECTIVE_INJECTED = "system_directive_injected"
    ASSISTANT_REPLY = "assistant_reply"
    TOOL_INVOCATION = "tool_invocation"
    TOOL_RESULT = "tool_result"
    CONTEXT_COMPACTED = "context_compacted"
    RULE_UPDATED = "rule_updated"


@dataclass(frozen=True)
class SessionLedgerEvent:
    """Immutable event record strictly appended to session event stream."""

    event_id: str
    session_id: str
    sequence_number: int
    kind: SessionEventKind
    timestamp_iso: str
    payload: Dict[str, str] = field(default_factory=dict)
    causation_id: Optional[str] = None
    event_digest: str = ""


@dataclass(frozen=True)
class ProjectedMessageItem:
    """Reconstructed message visible to the model at projection time."""

    role: str
    content: str
    step_sequence: int
    tool_call_id: Optional[str] = None


@dataclass(frozen=True)
class ProjectedModelVisibleContext:
    """Pure functional projection of what the model sees at an exact historical step."""

    session_id: str
    target_sequence: int
    effective_system_prompt: str
    visible_messages: List[ProjectedMessageItem] = field(default_factory=list)
    active_rules_digest: str = ""
    compaction_applied: bool = False
    context_digest: str = ""


@dataclass(frozen=True)
class ContextReplayCertificate:
    """Cryptographic audit certificate verifying deterministic replay outcome."""

    session_id: str
    target_sequence: int
    events_replayed_count: int
    projection_digest: str
    is_deterministic: bool
    timestamp_iso: str
