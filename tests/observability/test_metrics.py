"""Test observability metrics utilities.

Verifies create_counter/gauge/histogram工具函数功能正常。
"""

import pytest
from prometheus_client import Counter, Gauge, Histogram

from myrm_agent_harness.observability.metrics import (
    create_counter,
    create_gauge,
    create_histogram,
)


def test_create_counter_adds_myrm_prefix():
    """Test create_counter adds myrm_ prefix"""
    counter = create_counter("p1_5_test_total", "Test", ())
    assert isinstance(counter, Counter)
    assert "myrm" in counter._name.lower()


def test_create_counter_requires_total_suffix():
    """Test create_counter requires _total suffix"""
    with pytest.raises(ValueError, match="must end with '_total'"):
        create_counter("invalid_name", "Test")


def test_create_gauge_adds_myrm_prefix():
    """Test create_gauge adds myrm_ prefix"""
    gauge = create_gauge("p1_5_gauge", "Test", ())
    assert isinstance(gauge, Gauge)
    assert "myrm" in gauge._name.lower()


def test_create_histogram_adds_myrm_prefix():
    """Test create_histogram adds myrm_ prefix"""
    hist = create_histogram("p1_5_duration_seconds", "Test", ())
    assert isinstance(hist, Histogram)
    assert "myrm" in hist._name.lower()


def test_create_histogram_warns_without_suffix():
    """Test create_histogram warns without valid unit suffix"""
    with pytest.warns(UserWarning, match="Histogram name should end with"):
        create_histogram("p1_5_duration", "Test")


def test_create_histogram_no_warn_with_total_suffix():
    """Test create_histogram accepts _total suffix without warning"""
    hist = create_histogram("p1_5_token_usage_total", "Test", ())
    assert isinstance(hist, Histogram)


def test_create_histogram_no_warn_with_ratio_suffix():
    """Test create_histogram accepts _ratio suffix without warning"""
    hist = create_histogram("p1_5_hit_ratio", "Test", ())
    assert isinstance(hist, Histogram)
