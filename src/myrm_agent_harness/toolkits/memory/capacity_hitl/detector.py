"""[POS]: src/myrm_agent_harness/toolkits/memory/capacity_hitl/detector.py
[INPUT]: Memory entry counts and quota parameters.
[OUTPUT]: CapacityStatusReport and categorized alert status.
"""

import time

from myrm_agent_harness.toolkits.memory.capacity_hitl.models import (
    CapacityAlertKind,
    CapacityStatusReport,
)


class CapacityThresholdDetector:
    """Detects memory capacity utilization levels against configured threshold ladders."""

    def __init__(
        self,
        default_max_entries: int = 1000,
        near_capacity_ratio: float = 0.80,
        critical_capacity_ratio: float = 0.95,
    ) -> None:
        self._default_max_entries = max(1, default_max_entries)
        self._near_ratio = near_capacity_ratio
        self._critical_ratio = critical_capacity_ratio

    def evaluate(
        self,
        total_entries: int,
        max_entries: int | None = None,
        pending_candidates: int = 0,
    ) -> CapacityStatusReport:
        """Evaluate memory capacity utilization and determine alert tier."""
        effective_max = max(1, max_entries if max_entries is not None else self._default_max_entries)
        ratio = round(min(1.0, max(0.0, total_entries / effective_max)), 4)

        if ratio >= self._critical_ratio:
            alert = CapacityAlertKind.CRITICAL_FULL
        elif ratio >= self._near_ratio:
            alert = CapacityAlertKind.NEAR_CAPACITY
        else:
            alert = CapacityAlertKind.NORMAL

        return CapacityStatusReport(
            total_entries=total_entries,
            max_entries=effective_max,
            capacity_ratio=ratio,
            alert_level=alert,
            pending_candidate_count=pending_candidates,
            timestamp=time.time(),
        )
