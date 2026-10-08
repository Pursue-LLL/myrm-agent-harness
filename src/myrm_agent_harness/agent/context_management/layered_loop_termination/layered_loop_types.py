"""Types for layered loop termination, paired lifecycle events, and debt inbox."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class LoopHierarchyTier(str, Enum):
    """Five-tier hierarchy of agent execution loops."""

    REQUEST = "request"
    TURN = "turn"
    STEP = "step"
    ACTIVITY = "activity"
    GOAL = "goal"


class LoopTerminationReason(str, Enum):
    """Reason for terminating a specific execution loop layer."""

    NATURAL_COMPLETION = "natural_completion"
    STOP_HOOK_HALT = "stop_hook_halt"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ERROR_ABORTED = "error_aborted"
    DEBT_CLEARED = "debt_cleared"


class DebtKind(str, Enum):
    """Classification of pending debts blocking loop termination."""

    MODEL_RESPONSE_OWED = "model_response_owed"
    STEERING_MESSAGE_OWED = "steering_message_owed"
    INBOX_TASK_OWED = "inbox_task_owed"
    CORRECTION_PROMPT_OWED = "correction_prompt_owed"


@dataclass(frozen=True)
class DebtInboxItem:
    """Actionable consumable item enqueued into the next-step inbox."""

    debt_id: str
    kind: DebtKind
    source: str
    payload_text: str
    timestamp_iso: str
    consumed: bool = False


@dataclass(frozen=True)
class LayeredLoopEvent:
    """Pair-guaranteed lifecycle event marking loop start or end across tiers."""

    event_id: str
    tier: LoopHierarchyTier
    is_start: bool
    turn_id: int
    step_id: int
    timestamp_iso: str
    reason: Optional[LoopTerminationReason] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class LoopTerminationDecision:
    """Auditable dual-condition decision on whether a loop layer may terminate."""

    can_terminate: bool
    tier: LoopHierarchyTier
    turn_id: int
    model_debt_count: int
    message_debt_count: int
    pending_debts: List[DebtInboxItem] = field(default_factory=list)
    blocking_reason: Optional[str] = None
