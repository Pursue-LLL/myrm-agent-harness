"""Calculates exponential half-life decay and dynamic confidence for evidence facts.

[INPUT]
- toolkits.memory.rule_cascade.models::FiveDimEvidenceMetadata (POS: Types and models for rule cascade.)

[OUTPUT]
- TimeDecayCalculator: Calculates exponential half-life decay and dynamic confidence for evidence facts.

[POS]
Calculates exponential half-life decay and dynamic confidence for evidence facts.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.rule_cascade.models import (
    FiveDimEvidenceMetadata,
)


class TimeDecayCalculator:
    """Calculates exponential half-life decay and dynamic confidence for evidence facts."""

    def calculate_elapsed_days(
        self,
        created_at_iso: str,
        now: datetime | None = None,
    ) -> float:
        """Calculate elapsed days since created_at timestamp."""
        current = now or datetime.now(UTC)
        try:
            created_dt = datetime.fromisoformat(created_at_iso)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return 0.0

        elapsed_seconds = max(0.0, (current - created_dt).total_seconds())
        return elapsed_seconds / 86400.0

    def compute_decay_factor(
        self,
        elapsed_days: float,
        half_life_days: float,
    ) -> float:
        """Compute exponential decay factor S(t) = 2^(-t / half_life)."""
        if half_life_days <= 0.0 or elapsed_days <= 0.0:
            return 1.0
        exponent = -elapsed_days / half_life_days
        return math.pow(2.0, exponent)

    def compute_effective_confidence(
        self,
        metadata: FiveDimEvidenceMetadata,
        now: datetime | None = None,
    ) -> float:
        """Compute the current effective confidence combining baseline confidence and time decay."""
        elapsed_days = self.calculate_elapsed_days(metadata.created_at, now=now)
        decay = self.compute_decay_factor(elapsed_days, metadata.half_life_days)
        effective = metadata.confidence * decay
        return max(0.0, min(1.0, effective))

    def is_expired(
        self,
        metadata: FiveDimEvidenceMetadata,
        threshold: float = 0.3,
        now: datetime | None = None,
    ) -> bool:
        """Check if the dynamic effective confidence has decayed below threshold."""
        effective = self.compute_effective_confidence(metadata, now=now)
        return effective < threshold
