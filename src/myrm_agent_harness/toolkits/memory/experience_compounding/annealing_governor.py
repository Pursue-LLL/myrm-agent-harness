"""Obsolete context annealing and cold tiering governor.

[POS]
Applies exponential time-decay annealing to inactive and temporary context items,
protects items under active leases (pinned, in_progress), and sinks depleted items to cold storage.

[INPUT]
- math, time, uuid
- .models (AnnealingReport, CompoundedExperienceItem, ExperienceItemState)

[OUTPUT]
- ObsoleteContextAnnealingGovernor
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.experience_compounding.models import (
    AnnealingReport,
    CompoundedExperienceItem,
    ExperienceItemState,
)

_PROTECTED_TAGS = {"pinned", "in_progress", "active_task", "axiom", "core_rule"}
_TEMPORARY_TAGS = {"temporary", "transient", "one_off", "debug", "draft"}


class ObsoleteContextAnnealingGovernor:
    """Governs context lifecycle via active lease protection and cold tier demotion."""

    def __init__(
        self,
        cold_tier_threshold: float = 0.20,
        temporary_half_life_days: float = 3.0,
    ) -> None:
        self._cold_tier_threshold = cold_tier_threshold
        self._temp_half_life = temporary_half_life_days

    def apply_annealing(
        self,
        items: Sequence[CompoundedExperienceItem],
        current_time: float | None = None,
    ) -> AnnealingReport:
        """Evaluate and apply annealing decay to active memory items."""
        now = current_time if current_time is not None else time.time()
        report_id = f"anneal-{uuid.uuid4().hex[:8]}"

        inspected = 0
        exempt_count = 0
        cold_tiered_count = 0
        decayed_log: list[str] = []

        for it in items:
            if not it.is_active():
                continue

            inspected += 1

            # 1. Active Lease Protection: pinned, in_progress, or core axioms are exempt
            has_protected_tag = any(t.lower() in _PROTECTED_TAGS for t in it.tags)
            if it.is_pinned or has_protected_tag:
                exempt_count += 1
                continue

            # 2. Determine half life
            is_temp = it.is_temporary or any(t.lower() in _TEMPORARY_TAGS for t in it.tags)
            half_life = self._temp_half_life if is_temp else it.half_life_days

            # 3. Calculate elapsed days and exponential decay
            elapsed_seconds = max(0.0, now - it.last_adopted_at)
            elapsed_days = elapsed_seconds / 86400.0
            decay_factor = math.pow(0.5, elapsed_days / max(0.1, half_life))

            new_weight = round(it.peak_weight * decay_factor, 4)
            it.compounded_weight = new_weight

            # 4. Cold tier demotion when weight drops below critical threshold
            if new_weight < self._cold_tier_threshold:
                it.state = ExperienceItemState.COLD_TIERED
                cold_tiered_count += 1
                decayed_log.append(
                    f"Demoted item [{it.item_id}] (topic: {it.topic}) to cold storage (weight: {new_weight})."
                )

        return AnnealingReport(
            report_id=report_id,
            inspected_count=inspected,
            active_lease_exempt_count=exempt_count,
            cold_tiered_count=cold_tiered_count,
            decayed_items=decayed_log,
        )

    def reactivate(
        self,
        item: CompoundedExperienceItem,
        reset_weight: float = 1.0,
        timestamp: float | None = None,
    ) -> None:
        """Revive an archived or cold-tiered memory item back into active hot pool."""
        now = timestamp if timestamp is not None else time.time()
        item.state = ExperienceItemState.ACTIVE
        item.base_weight = reset_weight
        item.compounded_weight = reset_weight
        item.peak_weight = reset_weight
        item.last_adopted_at = now
