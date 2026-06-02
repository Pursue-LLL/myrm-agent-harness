"""Tests for HealthMonitor — backend health checking and crash recovery."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.acp.event_bus import EventBus
from myrm_agent_harness.toolkits.acp.health_monitor import HealthMetrics, HealthMonitor
from myrm_agent_harness.toolkits.acp.types import RuntimeEvent, RuntimeEventType


class _FakeBackend:
    """Minimal RuntimeBackend stub with controllable liveness."""

    def __init__(self, name: str = "test", alive: bool = True) -> None:
        self._name = name
        self._alive = alive
        self.close_called = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_alive(self) -> bool:
        return self._alive

    def set_alive(self, alive: bool) -> None:
        self._alive = alive

    async def close(self) -> None:
        self.close_called = True


class TestHealthMetrics:
    def test_initial_state(self) -> None:
        m = HealthMetrics()
        assert m.restart_count == 0
        assert m.last_crash_time is None
        assert m.last_check_time is None
        assert m.total_uptime_seconds == 0.0

    def test_record_start_and_crash(self) -> None:
        m = HealthMetrics()
        m.record_start()
        assert m._start_time is not None
        m.record_crash()
        assert m.restart_count == 1
        assert m.last_crash_time is not None
        assert m.total_uptime_seconds > 0.0
        assert m._start_time is None

    def test_record_crash_without_start(self) -> None:
        m = HealthMetrics()
        m.record_crash()
        assert m.restart_count == 1
        assert m.total_uptime_seconds == 0.0

    def test_to_dict(self) -> None:
        m = HealthMetrics()
        m.record_start()
        m.record_crash()
        d = m.to_dict()
        assert "restart_count" in d
        assert "last_crash_time" in d
        assert "total_uptime_seconds" in d
        assert d["restart_count"] == 1


class TestHealthMonitorRegistration:
    def test_register_and_unregister(self) -> None:
        monitor = HealthMonitor()
        backend = _FakeBackend("b1")
        monitor.register(backend)
        assert monitor.get_metrics("b1") is not None
        monitor.unregister("b1")
        assert monitor.get_metrics("b1") is None

    def test_get_all_metrics(self) -> None:
        monitor = HealthMonitor()
        monitor.register(_FakeBackend("a"))
        monitor.register(_FakeBackend("b"))
        all_m = monitor.get_all_metrics()
        assert "a" in all_m
        assert "b" in all_m

    def test_get_metrics_unknown(self) -> None:
        monitor = HealthMonitor()
        assert monitor.get_metrics("unknown") is None


class TestHealthMonitorCheckLoop:
    @pytest.mark.asyncio
    async def test_start_and_stop(self) -> None:
        monitor = HealthMonitor(check_interval=0.01)
        monitor.register(_FakeBackend("b1"))
        await monitor.start()
        assert monitor._task is not None
        await asyncio.sleep(0.05)
        await monitor.stop()
        assert monitor._task is None

    @pytest.mark.asyncio
    async def test_start_idempotent(self) -> None:
        monitor = HealthMonitor(check_interval=0.01)
        await monitor.start()
        task1 = monitor._task
        await monitor.start()
        assert monitor._task is task1
        await monitor.stop()

    @pytest.mark.asyncio
    async def test_alive_backend_records_start(self) -> None:
        monitor = HealthMonitor(check_interval=0.01)
        backend = _FakeBackend("b1", alive=True)
        monitor.register(backend)
        await monitor.start()
        await asyncio.sleep(0.05)
        await monitor.stop()
        metrics = monitor.get_metrics("b1")
        assert metrics is not None
        assert metrics.last_check_time is not None


class TestHealthMonitorCrashHandling:
    @pytest.mark.asyncio
    async def test_crash_triggers_close_and_event(self) -> None:
        bus = EventBus()
        events: list[RuntimeEvent] = []
        bus.subscribe(callback=lambda e: events.append(e))

        monitor = HealthMonitor(event_bus=bus, check_interval=0.01, max_restarts=5)
        backend = _FakeBackend("b1", alive=False)
        monitor.register(backend)

        _real_sleep = asyncio.sleep

        async def _fast_sleep(seconds: float) -> None:
            await _real_sleep(min(seconds, 0.01))

        with patch("myrm_agent_harness.toolkits.acp.health_monitor.asyncio.sleep", side_effect=_fast_sleep):
            await monitor.start()
            await _real_sleep(0.15)
            await monitor.stop()

        assert backend.close_called
        status_events = [e for e in events if e.type == RuntimeEventType.STATUS_UPDATE]
        assert len(status_events) >= 1
        assert "crashed" in str(status_events[0].data.get("status", ""))

    @pytest.mark.asyncio
    async def test_max_restarts_exceeded_emits_error(self) -> None:
        bus = EventBus()
        events: list[RuntimeEvent] = []
        bus.subscribe(callback=lambda e: events.append(e))

        monitor = HealthMonitor(event_bus=bus, check_interval=0.01, max_restarts=1)
        backend = _FakeBackend("b1", alive=False)
        monitor.register(backend)

        _real_sleep = asyncio.sleep

        async def _fast_sleep(seconds: float) -> None:
            await _real_sleep(min(seconds, 0.01))

        with patch("myrm_agent_harness.toolkits.acp.health_monitor.asyncio.sleep", side_effect=_fast_sleep):
            await monitor.start()
            await _real_sleep(0.2)
            await monitor.stop()

        error_events = [e for e in events if e.type == RuntimeEventType.ERROR]
        assert len(error_events) >= 1

    @pytest.mark.asyncio
    async def test_close_failure_does_not_crash_monitor(self) -> None:
        monitor = HealthMonitor(check_interval=0.01, max_restarts=5)
        backend = _FakeBackend("b1", alive=False)

        async def failing_close() -> None:
            raise OSError("close failed")

        backend.close = failing_close  # type: ignore[assignment]
        monitor.register(backend)

        _real_sleep = asyncio.sleep

        async def _fast_sleep(seconds: float) -> None:
            await _real_sleep(min(seconds, 0.01))

        with patch("myrm_agent_harness.toolkits.acp.health_monitor.asyncio.sleep", side_effect=_fast_sleep):
            await monitor.start()
            await _real_sleep(0.15)
            await monitor.stop()

    @pytest.mark.asyncio
    async def test_no_event_bus_still_works(self) -> None:
        monitor = HealthMonitor(event_bus=None, check_interval=0.01, max_restarts=5)
        backend = _FakeBackend("b1", alive=False)
        monitor.register(backend)

        _real_sleep = asyncio.sleep

        async def _fast_sleep(seconds: float) -> None:
            await _real_sleep(min(seconds, 0.01))

        with patch("myrm_agent_harness.toolkits.acp.health_monitor.asyncio.sleep", side_effect=_fast_sleep):
            await monitor.start()
            await _real_sleep(0.15)
            await monitor.stop()
        assert backend.close_called
