"""Subagent Tool Status Harmonizer & Anti-Deadlock Machine (Item 57).

[INPUT]
- Subagent heartbeat signals, execution lifecycle state updates, and timeout ticks.

[OUTPUT]
- Monotonically progressive status state machine transitions and audit events
  with automated watchdog deadlock prevention.

[POS]
- Eliminates UI status deadlocks and hung 'running' worker states across hierarchical
  subagent boundaries.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence

from myrm_agent_harness.agent.sub_agents.replay_dedup.types import (
    SubagentStatusTransitionEvent,
    ToolReplayStatusEnum,
)

TERMINAL_STATUSES: frozenset[ToolReplayStatusEnum] = frozenset({
    ToolReplayStatusEnum.COMPLETED,
    ToolReplayStatusEnum.FAILED,
    ToolReplayStatusEnum.CANCELLED,
    ToolReplayStatusEnum.TIMEOUT_TERMINATED,
})

VALID_TRANSITIONS: Mapping[ToolReplayStatusEnum, frozenset[ToolReplayStatusEnum]] = {
    ToolReplayStatusEnum.IDLE: frozenset({
        ToolReplayStatusEnum.RUNNING,
        ToolReplayStatusEnum.CANCELLED,
    }),
    ToolReplayStatusEnum.RUNNING: frozenset({
        ToolReplayStatusEnum.PENDING_APPROVAL,
        ToolReplayStatusEnum.COMPLETED,
        ToolReplayStatusEnum.FAILED,
        ToolReplayStatusEnum.CANCELLED,
        ToolReplayStatusEnum.TIMEOUT_TERMINATED,
    }),
    ToolReplayStatusEnum.PENDING_APPROVAL: frozenset({
        ToolReplayStatusEnum.RUNNING,
        ToolReplayStatusEnum.COMPLETED,
        ToolReplayStatusEnum.FAILED,
        ToolReplayStatusEnum.CANCELLED,
        ToolReplayStatusEnum.TIMEOUT_TERMINATED,
    }),
    ToolReplayStatusEnum.COMPLETED: frozenset(),
    ToolReplayStatusEnum.FAILED: frozenset(),
    ToolReplayStatusEnum.CANCELLED: frozenset(),
    ToolReplayStatusEnum.TIMEOUT_TERMINATED: frozenset(),
}


class SubagentStatusHarmonizer:
    """Manages monotonic subagent lifecycle states with active watchdog lease enforcement."""

    def __init__(self, lease_timeout_seconds: float = 30.0) -> None:
        self._lease_timeout_seconds = max(1.0, float(lease_timeout_seconds))
        self._states: dict[str, ToolReplayStatusEnum] = {}
        self._last_heartbeats: dict[str, float] = {}
        self._audit_events: list[SubagentStatusTransitionEvent] = []

    def register_subagent(
        self,
        subagent_id: str,
        initial_status: ToolReplayStatusEnum = ToolReplayStatusEnum.IDLE,
    ) -> None:
        """Enrolls a subagent into the harmonizer state tracker."""
        now = time.time()
        self._states[subagent_id] = initial_status
        self._last_heartbeats[subagent_id] = now
        event = SubagentStatusTransitionEvent(
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            subagent_id=subagent_id,
            previous_status=initial_status,
            new_status=initial_status,
            timestamp=now,
            reason="Subagent registered into harmonizer.",
            is_deadlock_prevented=False,
        )
        self._audit_events.append(event)

    def record_heartbeat(self, subagent_id: str, now: float | None = None) -> bool:
        """Refreshes the active lease timestamp for a running subagent."""
        if subagent_id not in self._states:
            return False
        if self._states[subagent_id] in TERMINAL_STATUSES:
            return False
        timestamp = now if now is not None else time.time()
        self._last_heartbeats[subagent_id] = timestamp
        return True

    def transition_status(
        self,
        subagent_id: str,
        new_status: ToolReplayStatusEnum,
        reason: str = "",
        now: float | None = None,
    ) -> SubagentStatusTransitionEvent:
        """Transitions subagent state adhering strictly to monotonic graph rules."""
        timestamp = now if now is not None else time.time()
        current = self._states.get(subagent_id, ToolReplayStatusEnum.IDLE)

        if current == new_status:
            return SubagentStatusTransitionEvent(
                event_id=f"evt-{uuid.uuid4().hex[:8]}",
                subagent_id=subagent_id,
                previous_status=current,
                new_status=current,
                timestamp=timestamp,
                reason=reason or "No-op transition to same status.",
                is_deadlock_prevented=False,
            )

        if current in TERMINAL_STATUSES:
            raise ValueError(
                f"Cannot transition terminal subagent '{subagent_id}' from '{current}' to '{new_status}'."
            )

        allowed = VALID_TRANSITIONS.get(current, frozenset())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid status transition for subagent '{subagent_id}': '{current}' -> '{new_status}'."
            )

        self._states[subagent_id] = new_status
        self._last_heartbeats[subagent_id] = timestamp

        event = SubagentStatusTransitionEvent(
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            subagent_id=subagent_id,
            previous_status=current,
            new_status=new_status,
            timestamp=timestamp,
            reason=reason or f"Status shifted from {current} to {new_status}.",
            is_deadlock_prevented=False,
        )
        self._audit_events.append(event)
        return event

    def check_watchdog(self, now: float | None = None) -> Sequence[SubagentStatusTransitionEvent]:
        """Scans active subagents and terminates expired leases to prevent UI deadlocks."""
        current_time = now if now is not None else time.time()
        interventions: list[SubagentStatusTransitionEvent] = []

        for subagent_id, status in list(self._states.items()):
            if status in TERMINAL_STATUSES:
                continue

            last_hb = self._last_heartbeats.get(subagent_id, current_time)
            elapsed = current_time - last_hb

            if elapsed >= self._lease_timeout_seconds:
                # Active worker exceeded heartbeat lease limit: trigger atomic watchdog termination
                self._states[subagent_id] = ToolReplayStatusEnum.TIMEOUT_TERMINATED
                self._last_heartbeats[subagent_id] = current_time

                event = SubagentStatusTransitionEvent(
                    event_id=f"evt-watchdog-{uuid.uuid4().hex[:8]}",
                    subagent_id=subagent_id,
                    previous_status=status,
                    new_status=ToolReplayStatusEnum.TIMEOUT_TERMINATED,
                    timestamp=current_time,
                    reason=(
                        f"Watchdog auto-terminated hung subagent '{subagent_id}' "
                        f"after {elapsed:.1f}s lease silence (threshold: {self._lease_timeout_seconds}s)."
                    ),
                    is_deadlock_prevented=True,
                )
                self._audit_events.append(event)
                interventions.append(event)

        return tuple(interventions)

    def get_status(self, subagent_id: str) -> ToolReplayStatusEnum:
        """Retrieves the current execution status of a subagent."""
        return self._states.get(subagent_id, ToolReplayStatusEnum.IDLE)

    def get_all_statuses(self) -> Mapping[str, ToolReplayStatusEnum]:
        """Returns an immutable snapshot of all tracked subagent statuses."""
        return dict(self._states)

    def get_audit_events(
        self,
        subagent_id: str | None = None,
        limit: int = 50,
    ) -> Sequence[SubagentStatusTransitionEvent]:
        """Returns chronologically ordered audit events, optionally filtered by subagent_id."""
        events = self._audit_events
        if subagent_id is not None:
            events = [e for e in events if e.subagent_id == subagent_id]
        return tuple(events[-limit:])

    def clear(self) -> None:
        """Resets all internal subagent states and transition journals."""
        self._states.clear()
        self._last_heartbeats.clear()
        self._audit_events.clear()
