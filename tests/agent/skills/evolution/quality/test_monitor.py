"""Tests for ToolQualityMonitor."""

import time

from myrm_agent_harness.agent.skills.evolution.quality.monitor import (
    ToolHealthMetrics,
    ToolQualityMonitor,
)


def test_monitor_initialization():
    monitor = ToolQualityMonitor(window_size=10, max_tools=5)
    assert monitor._window_size == 10
    assert monitor._max_tools == 5
    assert monitor.get_stats() == {
        "total_tools": 0,
        "tools_with_calls": 0,
        "avg_success_rate": 0.0,
    }

def test_track_call_success_rate():
    monitor = ToolQualityMonitor(window_size=5)

    # 3 success, 1 failure = 0.75
    monitor.track_call("tool_a", success=True, duration_ms=100)
    monitor.track_call("tool_a", success=True, duration_ms=120)
    monitor.track_call("tool_a", success=False, duration_ms=500, error_type="4xx")
    monitor.track_call("tool_a", success=True, duration_ms=110)

    metrics = monitor._metrics["tool_a"]
    assert metrics.total_calls == 4
    assert metrics.success_count == 3
    assert metrics.success_rate == 0.75

    # Push out of window
    monitor.track_call("tool_a", success=False, duration_ms=500, error_type="5xx")
    monitor.track_call("tool_a", success=False, duration_ms=500, error_type="5xx")
    assert len(metrics.window_calls) == 5
    assert metrics.total_calls == 6

def test_latency_calculation():
    monitor = ToolQualityMonitor()

    # Track calls with different latencies
    latencies = [100, 150, 200, 250, 300, 350, 400, 450, 500, 1000]
    for lat in latencies:
        monitor.track_call("tool_lat", success=True, duration_ms=lat)

    metrics = monitor._metrics["tool_lat"]
    assert metrics.baseline_latency == 350.0  # P50 (index 5)
    assert metrics.p95_latency == 1000.0      # P95 (index 9)

def test_server_error_rate():
    monitor = ToolQualityMonitor()

    monitor.track_call("tool_err", success=False, duration_ms=100, error_type="5xx")
    monitor.track_call("tool_err", success=False, duration_ms=100, error_type="5xx")
    monitor.track_call("tool_err", success=False, duration_ms=100, error_type="4xx")
    monitor.track_call("tool_err", success=True, duration_ms=100)

    metrics = monitor._metrics["tool_err"]
    assert metrics.server_error_rate == 0.5  # 2 / 4

def test_lru_eviction():
    monitor = ToolQualityMonitor(max_tools=2)

    monitor.track_call("tool_1", True, 100)
    time.sleep(0.01)
    monitor.track_call("tool_2", True, 100)
    time.sleep(0.01)

    # LRU is tool_1, should be evicted
    monitor.track_call("tool_3", True, 100)

    assert "tool_1" not in monitor._metrics
    assert "tool_2" in monitor._metrics
    assert "tool_3" in monitor._metrics

def test_get_degraded_tools():
    monitor = ToolQualityMonitor()

    # tool_good: 10 successes
    for _ in range(10):
        monitor.track_call("tool_good", True, 100)

    # tool_bad_success: 10 failures
    for _ in range(10):
        monitor.track_call("tool_bad_success", False, 100, "4xx")

    # tool_bad_latency: sudden spike
    for _ in range(9):
        monitor.track_call("tool_bad_latency", True, 100)
    monitor.track_call("tool_bad_latency", True, 1000)  # P95 spike

    # tool_bad_server: 5xx errors
    for _ in range(5):
        monitor.track_call("tool_bad_server", True, 100)
    for _ in range(5):
        monitor.track_call("tool_bad_server", False, 100, "5xx")

    degraded = monitor.get_degraded_tools(min_calls=10)
    assert len(degraded) == 3

    degraded_dict = {d.tool_key: d for d in degraded}
    assert "tool_good" not in degraded_dict

    assert "success" in degraded_dict["tool_bad_success"].degradation_type
    assert "latency" in degraded_dict["tool_bad_latency"].degradation_type
    assert "server_error" in degraded_dict["tool_bad_server"].degradation_type

    # Test to_dict
    d = degraded_dict["tool_bad_success"].to_dict()
    assert d["tool_key"] == "tool_bad_success"

def test_get_recovered_tools():
    monitor = ToolQualityMonitor()

    # Track to make it bad initially
    for _ in range(10):
        monitor.track_call("tool_recover", False, 100)

    degraded = monitor.get_degraded_tools()
    assert len(degraded) == 1

    # Track more to make it recover
    for _ in range(30):
        monitor.track_call("tool_recover", True, 100)

    recovered = monitor.get_recovered_tools(["tool_recover"])
    assert "tool_recover" in recovered

def test_empty_metrics():
    monitor = ToolQualityMonitor()
    assert monitor.get_stats()["avg_success_rate"] == 0.0

    metrics = ToolHealthMetrics(tool_name="test", total_calls=0, success_count=0)
    assert metrics.success_rate == 1.0
    assert metrics.p95_latency == 0.0
    assert metrics.server_error_rate == 0.0
    assert metrics.baseline_latency == 0.0
