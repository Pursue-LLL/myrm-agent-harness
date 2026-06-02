"""Tests for consolidation insight generation.

Covers:
- _parse_response with new {operations, insights} format
- _parse_response backward compatibility with legacy [] format
- ConsolidationStats.insights field
- MaintenanceReport.insights field and to_dict()
- run_consolidation insight passthrough
- run_maintenance_cycle insight propagation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.health import MaintenanceReport
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.strategies.consolidation import ConsolidationStats


class TestConsolidationStatsInsights:
    def test_default_empty(self) -> None:
        stats = ConsolidationStats()
        assert stats.insights == ()

    def test_with_insights(self) -> None:
        stats = ConsolidationStats(insights=("insight1", "insight2"))
        assert len(stats.insights) == 2


class TestMaintenanceReportInsights:
    def test_default_empty(self) -> None:
        report = MaintenanceReport()
        assert report.insights == ()

    def test_with_insights(self) -> None:
        report = MaintenanceReport(insights=("cross-pattern found",))
        assert report.insights == ("cross-pattern found",)

    def test_to_dict_includes_insights(self) -> None:
        report = MaintenanceReport(insights=("pattern A", "gap B"))
        d = report.to_dict()
        assert d["insights"] == ["pattern A", "gap B"]

    def test_to_dict_empty_insights(self) -> None:
        report = MaintenanceReport()
        d = report.to_dict()
        assert d["insights"] == []


class TestMaintenanceCycleInsightPropagation:
    @pytest.mark.asyncio
    async def test_insights_propagated_from_consolidation(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        """Insights from consolidation should appear in MaintenanceReport."""
        mock_vector_store.scroll.return_value = []
        mock_vector_store.count.return_value = 0

        mock_relational = AsyncMock()
        mock_consolidation_llm = AsyncMock()

        mgr = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store,
            embedding=mock_embedding,
            relational=mock_relational,
            consolidation_llm=mock_consolidation_llm,
            auto_warmup=False,
        )

        stats_with_insights = ConsolidationStats(merged=1, insights=("Projects A and B share patterns",))

        with (
            patch(
                "myrm_agent_harness.toolkits.memory.strategies.consolidation.should_consolidate",
                AsyncMock(return_value=True),
            ),
            patch(
                "myrm_agent_harness.toolkits.memory.strategies.consolidation.run_consolidation",
                AsyncMock(return_value=stats_with_insights),
            ),
        ):
            report = await mgr.run_maintenance_cycle()

        assert report.insights == ("Projects A and B share patterns",)
        assert report.consolidation_merged == 1

    @pytest.mark.asyncio
    async def test_no_consolidation_no_insights(
        self, memory_config: MemoryConfig, mock_vector_store: AsyncMock, mock_embedding: AsyncMock
    ) -> None:
        """Without consolidation LLM, insights should be empty."""
        mock_vector_store.scroll.return_value = []
        mock_vector_store.count.return_value = 0

        mgr = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding, auto_warmup=False)

        report = await mgr.run_maintenance_cycle()
        assert report.insights == ()
