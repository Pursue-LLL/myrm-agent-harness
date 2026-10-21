"""Scenario-aware model selection strategy.

Provides intelligent model selection based on usage scenario.

[INPUT]

[OUTPUT]
- ScenarioType: scenariotypeenum
- ModelMetrics: modelmetricsdataclass
- select_by_scenario: scenarioknownselectfunction

[POS]
Scenario-aware model selection. Optimizes model choice based on scenario (realtime/batch/balanced).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScenarioType(Enum):
    """Usage scenario types.

    REALTIME: Latency-first (minimize response time)
    BATCH: Cost-first (minimize cost)
    BALANCED: Balance between latency and cost
    QUALITY_FIRST: Quality-first (prioritize highest quality)
    """

    REALTIME = "realtime"
    BATCH = "batch"
    BALANCED = "balanced"
    QUALITY_FIRST = "quality_first"


@dataclass
class ModelMetrics:
    """Model performance metrics.

    Attributes:
        name: Model name
        priority: Base priority (lower = higher priority)
        cost: Relative cost (0.0-1.0, lower is better)
        latency: Relative latency (0.0-1.0, lower is better)
        quality: Relative quality (0.0-1.0, higher is better)
    """

    name: str
    priority: int
    cost: float = 0.5
    latency: float = 0.5
    quality: float = 0.5

    def __post_init__(self) -> None:
        """Validate metrics are in valid range."""
        if not 0.0 <= self.cost <= 1.0:
            raise ValueError(f"cost must be in [0.0, 1.0], got {self.cost}")
        if not 0.0 <= self.latency <= 1.0:
            raise ValueError(f"latency must be in [0.0, 1.0], got {self.latency}")
        if not 0.0 <= self.quality <= 1.0:
            raise ValueError(f"quality must be in [0.0, 1.0], got {self.quality}")


def select_by_scenario(
    candidates: list[ModelMetrics],
    scenario: ScenarioType,
) -> ModelMetrics:
    """Select best model for given scenario using lexicographic ordering.

    Strategy:
    - REALTIME: priority → latency → cost
    - BATCH: priority → cost → latency
    - BALANCED: priority → (cost + latency) / 2
    - QUALITY_FIRST: priority → quality (descending) → cost

    Args:
        candidates: List of model candidates with metrics
        scenario: Usage scenario

    Returns:
        Best model for the scenario

    Raises:
        ValueError: If candidates list is empty
    """
    if not candidates:
        raise ValueError("No candidates provided")

    if scenario == ScenarioType.REALTIME:
        # Latency-first: minimize latency, then cost
        def key(m: ModelMetrics) -> tuple[int, float, float]:
            return (m.priority, m.latency, m.cost)
    elif scenario == ScenarioType.BATCH:
        # Cost-first: minimize cost, then latency
        def key(m: ModelMetrics) -> tuple[int, float, float]:
            return (m.priority, m.cost, m.latency)
    elif scenario == ScenarioType.QUALITY_FIRST:
        # Quality-first: maximize quality, then minimize cost
        def key(m: ModelMetrics) -> tuple[int, float, float]:
            return (m.priority, -m.quality, m.cost)
    else:  # BALANCED
        # Balance: minimize average of cost and latency
        def key(m: ModelMetrics) -> tuple[int, float]:
            return (m.priority, (m.cost + m.latency) / 2)

    return sorted(candidates, key=key)[0]


def select_by_scenario_with_quality(
    candidates: list[ModelMetrics],
    scenario: ScenarioType,
    min_quality: float = 0.0,
) -> ModelMetrics:
    """Select best model with quality threshold.

    Filters candidates by minimum quality before applying scenario selection.

    Args:
        candidates: List of model candidates with metrics
        scenario: Usage scenario
        min_quality: Minimum quality threshold (0.0-1.0)

    Returns:
        Best model for the scenario

    Raises:
        ValueError: If no candidates meet quality threshold
    """
    if not 0.0 <= min_quality <= 1.0:
        raise ValueError(f"min_quality must be in [0.0, 1.0], got {min_quality}")

    # Filter by quality
    qualified = [c for c in candidates if c.quality >= min_quality]

    if not qualified:
        raise ValueError(
            f"No candidates meet quality threshold {min_quality}. "
            f"Available qualities: {[c.quality for c in candidates]}"
        )

    return select_by_scenario(qualified, scenario)
