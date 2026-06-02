"""Tests for Observability"""

import asyncio
import logging
import time

import pytest

from myrm_agent_harness.agent.skills.optimization.observability import (
    MetricsCollector,
    MetricType,
    Timer,
    structured_log,
)


@pytest.fixture
def metrics():
    """Create MetricsCollector instance"""
    collector = MetricsCollector()
    collector.reset_metrics()  # Clear any existing metrics
    return collector


def test_counter_increment(metrics):
    """Test counter increment"""
    metrics.inc_counter("test_counter", value=1.0)
    metrics.inc_counter("test_counter", value=2.0)

    all_metrics = metrics.get_metrics()

    assert "test_counter" in all_metrics
    assert all_metrics["test_counter"]["__default__"] == 3.0


def test_counter_with_labels(metrics):
    """Test counter with labels"""
    metrics.inc_counter("test_counter", value=1.0, labels={"env": "prod"})
    metrics.inc_counter("test_counter", value=2.0, labels={"env": "dev"})
    metrics.inc_counter("test_counter", value=3.0, labels={"env": "prod"})

    all_metrics = metrics.get_metrics()

    assert all_metrics["test_counter"]["env=dev"] == 2.0
    assert all_metrics["test_counter"]["env=prod"] == 4.0


def test_gauge_set_and_inc(metrics):
    """Test gauge set and increment"""
    metrics.set_gauge("test_gauge", 10.0)
    assert metrics.get_metrics()["test_gauge"]["__default__"] == 10.0

    metrics.inc_gauge("test_gauge", 5.0)
    assert metrics.get_metrics()["test_gauge"]["__default__"] == 15.0

    metrics.dec_gauge("test_gauge", 3.0)
    assert metrics.get_metrics()["test_gauge"]["__default__"] == 12.0


def test_histogram_observe(metrics):
    """Test histogram observe"""
    metrics.observe_histogram("test_histogram", 1.0)
    metrics.observe_histogram("test_histogram", 2.0)
    metrics.observe_histogram("test_histogram", 3.0)

    all_metrics = metrics.get_metrics()

    assert all_metrics["test_histogram"]["__default__"]["count"] == 3
    assert all_metrics["test_histogram"]["__default__"]["sum"] == 6.0
    assert all_metrics["test_histogram"]["__default__"]["min"] == 1.0
    assert all_metrics["test_histogram"]["__default__"]["max"] == 3.0
    assert all_metrics["test_histogram"]["__default__"]["avg"] == 2.0


def test_register_metric(metrics):
    """Test registering custom metric"""
    metrics.register_metric("custom_metric", MetricType.COUNTER, "Custom test metric", "count")

    metrics.inc_counter("custom_metric", 10.0)

    all_metrics = metrics.get_metrics()
    assert all_metrics["custom_metric"]["__default__"] == 10.0


def test_reset_metrics(metrics):
    """Test resetting metrics"""
    metrics.inc_counter("test_counter", 5.0)
    metrics.set_gauge("test_gauge", 10.0)

    metrics.reset_metrics()

    all_metrics = metrics.get_metrics()
    assert "test_counter" not in all_metrics
    assert "test_gauge" not in all_metrics


def test_builtin_metrics_registered(metrics):
    """Test that builtin metrics are registered"""
    # These should be pre-registered
    metrics.inc_counter("skill_optimizations_total")
    metrics.inc_counter("skill_optimizations_success_total")
    metrics.inc_counter("skill_optimizations_failed_total")
    metrics.observe_histogram("skill_optimizations_duration_seconds", 1.5)
    metrics.set_gauge("skill_optimizations_active", 3)

    all_metrics = metrics.get_metrics()

    assert "skill_optimizations_total" in all_metrics
    assert "skill_optimizations_success_total" in all_metrics
    assert "skill_optimizations_failed_total" in all_metrics
    assert "skill_optimizations_duration_seconds" in all_metrics
    assert "skill_optimizations_active" in all_metrics


def test_timer_context_manager(metrics):
    """Test Timer context manager"""
    with Timer("test_duration", labels={"operation": "test"}, collector=metrics):
        time.sleep(0.1)

    all_metrics = metrics.get_metrics()

    assert "test_duration" in all_metrics
    assert "operation=test" in all_metrics["test_duration"]

    duration = all_metrics["test_duration"]["operation=test"]["avg"]
    assert duration >= 0.1  # At least 100ms


@pytest.mark.asyncio
async def test_timer_async_context_manager(metrics):
    """Test Timer async context manager"""
    async with Timer("test_async_duration", labels={"operation": "async_test"}, collector=metrics):
        await asyncio.sleep(0.1)

    all_metrics = metrics.get_metrics()

    assert "test_async_duration" in all_metrics
    assert "operation=async_test" in all_metrics["test_async_duration"]

    duration = all_metrics["test_async_duration"]["operation=async_test"]["avg"]
    assert duration >= 0.1


def test_structured_log(caplog):
    """Test structured logging"""
    logger = logging.getLogger("test_logger")

    with caplog.at_level(logging.INFO):
        structured_log(logger, "INFO", "Test message", skill_id="test-skill", quality_score=0.75)

    # Check that log was recorded
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.message == "Test message"
    assert hasattr(record, "structured_data")
    assert record.structured_data["skill_id"] == "test-skill"
    assert record.structured_data["quality_score"] == 0.75
    assert "timestamp" in record.structured_data


def test_metrics_thread_safety(metrics):
    """Test metrics thread safety with concurrent operations"""
    import threading

    def increment_counter():
        for _ in range(100):
            metrics.inc_counter("thread_test", 1.0)

    threads = [threading.Thread(target=increment_counter) for _ in range(10)]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    all_metrics = metrics.get_metrics()
    assert all_metrics["thread_test"]["__default__"] == 1000.0


def test_labels_key_generation(metrics):
    """Test labels key generation for consistent ordering"""
    # Same labels, different order
    metrics.inc_counter("test", 1.0, labels={"a": "1", "b": "2"})
    metrics.inc_counter("test", 2.0, labels={"b": "2", "a": "1"})

    all_metrics = metrics.get_metrics()

    # Should be merged into same key
    assert all_metrics["test"]["a=1,b=2"] == 3.0
