"""Tests for myrm_agent_harness.runtime.resource_monitor."""

from __future__ import annotations

import asyncio
import tracemalloc
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import myrm_agent_harness.runtime.resource_monitor as resource_monitor
from myrm_agent_harness.runtime.resource_monitor import (
    ResourceMetrics,
    ResourceMonitor,
    get_resource_monitor,
)


def test_resource_metrics_attributes() -> None:
    m = ResourceMetrics(
        cpu_percent=10.5,
        memory_mb=128.0,
        vms_mb=256.0,
        python_gc_objects=1000,
        native_mb_estimate=64.0,
        disk_mb=1024.0,
        network_sent_mb=1.0,
        network_recv_mb=2.0,
        timestamp=123456.0,
    )
    assert m.cpu_percent == 10.5
    assert m.memory_mb == 128.0
    assert m.vms_mb == 256.0
    assert m.python_gc_objects == 1000
    assert m.native_mb_estimate == 64.0
    assert m.disk_mb == 1024.0
    assert m.network_sent_mb == 1.0
    assert m.network_recv_mb == 2.0
    assert m.timestamp == 123456.0


def _mock_psutil_module() -> MagicMock:
    mock_psutil = MagicMock()
    proc = MagicMock()
    proc.cpu_percent.return_value = 7.5
    mem = MagicMock()
    mem.rss = 50 * 1024 * 1024
    mem.vms = 100 * 1024 * 1024
    proc.memory_info.return_value = mem
    mock_psutil.Process.return_value = proc
    net0 = MagicMock(bytes_sent=1000, bytes_recv=2000)
    mock_psutil.net_io_counters.return_value = net0
    disk = MagicMock(used=10 * 1024 * 1024)
    mock_psutil.disk_usage.return_value = disk
    return mock_psutil


@pytest.mark.asyncio
async def test_collect_metrics_uses_psutil() -> None:
    mock_psutil = _mock_psutil_module()
    with patch.object(resource_monitor, "psutil", mock_psutil):
        mon = ResourceMonitor()
        metrics = await mon.collect_metrics()
    assert isinstance(metrics, ResourceMetrics)
    assert metrics.cpu_percent == 7.5
    mock_psutil.Process.assert_called_once()
    mock_psutil.disk_usage.assert_called_once_with("/")


@pytest.mark.asyncio
async def test_start_and_stop() -> None:
    mock_psutil = _mock_psutil_module()
    with patch.object(resource_monitor, "psutil", mock_psutil):
        mon = ResourceMonitor(report_interval=0.02)
        mon.collect_metrics = AsyncMock(  # type: ignore[method-assign]
            return_value=ResourceMetrics(1.0, 1.0, 1.0, 100, 0.5, 1.0, 0.0, 0.0, 1.0)
        )
        await mon.start()
        assert mon._monitor_task is not None
        await asyncio.sleep(0.06)
        await mon.stop()
        assert mon._monitor_task.done()


@pytest.mark.asyncio
async def test_monitor_loop_handles_collect_exception() -> None:
    mock_psutil = _mock_psutil_module()
    with patch.object(resource_monitor, "psutil", mock_psutil):
        mon = ResourceMonitor(report_interval=0.01)
        mon.collect_metrics = AsyncMock(side_effect=RuntimeError("collect failed"))  # type: ignore[method-assign]
        await mon.start()
        await asyncio.sleep(0.05)
        await mon.stop()


@pytest.mark.asyncio
async def test_monitor_listeners() -> None:
    mock_psutil = _mock_psutil_module()
    with patch.object(resource_monitor, "psutil", mock_psutil):
        mon = ResourceMonitor(report_interval=0.01)
        mon.collect_metrics = AsyncMock(  # type: ignore[method-assign]
            return_value=ResourceMetrics(1.0, 1.0, 1.0, 100, 0.5, 1.0, 0.0, 0.0, 1.0)
        )
        sync_listener = MagicMock()
        async_listener = AsyncMock()

        mon.add_listener(sync_listener)
        mon.add_listener(async_listener)

        await mon.start()
        await asyncio.sleep(0.05)
        await mon.stop()

        assert sync_listener.call_count >= 1
        assert async_listener.call_count >= 1


def test_start_profiling() -> None:
    mock_psutil = _mock_psutil_module()
    with patch.object(resource_monitor, "psutil", mock_psutil):
        mon = ResourceMonitor()
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        assert mon.start_profiling(frames=5) is True
        assert mon._is_profiling is True
        assert mon.start_profiling() is False
        tracemalloc.stop()
        mon._is_profiling = False


def test_stop_profiling_when_not_profiling() -> None:
    mock_psutil = _mock_psutil_module()
    with patch.object(resource_monitor, "psutil", mock_psutil):
        mon = ResourceMonitor()
        result = mon.stop_profiling()
        assert result == []


def test_stop_profiling_returns_allocations() -> None:
    mock_psutil = _mock_psutil_module()
    with patch.object(resource_monitor, "psutil", mock_psutil):
        mon = ResourceMonitor()
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        mon.start_profiling(frames=5)
        _dummy = [i for i in range(10000)]
        results = mon.stop_profiling()
        assert isinstance(results, list)
        assert mon._is_profiling is False
        if results:
            assert "file" in results[0]
            assert "line" in results[0]
            assert "size_kb" in results[0]
            assert "count" in results[0]


@pytest.mark.asyncio
async def test_collect_metrics_exception_reraises() -> None:
    mock_psutil = _mock_psutil_module()
    mock_psutil.Process.return_value.cpu_percent.side_effect = OSError("no cpu")
    with patch.object(resource_monitor, "psutil", mock_psutil):
        mon = ResourceMonitor()
        with pytest.raises(OSError, match="no cpu"):
            await mon.collect_metrics()


@pytest.mark.asyncio
async def test_stop_cleans_up_profiling() -> None:
    mock_psutil = _mock_psutil_module()
    with patch.object(resource_monitor, "psutil", mock_psutil):
        mon = ResourceMonitor()
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        mon.start_profiling()
        assert mon._is_profiling is True
        await mon.stop()
        assert mon._is_profiling is False


def test_get_resource_monitor_singleton() -> None:
    resource_monitor._monitor_instance = None
    mock_psutil = _mock_psutil_module()
    with patch.object(resource_monitor, "psutil", mock_psutil):
        m1 = get_resource_monitor()
        m2 = get_resource_monitor()
        assert m1 is m2
    resource_monitor._monitor_instance = None


def test_get_history() -> None:
    mock_psutil = _mock_psutil_module()
    with patch.object(resource_monitor, "psutil", mock_psutil):
        mon = ResourceMonitor()
        assert mon.get_history() == []
        metrics = ResourceMetrics(1.0, 1.0, 1.0, 100, 0.5, 1.0, 0.0, 0.0, 1.0)
        mon._history.append(metrics)
        history = mon.get_history()
        assert len(history) == 1
        assert history[0]["cpu_percent"] == 1.0


def test_resource_metrics_to_dict() -> None:
    m = ResourceMetrics(
        cpu_percent=10.5,
        memory_mb=128.0,
        vms_mb=256.0,
        python_gc_objects=1000,
        native_mb_estimate=64.0,
        disk_mb=1024.0,
        network_sent_mb=1.0,
        network_recv_mb=2.0,
        timestamp=123456.0,
    )
    d = m.to_dict()
    assert d["cpu_percent"] == 10.5
    assert d["memory_mb"] == 128.0
    assert d["timestamp"] == 123456.0


@pytest.mark.asyncio
async def test_monitor_loop_publishes_event() -> None:
    mock_psutil = _mock_psutil_module()
    mock_bus = MagicMock()
    with (
        patch.object(resource_monitor, "psutil", mock_psutil),
        patch(
            "myrm_agent_harness.runtime.resource_monitor.get_event_bus",
            return_value=mock_bus,
            create=True,
        ),
    ):
        mon = ResourceMonitor(report_interval=0.01)
        mon.collect_metrics = AsyncMock(  # type: ignore[method-assign]
            return_value=ResourceMetrics(1.0, 1.0, 1.0, 100, 0.5, 1.0, 0.0, 0.0, 1.0)
        )
        await mon.start()
        await asyncio.sleep(0.05)
        await mon.stop()


@pytest.mark.asyncio
async def test_info_logging_baseline_and_shutdown(caplog: pytest.LogCaptureFixture) -> None:
    """Verify [MEMORY] baseline logged on start and shutdown logged on stop."""
    mock_psutil = _mock_psutil_module()
    with patch.object(resource_monitor, "psutil", mock_psutil):
        mon = ResourceMonitor(report_interval=0.01)
        mon.collect_metrics = AsyncMock(  # type: ignore[method-assign]
            return_value=ResourceMetrics(1.0, 50.0, 100.0, 100, 0.5, 1.0, 0.0, 0.0, 1.0)
        )
        import logging
        with caplog.at_level(logging.INFO, logger="myrm_agent_harness.runtime.resource_monitor"):
            await mon.start()
            await asyncio.sleep(0.03)
            await mon.stop()

    memory_logs = [r for r in caplog.records if "[MEMORY]" in r.message]
    assert len(memory_logs) >= 2
    assert any("baseline" in r.message for r in memory_logs)
    assert any("shutdown" in r.message for r in memory_logs)


@pytest.mark.asyncio
async def test_info_logging_periodic(caplog: pytest.LogCaptureFixture) -> None:
    """Verify periodic [MEMORY] INFO emitted every _info_every ticks."""
    mock_psutil = _mock_psutil_module()
    with patch.object(resource_monitor, "psutil", mock_psutil):
        mon = ResourceMonitor(report_interval=0.01)
        mon._info_every = 3  # emit INFO every 3 ticks for fast test
        mon.collect_metrics = AsyncMock(  # type: ignore[method-assign]
            return_value=ResourceMetrics(1.0, 50.0, 100.0, 100, 0.5, 1.0, 0.0, 0.0, 1.0)
        )
        import logging
        with caplog.at_level(logging.INFO, logger="myrm_agent_harness.runtime.resource_monitor"):
            await mon.start()
            await asyncio.sleep(0.08)
            await mon.stop()

    periodic_logs = [
        r for r in caplog.records
        if "[MEMORY]" in r.message and "baseline" not in r.message and "shutdown" not in r.message
    ]
    assert len(periodic_logs) >= 1
