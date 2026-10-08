"""Progressive soft-cap gate making flow control decisions and tapering search results.

[INPUT]
- FloodActionKind, FloodGuardConfig, FloodGuardDecision: Domain definitions.
- PerAgentSlidingWindowTracker: Sliding window tracker.

[OUTPUT]
- ProgressiveSoftCapGate: Gate evaluating call rates, enforcing soft caps, and applying cooldown blocks.

[POS]
Decision evaluation and result tapering layer for search flood guard.
"""

from __future__ import annotations

import time
from typing import Mapping, Sequence, TypeVar

from .flood_guard_types import FloodActionKind, FloodGuardConfig, FloodGuardDecision
from .per_agent_sliding_window_tracker import PerAgentSlidingWindowTracker

T = TypeVar("T")


class ProgressiveSoftCapGate:
    """Evaluates search invocation frequency and enforces progressive result tapering and hard blocks."""

    def __init__(
        self,
        tracker: PerAgentSlidingWindowTracker,
        config: FloodGuardConfig | None = None,
    ) -> None:
        self._tracker = tracker
        self._config = config or FloodGuardConfig()

    def evaluate_and_record(
        self,
        session_id: str,
        subagent_id: str | None = None,
        timestamp: float | None = None,
    ) -> FloodGuardDecision:
        """Records invocation and returns authoritative rate limit verdict."""
        now = timestamp if timestamp is not None else time.time()

        # 1. Check existing hard cooldown block
        remaining_cooldown = self._tracker.get_remaining_cooldown(
            session_id=session_id,
            subagent_id=subagent_id,
            timestamp=now,
        )
        if remaining_cooldown > 0.0:
            return FloodGuardDecision(
                action=FloodActionKind.HARD_BLOCKED,
                current_count=self._tracker.get_window_count(session_id, subagent_id, now),
                allowed_results_per_query=0,
                retry_after_seconds=remaining_cooldown,
                reason=f"Search flood detected. Cooldown active for {remaining_cooldown:.1f}s.",
                is_blocked=True,
            )

        # 2. Record new invocation event
        current_count, _ = self._tracker.record_call(
            session_id=session_id,
            subagent_id=subagent_id,
            timestamp=now,
        )

        # 3. Check for hard block threshold violation
        if current_count > self._config.block_after:
            blocked_until = now + self._config.cooldown_seconds
            self._tracker.set_block_cooldown(session_id, subagent_id, blocked_until)
            return FloodGuardDecision(
                action=FloodActionKind.HARD_BLOCKED,
                current_count=current_count,
                allowed_results_per_query=0,
                retry_after_seconds=self._config.cooldown_seconds,
                reason=f"Exceeded hard block threshold ({current_count} > {self._config.block_after}). Cooling down for {self._config.cooldown_seconds:.1f}s.",
                is_blocked=True,
            )

        # 4. Check for soft cap threshold
        if current_count > self._config.soft_cap_after:
            return FloodGuardDecision(
                action=FloodActionKind.SOFT_CAPPED,
                current_count=current_count,
                allowed_results_per_query=self._config.soft_cap_results_limit,
                retry_after_seconds=0.0,
                reason=f"High search frequency ({current_count} calls in window). Tapered to {self._config.soft_cap_results_limit} result per query.",
                is_blocked=False,
            )

        # 5. Normal allowed invocation
        return FloodGuardDecision(
            action=FloodActionKind.ALLOWED,
            current_count=current_count,
            allowed_results_per_query=None,
            retry_after_seconds=0.0,
            reason="Search invocation within normal limits.",
            is_blocked=False,
        )

    def apply_soft_cap(
        self,
        results: Sequence[T],
        decision: FloodGuardDecision,
    ) -> Sequence[T]:
        """Tapers a flat sequence of search results if soft-cap disposition is active."""
        if not decision.should_taper_results or decision.allowed_results_per_query is None:
            return results
        limit = decision.allowed_results_per_query
        return tuple(results[:limit])

    def apply_soft_cap_to_grouped(
        self,
        grouped_results: Mapping[str, Sequence[T]],
        decision: FloodGuardDecision,
    ) -> Mapping[str, Sequence[T]]:
        """Tapers results grouped by query string if soft-cap disposition is active."""
        if not decision.should_taper_results or decision.allowed_results_per_query is None:
            return grouped_results

        limit = decision.allowed_results_per_query
        tapered: dict[str, Sequence[T]] = {}
        for query_text, items in grouped_results.items():
            tapered[query_text] = tuple(items[:limit])
        return tapered
