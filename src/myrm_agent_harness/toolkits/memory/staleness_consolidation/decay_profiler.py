"""Memory Half-Life Decay Profiler modeling staleness and access hotness (Item 158).

[INPUT]
- MemoryItemProfile records and current evaluation timestamp.

[OUTPUT]
- Calculated staleness scores and updated lifecycle statuses.

[POS]
- Half-life decay profiler in myrm_agent_harness/toolkits/memory/staleness_consolidation/.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from .models import MemoryItemProfile


class MemoryHalfLifeDecayProfiler:
    """Computes staleness decay scores based on elapsed time, half-life days, and recall frequency."""

    def __init__(
        self,
        half_life_days: float = 30.0,
        staleness_threshold: float = 0.65,
    ) -> None:
        self.half_life_days = max(1.0, half_life_days)
        self.staleness_threshold = min(0.99, max(0.01, staleness_threshold))

    @staticmethod
    def _parse_iso(timestamp_str: str) -> datetime:
        """Parse ISO 8601 string to timezone-aware UTC datetime."""
        if not timestamp_str:
            return datetime.now(timezone.utc)
        try:
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return datetime.now(timezone.utc)

    def compute_staleness_score(
        self,
        item: MemoryItemProfile,
        now: datetime | None = None,
    ) -> float:
        """Calculate staleness score in [0.0, 1.0]. 0.0 is brand new/frequently used, 1.0 is completely stale."""
        now_dt = now or datetime.now(timezone.utc)

        # Baseline point: latest of created_at or last_recalled_at
        created_dt = self._parse_iso(item.created_at)
        recalled_dt = (
            self._parse_iso(item.last_recalled_at)
            if item.last_recalled_at
            else created_dt
        )
        baseline_dt = max(created_dt, recalled_dt)

        elapsed_seconds = max(0.0, (now_dt - baseline_dt).total_seconds())
        elapsed_days = elapsed_seconds / 86400.0

        # Frequency retention factor: high recall count resists decay
        frequency_retention = 1.0 / (1.0 + 0.4 * math.log1p(max(0, item.recalled_count)))

        # Exponential half-life decay
        raw_decay = 1.0 - math.pow(2.0, -elapsed_days / self.half_life_days)
        staleness = raw_decay * frequency_retention

        return round(min(1.0, max(0.0, staleness)), 4)

    def evaluate_item(
        self,
        item: MemoryItemProfile,
        now: datetime | None = None,
    ) -> MemoryItemProfile:
        """Update the staleness score of a memory item and adjust status if crossed threshold."""
        score = self.compute_staleness_score(item, now=now)
        item.staleness_score = score

        if item.status == "active" and score >= self.staleness_threshold:
            item.status = "stale"
        elif item.status == "stale" and score < self.staleness_threshold:
            item.status = "active"

        return item

    def touch_recall(
        self,
        item: MemoryItemProfile,
        now_iso: str | None = None,
    ) -> MemoryItemProfile:
        """Record a successful recall event, resetting elapsed time and incrementing frequency."""
        now_str = now_iso or datetime.now(timezone.utc).isoformat()
        item.last_recalled_at = now_str
        item.recalled_count += 1
        return self.evaluate_item(item, now=self._parse_iso(now_str))
