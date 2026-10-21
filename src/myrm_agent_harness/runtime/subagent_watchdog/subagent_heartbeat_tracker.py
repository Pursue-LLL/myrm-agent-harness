"""Subagent execution heartbeat tracker and tiered health evaluator.

Benchmarked against Nous community multi-agent runtime reliability invariants:
- Collects periodic heartbeat pulses emitted by running subagents.
- Calculates elapsed delta since last received pulse against TimeoutLadderConfig.
- Evaluates health progression: HEALTHY -> WARNING -> SOFT_CANCELING -> TERMINATED.
- Automatically cleans up state upon unregistration.

[OUTPUT]
- SubagentHeartbeatTracker: Central tracker managing subagent heartbeats and health states.

[INPUT]
- __future__
- time

[OUTPUT]
- SubagentHeartbeatTracker

[POS]
Subagent execution heartbeat tracker and tiered health evaluator.
"""

from __future__ import annotations

import time

from myrm_agent_harness.runtime.subagent_watchdog.watchdog_types import (
    SubagentHealthState,
    TimeoutLadderConfig,
)


class SubagentHeartbeatTracker:
    """Manages heartbeat registrations and assesses subagent vitality states."""

    def __init__(self, default_ladder: TimeoutLadderConfig | None = None) -> None:
        self.default_ladder = default_ladder or TimeoutLadderConfig()
        # Mapping: subagent_id -> (last_pulse_timestamp, pulse_count, ladder_config)
        self._tracked: dict[str, tuple[float, int, TimeoutLadderConfig]] = {}

    def register(
        self,
        subagent_id: str,
        ladder: TimeoutLadderConfig | None = None,
        initial_time: float | None = None,
    ) -> None:
        """Register a new subagent to be monitored with a given timeout ladder."""
        now = initial_time if initial_time is not None else time.time()
        active_ladder = ladder or self.default_ladder
        self._tracked[subagent_id] = (now, 0, active_ladder)

    def pulse(
        self,
        subagent_id: str,
        note: str = "",
        timestamp: float | None = None,
    ) -> None:
        """Record an explicit heartbeat pulse from a subagent, refreshing its vitality."""
        now = timestamp if timestamp is not None else time.time()
        entry = self._tracked.get(subagent_id)
        if entry is not None:
            _, count, ladder = entry
            self._tracked[subagent_id] = (now, count + 1, ladder)
        else:
            self._tracked[subagent_id] = (now, 1, self.default_ladder)

    def evaluate_health(
        self, subagent_id: str, current_time: float | None = None
    ) -> tuple[SubagentHealthState, float]:
        """Assess the current health of a subagent based on time elapsed since last pulse.

        Returns:
            Tuple of (SubagentHealthState, elapsed_seconds_since_last_pulse).
        """
        now = current_time if current_time is not None else time.time()
        entry = self._tracked.get(subagent_id)
        if entry is None:
            return SubagentHealthState.TERMINATED, 0.0

        last_pulse, _, ladder = entry
        elapsed = max(0.0, now - last_pulse)

        if elapsed >= ladder.hard_terminate_threshold_s:
            return SubagentHealthState.TERMINATED, elapsed
        if elapsed >= ladder.soft_cancel_threshold_s:
            return SubagentHealthState.SOFT_CANCELING, elapsed
        if elapsed >= ladder.warning_threshold_s:
            return SubagentHealthState.WARNING, elapsed

        return SubagentHealthState.HEALTHY, elapsed

    def get_pulse_count(self, subagent_id: str) -> int:
        """Get the total count of heartbeats recorded for a subagent."""
        entry = self._tracked.get(subagent_id)
        return entry[1] if entry is not None else 0

    def unregister(self, subagent_id: str) -> None:
        """Stop tracking a completed or terminated subagent."""
        self._tracked.pop(subagent_id, None)
