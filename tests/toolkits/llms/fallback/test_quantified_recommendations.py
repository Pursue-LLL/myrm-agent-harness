"""Unit tests for quantified recommendation reasons."""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.fallback.recommendations import (
    FallbackRecommendation,
    generate_quantified_reason,
)


def test_quantified_reason_cost_reduction() -> None:
    """Test quantified reason with cost reduction."""
    rec = FallbackRecommendation(
        model_name="gpt-3.5-turbo",
        reason="Lower cost alternative",
        cost_factor=0.1,
        latency_factor=1.0,
        quality_factor=1.0,
    )

    result = generate_quantified_reason(rec)

    assert "90% cost reduction" in result
    assert "Lower cost alternative" in result


def test_quantified_reason_multiple_metrics() -> None:
    """Test quantified reason with multiple factor changes."""
    rec = FallbackRecommendation(
        model_name="gpt-3.5-turbo",
        reason="Lower cost",
        cost_factor=0.1,
        latency_factor=0.8,
        quality_factor=0.7,
    )

    result = generate_quantified_reason(rec)

    assert "90% cost reduction" in result
    assert "20% latency improvement" in result
    assert "30% quality trade-off" in result


def test_quantified_reason_no_changes() -> None:
    """Test quantified reason when all factors are 1.0."""
    rec = FallbackRecommendation(
        model_name="claude-3-opus-20240229",
        reason="Alternative provider",
        cost_factor=1.0,
        latency_factor=1.0,
        quality_factor=1.0,
    )

    result = generate_quantified_reason(rec)

    # Should return original reason when no metrics change
    assert result == "Alternative provider"


def test_quantified_reason_cost_increase() -> None:
    """Test quantified reason with cost increase."""
    rec = FallbackRecommendation(
        model_name="gpt-4",
        reason="Higher quality",
        cost_factor=5.0,
        latency_factor=1.0,
        quality_factor=1.2,
    )

    result = generate_quantified_reason(rec)

    assert "400% cost increase" in result
    assert "20% quality improvement" in result


def test_quantified_reason_latency_degradation() -> None:
    """Test quantified reason with latency degradation."""
    rec = FallbackRecommendation(
        model_name="claude-3-opus-20240229",
        reason="Higher quality",
        cost_factor=1.0,
        latency_factor=1.3,
        quality_factor=1.1,
    )

    result = generate_quantified_reason(rec)

    assert "30% latency increase" in result
    assert "10% quality improvement" in result
