"""Types and schemas for cross-deployment prompt cache economics and anti-drift HUD.

[INPUT]
Raw token usage counts (prompt, cached, completion), model names, and drift detections.

[OUTPUT]
Type-safe schemas for 30x cost savings calculation, health traffic lights,
session-wide economic rollups, and unified cross-deployment HUD payloads.

[POS]
Core protocol benchmarked against DeepSeek Harness 1/30 input pricing and 99% cache economics.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class HealthTrafficLight(StrEnum):
    """Visual traffic light indicator representing prefix cache stability."""
    GREEN_OPTIMAL = "green_optimal"      # >= 95% cache hit rate (sub-second, 1/30 price)
    YELLOW_PARTIAL = "yellow_partial"    # 60% - 94% cache hit rate (partial append/drift)
    RED_DRIFT_BREACH = "red_drift_breach"  # < 60% cache hit rate (cache broken or cold start)


@dataclass(frozen=True)
class ModelPricingTier:
    """Pricing configuration per million tokens in USD."""
    model_name: str
    uncached_input_per_m_usd: float
    cached_input_per_m_usd: float
    output_per_m_usd: float


@dataclass(frozen=True)
class TurnCacheEconomicsRecord:
    """Detailed financial and cache health metrics for a single conversational turn."""
    turn_index: int
    model_name: str
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int
    cache_hit_rate: float
    actual_cost_usd: float
    baseline_uncached_cost_usd: float
    savings_usd: float
    savings_ratio: float
    savings_multiplier: float
    traffic_light: HealthTrafficLight
    drift_diagnosis: str | None = None
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class SessionCacheEconomicsSummary:
    """Aggregated multi-turn financial and cache health statistics across session lifecycle."""
    session_id: str
    total_turns_count: int
    total_prompt_tokens: int
    total_cached_tokens: int
    total_completion_tokens: int
    overall_cache_hit_rate: float
    total_actual_cost_usd: float
    total_baseline_uncached_cost_usd: float
    total_savings_usd: float
    overall_savings_ratio: float
    overall_savings_multiplier: float
    dominant_traffic_light: HealthTrafficLight


@dataclass(frozen=True)
class CrossDeploymentHudPayload:
    """Unified HUD payload directly consumable by WebUI, Tauri Desktop, and Cloud Sandboxes."""
    session_id: str
    traffic_light: HealthTrafficLight
    traffic_light_badge: str
    cache_hit_rate_percent: float
    savings_multiplier_label: str
    total_savings_usd_formatted: str
    headline_message: str
    anti_drift_tips: tuple[str, ...]
