"""Tests for neglected memory detection.

Covers:
- detect_neglected pure function: filtering, sorting, truncation, edge cases
- NeglectedMemory dataclass: to_dict, frozen
- MaintenanceReport integration: neglected_memories field, to_dict
- run_maintenance_cycle integration
- Public API export
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.health import MaintenanceReport, NeglectedMemory, detect_neglected
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory


class TestDetectNeglected:
    def test_pinned_memory_detected(self) -> None:
        m = SemanticMemory(
            content="important pinned", pinned=True, importance=0.1, created_at=datetime.now(UTC) - timedelta(days=30)
        )
        result = detect_neglected([m], stale_days=14)
        assert len(result) == 1
        assert result[0].pinned is True

    def test_high_importance_detected(self) -> None:
        m = SemanticMemory(content="high importance", importance=0.8, created_at=datetime.now(UTC) - timedelta(days=30))
        result = detect_neglected([m], importance_threshold=0.6, stale_days=14)
        assert len(result) == 1
        assert result[0].importance == 0.8

    def test_low_importance_not_detected(self) -> None:
        m = SemanticMemory(content="low importance", importance=0.3, created_at=datetime.now(UTC) - timedelta(days=30))
        result = detect_neglected([m], importance_threshold=0.6, stale_days=14)
        assert len(result) == 0

    def test_recently_accessed_not_detected(self) -> None:
        m = SemanticMemory(
            content="recently accessed",
            importance=0.9,
            last_accessed_at=datetime.now(UTC) - timedelta(days=3),
            created_at=datetime.now(UTC) - timedelta(days=60),
        )
        result = detect_neglected([m], stale_days=14)
        assert len(result) == 0

    def test_sorted_by_days_descending(self) -> None:
        now = datetime.now(UTC)
        m1 = SemanticMemory(content="old", importance=0.9, created_at=now - timedelta(days=60))
        m2 = SemanticMemory(content="older", importance=0.9, created_at=now - timedelta(days=90))
        result = detect_neglected([m1, m2], stale_days=14)
        assert len(result) == 2
        assert result[0].days_since_access >= result[1].days_since_access

    def test_max_items_truncation(self) -> None:
        now = datetime.now(UTC)
        memories = [
            SemanticMemory(content=f"memory {i}", importance=0.9, created_at=now - timedelta(days=30 + i))
            for i in range(20)
        ]
        result = detect_neglected(memories, max_items=5)
        assert len(result) == 5

    def test_empty_list(self) -> None:
        result = detect_neglected([])
        assert result == ()

    def test_content_preview_truncation(self) -> None:
        long_content = "x" * 200
        m = SemanticMemory(content=long_content, importance=0.9, created_at=datetime.now(UTC) - timedelta(days=30))
        result = detect_neglected([m])
        assert len(result[0].content_preview) == 100

    def test_short_content_not_truncated(self) -> None:
        m = SemanticMemory(content="short", importance=0.9, created_at=datetime.now(UTC) - timedelta(days=30))
        result = detect_neglected([m])
        assert result[0].content_preview == "short"

    def test_episodic_memory_detected(self) -> None:
        m = EpisodicMemory(content="event", importance=0.8, created_at=datetime.now(UTC) - timedelta(days=30))
        result = detect_neglected([m], importance_threshold=0.6)
        assert len(result) == 1

    def test_uses_last_accessed_at_over_created_at(self) -> None:
        now = datetime.now(UTC)
        m = SemanticMemory(
            content="recently accessed",
            importance=0.9,
            created_at=now - timedelta(days=60),
            last_accessed_at=now - timedelta(days=5),
        )
        result = detect_neglected([m], stale_days=14)
        assert len(result) == 0


class TestNeglectedMemoryDataclass:
    def test_to_dict(self) -> None:
        n = NeglectedMemory(
            memory_id="m1",
            content_preview="test",
            importance=0.8,
            pinned=True,
            days_since_access=30,
            memory_type="semantic",
        )
        d = n.to_dict()
        assert d["memory_id"] == "m1"
        assert d["pinned"] is True
        assert d["days_since_access"] == 30

    def test_frozen(self) -> None:
        n = NeglectedMemory(
            memory_id="m1",
            content_preview="test",
            importance=0.8,
            pinned=False,
            days_since_access=30,
            memory_type="semantic",
        )
        with pytest.raises(AttributeError):
            n.memory_id = "m2"  # type: ignore[misc]


class TestMaintenanceReportNeglected:
    def test_empty_neglected(self) -> None:
        r = MaintenanceReport()
        assert r.neglected_memories == ()
        d = r.to_dict()
        assert d["neglected"] == []

    def test_with_neglected(self) -> None:
        n = NeglectedMemory(
            memory_id="m1",
            content_preview="test",
            importance=0.8,
            pinned=True,
            days_since_access=30,
            memory_type="semantic",
        )
        r = MaintenanceReport(neglected_memories=(n,))
        d = r.to_dict()
        assert len(d["neglected"]) == 1  # type: ignore[arg-type]
        assert d["neglected"][0]["memory_id"] == "m1"  # type: ignore[index]


class TestRunMaintenanceCycleNeglected:
    @pytest.mark.asyncio
    async def test_neglected_in_report(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        now = datetime.now(UTC)
        old_memory = SemanticMemory(
            content="important old memory",
            importance=0.9,
            pinned=True,
            created_at=now - timedelta(days=60),
        )

        mock_vector_store.scroll.return_value = []

        mgr = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False)

        scroll_mock = AsyncMock(return_value=[old_memory])
        with patch.object(MemoryManager, "_scroll_all_memories", scroll_mock):
            report = await mgr.run_maintenance_cycle()

        assert len(report.neglected_memories) == 1
        assert report.neglected_memories[0].pinned is True

    @pytest.mark.asyncio
    async def test_neglected_error_handled(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        mock_vector_store.scroll.return_value = []

        mgr = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False)

        scroll_mock = AsyncMock(side_effect=RuntimeError("scroll failed"))
        with patch.object(MemoryManager, "_scroll_all_memories", scroll_mock):
            report = await mgr.run_maintenance_cycle()

        assert report.neglected_memories == ()
        assert not report.skipped


class TestPublicExport:
    def test_neglected_memory_importable(self) -> None:
        from myrm_agent_harness.toolkits.memory import NeglectedMemory as NeglectedMem

        assert NeglectedMem is NeglectedMemory
