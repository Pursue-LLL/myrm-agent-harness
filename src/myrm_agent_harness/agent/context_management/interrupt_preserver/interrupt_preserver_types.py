"""Type definitions for Graceful Turn Interrupt and Queued Message Draft Preserver.

Provides immutable data contracts for context state freezing, zero-pruning
verification, and in-flight queued message salvage into editable drafts.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- InterruptReason: Enumeration of trigger reasons for turn interruption.
- PreservedTurnState: Snapshot of preserved conversation context at the moment of interruption.
- QueuedTurnMessage: In-flight user message currently waiting in the turn execution queue.
- SalvagedDraft: Salvaged message content returned to the client UI as an editable draft.
- InterruptPreservationResult: Complete result contract emitted upon turn interruption.

[POS]
Type definitions for Graceful Turn Interrupt and Queued Message Draft Preserver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time


class InterruptReason(str, Enum):
    """Enumeration of trigger reasons for turn interruption."""

    USER_STOP = "USER_STOP"
    TIMEOUT = "TIMEOUT"
    SAFETY_ABORT = "SAFETY_ABORT"
    DISCONNECT = "DISCONNECT"


@dataclass(frozen=True)
class PreservedTurnState:
    """Snapshot of preserved conversation context at the moment of interruption."""

    session_id: str
    turn_id: str
    reason: InterruptReason
    interrupted_at: float
    total_messages_preserved: int
    frozen_tool_results_count: int
    zero_pruning_verified: bool
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class QueuedTurnMessage:
    """In-flight user message currently waiting in the turn execution queue."""

    message_id: str
    session_id: str
    content: str
    enqueued_at: float
    author_role: str = "user"
    is_consumed: bool = False


@dataclass(frozen=True)
class SalvagedDraft:
    """Salvaged message content returned to the client UI as an editable draft."""

    draft_id: str
    session_id: str
    queued_message_id: str
    content: str
    salvaged_at: float
    cursor_position: int
    hint_text: str


@dataclass(frozen=True)
class InterruptPreservationResult:
    """Complete result contract emitted upon turn interruption."""

    session_id: str
    turn_id: str
    turn_state: PreservedTurnState
    salvaged_drafts: tuple[SalvagedDraft, ...]
    has_unconsumed_messages: bool
    recommended_action: str
