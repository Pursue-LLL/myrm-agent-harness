"""Tests for scenario validation and edge cases."""

import pytest

from myrm_agent_harness.toolkits.llms.fallback.scenario import (
    ModelMetrics,
    ScenarioType,
    select_by_scenario,
)


def test_model_metrics_validation_cost_negative():
    """ModelMetrics rejects negative cost."""
    with pytest.raises(ValueError, match="cost must be in"):
        ModelMetrics(name="test", priority=0, cost=-0.1, latency=0.5, quality=0.8)


def test_model_metrics_validation_cost_too_high():
    """ModelMetrics rejects cost > 1.0."""
    with pytest.raises(ValueError, match="cost must be in"):
        ModelMetrics(name="test", priority=0, cost=1.5, latency=0.5, quality=0.8)


def test_model_metrics_validation_latency_negative():
    """ModelMetrics rejects negative latency."""
    with pytest.raises(ValueError, match="latency must be in"):
        ModelMetrics(name="test", priority=0, cost=0.5, latency=-0.1, quality=0.8)


def test_model_metrics_validation_latency_too_high():
    """ModelMetrics rejects latency > 1.0."""
    with pytest.raises(ValueError, match="latency must be in"):
        ModelMetrics(name="test", priority=0, cost=0.5, latency=1.5, quality=0.8)


def test_model_metrics_validation_quality_negative():
    """ModelMetrics rejects negative quality."""
    with pytest.raises(ValueError, match="quality must be in"):
        ModelMetrics(name="test", priority=0, cost=0.5, latency=0.5, quality=-0.1)


def test_model_metrics_validation_quality_too_high():
    """ModelMetrics rejects quality > 1.0."""
    with pytest.raises(ValueError, match="quality must be in"):
        ModelMetrics(name="test", priority=0, cost=0.5, latency=0.5, quality=1.5)


def test_model_metrics_validation_edge_values():
    """ModelMetrics accepts edge values 0.0 and 1.0."""
    # Should not raise
    m1 = ModelMetrics(name="min", priority=0, cost=0.0, latency=0.0, quality=0.0)
    assert m1.cost == 0.0

    m2 = ModelMetrics(name="max", priority=0, cost=1.0, latency=1.0, quality=1.0)
    assert m2.cost == 1.0


def test_select_by_scenario_empty_candidates():
    """select_by_scenario raises error on empty candidate list."""
    with pytest.raises(ValueError, match="No candidates provided"):
        select_by_scenario([], ScenarioType.REALTIME)


def test_select_by_scenario_realtime_with_single_candidate():
    """select_by_scenario works with single candidate."""
    m = ModelMetrics(name="only", priority=0, cost=0.5, latency=0.3, quality=0.8)

    result = select_by_scenario([m], ScenarioType.REALTIME)

    assert result.name == "only"


def test_select_by_scenario_quality_first():
    """select_by_scenario prioritizes quality in QUALITY_FIRST mode."""
    candidates = [
        ModelMetrics(name="low-quality", priority=0, cost=0.1, latency=0.2, quality=0.5),
        ModelMetrics(name="high-quality", priority=0, cost=0.9, latency=0.8, quality=0.95),
        ModelMetrics(name="mid-quality", priority=0, cost=0.5, latency=0.5, quality=0.7),
    ]

    result = select_by_scenario(candidates, ScenarioType.QUALITY_FIRST)

    # Should select highest quality
    assert result.name == "high-quality"
    assert result.quality == 0.95
