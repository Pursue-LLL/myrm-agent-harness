"""Unit tests for wait_strategies module."""

import pytest

from myrm_agent_harness.toolkits.browser._dom_stable_js import generate_dom_stable_js
from myrm_agent_harness.toolkits.browser.wait_strategies import (
    WaitMetrics,
    WaitStrategy,
)


def test_wait_strategy_enum():
    """Test WaitStrategy enum values."""
    assert WaitStrategy.NETWORKIDLE == "networkidle"
    assert WaitStrategy.DOM_STABLE == "dom_stable"
    assert WaitStrategy.HYBRID == "hybrid"


def test_wait_metrics_creation():
    """Test WaitMetrics dataclass creation."""
    metrics = WaitMetrics(
        strategy=WaitStrategy.HYBRID,
        reason="both",
        elapsed_ms=1200,
        network_idle_ms=1000,
        dom_stable_ms=800,
        dom_mutation_count=15,
        dom_reset_count=3,
    )

    assert metrics.strategy == WaitStrategy.HYBRID
    assert metrics.reason == "both"
    assert metrics.elapsed_ms == 1200
    assert metrics.network_idle_ms == 1000
    assert metrics.dom_stable_ms == 800
    assert metrics.dom_mutation_count == 15
    assert metrics.dom_reset_count == 3


def test_wait_metrics_to_log_dict():
    """Test WaitMetrics.to_log_dict() conversion."""
    metrics = WaitMetrics(
        strategy=WaitStrategy.DOM_STABLE,
        reason="quiet",
        elapsed_ms=500,
        dom_stable_ms=500,
        dom_mutation_count=5,
        dom_reset_count=1,
    )

    log_dict = metrics.to_log_dict()

    assert log_dict["strategy"] == WaitStrategy.DOM_STABLE
    assert log_dict["reason"] == "quiet"
    assert log_dict["elapsed_ms"] == 500
    assert log_dict["dom_stable_ms"] == 500
    assert log_dict["dom_mutation_count"] == 5
    assert log_dict["dom_reset_count"] == 1
    assert log_dict["network_idle_ms"] is None


def test_generate_dom_stable_js_contains_key_elements():
    """Test that generated JS contains key monitoring elements."""
    js_code = generate_dom_stable_js(max_ms=5000, quiet_ms=500)

    assert "MutationObserver" in js_code
    assert "IGNORED_ATTRS" in js_code
    assert "style" in js_code  # 过滤动画属性
    assert "class" in js_code
    assert "aria-busy" in js_code
    assert "childList: true" in js_code
    assert "subtree: true" in js_code
    assert "attributes: true" in js_code
    assert "performance.now()" in js_code
    assert "mutation_count" in js_code
    assert "reset_count" in js_code


def test_generate_dom_stable_js_parameters():
    """Test that JS code uses correct timeout parameters."""
    js_code = generate_dom_stable_js(max_ms=3000, quiet_ms=800)

    assert "3000" in js_code  # max_ms
    assert "800" in js_code  # quiet_ms


def test_wait_metrics_frozen():
    """Test that WaitMetrics is immutable (frozen dataclass)."""
    metrics = WaitMetrics(
        strategy=WaitStrategy.HYBRID,
        reason="both",
        elapsed_ms=1000,
    )

    with pytest.raises(AttributeError):
        metrics.elapsed_ms = 2000  # type: ignore


def test_wait_metrics_defaults():
    """Test WaitMetrics default values."""
    metrics = WaitMetrics(
        strategy=WaitStrategy.NETWORKIDLE,
        reason="network_only",
        elapsed_ms=1500,
    )

    assert metrics.network_idle_ms is None
    assert metrics.dom_stable_ms is None
    assert metrics.dom_mutation_count == 0
    assert metrics.dom_reset_count == 0


def test_wait_metrics_all_reasons():
    """Test all possible reason values."""
    reasons = ["quiet", "capped", "network_only", "dom_only", "both", "first_completed"]

    for reason in reasons:
        metrics = WaitMetrics(
            strategy=WaitStrategy.HYBRID,
            reason=reason,  # type: ignore
            elapsed_ms=1000,
        )
        assert metrics.reason == reason
