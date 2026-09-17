"""Continuous-time gravity decay scoring model for memory retrieval and pulse intelligence.

[INPUT]
- created_at: datetime | str | float | int (timestamp of the memory item)
- now: datetime | None (reference evaluation time, defaults to UTC now)
- interactions: int | float (number of clicks, expansions, citations)
- quality_score: float (explicit/implicit quality rating in [0.0, 1.0])
- config: GravityDecayConfig (decay parameters)

[OUTPUT]
- float: continuous gravity decay factor in (0.0, +inf)

[POS]
Continuous power-law gravity model inspired by physical decay and Hacker News ranking.
Replaces discrete day-based half-life with sub-hour precision continuous dynamics.
Provides bounded, positive-definite values resistant to zero-division and clock-skew.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

DEFAULT_GRAVITY_POWER: Final[float] = 1.8
DEFAULT_TIME_SCALE_HOURS: Final[float] = 24.0
DEFAULT_INTERACTION_WEIGHT: Final[float] = 0.15
DEFAULT_QUALITY_WEIGHT: Final[float] = 0.25
DEFAULT_FLOOR_EPSILON: Final[float] = 1e-4


@dataclass(frozen=True, slots=True)
class GravityDecayConfig:
    """Configuration parameters for continuous gravity decay scoring."""

    gravity: float = DEFAULT_GRAVITY_POWER
    time_scale_hours: float = DEFAULT_TIME_SCALE_HOURS
    interaction_weight: float = DEFAULT_INTERACTION_WEIGHT
    quality_weight: float = DEFAULT_QUALITY_WEIGHT
    floor_epsilon: float = DEFAULT_FLOOR_EPSILON

    def __post_init__(self) -> None:
        if self.gravity <= 0.0:
            msg = f"gravity must be strictly positive, got {self.gravity}"
            raise ValueError(msg)
        if self.time_scale_hours <= 0.0:
            msg = f"time_scale_hours must be strictly positive, got {self.time_scale_hours}"
            raise ValueError(msg)
        if self.interaction_weight < 0.0:
            msg = f"interaction_weight cannot be negative, got {self.interaction_weight}"
            raise ValueError(msg)
        if self.quality_weight < 0.0:
            msg = f"quality_weight cannot be negative, got {self.quality_weight}"
            raise ValueError(msg)


def parse_timestamp_utc(value: datetime | str | float | int | None) -> datetime:
    """Parse various timestamp representations into timezone-aware UTC datetime.

    Args:
        value: datetime, ISO string, unix timestamp float/int, or None.

    Returns:
        timezone-aware datetime in UTC.
    """
    if value is None:
        return datetime.now(UTC)

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)

    if isinstance(value, str):
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            return datetime.now(UTC)

    return datetime.now(UTC)


def compute_gravity_decay(
    created_at: datetime | str | float | int | None,
    *,
    now: datetime | None = None,
    interactions: int | float = 0,
    quality_score: float = 0.0,
    config: GravityDecayConfig | None = None,
) -> float:
    """Compute continuous power-law gravity decay score.

    Mathematical formulation:
        delta_t_hours = max(0.0, (now - created_at).total_seconds() / 3600.0)
        numerator = 1.0 + max(0, interactions) * w_int + clamp(quality_score, 0, 1) * w_qual
        denominator = (1.0 + delta_t_hours / time_scale_hours) ** gravity
        score = numerator / denominator

    Properties:
        - At delta_t=0 with 0 interactions and 0 quality, score = 1.0.
        - Strictly monotonically decreasing with respect to elapsed time.
        - Strictly positive: never returns negative values or zero division.
        - High-frequency interactions or verified quality produce pulse boosts.

    Args:
        created_at: Memory item creation or latest update timestamp.
        now: Reference evaluation time (defaults to current UTC).
        interactions: Cumulative access, click, or citation count.
        quality_score: Intrinsic quality score in range [0.0, 1.0].
        config: Optional tuning parameters.

    Returns:
        Continuous decay factor >= floor_epsilon.
    """
    cfg = config or GravityDecayConfig()
    eval_now = now.astimezone(UTC) if (now and now.tzinfo) else (now.replace(tzinfo=UTC) if now else datetime.now(UTC))
    item_time = parse_timestamp_utc(created_at)

    elapsed_seconds = (eval_now - item_time).total_seconds()
    # Guard against clock skew or future-dated records
    delta_hours = max(0.0, elapsed_seconds / 3600.0)

    safe_interactions = max(0.0, float(interactions))
    safe_quality = max(0.0, min(1.0, float(quality_score)))

    numerator = 1.0 + (safe_interactions * cfg.interaction_weight) + (safe_quality * cfg.quality_weight)
    scaled_time = 1.0 + (delta_hours / cfg.time_scale_hours)
    denominator = scaled_time**cfg.gravity

    if denominator <= 0.0 or not math.isfinite(denominator):
        return cfg.floor_epsilon

    score = numerator / denominator
    return max(cfg.floor_epsilon, score)


class GravityDecayScorer:
    """Stateful helper for applying gravity decay scoring over memory batches."""

    def __init__(self, config: GravityDecayConfig | None = None) -> None:
        self._config = config or GravityDecayConfig()

    @property
    def config(self) -> GravityDecayConfig:
        return self._config

    def score(
        self,
        created_at: datetime | str | float | int | None,
        *,
        now: datetime | None = None,
        interactions: int | float = 0,
        quality_score: float = 0.0,
    ) -> float:
        """Compute score with internal configuration."""
        return compute_gravity_decay(
            created_at,
            now=now,
            interactions=interactions,
            quality_score=quality_score,
            config=self._config,
        )
