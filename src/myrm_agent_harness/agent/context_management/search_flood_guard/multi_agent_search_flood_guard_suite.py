"""Unified facade suite for multi-agent per-context search flood guard and progressive soft-cap.

[INPUT]
- FloodActionKind, FloodGuardConfig, FloodGuardDecision, FloodGuardStatus: Domain models.
- PerAgentSlidingWindowTracker: Per-context sliding window rate tracking engine.
- ProgressiveSoftCapGate: Progressive result tapering and hard cooldown evaluation gate.

[OUTPUT]
- MultiAgentSearchFloodGuardSuite: Cohesive facade coordinating isolated per-agent sliding windows,
  progressive result soft-capping, and hard circuit-breaker cooldowns.

[POS]
Top-level entry point for multi-agent search flood protection in context management.
"""

from __future__ import annotations

import time
from typing import Mapping, Sequence, TypeVar

from .flood_guard_types import (
    FloodActionKind,
    FloodGuardConfig,
    FloodGuardDecision,
    FloodGuardStatus,
)
from .per_agent_sliding_window_tracker import PerAgentSlidingWindowTracker
from .progressive_soft_cap_gate import ProgressiveSoftCapGate

T = TypeVar("T")


class MultiAgentSearchFloodGuardSuite:
    """Industrial facade coordinating isolated search rate windows, soft-caps, and cooldowns."""

    def __init__(
        self,
        config: FloodGuardConfig | None = None,
        tracker: PerAgentSlidingWindowTracker | None = None,
        gate: ProgressiveSoftCapGate | None = None,
    ) -> None:
        self._config = config or FloodGuardConfig()
        self._tracker = tracker or PerAgentSlidingWindowTracker(self._config)
        self._gate = gate or ProgressiveSoftCapGate(self._tracker, self._config)

    @property
    def config(self) -> FloodGuardConfig:
        """Returns the active configuration governing the flood guard."""
        return self._config

    @property
    def tracker(self) -> PerAgentSlidingWindowTracker:
        """Returns the internal per-agent sliding window tracker."""
        return self._tracker

    @property
    def gate(self) -> ProgressiveSoftCapGate:
        """Returns the progressive soft-cap evaluation gate."""
        return self._gate

    @property
    def tracked_keys_count(self) -> int:
        """Returns total distinct agent contexts currently tracked in memory."""
        return self._tracker.tracked_keys_count

    def evaluate_and_record(
        self,
        session_id: str,
        subagent_id: str | None = None,
        timestamp: float | None = None,
    ) -> FloodGuardDecision:
        """Records a search call for the agent context and yields an authoritative flow decision."""
        return self._gate.evaluate_and_record(
            session_id=session_id,
            subagent_id=subagent_id,
            timestamp=timestamp,
        )

    def apply_soft_cap(
        self,
        results: Sequence[T],
        decision: FloodGuardDecision,
    ) -> Sequence[T]:
        """Tapers a flat sequence of search results if soft-capping is active."""
        return self._gate.apply_soft_cap(results=results, decision=decision)

    def apply_soft_cap_to_grouped(
        self,
        grouped_results: Mapping[str, Sequence[T]],
        decision: FloodGuardDecision,
    ) -> Mapping[str, Sequence[T]]:
        """Tapers multi-query grouped search results if soft-capping is active."""
        return self._gate.apply_soft_cap_to_grouped(
            grouped_results=grouped_results,
            decision=decision,
        )

    def get_window_count(
        self,
        session_id: str,
        subagent_id: str | None = None,
        timestamp: float | None = None,
    ) -> int:
        """Inspects current active calls within the rolling window without mutating state."""
        return self._tracker.get_window_count(
            session_id=session_id,
            subagent_id=subagent_id,
            timestamp=timestamp,
        )

    def get_remaining_cooldown(
        self,
        session_id: str,
        subagent_id: str | None = None,
        timestamp: float | None = None,
    ) -> float:
        """Returns remaining cooldown seconds if context is currently hard-blocked."""
        return self._tracker.get_remaining_cooldown(
            session_id=session_id,
            subagent_id=subagent_id,
            timestamp=timestamp,
        )

    def get_status(
        self,
        session_id: str,
        subagent_id: str | None = None,
        timestamp: float | None = None,
    ) -> FloodGuardStatus:
        """Produces a complete point-in-time status snapshot for the specified agent context."""
        now = timestamp if timestamp is not None else time.time()
        key = self._tracker.format_key(session_id, subagent_id)
        count = self._tracker.get_window_count(session_id, subagent_id, now)
        remaining = self._tracker.get_remaining_cooldown(session_id, subagent_id, now)
        is_blocked = remaining > 0.0

        if is_blocked:
            action = FloodActionKind.HARD_BLOCKED
        elif count > self._config.soft_cap_after:
            action = FloodActionKind.SOFT_CAPPED
        else:
            action = FloodActionKind.ALLOWED

        return FloodGuardStatus(
            session_id=session_id,
            subagent_id=subagent_id,
            tracking_key=key,
            window_count=count,
            is_blocked=is_blocked,
            remaining_cooldown=remaining,
            current_action=action,
        )

    def reset(self, session_id: str, subagent_id: str | None = None) -> None:
        """Resets tracking bucket and clears any active cooldown for the specified context."""
        self._tracker.reset_bucket(session_id=session_id, subagent_id=subagent_id)
