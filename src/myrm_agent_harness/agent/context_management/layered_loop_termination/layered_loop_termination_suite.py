"""Suite managing paired layered loop lifecycle events, dual-condition termination, and stop hooks.

[INPUT]
- agent.context_management.layered_loop_termination.debt_inbox_manager::DebtInboxManager (POS: Manager for
  consumable debt inbox and model response debt accounting.)
- agent.context_management.layered_loop_termination.layered_loop_types::LayeredLoopEvent, LoopHierarchyTier,
  LoopTerminationDecision, LoopTerminationReason (POS: Types for layered loop termination, paired lifecycle
  events, and debt inbox.)

[OUTPUT]
- LayeredLoopTerminationAndDebtInboxSuite: Orchestrates five-tier loop events, pair guarantee, debt
  accounting, and rechecked termination.

[POS]
Suite managing paired layered loop lifecycle events, dual-condition termination, and stop hooks.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from .debt_inbox_manager import DebtInboxManager
from .layered_loop_types import (
    LayeredLoopEvent,
    LoopHierarchyTier,
    LoopTerminationDecision,
    LoopTerminationReason,
)


class LayeredLoopTerminationAndDebtInboxSuite:
    """Orchestrates five-tier loop events, pair guarantee, debt accounting, and rechecked termination."""

    def __init__(self, inbox_manager: Optional[DebtInboxManager] = None) -> None:
        self._inbox = inbox_manager or DebtInboxManager()
        self._events: List[LayeredLoopEvent] = []
        self._open_starts: Dict[str, LayeredLoopEvent] = {}
        self._stop_hooks: List[Callable[[DebtInboxManager], None]] = []

    @property
    def inbox(self) -> DebtInboxManager:
        """Access the underlying debt inbox manager."""
        return self._inbox

    def register_stop_hook(self, hook: Callable[[DebtInboxManager], None]) -> None:
        """Register a stop hook callback that may optionally enqueue steering data into the inbox."""
        self._stop_hooks.append(hook)

    def start_loop(
        self,
        tier: LoopHierarchyTier,
        turn_id: int = 0,
        step_id: int = 0,
    ) -> LayeredLoopEvent:
        """Emit a pair-guaranteed start event for a loop tier."""
        now_iso = datetime.now(timezone.utc).isoformat()
        key = f"{tier.value}:{turn_id}:{step_id}"
        event_id = f"evt-start-{hashlib.sha256(f'{key}:{time.time()}'.encode('utf-8')).hexdigest()[:8]}"

        event = LayeredLoopEvent(
            event_id=event_id,
            tier=tier,
            is_start=True,
            turn_id=turn_id,
            step_id=step_id,
            timestamp_iso=now_iso,
        )
        self._events.append(event)
        self._open_starts[key] = event
        return event

    def end_loop(
        self,
        tier: LoopHierarchyTier,
        turn_id: int = 0,
        step_id: int = 0,
        reason: LoopTerminationReason = LoopTerminationReason.NATURAL_COMPLETION,
        error_message: Optional[str] = None,
    ) -> LayeredLoopEvent:
        """Emit the closing end event for a loop tier, guaranteeing strict pair closure."""
        now_iso = datetime.now(timezone.utc).isoformat()
        key = f"{tier.value}:{turn_id}:{step_id}"
        event_id = f"evt-end-{hashlib.sha256(f'{key}:{time.time()}'.encode('utf-8')).hexdigest()[:8]}"

        # Close open start if present
        self._open_starts.pop(key, None)

        event = LayeredLoopEvent(
            event_id=event_id,
            tier=tier,
            is_start=False,
            turn_id=turn_id,
            step_id=step_id,
            timestamp_iso=now_iso,
            reason=reason,
            error_message=error_message,
        )
        self._events.append(event)
        return event

    def evaluate_turn_termination(self, turn_id: int) -> LoopTerminationDecision:
        """Perform dual-condition evaluation: model debt == 0 and message debt == 0."""
        model_debts = self._inbox.model_debt_count
        message_debts = self._inbox.message_debt_count
        pending_items = self._inbox.get_pending_debts()

        if model_debts > 0:
            return LoopTerminationDecision(
                can_terminate=False,
                tier=LoopHierarchyTier.TURN,
                turn_id=turn_id,
                model_debt_count=model_debts,
                message_debt_count=message_debts,
                pending_debts=pending_items,
                blocking_reason=f"Model debt unpaid: {model_debts} response(s) owed following tool executions.",
            )

        if message_debts > 0:
            return LoopTerminationDecision(
                can_terminate=False,
                tier=LoopHierarchyTier.TURN,
                turn_id=turn_id,
                model_debt_count=model_debts,
                message_debt_count=message_debts,
                pending_debts=pending_items,
                blocking_reason=f"Message debt pending: {message_debts} unconsumed inbox item(s) awaiting processing.",
            )

        return LoopTerminationDecision(
            can_terminate=True,
            tier=LoopHierarchyTier.TURN,
            turn_id=turn_id,
            model_debt_count=0,
            message_debt_count=0,
            pending_debts=[],
            blocking_reason=None,
        )

    def trigger_stop_hooks_and_recheck(self, turn_id: int) -> LoopTerminationDecision:
        """Execute all stop hooks, then re-evaluate inbox to see if a hook injected new work."""
        for hook in self._stop_hooks:
            hook(self._inbox)

        # Post-hook data-driven recheck
        decision = self.evaluate_turn_termination(turn_id)
        return decision

    def has_unclosed_starts(self) -> bool:
        """Check if any loop layer start event remains unclosed."""
        return len(self._open_starts) > 0

    def get_events(self) -> List[LayeredLoopEvent]:
        """Return full ledger of lifecycle events."""
        return list(self._events)
