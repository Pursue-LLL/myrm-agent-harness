"""Tests for MemorySnapshot and before/after in MaintenanceReport."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.health import MaintenanceReport, MemorySnapshot
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import MemoryType

# ── MemorySnapshot dataclass ──


class TestMemorySnapshot:
    def test_basic_construction(self) -> None:
        snap = MemorySnapshot(semantic=80, episodic=50)
        assert snap.semantic == 80
        assert snap.episodic == 50
        assert snap.total == 130

    def test_total_is_derived(self) -> None:
        snap = MemorySnapshot(semantic=0, episodic=0)
        assert snap.total == 0

    def test_total_is_property_not_field(self) -> None:
        snap = MemorySnapshot(semantic=10, episodic=20)
        assert snap.total == 30
        with pytest.raises(AttributeError):
            snap.total = 999  # type: ignore[misc]

    def test_frozen(self) -> None:
        snap = MemorySnapshot(semantic=10, episodic=20)
        with pytest.raises(AttributeError):
            snap.semantic = 99  # type: ignore[misc]

    def test_to_dict(self) -> None:
        snap = MemorySnapshot(semantic=80, episodic=50)
        d = snap.to_dict()
        assert d == {"semantic": 80, "episodic": 50, "total": 130}

    def test_to_dict_zero(self) -> None:
        snap = MemorySnapshot(semantic=0, episodic=0)
        d = snap.to_dict()
        assert d == {"semantic": 0, "episodic": 0, "total": 0}


# ── MaintenanceReport with before/after ──


class TestMaintenanceReportSnapshot:
    def test_default_none(self) -> None:
        report = MaintenanceReport()
        assert report.before is None
        assert report.after is None

    def test_with_snapshots(self) -> None:
        before = MemorySnapshot(semantic=80, episodic=50)
        after = MemorySnapshot(semantic=82, episodic=48)
        report = MaintenanceReport(before=before, after=after)
        assert report.before is before
        assert report.after is after

    def test_to_dict_with_snapshots(self) -> None:
        before = MemorySnapshot(semantic=80, episodic=50)
        after = MemorySnapshot(semantic=82, episodic=48)
        report = MaintenanceReport(before=before, after=after)
        d = report.to_dict()
        assert d["before"] == {"semantic": 80, "episodic": 50, "total": 130}
        assert d["after"] == {"semantic": 82, "episodic": 48, "total": 130}

    def test_to_dict_without_snapshots(self) -> None:
        report = MaintenanceReport()
        d = report.to_dict()
        assert d["before"] is None
        assert d["after"] is None

    def test_to_dict_partial_snapshots(self) -> None:
        before = MemorySnapshot(semantic=80, episodic=50)
        report = MaintenanceReport(before=before, after=None)
        d = report.to_dict()
        assert d["before"] == {"semantic": 80, "episodic": 50, "total": 130}
        assert d["after"] is None


# ── _collect_snapshot ──


class TestCollectSnapshot:
    @pytest.fixture
    def manager(self) -> MemoryManager:
        mock_vector = AsyncMock()
        mock_embedding = AsyncMock()
        mgr = MemoryManager(
            MemoryConfig(embedding_model="test-model"),
            user_id="test_user",
            vector=mock_vector,
            embedding=mock_embedding,
            auto_warmup=False,
        )
        return mgr

    @pytest.mark.asyncio
    async def test_collect_success(self, manager: MemoryManager) -> None:
        with patch.object(MemoryManager, "count_memories", new_callable=AsyncMock) as mock_count:
            mock_count.side_effect = lambda t: {
                MemoryType.SEMANTIC: 80,
                MemoryType.EPISODIC: 50,
            }[t]
            snap = await manager._collect_snapshot()
        assert snap is not None
        assert snap.semantic == 80
        assert snap.episodic == 50
        assert snap.total == 130

    @pytest.mark.asyncio
    async def test_collect_failure_returns_none(self, manager: MemoryManager) -> None:
        with patch.object(MemoryManager, "count_memories", new_callable=AsyncMock) as mock_count:
            mock_count.side_effect = RuntimeError("DB down")
            snap = await manager._collect_snapshot()
        assert snap is None

    @pytest.mark.asyncio
    async def test_collect_no_vector(self) -> None:
        mgr = MemoryManager(MemoryConfig(embedding_model="test-model"), user_id="test_user", auto_warmup=False)
        snap = await mgr._collect_snapshot()
        assert snap is not None
        assert snap.semantic == 0
        assert snap.episodic == 0
        assert snap.total == 0


# ── run_maintenance_cycle with before/after ──


class TestMaintenanceCycleSnapshot:
    @pytest.fixture
    def manager(self) -> MemoryManager:
        mock_vector = AsyncMock()
        mock_embedding = AsyncMock()
        mock_vector.count = AsyncMock(return_value=0)
        mock_vector.scroll = AsyncMock(return_value=[])
        mgr = MemoryManager(
            MemoryConfig(embedding_model="test-model"),
            user_id="test_user",
            vector=mock_vector,
            embedding=mock_embedding,
            auto_warmup=False,
        )
        return mgr

    @pytest.mark.asyncio
    async def test_report_contains_snapshots(self, manager: MemoryManager) -> None:
        call_count = 0
        before_snap = MemorySnapshot(semantic=80, episodic=50)
        after_snap = MemorySnapshot(semantic=82, episodic=48)

        async def mock_collect(self_: MemoryManager) -> MemorySnapshot | None:
            nonlocal call_count
            call_count += 1
            return before_snap if call_count == 1 else after_snap

        with (
            patch.object(MemoryManager, "_collect_snapshot", mock_collect),
            patch.object(MemoryManager, "compute_health_score", new_callable=AsyncMock, return_value=None),
            patch.object(MemoryManager, "_scroll_all_memories", new_callable=AsyncMock, return_value=[]),
        ):
            report = await manager.run_maintenance_cycle()

        assert report.before is before_snap
        assert report.after is after_snap
        assert report.before.total == 130
        assert report.after.total == 130

    @pytest.mark.asyncio
    async def test_skipped_report_has_no_snapshots(self, manager: MemoryManager) -> None:
        async with manager._maintenance_lock:
            report = await manager.run_maintenance_cycle()
        assert report.skipped is True
        assert report.before is None
        assert report.after is None

    @pytest.mark.asyncio
    async def test_snapshot_failure_doesnt_block_maintenance(self, manager: MemoryManager) -> None:
        """When count_memories fails, _collect_snapshot returns None, maintenance continues."""

        async def mock_collect_none(self_: MemoryManager) -> MemorySnapshot | None:
            return None

        with (
            patch.object(MemoryManager, "_collect_snapshot", mock_collect_none),
            patch.object(MemoryManager, "compute_health_score", new_callable=AsyncMock, return_value=None),
            patch.object(MemoryManager, "_scroll_all_memories", new_callable=AsyncMock, return_value=[]),
        ):
            report = await manager.run_maintenance_cycle()

        assert report.skipped is False
        assert report.before is None
        assert report.after is None


# ── Public API export ──


class TestPublicExport:
    def test_memory_snapshot_exported(self) -> None:
        from myrm_agent_harness.toolkits.memory import MemorySnapshot as Exported

        assert Exported is MemorySnapshot
