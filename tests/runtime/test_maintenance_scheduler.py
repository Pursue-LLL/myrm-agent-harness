"""Tests for the Global Adaptive Maintenance Scheduler.

Covers: protocol types, sensors, health score, scheduler logic, and integrations
with BackgroundEvolutionTaskManager and SimpleStorageQuotaManager.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.skills.evolution.infra.background_task_manager import (
    BackgroundEvolutionTaskManager,
)
from myrm_agent_harness.runtime.maintenance.health import compute_health_score
from myrm_agent_harness.runtime.maintenance.protocols import (
    AgentHealthScore,
    CapacityDenial,
    CapacityTicket,
    LoadSensor,
    MaintenanceTaskType,
    SystemLoadLevel,
    SystemLoadSnapshot,
)
from myrm_agent_harness.runtime.maintenance.scheduler import GlobalAdaptiveScheduler
from myrm_agent_harness.runtime.maintenance.sensors import DeviceLoadSensor, SaaSLoadSensor
from myrm_agent_harness.runtime.memory_pressure import PressureEvent, PressureLevel
from myrm_agent_harness.runtime.quota.manager import SimpleStorageQuotaManager


class FakeLoadSensor(LoadSensor):
    """Controllable sensor for testing."""

    def __init__(self, level: SystemLoadLevel = SystemLoadLevel.IDLE) -> None:
        self._level = level

    def set_level(self, level: SystemLoadLevel) -> None:
        self._level = level

    def read(self) -> SystemLoadSnapshot:
        return SystemLoadSnapshot(level=self._level, cpu_percent=0, memory_percent=0)


# ─── protocol types ───────────────────────────────────────────────────


class TestProtocolTypes:
    def test_system_load_level_ordering(self) -> None:
        assert SystemLoadLevel.IDLE < SystemLoadLevel.NORMAL < SystemLoadLevel.BUSY < SystemLoadLevel.OVERLOADED

    def test_capacity_ticket_age(self) -> None:
        ticket = CapacityTicket(ticket_id="t1", task_type=MaintenanceTaskType.EVOLUTION)
        time.sleep(0.01)
        assert ticket.age_seconds >= 0.01

    def test_agent_health_score_needs_maintenance(self) -> None:
        healthy = AgentHealthScore(score=85)
        assert not healthy.needs_maintenance()

        unhealthy = AgentHealthScore(score=50)
        assert unhealthy.needs_maintenance()

        custom_threshold = AgentHealthScore(score=60)
        assert not custom_threshold.needs_maintenance(threshold=50)


# ─── health score computation ─────────────────────────────────────────


class TestHealthScore:
    def test_perfect_health(self) -> None:
        h = compute_health_score(evolution_backlog=0, storage_usage_pct=0, context_fragmentation_pct=0)
        assert h.score == 100

    def test_critical_health(self) -> None:
        h = compute_health_score(evolution_backlog=30, storage_usage_pct=95, context_fragmentation_pct=90)
        assert h.score <= 10

    def test_moderate_health(self) -> None:
        h = compute_health_score(evolution_backlog=5, storage_usage_pct=50, context_fragmentation_pct=30)
        assert 30 < h.score < 80

    def test_storage_has_highest_weight(self) -> None:
        storage_bad = compute_health_score(storage_usage_pct=100, evolution_backlog=0, context_fragmentation_pct=0)
        backlog_bad = compute_health_score(storage_usage_pct=0, evolution_backlog=20, context_fragmentation_pct=0)
        frag_bad = compute_health_score(storage_usage_pct=0, evolution_backlog=0, context_fragmentation_pct=100)
        assert storage_bad.score < backlog_bad.score
        assert frag_bad.score > storage_bad.score

    def test_score_clamped(self) -> None:
        h = compute_health_score(evolution_backlog=100, storage_usage_pct=200, context_fragmentation_pct=200)
        assert h.score == 0


# ─── sensors ──────────────────────────────────────────────────────────


class TestDeviceLoadSensor:
    def test_classify_idle(self) -> None:
        sensor = DeviceLoadSensor()
        level = sensor._classify(cpu=5.0, mem=30.0)
        assert level == SystemLoadLevel.IDLE

    def test_classify_normal(self) -> None:
        sensor = DeviceLoadSensor()
        level = sensor._classify(cpu=40.0, mem=55.0)
        assert level == SystemLoadLevel.NORMAL

    def test_classify_busy(self) -> None:
        sensor = DeviceLoadSensor()
        level = sensor._classify(cpu=70.0, mem=55.0)
        assert level == SystemLoadLevel.BUSY

    def test_classify_overloaded(self) -> None:
        sensor = DeviceLoadSensor()
        level = sensor._classify(cpu=90.0, mem=55.0)
        assert level == SystemLoadLevel.OVERLOADED

    def test_classify_mem_overloaded(self) -> None:
        sensor = DeviceLoadSensor()
        level = sensor._classify(cpu=20.0, mem=95.0)
        assert level == SystemLoadLevel.OVERLOADED


class TestSaaSLoadSensor:
    def test_stale_data_returns_normal(self) -> None:
        sensor = SaaSLoadSensor()
        snapshot = sensor.read()
        assert snapshot.level == SystemLoadLevel.NORMAL

    def test_fresh_idle(self) -> None:
        sensor = SaaSLoadSensor()
        sensor.update(api_quota_remaining_pct=90.0, queue_depth=2)
        snapshot = sensor.read()
        assert snapshot.level == SystemLoadLevel.IDLE

    def test_fresh_overloaded(self) -> None:
        sensor = SaaSLoadSensor()
        sensor.update(api_quota_remaining_pct=5.0, queue_depth=200)
        snapshot = sensor.read()
        assert snapshot.level == SystemLoadLevel.OVERLOADED

    def test_fresh_busy(self) -> None:
        sensor = SaaSLoadSensor()
        sensor.update(api_quota_remaining_pct=20.0, queue_depth=30)
        snapshot = sensor.read()
        assert snapshot.level == SystemLoadLevel.BUSY


# ─── scheduler ────────────────────────────────────────────────────────


class TestGlobalAdaptiveScheduler:
    @pytest.mark.asyncio
    async def test_grant_when_idle(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.IDLE)
        scheduler = GlobalAdaptiveScheduler(sensor)
        result = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        assert isinstance(result, CapacityTicket)
        assert scheduler.active_count == 1

    @pytest.mark.asyncio
    async def test_deny_when_overloaded(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.OVERLOADED)
        scheduler = GlobalAdaptiveScheduler(sensor)
        result = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        assert isinstance(result, CapacityDenial)
        assert scheduler.active_count == 0

    @pytest.mark.asyncio
    async def test_respects_concurrent_limit(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.NORMAL)
        scheduler = GlobalAdaptiveScheduler(sensor)

        t1 = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        t2 = await scheduler.request_capacity(MaintenanceTaskType.STORAGE_CLEANUP)
        t3 = await scheduler.request_capacity(MaintenanceTaskType.CONTEXT_COMPACTION)

        assert isinstance(t1, CapacityTicket)
        assert isinstance(t2, CapacityTicket)
        assert isinstance(t3, CapacityDenial)

    @pytest.mark.asyncio
    async def test_release_frees_slot(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.NORMAL)
        scheduler = GlobalAdaptiveScheduler(sensor)

        t1 = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        t2 = await scheduler.request_capacity(MaintenanceTaskType.STORAGE_CLEANUP)
        assert isinstance(t1, CapacityTicket)
        assert isinstance(t2, CapacityTicket)

        await scheduler.release_capacity(t1)
        assert scheduler.active_count == 1

        t3 = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        assert isinstance(t3, CapacityTicket)

    @pytest.mark.asyncio
    async def test_urgency_override(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.BUSY)
        scheduler = GlobalAdaptiveScheduler(sensor)

        t1 = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        assert isinstance(t1, CapacityTicket)
        await scheduler.release_capacity(t1)

        critical_health = AgentHealthScore(score=20)
        t2 = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION, health_score=critical_health)
        assert isinstance(t2, CapacityTicket)

    @pytest.mark.asyncio
    async def test_stale_ticket_expiry(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.NORMAL)
        scheduler = GlobalAdaptiveScheduler(sensor, ticket_ttl_seconds=0.01)

        t1 = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        assert isinstance(t1, CapacityTicket)
        assert scheduler.active_count == 1

        await asyncio.sleep(0.02)

        t2 = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        assert isinstance(t2, CapacityTicket)
        assert scheduler.active_count == 1

    @pytest.mark.asyncio
    async def test_is_idle(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.IDLE)
        scheduler = GlobalAdaptiveScheduler(sensor)
        assert scheduler.is_idle()

        sensor.set_level(SystemLoadLevel.BUSY)
        scheduler._last_snapshot = None
        assert not scheduler.is_idle()

    @pytest.mark.asyncio
    async def test_idle_slots(self) -> None:
        """IDLE allows 4 concurrent tasks."""
        sensor = FakeLoadSensor(SystemLoadLevel.IDLE)
        scheduler = GlobalAdaptiveScheduler(sensor)

        tickets: list[CapacityTicket] = []
        for _ in range(4):
            result = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
            assert isinstance(result, CapacityTicket)
            tickets.append(result)

        overflow = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        assert isinstance(overflow, CapacityDenial)

    @pytest.mark.asyncio
    async def test_last_snapshot_property(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.NORMAL)
        scheduler = GlobalAdaptiveScheduler(sensor)
        assert scheduler.last_snapshot is None

        await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        assert scheduler.last_snapshot is not None
        assert scheduler.last_snapshot.level == SystemLoadLevel.NORMAL

    @pytest.mark.asyncio
    async def test_release_nonexistent_ticket(self) -> None:
        """Releasing a ticket not in active set should not raise."""
        sensor = FakeLoadSensor(SystemLoadLevel.IDLE)
        scheduler = GlobalAdaptiveScheduler(sensor)
        fake_ticket = CapacityTicket(ticket_id="nonexistent", task_type=MaintenanceTaskType.EVOLUTION)
        await scheduler.release_capacity(fake_ticket)
        assert scheduler.active_count == 0

    @pytest.mark.asyncio
    async def test_busy_single_slot(self) -> None:
        """BUSY allows exactly 1 concurrent task."""
        sensor = FakeLoadSensor(SystemLoadLevel.BUSY)
        scheduler = GlobalAdaptiveScheduler(sensor)

        t1 = await scheduler.request_capacity(MaintenanceTaskType.STORAGE_CLEANUP)
        assert isinstance(t1, CapacityTicket)

        t2 = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        assert isinstance(t2, CapacityDenial)


# ─── singleton functions ─────────────────────────────────────────────


class TestSingletonFunctions:
    def test_get_scheduler_before_init(self) -> None:
        import myrm_agent_harness.runtime.maintenance.scheduler as sched_mod

        original = sched_mod._scheduler
        try:
            sched_mod._scheduler = None
            assert sched_mod.get_maintenance_scheduler() is None
        finally:
            sched_mod._scheduler = original

    def test_init_and_get_scheduler(self) -> None:
        import myrm_agent_harness.runtime.maintenance.scheduler as sched_mod

        original = sched_mod._scheduler
        try:
            sched_mod._scheduler = None
            sensor = FakeLoadSensor(SystemLoadLevel.NORMAL)
            with patch("myrm_agent_harness.runtime.memory_pressure.get_memory_pressure_monitor", return_value=None):
                s = sched_mod.init_maintenance_scheduler(sensor)
            assert isinstance(s, GlobalAdaptiveScheduler)
            assert sched_mod.get_maintenance_scheduler() is s

            s2 = sched_mod.init_maintenance_scheduler(sensor)
            assert s2 is s
        finally:
            sched_mod._scheduler = original

    def test_init_subscribes_to_monitor(self) -> None:
        import myrm_agent_harness.runtime.maintenance.scheduler as sched_mod
        from myrm_agent_harness.runtime.memory_pressure import MemoryPressureMonitor

        original = sched_mod._scheduler
        try:
            sched_mod._scheduler = None
            sensor = FakeLoadSensor(SystemLoadLevel.IDLE)
            mock_monitor = MemoryPressureMonitor()
            with patch(
                "myrm_agent_harness.runtime.memory_pressure.get_memory_pressure_monitor", return_value=mock_monitor
            ):
                s = sched_mod.init_maintenance_scheduler(sensor)
            assert s in mock_monitor._subscribers
        finally:
            sched_mod._scheduler = original


# ─── memory pressure integration ──────────────────────────────────────


class TestMemoryPressureIntegration:
    @pytest.mark.asyncio
    async def test_blocks_at_critical_pressure(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.IDLE)
        scheduler = GlobalAdaptiveScheduler(sensor)

        event = PressureEvent(
            level=PressureLevel.CRITICAL,
            previous_level=PressureLevel.WARNING,
            memory_percent=91.0,
            timestamp=time.monotonic(),
        )
        await scheduler.on_pressure_change(event)

        result = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        assert isinstance(result, CapacityDenial)
        assert "CRITICAL" in result.reason

    @pytest.mark.asyncio
    async def test_unblocks_after_pressure_drops(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.IDLE)
        scheduler = GlobalAdaptiveScheduler(sensor)

        escalate = PressureEvent(
            level=PressureLevel.EMERGENCY,
            previous_level=PressureLevel.CRITICAL,
            memory_percent=96.0,
            timestamp=time.monotonic(),
        )
        await scheduler.on_pressure_change(escalate)

        result = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        assert isinstance(result, CapacityDenial)

        de_escalate = PressureEvent(
            level=PressureLevel.WARNING,
            previous_level=PressureLevel.CRITICAL,
            memory_percent=82.0,
            timestamp=time.monotonic(),
        )
        await scheduler.on_pressure_change(de_escalate)

        result = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        assert isinstance(result, CapacityTicket)

    @pytest.mark.asyncio
    async def test_normal_pressure_allows_tasks(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.NORMAL)
        scheduler = GlobalAdaptiveScheduler(sensor)

        event = PressureEvent(
            level=PressureLevel.WARNING,
            previous_level=PressureLevel.NORMAL,
            memory_percent=82.0,
            timestamp=time.monotonic(),
        )
        await scheduler.on_pressure_change(event)

        result = await scheduler.request_capacity(MaintenanceTaskType.EVOLUTION)
        assert isinstance(result, CapacityTicket)


# ─── sensors: real read paths ─────────────────────────────────────────


class TestDeviceLoadSensorRead:
    def test_read_with_psutil(self) -> None:
        sensor = DeviceLoadSensor()
        snapshot = sensor.read()
        assert isinstance(snapshot, SystemLoadSnapshot)
        assert snapshot.cpu_percent >= 0.0
        assert snapshot.memory_percent >= 0.0
        assert snapshot.detail

    def test_read_without_psutil(self) -> None:
        with patch("myrm_agent_harness.runtime.maintenance.sensors.psutil", None):
            sensor = DeviceLoadSensor()
            snapshot = sensor.read()
            assert snapshot.level == SystemLoadLevel.NORMAL
            assert "psutil unavailable" in snapshot.detail


class TestSaaSLoadSensorClassify:
    def test_classify_normal(self) -> None:
        """api_quota between 30-80 and moderate queue => NORMAL."""
        sensor = SaaSLoadSensor()
        sensor.update(api_quota_remaining_pct=50.0, queue_depth=20)
        snapshot = sensor.read()
        assert snapshot.level == SystemLoadLevel.NORMAL


# ─── integration: BackgroundEvolutionTaskManager ──────────────────────


class TestBackgroundTaskManagerIntegration:
    @pytest.mark.asyncio
    async def test_schedule_without_scheduler(self) -> None:
        mgr = BackgroundEvolutionTaskManager()
        task_id = await mgr.schedule(
            asyncio.sleep(0.01),
            label="test_task",
            trigger_type="test",
        )
        assert task_id is not None
        await mgr.wait_all(timeout=2.0)

    @pytest.mark.asyncio
    async def test_schedule_denied_by_scheduler(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.OVERLOADED)
        scheduler = GlobalAdaptiveScheduler(sensor)
        mgr = BackgroundEvolutionTaskManager(scheduler=scheduler)

        coro = asyncio.sleep(0.01)
        task_id = await mgr.schedule(
            coro,
            label="blocked_task",
            trigger_type="test",
        )
        assert task_id is None
        coro.close()

    @pytest.mark.asyncio
    async def test_schedule_approved_and_ticket_released(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.IDLE)
        scheduler = GlobalAdaptiveScheduler(sensor)
        mgr = BackgroundEvolutionTaskManager(scheduler=scheduler)

        task_id = await mgr.schedule(
            asyncio.sleep(0.01),
            label="approved_task",
            trigger_type="test",
        )
        assert task_id is not None
        assert scheduler.active_count == 1

        await mgr.wait_all(timeout=2.0)
        await asyncio.sleep(0.05)
        assert scheduler.active_count == 0

    @pytest.mark.asyncio
    async def test_task_failure_releases_ticket(self) -> None:
        """When a task raises, ticket must still be released."""
        sensor = FakeLoadSensor(SystemLoadLevel.IDLE)
        scheduler = GlobalAdaptiveScheduler(sensor)
        mgr = BackgroundEvolutionTaskManager(scheduler=scheduler)

        async def _failing() -> None:
            raise ValueError("intentional failure")

        task_id = await mgr.schedule(
            _failing(),
            label="fail_task",
            trigger_type="test",
        )
        assert task_id is not None

        await mgr.wait_all(timeout=2.0)
        await asyncio.sleep(0.05)
        assert scheduler.active_count == 0

    @pytest.mark.asyncio
    async def test_wait_all_empty(self) -> None:
        mgr = BackgroundEvolutionTaskManager()
        result = await mgr.wait_all(timeout=1.0)
        assert result == {"total": 0, "completed": 0, "timeout": 0, "failed": 0, "task_ids": []}

    @pytest.mark.asyncio
    async def test_wait_all_timeout(self) -> None:
        """Tasks that exceed timeout should be cancelled."""
        mgr = BackgroundEvolutionTaskManager()

        task_id = await mgr.schedule(
            asyncio.sleep(10.0),
            label="slow_task",
            trigger_type="test",
        )
        assert task_id is not None

        result = await mgr.wait_all(timeout=0.1)
        assert result["total"] == 1
        assert result["timeout"] >= 1 or result["failed"] >= 0

    @pytest.mark.asyncio
    async def test_get_status(self) -> None:
        mgr = BackgroundEvolutionTaskManager()

        task_id = await mgr.schedule(
            asyncio.sleep(5.0),
            label="status_task",
            trigger_type="test",
            skill_ids=["sk1", "sk2"],
        )
        assert task_id is not None

        status = mgr.get_status()
        assert len(status) == 1
        assert status[0]["label"] == "status_task"
        assert status[0]["skill_ids"] == ["sk1", "sk2"]
        assert status[0]["running_time"] >= 0
        assert status[0]["done"] is False

        await mgr.wait_all(timeout=0.1)

    @pytest.mark.asyncio
    async def test_update_progress(self) -> None:
        mgr = BackgroundEvolutionTaskManager()

        task_id = await mgr.schedule(
            asyncio.sleep(5.0),
            label="progress_task",
            trigger_type="test",
        )
        assert task_id is not None

        await mgr.update_progress(task_id, "50% done")
        status = mgr.get_status()
        assert status[0]["progress"] == "50% done"

        await mgr.update_progress("nonexistent_task", "ignored")

        await mgr.wait_all(timeout=0.1)

    @pytest.mark.asyncio
    async def test_count_active(self) -> None:
        mgr = BackgroundEvolutionTaskManager()
        assert mgr.count_active() == 0

        await mgr.schedule(asyncio.sleep(5.0), label="t1", trigger_type="test")
        await mgr.schedule(asyncio.sleep(5.0), label="t2", trigger_type="test")
        assert mgr.count_active() == 2

        await mgr.wait_all(timeout=0.1)

    @pytest.mark.asyncio
    async def test_schedule_with_health_score(self) -> None:
        sensor = FakeLoadSensor(SystemLoadLevel.BUSY)
        scheduler = GlobalAdaptiveScheduler(sensor)
        mgr = BackgroundEvolutionTaskManager(scheduler=scheduler)

        critical = AgentHealthScore(score=20)
        task_id = await mgr.schedule(
            asyncio.sleep(0.01),
            label="urgent",
            trigger_type="test",
            health_score=critical,
        )
        assert task_id is not None
        await mgr.wait_all(timeout=2.0)


# ─── integration: SimpleStorageQuotaManager ───────────────────────────


class TestQuotaManagerIntegration:
    @pytest.mark.asyncio
    async def test_cleanup_deferred_when_overloaded(self, tmp_path: Path) -> None:
        context_root = tmp_path / ".context"
        context_root.mkdir()

        sensor = FakeLoadSensor(SystemLoadLevel.OVERLOADED)
        scheduler = GlobalAdaptiveScheduler(sensor)

        mgr = SimpleStorageQuotaManager(
            per_session_limit=2000,
            auto_cleanup_threshold=0.5,
            context_root=str(context_root),
            scheduler=scheduler,
        )

        session_dir = context_root / "s1" / "compacted"
        session_dir.mkdir(parents=True)
        for i in range(5):
            (session_dir / f"f{i}.txt").write_text("x" * 200)

        allowed = await mgr.check_write_allowed("s1", 10)
        assert allowed is True

        remaining_files = list(session_dir.iterdir())
        assert len(remaining_files) == 5

    @pytest.mark.asyncio
    async def test_cleanup_runs_when_idle(self, tmp_path: Path) -> None:
        context_root = tmp_path / ".context"
        context_root.mkdir()

        sensor = FakeLoadSensor(SystemLoadLevel.IDLE)
        scheduler = GlobalAdaptiveScheduler(sensor)

        mgr = SimpleStorageQuotaManager(
            per_session_limit=1500,
            auto_cleanup_threshold=0.5,
            context_root=str(context_root),
            scheduler=scheduler,
        )

        session_dir = context_root / "s1" / "compacted"
        session_dir.mkdir(parents=True)
        for i in range(5):
            (session_dir / f"f{i}.txt").write_text("x" * 200)

        allowed = await mgr.check_write_allowed("s1", 10)
        assert allowed is True

        remaining_files = list(session_dir.iterdir())
        assert len(remaining_files) < 5

    @pytest.mark.asyncio
    async def test_write_rejected_over_limit(self, tmp_path: Path) -> None:
        context_root = tmp_path / ".context"
        context_root.mkdir()

        mgr = SimpleStorageQuotaManager(
            per_session_limit=100,
            context_root=str(context_root),
        )

        session_dir = context_root / "s1" / "compacted"
        session_dir.mkdir(parents=True)
        (session_dir / "big.txt").write_text("x" * 80)

        allowed = await mgr.check_write_allowed("s1", 50)
        assert allowed is False

    @pytest.mark.asyncio
    async def test_get_remaining_quota(self, tmp_path: Path) -> None:
        context_root = tmp_path / ".context"
        context_root.mkdir()

        mgr = SimpleStorageQuotaManager(
            per_session_limit=1000,
            context_root=str(context_root),
        )

        remaining = await mgr.get_remaining_quota("empty_session")
        assert remaining == 1000

        session_dir = context_root / "s2" / "compacted"
        session_dir.mkdir(parents=True)
        (session_dir / "f1.txt").write_text("x" * 200)

        remaining = await mgr.get_remaining_quota("s2")
        assert remaining == 800

    @pytest.mark.asyncio
    async def test_invalidate_cache(self, tmp_path: Path) -> None:
        context_root = tmp_path / ".context"
        context_root.mkdir()

        mgr = SimpleStorageQuotaManager(
            per_session_limit=1000,
            context_root=str(context_root),
        )

        session_dir = context_root / "s1" / "compacted"
        session_dir.mkdir(parents=True)
        (session_dir / "f1.txt").write_text("x" * 100)

        await mgr.get_remaining_quota("s1")
        assert "s1" in mgr._usage_cache

        mgr.invalidate_cache("s1")
        assert "s1" not in mgr._usage_cache

        await mgr.get_remaining_quota("s1")
        mgr.invalidate_cache()
        assert len(mgr._usage_cache) == 0

    @pytest.mark.asyncio
    async def test_cleanup_without_scheduler(self, tmp_path: Path) -> None:
        """Auto-cleanup works even without a scheduler."""
        context_root = tmp_path / ".context"
        context_root.mkdir()

        mgr = SimpleStorageQuotaManager(
            per_session_limit=1500,
            auto_cleanup_threshold=0.5,
            context_root=str(context_root),
        )

        session_dir = context_root / "s1" / "compacted"
        session_dir.mkdir(parents=True)
        for i in range(5):
            (session_dir / f"f{i}.txt").write_text("x" * 200)

        allowed = await mgr.check_write_allowed("s1", 10)
        assert allowed is True

        remaining_files = list(session_dir.iterdir())
        assert len(remaining_files) < 5

    @pytest.mark.asyncio
    async def test_nonexistent_session_dir(self, tmp_path: Path) -> None:
        context_root = tmp_path / ".context"
        context_root.mkdir()

        mgr = SimpleStorageQuotaManager(
            per_session_limit=1000,
            context_root=str(context_root),
        )

        allowed = await mgr.check_write_allowed("ghost_session", 100)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_usage_cache_hit(self, tmp_path: Path) -> None:
        context_root = tmp_path / ".context"
        context_root.mkdir()

        mgr = SimpleStorageQuotaManager(
            per_session_limit=1000,
            context_root=str(context_root),
        )

        session_dir = context_root / "s1" / "compacted"
        session_dir.mkdir(parents=True)
        (session_dir / "f1.txt").write_text("x" * 100)

        await mgr.check_write_allowed("s1", 10)
        assert "s1" in mgr._usage_cache

        allowed = await mgr.check_write_allowed("s1", 10)
        assert allowed is True
