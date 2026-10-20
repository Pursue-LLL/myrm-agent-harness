"""Adaptive wakeup router deciding between injection, followup, degradation, or suppression.

Routes background asynchronous settlements based on real-time host activity state
and bounded consecutive wake budgets.

[INPUT]
- threading
- budget_tracker
- types

[OUTPUT]
- AdaptiveWakeupRouter

[POS]
Adaptive wakeup router deciding between injection, followup, degradation, or suppression.
"""

import threading

from .budget_tracker import WakeupBudgetTracker
from .types import (
    HostActivityState,
    RoutingDecision,
    WakeupChannel,
    WakeupEvent,
)


class AdaptiveWakeupRouter:
    """Orchestrates settlement delivery channel selection for asynchronous tasks."""

    def __init__(
        self,
        budget_tracker: WakeupBudgetTracker | None = None,
        default_max_consecutive_wakes: int = 3,
    ) -> None:
        self._tracker: WakeupBudgetTracker = (
            budget_tracker
            if budget_tracker is not None
            else WakeupBudgetTracker(default_max_consecutive_wakes)
        )
        self._host_states: dict[str, HostActivityState] = {}
        self._injected_inboxes: dict[str, list[WakeupEvent]] = {}
        self._lock: threading.Lock = threading.Lock()

    @property
    def budget_tracker(self) -> WakeupBudgetTracker:
        """The underlying budget tracker instance."""
        return self._tracker

    def set_host_activity(self, session_id: str, state: HostActivityState) -> None:
        """Update host execution activity (IDLE, BUSY, or STOPPED)."""
        with self._lock:
            self._host_states[session_id] = state
            if state == HostActivityState.STOPPED:
                self._tracker.record_user_stop(session_id)

    def get_host_activity(self, session_id: str) -> HostActivityState:
        """Query current host activity, defaulting to IDLE if untracked."""
        with self._lock:
            return self._host_states.get(session_id, HostActivityState.IDLE)

    def record_human_turn(self, session_id: str) -> None:
        """Notify router of an explicit human interaction turn, resetting wake budget."""
        with self._lock:
            self._host_states[session_id] = HostActivityState.IDLE
        self._tracker.record_human_turn(session_id)

    def record_user_stop(self, session_id: str) -> None:
        """Notify router of an explicit user stop/cancellation request."""
        with self._lock:
            self._host_states[session_id] = HostActivityState.STOPPED
        self._tracker.record_user_stop(session_id)

    def route(self, event: WakeupEvent) -> RoutingDecision:
        """Determine settlement delivery channel for an asynchronous completion event."""
        with self._lock:
            budget_state = self._tracker.get_budget_state(event.session_id)
            current_host_state = self._host_states.get(
                event.session_id, HostActivityState.IDLE
            )

            # 1. User stopped suppression guard
            if budget_state.is_user_stopped or current_host_state == HostActivityState.STOPPED:
                return RoutingDecision(
                    channel=WakeupChannel.SUPPRESS,
                    reason="Suppressed: user requested stop or session execution was cancelled",
                    session_id=event.session_id,
                    source_id=event.source_id,
                    consecutive_wakes=budget_state.consecutive_wakes,
                    budget_remaining=budget_state.budget_remaining,
                )

            # 2. Busy host injection channel
            if current_host_state == HostActivityState.BUSY:
                inbox = self._injected_inboxes.setdefault(event.session_id, [])
                inbox.append(event)
                return RoutingDecision(
                    channel=WakeupChannel.INJECT,
                    reason="Injected: host is actively executing, merged into in-flight turn",
                    session_id=event.session_id,
                    source_id=event.source_id,
                    consecutive_wakes=budget_state.consecutive_wakes,
                    budget_remaining=budget_state.budget_remaining,
                )

        # 3. Idle host followup vs degradation channel (check budget outside host lock)
        acquired = self._tracker.consume_wake_budget(event.session_id)
        latest_budget = self._tracker.get_budget_state(event.session_id)

        with self._lock:
            if acquired:
                return RoutingDecision(
                    channel=WakeupChannel.FOLLOWUP,
                    reason=(
                        f"Followup: host is idle and autonomous wake budget available "
                        f"({latest_budget.consecutive_wakes}/{latest_budget.max_consecutive_wakes})"
                    ),
                    session_id=event.session_id,
                    source_id=event.source_id,
                    consecutive_wakes=latest_budget.consecutive_wakes,
                    budget_remaining=latest_budget.budget_remaining,
                )

            # 4. Budget exhausted degradation channel
            inbox = self._injected_inboxes.setdefault(event.session_id, [])
            inbox.append(event)
            return RoutingDecision(
                channel=WakeupChannel.DEGRADE,
                reason=(
                    f"Degraded: consecutive autonomous wake budget exhausted "
                    f"({latest_budget.consecutive_wakes}/{latest_budget.max_consecutive_wakes}), "
                    "awaiting human input"
                ),
                session_id=event.session_id,
                source_id=event.source_id,
                consecutive_wakes=latest_budget.consecutive_wakes,
                budget_remaining=latest_budget.budget_remaining,
            )

    def drain_injected_events(self, session_id: str) -> list[WakeupEvent]:
        """Atomically drain all queued injected events for a session."""
        with self._lock:
            events = self._injected_inboxes.pop(session_id, [])
            return list(events)

    def peek_injected_events(self, session_id: str) -> list[WakeupEvent]:
        """Inspect queued injected events without draining."""
        with self._lock:
            return list(self._injected_inboxes.get(session_id, []))

    def reset_session(self, session_id: str) -> None:
        """Clear all router states and inboxes for a session."""
        with self._lock:
            self._host_states.pop(session_id, None)
            self._injected_inboxes.pop(session_id, None)
        self._tracker.reset_session(session_id)
