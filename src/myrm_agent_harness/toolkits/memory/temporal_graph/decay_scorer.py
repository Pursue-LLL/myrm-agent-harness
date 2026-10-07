"""[POS]: src/myrm_agent_harness/toolkits/memory/temporal_graph/decay_scorer.py
[INPUT]: TemporalFactEdge, timestamp math, and configurable half-life decay parameters.
[OUTPUT]: TemporalDecayScorer calculating dynamic recency scores, reinforcement bonuses, and edge lifecycle statuses.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from .models import TemporalFactEdge


class TemporalDecayScorer:
    """Calculates exponential half-life decay and access reinforcement for temporal graph edges."""

    def __init__(
        self,
        half_life_days: float = 30.0,
        superseded_penalty: float = 0.05,
        access_bonus_cap: float = 0.5,
    ) -> None:
        self._half_life_days = max(1.0, half_life_days)
        self._superseded_penalty = max(0.0, min(1.0, superseded_penalty))
        self._access_bonus_cap = max(0.0, access_bonus_cap)

    def calculate_score(
        self,
        edge: TemporalFactEdge,
        as_of: datetime | None = None,
    ) -> tuple[float, str]:
        """Calculates dynamic score and effective status for a temporal fact edge.

        Returns:
            Tuple of (decayed_score, effective_status) where status is 'active', 'superseded', or 'expired'.
        """
        now = as_of or datetime.now(UTC)

        # Determine reference time for decay (prefer last accessed time, fallback to valid_from)
        ref_time = edge.last_accessed_at or edge.valid_from
        elapsed_seconds = max(0.0, (now - ref_time).total_seconds())
        elapsed_days = elapsed_seconds / 86400.0

        # Exponential decay factor: 2^(-delta_t / half_life)
        decay_factor = math.pow(2.0, -elapsed_days / self._half_life_days)

        # Access reinforcement bonus (up to access_bonus_cap)
        bonus = min(self._access_bonus_cap, edge.access_count * 0.05)
        raw_score = edge.confidence_score * (decay_factor + bonus)

        # Check supersession and validity intervals
        if edge.is_superseded:
            score = raw_score * self._superseded_penalty
            return round(score, 4), "superseded"

        if edge.valid_until and now > edge.valid_until:
            score = raw_score * self._superseded_penalty
            return round(score, 4), "expired"

        score = max(0.0, min(1.0, raw_score))
        return round(score, 4), "active"

    def record_access(
        self,
        edge: TemporalFactEdge,
        access_time: datetime | None = None,
    ) -> TemporalFactEdge:
        """Reinforces the edge upon retrieval by incrementing access count and updating timestamp."""
        now = access_time or datetime.now(UTC)
        edge.access_count += 1
        edge.last_accessed_at = now
        return edge
