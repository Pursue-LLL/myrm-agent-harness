"""Unit tests for extended model coverage (Gemini, Mistral, DeepSeek, etc.)."""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.fallback.recommendations import (
    get_primary_recommendation,
    recommend_fallback,
)


def test_gemini_pro_recommendations() -> None:
    """Test recommendations for gemini-2.5-pro."""
    recommendations = recommend_fallback("gemini-2.5-pro")

    assert len(recommendations) == 2
    assert recommendations[0].model_name == "claude-sonnet-4-20250514"
    assert recommendations[0].is_primary is True
    assert recommendations[1].model_name == "gpt-4o"


def test_gemini_flash_recommendations() -> None:
    """Test recommendations for gemini-2.5-flash."""
    recommendations = recommend_fallback("gemini-2.5-flash")

    assert len(recommendations) == 2
    assert recommendations[0].model_name == "gpt-4o-mini"
    assert recommendations[0].is_primary is True


def test_mistral_large_recommendations() -> None:
    """Test recommendations for mistral-large-latest."""
    recommendations = recommend_fallback("mistral-large-latest")

    assert len(recommendations) == 2
    assert recommendations[0].model_name == "gpt-4o"
    assert recommendations[0].is_primary is True


def test_mistral_small_recommendations() -> None:
    """Test recommendations for mistral-small-latest."""
    recommendations = recommend_fallback("mistral-small-latest")

    assert len(recommendations) == 2
    assert recommendations[0].model_name == "gpt-4o-mini"
    assert recommendations[0].is_primary is True


def test_deepseek_chat_recommendations() -> None:
    """Test recommendations for deepseek-chat."""
    recommendations = recommend_fallback("deepseek-chat")

    assert len(recommendations) == 2
    assert recommendations[0].model_name == "gpt-4o"
    assert recommendations[0].is_primary is True


def test_deepseek_reasoner_recommendations() -> None:
    """Test recommendations for deepseek-reasoner."""
    recommendations = recommend_fallback("deepseek-reasoner")

    assert len(recommendations) == 2
    assert recommendations[0].model_name == "o4-mini"
    assert recommendations[0].is_primary is True


def test_gemini_primary_recommendation() -> None:
    """Test getting primary recommendation for Gemini models."""
    primary = get_primary_recommendation("gemini-2.5-pro")

    assert primary is not None
    assert primary.model_name == "claude-sonnet-4-20250514"
    assert primary.is_primary is True


def test_mistral_primary_recommendation() -> None:
    """Test getting primary recommendation for Mistral models."""
    primary = get_primary_recommendation("mistral-large-latest")

    assert primary is not None
    assert primary.model_name == "gpt-4o"
    assert primary.is_primary is True
