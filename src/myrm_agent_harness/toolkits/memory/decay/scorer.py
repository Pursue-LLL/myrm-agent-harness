"""Ebbinghaus exponential decay and RFM frequency reinforcement scoring function.

[INPUT]
- toolkits.memory.decay.types::DecayScorerConfig, MemoryDecayProfile, StorageTier (POS: Domain models and
  type definitions for Ebbinghaus decay and tiered storage lifecycle.)

[OUTPUT]
- EbbinghausDecayScorer: Calculates active memory retention using Ebbinghaus decay curve and RFM frequency
  boost.

[POS]
Ebbinghaus exponential decay and RFM frequency reinforcement scoring function.
"""

import math
import time

from myrm_agent_harness.toolkits.memory.decay.types import (
    DecayScorerConfig,
    MemoryDecayProfile,
    StorageTier,
)


class EbbinghausDecayScorer:
    """Calculates active memory retention using Ebbinghaus decay curve and RFM frequency boost."""

    def __init__(self, config: DecayScorerConfig | None = None) -> None:
        self.config = config or DecayScorerConfig()

    def calculate_score(
        self, profile: MemoryDecayProfile, current_time: float | None = None
    ) -> tuple[float, StorageTier]:
        """Compute the dynamic retention score and classify the appropriate storage tier."""
        now = time.time() if current_time is None else current_time

        if profile.pinned:
            return 1.0, StorageTier.HOT

        delta_seconds = max(0.0, now - profile.last_accessed_at)
        delta_days = delta_seconds / 86400.0

        # Ebbinghaus exponential decay over elapsed days
        time_retention = math.exp(-self.config.lambda_decay * delta_days)

        # Logarithmic frequency reinforcement
        freq_boost = 1.0 + self.config.alpha_freq * math.log(
            1.0 + max(0, profile.access_count)
        )

        raw_score = profile.importance * time_retention * freq_boost
        score = min(1.0, max(0.0, raw_score))

        # Determine target tier based on score and overall item age
        total_age_days = max(0.0, now - profile.created_at) / 86400.0

        if score >= self.config.hot_threshold:
            tier = StorageTier.HOT
        elif (
            score < self.config.cold_threshold
            and total_age_days >= self.config.cold_min_age_days
        ):
            tier = StorageTier.COLD
        else:
            tier = StorageTier.WARM

        return round(score, 4), tier

    def touch(
        self, profile: MemoryDecayProfile, current_time: float | None = None
    ) -> tuple[float, StorageTier]:
        """Record an access/retrieval event, incrementing frequency and refreshing timestamp."""
        now = time.time() if current_time is None else current_time
        profile.last_accessed_at = now
        profile.access_count += 1
        new_score, new_tier = self.calculate_score(profile, current_time=now)
        profile.current_score = new_score
        profile.current_tier = new_tier
        return new_score, new_tier
