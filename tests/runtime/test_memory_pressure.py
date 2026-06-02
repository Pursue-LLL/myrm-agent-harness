"""Tests for memory_pressure: global memory pressure monitor."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.runtime.memory_pressure import (
    MemoryPressureMonitor,
    PressureConfig,
    PressureEvent,
    PressureLevel,
    PressureSubscriber,
    _read_cgroup_memory_percent,
    get_memory_pressure_monitor,
    init_memory_pressure_monitor,
)


class TestPressureLevel:
    def test_ordering(self):
        assert PressureLevel.NORMAL < PressureLevel.WARNING
        assert PressureLevel.WARNING < PressureLevel.CRITICAL
        assert PressureLevel.CRITICAL < PressureLevel.EMERGENCY

    def test_int_values(self):
        assert int(PressureLevel.NORMAL) == 0
        assert int(PressureLevel.EMERGENCY) == 3


class TestPressureConfig:
    def test_defaults(self):
        config = PressureConfig()
        assert config.warning_threshold == 80.0
        assert config.critical_threshold == 90.0
        assert config.emergency_threshold == 95.0
        assert config.check_interval_seconds == 5.0
        assert config.escalation_count == 2
        assert config.de_escalation_count == 3

    def test_custom_thresholds(self):
        config = PressureConfig(warning_threshold=70.0, critical_threshold=85.0, emergency_threshold=95.0)
        assert config.warning_threshold == 70.0

    def test_threshold_out_of_range(self):
        with pytest.raises(ValueError, match="warning_threshold"):
            PressureConfig(warning_threshold=49.0)
        with pytest.raises(ValueError, match="emergency_threshold"):
            PressureConfig(emergency_threshold=99.5)

    def test_thresholds_not_strictly_increasing(self):
        with pytest.raises(ValueError, match="strictly increasing"):
            PressureConfig(warning_threshold=90.0, critical_threshold=90.0)

    def test_invalid_interval(self):
        with pytest.raises(ValueError, match="check_interval_seconds"):
            PressureConfig(check_interval_seconds=0)

    def test_invalid_escalation_count(self):
        with pytest.raises(ValueError, match="escalation_count"):
            PressureConfig(escalation_count=0)

    def test_invalid_de_escalation_count(self):
        with pytest.raises(ValueError, match="de_escalation_count"):
            PressureConfig(de_escalation_count=0)

    def test_invalid_subscriber_timeout(self):
        with pytest.raises(ValueError, match="subscriber_timeout_seconds"):
            PressureConfig(subscriber_timeout_seconds=0)
        with pytest.raises(ValueError, match="subscriber_timeout_seconds"):
            PressureConfig(subscriber_timeout_seconds=-1.0)


class TestPressureEvent:
    def test_escalated(self):
        event = PressureEvent(
            level=PressureLevel.WARNING,
            previous_level=PressureLevel.NORMAL,
            memory_percent=82.0,
            timestamp=1.0,
        )
        assert event.escalated is True
        assert event.de_escalated is False

    def test_de_escalated(self):
        event = PressureEvent(
            level=PressureLevel.NORMAL,
            previous_level=PressureLevel.WARNING,
            memory_percent=75.0,
            timestamp=1.0,
        )
        assert event.escalated is False
        assert event.de_escalated is True

    def test_frozen(self):
        event = PressureEvent(
            level=PressureLevel.NORMAL,
            previous_level=PressureLevel.NORMAL,
            memory_percent=50.0,
            timestamp=1.0,
        )
        with pytest.raises(AttributeError):
            event.level = PressureLevel.WARNING  # type: ignore[misc]


class TestCgroupMemoryReading:
    def test_cgroup_not_available(self):
        with patch("myrm_agent_harness.runtime.memory_pressure._CGROUP_MEMORY_CURRENT") as mock_current:
            mock_current.read_text.side_effect = FileNotFoundError
            assert _read_cgroup_memory_percent() is None

    def test_cgroup_max_is_max_string(self):
        with (
            patch("myrm_agent_harness.runtime.memory_pressure._CGROUP_MEMORY_CURRENT") as mock_current,
            patch("myrm_agent_harness.runtime.memory_pressure._CGROUP_MEMORY_MAX") as mock_max,
        ):
            mock_current.read_text.return_value = "1000000"
            mock_max.read_text.return_value = "max"
            assert _read_cgroup_memory_percent() is None


class TestClassifyLevel:
    @pytest.fixture()
    def monitor(self):
        return MemoryPressureMonitor(PressureConfig())

    def test_normal(self, monitor: MemoryPressureMonitor):
        assert monitor._classify_level(50.0) == PressureLevel.NORMAL

    def test_warning(self, monitor: MemoryPressureMonitor):
        assert monitor._classify_level(80.0) == PressureLevel.WARNING
        assert monitor._classify_level(85.0) == PressureLevel.WARNING

    def test_critical(self, monitor: MemoryPressureMonitor):
        assert monitor._classify_level(90.0) == PressureLevel.CRITICAL
        assert monitor._classify_level(94.0) == PressureLevel.CRITICAL

    def test_emergency(self, monitor: MemoryPressureMonitor):
        assert monitor._classify_level(95.0) == PressureLevel.EMERGENCY
        assert monitor._classify_level(99.0) == PressureLevel.EMERGENCY

    def test_boundary_just_below(self, monitor: MemoryPressureMonitor):
        assert monitor._classify_level(79.9) == PressureLevel.NORMAL
        assert monitor._classify_level(89.9) == PressureLevel.WARNING
        assert monitor._classify_level(94.9) == PressureLevel.CRITICAL


class TestHysteresis:
    @pytest.fixture()
    def monitor(self):
        return MemoryPressureMonitor(PressureConfig(escalation_count=2, de_escalation_count=3))

    def test_escalation_requires_consecutive_samples(self, monitor: MemoryPressureMonitor):
        assert monitor._apply_hysteresis(PressureLevel.WARNING) == PressureLevel.NORMAL
        assert monitor._apply_hysteresis(PressureLevel.WARNING) == PressureLevel.WARNING

    def test_single_sample_no_escalation(self, monitor: MemoryPressureMonitor):
        result = monitor._apply_hysteresis(PressureLevel.WARNING)
        assert result == PressureLevel.NORMAL

    def test_de_escalation_requires_more_samples(self, monitor: MemoryPressureMonitor):
        monitor._level = PressureLevel.WARNING
        assert monitor._apply_hysteresis(PressureLevel.NORMAL) == PressureLevel.WARNING
        assert monitor._apply_hysteresis(PressureLevel.NORMAL) == PressureLevel.WARNING
        assert monitor._apply_hysteresis(PressureLevel.NORMAL) == PressureLevel.NORMAL

    def test_interrupted_escalation_resets(self, monitor: MemoryPressureMonitor):
        monitor._apply_hysteresis(PressureLevel.WARNING)
        monitor._apply_hysteresis(PressureLevel.NORMAL)
        result = monitor._apply_hysteresis(PressureLevel.WARNING)
        assert result == PressureLevel.NORMAL

    def test_same_level_resets_counters(self, monitor: MemoryPressureMonitor):
        monitor._apply_hysteresis(PressureLevel.WARNING)
        monitor._apply_hysteresis(PressureLevel.NORMAL)
        assert monitor._consecutive_at_target == 0
        assert monitor._consecutive_below == 0


class TestSubscriberNotification:
    @pytest.fixture()
    def monitor(self):
        return MemoryPressureMonitor(PressureConfig(subscriber_timeout_seconds=1.0))

    @pytest.mark.asyncio()
    async def test_subscriber_receives_event(self, monitor: MemoryPressureMonitor):
        received_events: list[PressureEvent] = []

        class TestSubscriber:
            async def on_pressure_change(self, event: PressureEvent) -> None:
                received_events.append(event)

        subscriber = TestSubscriber()
        monitor.subscribe(subscriber)

        event = PressureEvent(
            level=PressureLevel.WARNING,
            previous_level=PressureLevel.NORMAL,
            memory_percent=82.0,
            timestamp=1.0,
        )
        await monitor._notify_subscribers(event)

        assert len(received_events) == 1
        assert received_events[0].level == PressureLevel.WARNING

    @pytest.mark.asyncio()
    async def test_subscriber_exception_isolation(self, monitor: MemoryPressureMonitor):
        events_received: list[PressureLevel] = []

        class FailingSubscriber:
            async def on_pressure_change(self, event: PressureEvent) -> None:
                raise RuntimeError("subscriber failed")

        class GoodSubscriber:
            async def on_pressure_change(self, event: PressureEvent) -> None:
                events_received.append(event.level)

        monitor.subscribe(FailingSubscriber())
        monitor.subscribe(GoodSubscriber())

        event = PressureEvent(
            level=PressureLevel.CRITICAL,
            previous_level=PressureLevel.WARNING,
            memory_percent=91.0,
            timestamp=1.0,
        )
        await monitor._notify_subscribers(event)

        assert events_received == [PressureLevel.CRITICAL]

    @pytest.mark.asyncio()
    async def test_subscriber_timeout(self, monitor: MemoryPressureMonitor):
        class SlowSubscriber:
            async def on_pressure_change(self, event: PressureEvent) -> None:
                await asyncio.sleep(10.0)

        monitor.subscribe(SlowSubscriber())
        event = PressureEvent(
            level=PressureLevel.WARNING,
            previous_level=PressureLevel.NORMAL,
            memory_percent=82.0,
            timestamp=1.0,
        )
        await monitor._notify_subscribers(event)

    def test_subscribe_unsubscribe(self, monitor: MemoryPressureMonitor):
        subscriber = AsyncMock(spec=PressureSubscriber)
        monitor.subscribe(subscriber)
        assert subscriber in monitor._subscribers
        monitor.unsubscribe(subscriber)
        assert subscriber not in monitor._subscribers

    def test_unsubscribe_nonexistent(self, monitor: MemoryPressureMonitor):
        subscriber = AsyncMock(spec=PressureSubscriber)
        monitor.unsubscribe(subscriber)

    def test_duplicate_subscribe(self, monitor: MemoryPressureMonitor):
        subscriber = AsyncMock(spec=PressureSubscriber)
        monitor.subscribe(subscriber)
        monitor.subscribe(subscriber)
        assert monitor._subscribers.count(subscriber) == 1

    @pytest.mark.asyncio()
    async def test_subscriber_self_unsubscribe_during_notification(self, monitor: MemoryPressureMonitor):
        received: list[PressureLevel] = []

        class SelfRemovingSubscriber:
            async def on_pressure_change(self, event: PressureEvent) -> None:
                monitor.unsubscribe(self)
                received.append(event.level)

        class StableSubscriber:
            async def on_pressure_change(self, event: PressureEvent) -> None:
                received.append(event.level)

        monitor.subscribe(SelfRemovingSubscriber())
        monitor.subscribe(StableSubscriber())

        event = PressureEvent(
            level=PressureLevel.WARNING,
            previous_level=PressureLevel.NORMAL,
            memory_percent=82.0,
            timestamp=1.0,
        )
        await monitor._notify_subscribers(event)
        assert received == [PressureLevel.WARNING, PressureLevel.WARNING]
        assert len(monitor._subscribers) == 1


class TestMonitorProperties:
    def test_initial_state(self):
        monitor = MemoryPressureMonitor()
        assert monitor.current_level == PressureLevel.NORMAL
        assert monitor.current_memory_percent == 0.0
        assert monitor.is_under_pressure() is False

    def test_under_pressure(self):
        monitor = MemoryPressureMonitor()
        monitor._level = PressureLevel.WARNING
        assert monitor.is_under_pressure() is True

    def test_memory_source_detection(self):
        with patch("myrm_agent_harness.runtime.memory_pressure._CGROUP_MEMORY_CURRENT") as mock_current:
            with patch("myrm_agent_harness.runtime.memory_pressure._CGROUP_MEMORY_MAX") as mock_max:
                mock_current.exists.return_value = False
                mock_max.exists.return_value = False
                monitor = MemoryPressureMonitor()
                assert monitor._use_cgroup is False


class TestMonitorLifecycle:
    @pytest.mark.asyncio()
    async def test_start_initializes_memory_reading(self):
        monitor = MemoryPressureMonitor(PressureConfig(check_interval_seconds=0.1))
        assert monitor.current_memory_percent == 0.0
        with patch.object(monitor, "_read_memory_percent", return_value=75.0):
            await monitor.start()
        assert monitor.current_memory_percent == 75.0
        assert monitor.current_level == PressureLevel.NORMAL
        await monitor.stop()

    @pytest.mark.asyncio()
    async def test_start_stop(self):
        monitor = MemoryPressureMonitor(PressureConfig(check_interval_seconds=0.1))
        await monitor.start()
        assert monitor._monitor_task is not None
        await monitor.stop()
        assert monitor._monitor_task is None

    @pytest.mark.asyncio()
    async def test_double_start(self):
        monitor = MemoryPressureMonitor(PressureConfig(check_interval_seconds=0.1))
        await monitor.start()
        task = monitor._monitor_task
        await monitor.start()
        assert monitor._monitor_task is task
        await monitor.stop()

    @pytest.mark.asyncio()
    async def test_stop_without_start(self):
        monitor = MemoryPressureMonitor()
        await monitor.stop()


class TestEmergencyGC:
    @pytest.mark.asyncio()
    async def test_gc_runs_on_emergency(self):
        with patch("myrm_agent_harness.runtime.memory_pressure.gc.collect", return_value=42) as mock_gc:
            monitor = MemoryPressureMonitor()
            await monitor._emergency_gc()
            mock_gc.assert_called_once()


class TestModuleSingleton:
    def test_init_and_get(self):
        import myrm_agent_harness.runtime.memory_pressure as mp

        mp._monitor = None
        monitor = init_memory_pressure_monitor()
        assert monitor is not None
        assert get_memory_pressure_monitor() is monitor
        mp._monitor = None

    def test_double_init_returns_same(self):
        import myrm_agent_harness.runtime.memory_pressure as mp

        mp._monitor = None
        m1 = init_memory_pressure_monitor()
        m2 = init_memory_pressure_monitor()
        assert m1 is m2
        mp._monitor = None

    def test_get_before_init(self):
        import myrm_agent_harness.runtime.memory_pressure as mp

        mp._monitor = None
        assert get_memory_pressure_monitor() is None


class TestReadMemoryPercent:
    def test_psutil_fallback(self):
        monitor = MemoryPressureMonitor()
        monitor._use_cgroup = False
        with patch("myrm_agent_harness.runtime.memory_pressure._read_psutil_memory_percent", return_value=65.0):
            assert monitor._read_memory_percent() == 65.0

    def test_cgroup_preferred(self):
        monitor = MemoryPressureMonitor()
        monitor._use_cgroup = True
        with patch(
            "myrm_agent_harness.runtime.memory_pressure._read_cgroup_memory_percent",
            return_value=72.5,
        ):
            assert monitor._read_memory_percent() == 72.5

    def test_cgroup_fallback_to_psutil(self):
        monitor = MemoryPressureMonitor()
        monitor._use_cgroup = True
        with (
            patch(
                "myrm_agent_harness.runtime.memory_pressure._read_cgroup_memory_percent",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.runtime.memory_pressure._read_psutil_memory_percent",
                return_value=55.0,
            ),
        ):
            assert monitor._read_memory_percent() == 55.0


class TestMonitorLoop:
    @pytest.mark.asyncio()
    async def test_level_change_triggers_notification(self):
        config = PressureConfig(
            check_interval_seconds=0.05,
            escalation_count=1,
            de_escalation_count=1,
        )
        monitor = MemoryPressureMonitor(config)
        received: list[PressureEvent] = []
        call_count = 0

        class Collector:
            async def on_pressure_change(self, event: PressureEvent) -> None:
                received.append(event)

        monitor.subscribe(Collector())

        def rising_memory() -> float:
            nonlocal call_count
            call_count += 1
            return 50.0 if call_count <= 1 else 85.0

        with patch.object(monitor, "_read_memory_percent", side_effect=rising_memory):
            await monitor.start()
            await asyncio.sleep(0.15)
            await monitor.stop()

        assert len(received) >= 1
        assert received[0].level == PressureLevel.WARNING
        assert received[0].previous_level == PressureLevel.NORMAL
        assert received[0].escalated is True
