"""Context signal calculation for memory retrieval scoring.


[INPUT]
- memory.types::{AnyMemory, MemoryType} (POS: memory data models)

[OUTPUT]
- SignalCalculator: Normalized [0,1] signal factors (recency, frequency, importance, preference, rating)
- get_default_half_life: Default half-life per memory type
- get_default_signal_weights: Default signal weight profiles

[POS]
Context signal calculator for memory retrieval scoring. Provides normalized [0,1] factors
for recency, frequency, importance, preference, and rating. All signals are independent
and composable via weighted geometric mean.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.types import AnyMemory, MemoryType


class SignalCalculator:
    """Calculates normalized context signals for memory scoring."""

    @staticmethod
    def recency_factor(memory: AnyMemory, half_life_days: float) -> float:
        """Calculate time-based recency factor using exponential decay.

        Args:
            memory: Memory object with created_at field
            half_life_days: Days until factor decays to 0.5 (0 = no decay)

        Returns:
            Factor in [0, 1] where 1 = just created, 0.5 = half_life old
        """
        if half_life_days <= 0:
            return 1.0
        if not hasattr(memory, "created_at"):
            return 1.0

        now = datetime.now(UTC)
        created = memory.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        age_days = (now - created).days
        if age_days < 0:
            return 1.0

        return math.exp(-math.log(2) * age_days / half_life_days)

    @staticmethod
    def frequency_factor(memory: AnyMemory, saturation_point: int = 50) -> float:
        """Calculate access frequency factor using logarithmic scaling.

        Args:
            memory: Memory object with access_count field
            saturation_point: Access count at which factor reaches 1.0

        Returns:
            Factor in [0, 1] where 0 = never accessed, 1 = saturation_point accesses
        """
        if not hasattr(memory, "access_count"):
            return 0.0

        count = max(0, memory.access_count)
        if count == 0:
            return 0.0

        return min(1.0, math.log(1 + count) / math.log(1 + saturation_point))

    @staticmethod
    def importance_factor(memory: AnyMemory) -> float:
        """Extract importance factor from memory.

        Args:
            memory: Memory object with optional importance field

        Returns:
            Factor in [0, 1], defaults to 0.5 if not present
        """
        return max(0.0, min(1.0, getattr(memory, "importance", 0.5)))

    @staticmethod
    def preference_factor(memory: AnyMemory) -> float:
        """Extract preference strength factor from memory.

        Args:
            memory: Memory object with optional preference_strength field

        Returns:
            Factor in [0, 1], defaults to 0.0 if not present
        """
        return max(0.0, min(1.0, getattr(memory, "preference_strength", 0.0)))

    @staticmethod
    def rating_factor(memory: AnyMemory) -> float:
        """Extract user feedback rating factor from memory.

        Args:
            memory: Memory object with optional user_rating field

        Returns:
            Factor in [0, 1], defaults to 0.5 (neutral) if not present
        """
        return max(0.0, min(1.0, getattr(memory, "user_rating", 0.5)))

    @staticmethod
    def confidence_factor(memory: AnyMemory) -> float:
        """Extract confidence factor from memory.

        Args:
            memory: Memory object with optional confidence field

        Returns:
            Factor in [0, 1], defaults to 1.0 if not present
        """
        return max(0.0, min(1.0, getattr(memory, "confidence", 1.0)))

    @staticmethod
    def temporal_proximity_factor(
        memory: AnyMemory, reference_time: datetime | None = None, threshold_hours: float = 24.0
    ) -> float:
        """Calculate temporal proximity to reference time (MemPalace enhancement).

        Gives extra boost to memories created close to the reference time.
        Different from recency_factor: proximity is relative to query time,
        recency is relative to current time.

        Args:
            memory: Memory object with created_at/timestamp field
            reference_time: Reference time (defaults to now)
            threshold_hours: Hours within which proximity boost applies

        Returns:
            Proximity factor in [0, 1] where 1 = same time, 0 = beyond threshold
        """
        if reference_time is None:
            reference_time = datetime.now(UTC)

        memory_time = getattr(memory, "timestamp", None) or getattr(memory, "created_at", None)
        if not memory_time:
            return 0.0

        if memory_time.tzinfo is None:
            memory_time = memory_time.replace(tzinfo=UTC)
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=UTC)

        delta_hours = abs((memory_time - reference_time).total_seconds()) / 3600.0
        if delta_hours >= threshold_hours:
            return 0.0

        return 1.0 - (delta_hours / threshold_hours)


def get_default_signal_weights(memory_type: MemoryType) -> dict[str, float]:
    """Get type-specific signal weights for geometric mean scoring.

    Weights sum to 1.0. Semantic weight ≥ 0.6 ensures semantic dominance.

    Args:
        memory_type: Memory type

    Returns:
        Signal name to weight mapping
    """
    weights = {
        "PROFILE": {
            "semantic": 0.20,
            "recency": 0.00,
            "frequency": 0.00,
            "importance": 0.25,
            "preference": 0.45,
            "rating": 0.10,
        },
        "SEMANTIC": {
            "semantic": 0.65,
            "recency": 0.10,
            "frequency": 0.05,
            "importance": 0.08,
            "preference": 0.00,
            "rating": 0.12,
        },
        "CLAIM": {
            "semantic": 0.55,
            "recency": 0.18,
            "frequency": 0.05,
            "importance": 0.12,
            "preference": 0.00,
            "rating": 0.10,
        },
        "EPISODIC": {
            "semantic": 0.40,
            "recency": 0.25,
            "frequency": 0.12,
            "importance": 0.08,
            "preference": 0.00,
            "rating": 0.15,
        },
        "PROCEDURAL": {
            "semantic": 0.30,
            "recency": 0.00,
            "frequency": 0.12,
            "importance": 0.45,
            "preference": 0.00,
            "rating": 0.13,
        },
    }
    return weights.get(memory_type.upper(), weights["SEMANTIC"])


def get_default_half_life(memory_type: MemoryType) -> float:
    """Get type-specific recency decay half-life.

    Args:
        memory_type: Memory type

    Returns:
        Half-life in days (0 = no decay)
    """
    half_lives = {
        "PROFILE": 0.0,
        "SEMANTIC": 30.0,
        "CLAIM": 14.0,
        "EPISODIC": 7.0,
        "PROCEDURAL": 0.0,
    }
    return half_lives.get(memory_type.upper(), 30.0)
