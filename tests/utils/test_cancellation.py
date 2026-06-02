"""Tests for myrm_agent_harness.utils.runtime.cancellation."""

import asyncio

import pytest

from myrm_agent_harness.utils.runtime.cancellation import (
    CancellationMonitor,
    CancellationToken,
    create_cancellation_context,
)
from myrm_agent_harness.utils.runtime.cancellation_metrics import CancellationMetrics


def test_token_initial_state() -> None:
    t = CancellationToken()
    assert t.is_cancelled is False


def test_token_cancel_and_reason() -> None:
    t = CancellationToken()
    t.cancel("gone")
    assert t.is_cancelled is True
    assert t.cancel_reason == "gone"


def test_token_request_id_default_and_custom() -> None:
    assert CancellationToken().request_id == "unknown"
    assert CancellationToken("rid-1").request_id == "rid-1"


def test_check_cancelled_raises_when_cancelled() -> None:
    t = CancellationToken()
    t.check_cancelled()
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        t.check_cancelled()


def test_repeat_cancel_idempotent() -> None:
    t = CancellationToken()
    t.cancel("a")
    t.cancel("b")
    assert t.cancel_reason == "a"


@pytest.mark.asyncio
async def test_monitor_start_stop() -> None:
    t = CancellationToken()

    async def never_disconnect() -> bool:
        return False

    mon = CancellationMonitor(t, never_disconnect, check_interval=0.02)
    await mon.start()
    await asyncio.sleep(0.03)
    await mon.stop()
    assert t.is_cancelled is False


@pytest.mark.asyncio
async def test_monitor_loop_disconnect_cancels_token() -> None:
    t = CancellationToken()

    async def disconnected() -> bool:
        return True

    mon = CancellationMonitor(t, disconnected, check_interval=0.01)
    await mon._monitor_loop()
    assert t.is_cancelled is True
    assert t.cancel_reason == "client_disconnected"


def test_create_cancellation_context() -> None:
    token, factory = create_cancellation_context("msg-9")
    assert token.request_id == "msg-9"

    async def chk() -> bool:
        return False

    m = factory(chk)
    assert m._token is token


# ============== CancellationMetrics Tests ==============


def test_cancellation_metrics_initial_state() -> None:
    """Test CancellationMetrics initial state."""
    metrics = CancellationMetrics()
    assert metrics.check_count == 0
    assert metrics.disconnect_detected_count == 0
    assert metrics.check_total_ms == 0.0
    assert metrics.max_check_ms == 0.0
    assert metrics.cancel_triggered_count == 0
    assert metrics.cancel_completed_count == 0
    assert metrics.active_monitors == 0


def test_cancellation_metrics_properties() -> None:
    """Test CancellationMetrics calculated properties."""
    metrics = CancellationMetrics()

    # Empty metrics
    assert metrics.disconnect_detection_rate == 0.0
    assert metrics.check_avg_ms == 0.0
    assert metrics.cancel_completion_rate == 0.0

    # After some checks
    metrics.check_count = 10
    metrics.disconnect_detected_count = 2
    metrics.check_total_ms = 50.0

    assert metrics.disconnect_detection_rate == 0.2  # 2/10
    assert metrics.check_avg_ms == 5.0  # 50/10

    # After cancellations
    metrics.cancel_triggered_count = 3
    metrics.cancel_completed_count = 2

    assert metrics.cancel_completion_rate == pytest.approx(0.666666, rel=0.01)  # 2/3


def test_cancellation_metrics_to_dict() -> None:
    """Test CancellationMetrics.to_dict() export."""
    metrics = CancellationMetrics()
    metrics.check_count = 5
    metrics.disconnect_detected_count = 1
    metrics.check_total_ms = 25.0
    metrics.max_check_ms = 8.0

    exported = metrics.to_dict()

    assert exported["check_count"] == 5
    assert exported["disconnect_detected_count"] == 1
    assert exported["disconnect_detection_rate"] == 0.2
    assert exported["check_avg_ms"] == 5.0
    assert exported["check_total_ms"] == 25.0
    assert exported["max_check_ms"] == 8.0


@pytest.mark.asyncio
async def test_monitor_metrics_collection() -> None:
    """Test CancellationMonitor collects metrics correctly."""
    t = CancellationToken()

    async def never_disconnect() -> bool:
        await asyncio.sleep(0.001)  # Simulate check duration
        return False

    mon = CancellationMonitor(t, never_disconnect, check_interval=0.01)

    # Initially no metrics
    assert mon.metrics.check_count == 0
    assert mon.metrics.active_monitors == 0

    await mon.start()
    assert mon.metrics.active_monitors == 1

    await asyncio.sleep(0.03)  # Allow ~2-3 checks
    await mon.stop()

    # Should have recorded checks
    assert mon.metrics.check_count >= 2
    assert mon.metrics.check_total_ms > 0
    assert mon.metrics.max_check_ms > 0
    assert mon.metrics.disconnect_detected_count == 0  # Never disconnected
    assert mon.metrics.active_monitors == 0


@pytest.mark.asyncio
async def test_monitor_disconnect_metrics() -> None:
    """Test CancellationMonitor metrics when disconnect detected."""
    t = CancellationToken()

    async def disconnected() -> bool:
        return True

    mon = CancellationMonitor(t, disconnected, check_interval=0.01)
    await mon.start()
    await asyncio.sleep(0.02)  # Allow disconnect detection
    await mon.stop()

    # Should have detected disconnect
    assert mon.metrics.check_count >= 1
    assert mon.metrics.disconnect_detected_count == 1
    assert mon.metrics.cancel_triggered_count == 1
    assert mon.metrics.cancel_completed_count == 1


@pytest.mark.asyncio
async def test_monitor_immediate_mode() -> None:
    """Test CancellationMonitor immediate_mode uses 0.1s interval."""
    t = CancellationToken()

    async def never_disconnect() -> bool:
        return False

    # Normal mode (0.5s default)
    mon_normal = CancellationMonitor(t, never_disconnect)
    assert mon_normal._check_interval == 0.5

    # Immediate mode (0.1s)
    mon_immediate = CancellationMonitor(t, never_disconnect, immediate_mode=True)
    assert mon_immediate._check_interval == 0.1

    # Custom interval without immediate_mode
    mon_custom = CancellationMonitor(t, never_disconnect, check_interval=2.0)
    assert mon_custom._check_interval == 2.0

    # immediate_mode overrides custom interval
    mon_override = CancellationMonitor(t, never_disconnect, check_interval=2.0, immediate_mode=True)
    assert mon_override._check_interval == 0.1
