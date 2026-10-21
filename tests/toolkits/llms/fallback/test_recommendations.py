"""Tests for smart fallback recommendations."""

from myrm_agent_harness.toolkits.llms.fallback import (
    get_primary_recommendation,
    recommend_fallback,
)


def test_recommend_fallback_gpt4o():
    """Test recommendations for GPT-4o."""
    recommendations = recommend_fallback("gpt-4o")

    assert len(recommendations) >= 1
    assert recommendations[0].model_name == "claude-sonnet-4-20250514"
    assert recommendations[0].is_primary
    assert "alternative provider" in recommendations[0].reason.lower()


def test_recommend_fallback_include_secondary():
    """Test including secondary recommendations."""
    recommendations = recommend_fallback("gpt-4o", include_secondary=True)

    assert len(recommendations) >= 2
    primary_count = sum(1 for rec in recommendations if rec.is_primary)
    secondary_count = sum(1 for rec in recommendations if not rec.is_primary)
    assert primary_count >= 1
    assert secondary_count >= 1


def test_recommend_fallback_primary_only():
    """Test getting only primary recommendations."""
    recommendations = recommend_fallback("gpt-4o", include_secondary=False)

    assert len(recommendations) >= 1
    assert all(rec.is_primary for rec in recommendations)


def test_recommend_fallback_unknown_model():
    """Test recommendations for unknown model."""
    recommendations = recommend_fallback("unknown-model-xyz")

    assert len(recommendations) == 0


def test_get_primary_recommendation_gpt4o():
    """Test getting primary recommendation for GPT-4o."""
    rec = get_primary_recommendation("gpt-4o")

    assert rec is not None
    assert rec.model_name == "claude-sonnet-4-20250514"
    assert rec.is_primary


def test_get_primary_recommendation_claude_opus4():
    """Test getting primary recommendation for Claude Opus 4."""
    rec = get_primary_recommendation("claude-opus-4-20250514")

    assert rec is not None
    assert rec.model_name == "o3"
    assert rec.is_primary


def test_get_primary_recommendation_unknown_model():
    """Test getting primary recommendation for unknown model."""
    rec = get_primary_recommendation("unknown-model-xyz")

    assert rec is None


def test_recommendation_cost_factors():
    """Test that recommendations include cost factors."""
    recommendations = recommend_fallback("gpt-4o")

    assert len(recommendations) >= 1
    for rec in recommendations:
        assert rec.cost_factor > 0
        assert rec.latency_factor > 0
        assert rec.quality_factor > 0


def test_claude_haiku_recommendations():
    """Test recommendations for Claude 3.5 Haiku (fast, cheap model)."""
    recommendations = recommend_fallback("claude-3-5-haiku-20241022")

    assert len(recommendations) >= 1
    primary = recommendations[0]
    assert primary.model_name in ["gpt-4o-mini", "gemini-2.5-flash"]


def test_deepseek_chat_recommendations():
    """Test recommendations for DeepSeek Chat."""
    recommendations = recommend_fallback("deepseek-chat")

    assert len(recommendations) >= 1
    primary = recommendations[0]
    assert "alternative" in primary.reason.lower() or "quality" in primary.reason.lower()


def test_gpt_4o_recommendations():
    """Test recommendations for GPT-4o (current flagship)."""
    recommendations = recommend_fallback("gpt-4o")

    assert len(recommendations) >= 1
    primary = recommendations[0]
    assert primary.model_name in ["claude-sonnet-4-20250514", "gemini-2.5-pro"]


def test_recommendation_reasons_are_descriptive():
    """Test that all recommendations have descriptive reasons."""
    all_models = [
        "gpt-4o",
        "gpt-4.1",
        "gpt-4o-mini",
        "gpt-4.1-mini",
        "o3",
        "o4-mini",
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-3-5-haiku-20241022",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "deepseek-chat",
        "deepseek-reasoner",
    ]

    for model in all_models:
        recommendations = recommend_fallback(model)
        for rec in recommendations:
            assert len(rec.reason) > 10
            assert rec.reason[0].isupper()
