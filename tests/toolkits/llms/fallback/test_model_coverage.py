"""Unit tests for extended model coverage (Gemini, Mistral, etc.)."""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.fallback.recommendations import (
    get_primary_recommendation,
    recommend_fallback,
)


def test_gemini_pro_recommendations() -> None:
    """Test recommendations for gemini-1.5-pro."""
    recommendations = recommend_fallback("gemini-1.5-pro")

    assert len(recommendations) == 2
    assert recommendations[0].model_name == "gpt-4-turbo"
    assert recommendations[0].is_primary is True
    assert recommendations[1].model_name == "claude-3-opus-20240229"


def test_gemini_flash_recommendations() -> None:
    """Test recommendations for gemini-1.5-flash."""
    recommendations = recommend_fallback("gemini-1.5-flash")

    assert len(recommendations) == 2
    assert recommendations[0].model_name == "claude-3-haiku-20240307"
    assert recommendations[0].is_primary is True


def test_gemini_2_flash_recommendations() -> None:
    """Test recommendations for gemini-2.0-flash-exp."""
    recommendations = recommend_fallback("gemini-2.0-flash-exp")

    assert len(recommendations) == 2
    assert recommendations[0].model_name == "gpt-4o"
    assert recommendations[0].is_primary is True


def test_mistral_large_recommendations() -> None:
    """Test recommendations for mistral-large."""
    recommendations = recommend_fallback("mistral-large")

    assert len(recommendations) == 2
    assert recommendations[0].model_name == "gpt-4"
    assert recommendations[0].is_primary is True


def test_mistral_medium_recommendations() -> None:
    """Test recommendations for mistral-medium."""
    recommendations = recommend_fallback("mistral-medium")

    assert len(recommendations) == 2
    assert recommendations[0].model_name == "gpt-4-turbo"
    assert recommendations[0].is_primary is True


def test_mistral_small_recommendations() -> None:
    """Test recommendations for mistral-small."""
    recommendations = recommend_fallback("mistral-small")

    assert len(recommendations) == 2
    assert recommendations[0].model_name == "gpt-3.5-turbo"
    assert recommendations[0].is_primary is True


def test_gemini_primary_recommendation() -> None:
    """Test getting primary recommendation for Gemini models."""
    primary = get_primary_recommendation("gemini-1.5-pro")

    assert primary is not None
    assert primary.model_name == "gpt-4-turbo"
    assert primary.is_primary is True


def test_mistral_primary_recommendation() -> None:
    """Test getting primary recommendation for Mistral models."""
    primary = get_primary_recommendation("mistral-large")

    assert primary is not None
    assert primary.model_name == "gpt-4"
    assert primary.is_primary is True
