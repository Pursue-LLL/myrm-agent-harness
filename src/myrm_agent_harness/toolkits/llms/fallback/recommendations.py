"""Smart fallback model recommendations.

[INPUT]

[OUTPUT]
- FallbackRecommendation: Fallback recommendation data class
- recommend_fallback: Function to get fallback recommendations for a model
- FALLBACK_RECOMMENDATIONS: Pre-defined recommendation mapping

[POS]
Provides intelligent fallback model recommendations based on model capabilities,
cost, and performance characteristics. Helps users configure appropriate fallback
models without deep knowledge of model trade-offs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FallbackRecommendation:
    """Recommended fallback model with rationale.

    Attributes:
        model_name: Name of the recommended fallback model
        reason: Human-readable reason for this recommendation
        is_primary: Whether this is the primary (top) recommendation
        cost_factor: Relative cost compared to main model (e.g., 0.5 = half the cost)
        latency_factor: Relative latency compared to main model
        quality_factor: Relative quality compared to main model
    """

    model_name: str
    reason: str
    is_primary: bool = True
    cost_factor: float = 1.0
    latency_factor: float = 1.0
    quality_factor: float = 1.0


FALLBACK_RECOMMENDATIONS: dict[str, list[FallbackRecommendation]] = {
    # --- OpenAI flagship ---
    "gpt-4o": [
        FallbackRecommendation(
            model_name="claude-sonnet-4-20250514",
            reason="Similar performance, alternative provider reduces rate limit impact",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=0.9,
            quality_factor=0.95,
        ),
        FallbackRecommendation(
            model_name="gemini-2.5-flash",
            reason="Lower cost, fast alternative",
            is_primary=False,
            cost_factor=0.3,
            latency_factor=0.7,
            quality_factor=0.9,
        ),
    ],
    "gpt-4.1": [
        FallbackRecommendation(
            model_name="claude-sonnet-4-20250514",
            reason="Similar capabilities, alternative provider",
            is_primary=True,
            cost_factor=0.8,
            latency_factor=0.9,
            quality_factor=0.95,
        ),
        FallbackRecommendation(
            model_name="gpt-4o",
            reason="Same family, proven reliability",
            is_primary=False,
            cost_factor=0.6,
            latency_factor=0.9,
            quality_factor=0.93,
        ),
    ],
    "gpt-4o-mini": [
        FallbackRecommendation(
            model_name="claude-3-5-haiku-20241022",
            reason="Similar cost and speed, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=0.95,
        ),
        FallbackRecommendation(
            model_name="gemini-2.5-flash",
            reason="Fast and cost-effective alternative",
            is_primary=False,
            cost_factor=0.8,
            latency_factor=0.8,
            quality_factor=0.95,
        ),
    ],
    "gpt-4.1-mini": [
        FallbackRecommendation(
            model_name="claude-3-5-haiku-20241022",
            reason="Similar speed tier, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=0.95,
        ),
        FallbackRecommendation(
            model_name="gpt-4o-mini",
            reason="Same family, proven reliability",
            is_primary=False,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=0.9,
        ),
    ],
    # --- OpenAI reasoning ---
    "o3": [
        FallbackRecommendation(
            model_name="claude-sonnet-4-20250514",
            reason="Strong reasoning, alternative provider",
            is_primary=True,
            cost_factor=0.3,
            latency_factor=0.5,
            quality_factor=0.9,
        ),
        FallbackRecommendation(
            model_name="gpt-4o",
            reason="Same provider, much faster for non-reasoning tasks",
            is_primary=False,
            cost_factor=0.1,
            latency_factor=0.3,
            quality_factor=0.8,
        ),
    ],
    "o4-mini": [
        FallbackRecommendation(
            model_name="gemini-2.5-flash",
            reason="Similar speed tier, alternative provider",
            is_primary=True,
            cost_factor=0.5,
            latency_factor=0.8,
            quality_factor=0.9,
        ),
        FallbackRecommendation(
            model_name="gpt-4o-mini",
            reason="Same provider, lower cost for simpler tasks",
            is_primary=False,
            cost_factor=0.3,
            latency_factor=0.5,
            quality_factor=0.8,
        ),
    ],
    # --- Anthropic ---
    "claude-sonnet-4-20250514": [
        FallbackRecommendation(
            model_name="gpt-4o",
            reason="Similar performance, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.1,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="gemini-2.5-pro",
            reason="Strong reasoning alternative",
            is_primary=False,
            cost_factor=0.8,
            latency_factor=1.0,
            quality_factor=0.98,
        ),
    ],
    "claude-opus-4-20250514": [
        FallbackRecommendation(
            model_name="o3",
            reason="Top-tier reasoning, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=0.95,
        ),
        FallbackRecommendation(
            model_name="claude-sonnet-4-20250514",
            reason="Same family, faster and cheaper",
            is_primary=False,
            cost_factor=0.2,
            latency_factor=0.5,
            quality_factor=0.9,
        ),
    ],
    "claude-3-5-haiku-20241022": [
        FallbackRecommendation(
            model_name="gpt-4o-mini",
            reason="Similar speed and cost, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="gemini-2.5-flash",
            reason="Fast alternative, competitive quality",
            is_primary=False,
            cost_factor=0.8,
            latency_factor=0.8,
            quality_factor=1.0,
        ),
    ],
    # --- Google Gemini ---
    "gemini-2.5-pro": [
        FallbackRecommendation(
            model_name="claude-sonnet-4-20250514",
            reason="Similar capabilities, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=0.9,
            quality_factor=0.95,
        ),
        FallbackRecommendation(
            model_name="gpt-4o",
            reason="Proven reliability, alternative provider",
            is_primary=False,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=0.95,
        ),
    ],
    "gemini-2.5-flash": [
        FallbackRecommendation(
            model_name="gpt-4o-mini",
            reason="Similar speed and cost, alternative provider",
            is_primary=True,
            cost_factor=1.2,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="claude-3-5-haiku-20241022",
            reason="Fast alternative, alternative provider",
            is_primary=False,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
    ],
    # --- DeepSeek ---
    "deepseek-chat": [
        FallbackRecommendation(
            model_name="gpt-4o",
            reason="Higher quality alternative, different provider",
            is_primary=True,
            cost_factor=5.0,
            latency_factor=1.0,
            quality_factor=1.1,
        ),
        FallbackRecommendation(
            model_name="gemini-2.5-flash",
            reason="Fast and cheap alternative",
            is_primary=False,
            cost_factor=1.5,
            latency_factor=0.8,
            quality_factor=1.0,
        ),
    ],
    "deepseek-reasoner": [
        FallbackRecommendation(
            model_name="o4-mini",
            reason="Reasoning-capable alternative, different provider",
            is_primary=True,
            cost_factor=2.0,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="gemini-2.5-pro",
            reason="Strong reasoning alternative",
            is_primary=False,
            cost_factor=1.5,
            latency_factor=1.0,
            quality_factor=0.95,
        ),
    ],
    # --- Volcengine / Doubao ---
    "doubao-seed-2.0-code": [
        FallbackRecommendation(
            model_name="deepseek-chat",
            reason="Similar coding capabilities, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="gpt-4o",
            reason="Higher coding quality, alternative provider",
            is_primary=False,
            cost_factor=5.0,
            latency_factor=1.0,
            quality_factor=1.2,
        ),
    ],
    # --- Mistral ---
    "mistral-large-latest": [
        FallbackRecommendation(
            model_name="gpt-4o",
            reason="Similar capabilities, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="claude-sonnet-4-20250514",
            reason="Strong alternative, different provider",
            is_primary=False,
            cost_factor=1.0,
            latency_factor=0.9,
            quality_factor=1.0,
        ),
    ],
    "mistral-small-latest": [
        FallbackRecommendation(
            model_name="gpt-4o-mini",
            reason="Similar speed and cost, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="claude-3-5-haiku-20241022",
            reason="Similar capabilities, alternative provider",
            is_primary=False,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
    ],
}


def recommend_fallback(
    main_model: str,
    *,
    include_secondary: bool = True,
) -> list[FallbackRecommendation]:
    """Get fallback model recommendations for a main model.

    Args:
        main_model: Name of the main model
        include_secondary: Whether to include secondary (non-primary) recommendations

    Returns:
        List of recommended fallback models, ordered by recommendation priority

    Example:
        >>> recommendations = recommend_fallback("gpt-4o")
        >>> for rec in recommendations:
        ...     print(f"{rec.model_name}: {rec.reason}")
        claude-sonnet-4-20250514: Similar performance, alternative provider ...
        gemini-2.5-flash: Lower cost, fast alternative
    """
    recommendations = FALLBACK_RECOMMENDATIONS.get(main_model, [])

    if not include_secondary:
        recommendations = [rec for rec in recommendations if rec.is_primary]

    return recommendations


def get_primary_recommendation(main_model: str) -> FallbackRecommendation | None:
    """Get the primary (top) fallback recommendation for a main model.

    Args:
        main_model: Name of the main model

    Returns:
        Primary recommendation, or None if no recommendations exist

    Example:
        >>> rec = get_primary_recommendation("gpt-4o")
        >>> print(rec.model_name if rec else "No recommendation")
        claude-sonnet-4-20250514
    """
    recommendations = recommend_fallback(main_model, include_secondary=False)
    return recommendations[0] if recommendations else None


def generate_quantified_reason(recommendation: FallbackRecommendation) -> str:
    """Generate a quantified reason string with cost/latency/quality metrics.

    Args:
        recommendation: Fallback recommendation with factors

    Returns:
        Human-readable reason with quantified metrics

    Example:
        >>> rec = FallbackRecommendation("gpt-3.5-turbo", reason="Lower cost", cost_factor=0.1)
        >>> print(generate_quantified_reason(rec))
        Lower cost (90% cost reduction, 20% latency improvement, 30% quality trade-off)
    """
    metrics = []

    # Cost comparison
    if recommendation.cost_factor < 1.0:
        reduction = round((1.0 - recommendation.cost_factor) * 100)
        metrics.append(f"{reduction}% cost reduction")
    elif recommendation.cost_factor > 1.0:
        increase = round((recommendation.cost_factor - 1.0) * 100)
        metrics.append(f"{increase}% cost increase")

    # Latency comparison
    if recommendation.latency_factor < 1.0:
        improvement = round((1.0 - recommendation.latency_factor) * 100)
        metrics.append(f"{improvement}% latency improvement")
    elif recommendation.latency_factor > 1.0:
        degradation = round((recommendation.latency_factor - 1.0) * 100)
        metrics.append(f"{degradation}% latency increase")

    # Quality comparison
    if recommendation.quality_factor < 1.0:
        tradeoff = round((1.0 - recommendation.quality_factor) * 100)
        metrics.append(f"{tradeoff}% quality trade-off")
    elif recommendation.quality_factor > 1.0:
        improvement = round((recommendation.quality_factor - 1.0) * 100)
        metrics.append(f"{improvement}% quality improvement")

    if metrics:
        return f"{recommendation.reason} ({', '.join(metrics)})"
    return recommendation.reason
