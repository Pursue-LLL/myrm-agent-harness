"""Frequency-driven logarithmic compounding engine for memory experience reinforcement.

[POS]
Calculates bounded non-linear compounding weights based on positive adoption frequency,
extending memory half-life for repeatedly verified personal axioms.

[INPUT]
- math, time
- .models (CompoundedExperienceItem)

[OUTPUT]
- FrequencyCompoundingEngine, compute_compounded_weight
"""

from __future__ import annotations

import math
import time

from myrm_agent_harness.toolkits.memory.experience_compounding.models import (
    CompoundedExperienceItem,
)


def compute_compounded_weight(
    base_weight: float,
    adoption_count: int,
    alpha: float = 0.35,
    beta: float = 1.2,
    max_multiplier: float = 2.5,
) -> float:
    """Compute bounded logarithmic compounding weight without exploding.

    Formula: W_compounded = min(base_weight * (1.0 + alpha * ln(1.0 + beta * N)), base_weight * max_multiplier)
    """
    if adoption_count <= 0:
        return base_weight

    growth = 1.0 + alpha * math.log(1.0 + beta * float(adoption_count))
    capped_growth = min(growth, max_multiplier)
    return round(base_weight * capped_growth, 4)


class FrequencyCompoundingEngine:
    """Orchestrates frequency tracking, logarithmic compounding, and half-life immunity."""

    def __init__(
        self,
        alpha: float = 0.35,
        beta: float = 1.2,
        max_multiplier: float = 2.5,
        max_half_life_days: float = 180.0,
    ) -> None:
        self._alpha = alpha
        self._beta = beta
        self._max_multiplier = max_multiplier
        self._max_half_life = max_half_life_days

    def reinforce(
        self,
        item: CompoundedExperienceItem,
        adopted: bool = True,
        timestamp: float | None = None,
    ) -> float:
        """Reinforce item weight and update operational metadata."""
        now = timestamp if timestamp is not None else time.time()
        item.hit_count += 1

        if adopted:
            item.adoption_count += 1
            item.last_adopted_at = now
            # Extend half-life dynamically as verification compounds
            extended_half_life = 14.0 + math.log(1.0 + item.adoption_count) * 20.0
            item.half_life_days = min(extended_half_life, self._max_half_life)

        new_weight = compute_compounded_weight(
            base_weight=item.base_weight,
            adoption_count=item.adoption_count,
            alpha=self._alpha,
            beta=self._beta,
            max_multiplier=self._max_multiplier,
        )
        item.compounded_weight = new_weight
        if new_weight > item.peak_weight:
            item.peak_weight = new_weight
        return new_weight

    def penalize_contradiction(
        self,
        item: CompoundedExperienceItem,
        severity: float = 0.5,
        timestamp: float | None = None,
    ) -> float:
        """Penalize contradicted or rejected memory item to prevent upward blindness."""
        now = timestamp if timestamp is not None else time.time()
        decayed_adoption = max(0, int(item.adoption_count * (1.0 - severity)))
        item.adoption_count = decayed_adoption
        item.last_adopted_at = now
        new_weight = round(max(0.05, item.compounded_weight * (1.0 - severity)), 4)
        item.compounded_weight = new_weight
        item.peak_weight = new_weight
        item.half_life_days = max(1.0, item.half_life_days * 0.5)
        return new_weight

    def evaluate_weight(self, item: CompoundedExperienceItem) -> float:
        """Evaluate and return current compounding weight without mutation."""
        return compute_compounded_weight(
            base_weight=item.base_weight,
            adoption_count=item.adoption_count,
            alpha=self._alpha,
            beta=self._beta,
            max_multiplier=self._max_multiplier,
        )
