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


# Pre-defined fallback recommendations
# Format: main_model -> [recommendations]
FALLBACK_RECOMMENDATIONS: dict[str, list[FallbackRecommendation]] = {
    # GPT-4 family
    "gpt-4": [
        FallbackRecommendation(
            model_name="claude-3-opus-20240229",
            reason="Similar capabilities, alternative provider reduces rate limit impact",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=0.95,
        ),
        FallbackRecommendation(
            model_name="gpt-3.5-turbo",
            reason="Same provider, significantly lower cost, good for fallback scenarios",
            is_primary=False,
            cost_factor=0.1,
            latency_factor=0.8,
            quality_factor=0.7,
        ),
    ],
    "gpt-4-turbo": [
        FallbackRecommendation(
            model_name="claude-3-opus-20240229",
            reason="Similar capabilities, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.1,
            quality_factor=0.95,
        ),
        FallbackRecommendation(
            model_name="gpt-4",
            reason="Same family, slightly lower cost",
            is_primary=False,
            cost_factor=0.9,
            latency_factor=1.0,
            quality_factor=0.98,
        ),
    ],
    "gpt-4o": [
        FallbackRecommendation(
            model_name="claude-3-5-sonnet-20241022",
            reason="Similar performance, alternative provider",
            is_primary=True,
            cost_factor=0.8,
            latency_factor=0.9,
            quality_factor=0.95,
        ),
        FallbackRecommendation(
            model_name="gpt-4-turbo",
            reason="Same family, proven reliability",
            is_primary=False,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=0.95,
        ),
    ],
    # GPT-3.5 family
    "gpt-3.5-turbo": [
        FallbackRecommendation(
            model_name="claude-3-haiku-20240307",
            reason="Similar speed and cost, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="gpt-4o-mini",
            reason="Better quality, similar cost",
            is_primary=False,
            cost_factor=1.2,
            latency_factor=1.0,
            quality_factor=1.3,
        ),
    ],
    # Claude 3 family
    "claude-3-opus-20240229": [
        FallbackRecommendation(
            model_name="gpt-4",
            reason="Similar capabilities, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=0.95,
        ),
        FallbackRecommendation(
            model_name="claude-3-sonnet-20240229",
            reason="Same family, lower cost and faster",
            is_primary=False,
            cost_factor=0.2,
            latency_factor=0.7,
            quality_factor=0.85,
        ),
    ],
    "claude-3-sonnet-20240229": [
        FallbackRecommendation(
            model_name="gpt-4",
            reason="Similar quality, alternative provider",
            is_primary=True,
            cost_factor=5.0,
            latency_factor=1.0,
            quality_factor=1.05,
        ),
        FallbackRecommendation(
            model_name="claude-3-haiku-20240307",
            reason="Same family, much lower cost",
            is_primary=False,
            cost_factor=0.2,
            latency_factor=0.8,
            quality_factor=0.8,
        ),
    ],
    "claude-3-5-sonnet-20241022": [
        FallbackRecommendation(
            model_name="gpt-4o",
            reason="Similar performance, alternative provider",
            is_primary=True,
            cost_factor=1.25,
            latency_factor=1.1,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="claude-3-sonnet-20240229",
            reason="Same family, proven stability",
            is_primary=False,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=0.95,
        ),
    ],
    "claude-3-haiku-20240307": [
        FallbackRecommendation(
            model_name="gpt-3.5-turbo",
            reason="Similar speed, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="gpt-4o-mini",
            reason="Similar cost, better quality",
            is_primary=False,
            cost_factor=1.2,
            latency_factor=1.0,
            quality_factor=1.2,
        ),
    ],
    # GPT-4o mini
    "gpt-4o-mini": [
        FallbackRecommendation(
            model_name="claude-3-haiku-20240307",
            reason="Similar cost and speed, alternative provider",
            is_primary=True,
            cost_factor=0.8,
            latency_factor=1.0,
            quality_factor=0.9,
        ),
        FallbackRecommendation(
            model_name="gpt-3.5-turbo",
            reason="Same provider, similar capabilities",
            is_primary=False,
            cost_factor=0.8,
            latency_factor=1.0,
            quality_factor=0.8,
        ),
    ],
    # Gemini family
    "gemini-1.5-pro": [
        FallbackRecommendation(
            model_name="gpt-4-turbo",
            reason="Similar capabilities, alternative provider for rate limit resilience",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=0.9,
            quality_factor=0.95,
        ),
        FallbackRecommendation(
            model_name="claude-3-opus-20240229",
            reason="Similar quality, alternative provider",
            is_primary=False,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=0.95,
        ),
    ],
    "gemini-1.5-flash": [
        FallbackRecommendation(
            model_name="claude-3-haiku-20240307",
            reason="Similar speed and cost, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="gpt-4o-mini",
            reason="Similar capabilities, alternative provider",
            is_primary=False,
            cost_factor=1.2,
            latency_factor=1.0,
            quality_factor=1.1,
        ),
    ],
    "gemini-2.0-flash-exp": [
        FallbackRecommendation(
            model_name="gpt-4o",
            reason="Similar speed, alternative provider with proven reliability",
            is_primary=True,
            cost_factor=1.5,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="claude-3-5-sonnet-20241022",
            reason="Similar quality, alternative provider",
            is_primary=False,
            cost_factor=1.2,
            latency_factor=0.9,
            quality_factor=0.98,
        ),
    ],
    # Mistral family
    "mistral-large": [
        FallbackRecommendation(
            model_name="gpt-4",
            reason="Similar capabilities, alternative provider for rate limit resilience",
            is_primary=True,
            cost_factor=1.25,
            latency_factor=0.9,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="claude-3-opus-20240229",
            reason="Similar quality, alternative provider",
            is_primary=False,
            cost_factor=1.25,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
    ],
    "mistral-medium": [
        FallbackRecommendation(
            model_name="gpt-4-turbo",
            reason="Slightly higher quality, alternative provider",
            is_primary=True,
            cost_factor=1.5,
            latency_factor=1.0,
            quality_factor=1.1,
        ),
        FallbackRecommendation(
            model_name="claude-3-sonnet-20240229",
            reason="Similar capabilities, alternative provider",
            is_primary=False,
            cost_factor=1.3,
            latency_factor=0.9,
            quality_factor=1.0,
        ),
    ],
    "mistral-small": [
        FallbackRecommendation(
            model_name="gpt-3.5-turbo",
            reason="Similar speed and cost, alternative provider",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=0.9,
        ),
        FallbackRecommendation(
            model_name="claude-3-haiku-20240307",
            reason="Similar capabilities, alternative provider",
            is_primary=False,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
    ],
    # Volcengine Ark Coding Plan
    "doubao-seed-2.0-code": [
        FallbackRecommendation(
            model_name="deepseek-v3.2",
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
            cost_factor=2.0,
            latency_factor=1.0,
            quality_factor=1.2,
        ),
    ],
    "deepseek-v3.2": [
        FallbackRecommendation(
            model_name="doubao-seed-2.0-code",
            reason="Alternative coding model in Ark plan",
            is_primary=True,
            cost_factor=1.0,
            latency_factor=1.0,
            quality_factor=1.0,
        ),
        FallbackRecommendation(
            model_name="claude-3-5-sonnet-20241022",
            reason="Top tier coding model",
            is_primary=False,
            cost_factor=2.0,
            latency_factor=1.0,
            quality_factor=1.2,
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
        >>> recommendations = recommend_fallback("gpt-4")
        >>> for rec in recommendations:
        ...     print(f"{rec.model_name}: {rec.reason}")
        claude-3-opus-20240229: Similar capabilities, alternative provider
        gpt-3.5-turbo: Same provider, lower cost
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
        >>> rec = get_primary_recommendation("gpt-4")
        >>> print(rec.model_name if rec else "No recommendation")
        claude-3-opus-20240229
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
