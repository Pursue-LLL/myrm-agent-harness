"""Tests for smart fallback recommendations."""

from myrm_agent_harness.toolkits.llms.fallback import (
    get_primary_recommendation,
    recommend_fallback,
)


def test_recommend_fallback_gpt4():
    """Test recommendations for GPT-4."""
    recommendations = recommend_fallback("gpt-4")

    assert len(recommendations) >= 1
    # Primary recommendation should be Claude Opus
    assert recommendations[0].model_name == "claude-3-opus-20240229"
    assert recommendations[0].is_primary
    assert "alternative provider" in recommendations[0].reason.lower()


def test_recommend_fallback_include_secondary():
    """Test including secondary recommendations."""
    recommendations = recommend_fallback("gpt-4", include_secondary=True)

    # Should have both primary and secondary
    assert len(recommendations) >= 2
    primary_count = sum(1 for rec in recommendations if rec.is_primary)
    secondary_count = sum(1 for rec in recommendations if not rec.is_primary)
    assert primary_count >= 1
    assert secondary_count >= 1


def test_recommend_fallback_primary_only():
    """Test getting only primary recommendations."""
    recommendations = recommend_fallback("gpt-4", include_secondary=False)

    # Should have only primary
    assert len(recommendations) >= 1
    assert all(rec.is_primary for rec in recommendations)


def test_recommend_fallback_unknown_model():
    """Test recommendations for unknown model."""
    recommendations = recommend_fallback("unknown-model-xyz")

    # Should return empty list for unknown models
    assert len(recommendations) == 0


def test_get_primary_recommendation_gpt4():
    """Test getting primary recommendation for GPT-4."""
    rec = get_primary_recommendation("gpt-4")

    assert rec is not None
    assert rec.model_name == "claude-3-opus-20240229"
    assert rec.is_primary


def test_get_primary_recommendation_claude_opus():
    """Test getting primary recommendation for Claude Opus."""
    rec = get_primary_recommendation("claude-3-opus-20240229")

    assert rec is not None
    assert rec.model_name == "gpt-4"
    assert rec.is_primary


def test_get_primary_recommendation_unknown_model():
    """Test getting primary recommendation for unknown model."""
    rec = get_primary_recommendation("unknown-model-xyz")

    assert rec is None


def test_recommendation_cost_factors():
    """Test that recommendations include cost factors."""
    recommendations = recommend_fallback("gpt-4")

    assert len(recommendations) >= 1
    for rec in recommendations:
        assert rec.cost_factor > 0
        assert rec.latency_factor > 0
        assert rec.quality_factor > 0


def test_claude_haiku_recommendations():
    """Test recommendations for Claude Haiku (fast, cheap model)."""
    recommendations = recommend_fallback("claude-3-haiku-20240307")

    assert len(recommendations) >= 1
    # Should recommend similar speed/cost model
    primary = recommendations[0]
    assert primary.model_name in ["gpt-3.5-turbo", "gpt-4o-mini"]


def test_gpt_35_turbo_recommendations():
    """Test recommendations for GPT-3.5 Turbo."""
    recommendations = recommend_fallback("gpt-3.5-turbo")

    assert len(recommendations) >= 1
    # Should recommend similar capabilities
    primary = recommendations[0]
    assert "alternative provider" in primary.reason.lower() or "quality" in primary.reason.lower()


def test_gpt_4o_recommendations():
    """Test recommendations for GPT-4o (latest model)."""
    recommendations = recommend_fallback("gpt-4o")

    assert len(recommendations) >= 1
    primary = recommendations[0]
    # Should recommend Claude 3.5 Sonnet or similar
    assert primary.model_name in ["claude-3-5-sonnet-20241022", "gpt-4-turbo", "claude-3-opus-20240229"]


def test_recommendation_reasons_are_descriptive():
    """Test that all recommendations have descriptive reasons."""
    all_models = [
        "gpt-4",
        "gpt-4-turbo",
        "gpt-4o",
        "gpt-3.5-turbo",
        "gpt-4o-mini",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-5-sonnet-20241022",
        "claude-3-haiku-20240307",
    ]

    for model in all_models:
        recommendations = recommend_fallback(model)
        for rec in recommendations:
            # Reason should be non-empty and meaningful
            assert len(rec.reason) > 10
            assert rec.reason[0].isupper()  # Should start with capital
