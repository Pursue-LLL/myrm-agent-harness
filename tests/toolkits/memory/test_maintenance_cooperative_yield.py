"""Tests for cooperative pause and yielding during memory maintenance cycles."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.runtime.cognitive_clock.signals import CooperativePauseSignal
from myrm_agent_harness.toolkits.memory.cognitive.consolidator import CognitiveConsolidator
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.strategies.consolidation import ConsolidationStats


def _create_manager(
    memory_config: MemoryConfig,
    mock_vector_store: AsyncMock,
    mock_embedding: AsyncMock,
    consolidation_llm: object | None = None,
    mock_relational_store: AsyncMock | None = None,
) -> MemoryManager:
    return MemoryManager(
        memory_config,
        user_id="test_user",
        vector=mock_vector_store,
        embedding=mock_embedding,
        relational=mock_relational_store,
        consolidation_llm=consolidation_llm,
        auto_warmup=False,
    )


@pytest.mark.asyncio
async def test_maintenance_yields_immediately_when_pre_paused(
    memory_config: MemoryConfig,
    mock_vector_store: AsyncMock,
    mock_embedding: AsyncMock,
) -> None:
    """If pause is already requested before cycle runs, it should yield immediately."""
    mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)
    pause_signal = CooperativePauseSignal()
    pause_signal.request_pause("foreground_user_typing")

    report = await mgr.run_maintenance_cycle(pause_signal=pause_signal)

    assert report.skipped is True
    assert report.interrupted_by_pause is True
    assert "foreground_user_typing" in report.skip_reason
    assert report.to_dict()["interrupted_by_pause"] is True
    assert report.consolidation_merged == 0


@pytest.mark.asyncio
async def test_maintenance_yields_between_phases_and_preserves_stats(
    memory_config: MemoryConfig,
    mock_vector_store: AsyncMock,
    mock_embedding: AsyncMock,
) -> None:
    """If pause is requested after consolidation, subsequent phases yield and report keeps consolidation stats."""
    mock_relational = AsyncMock()
    mock_consolidation_llm = AsyncMock()
    mgr = _create_manager(
        memory_config,
        mock_vector_store,
        mock_embedding,
        consolidation_llm=mock_consolidation_llm,
        mock_relational_store=mock_relational,
    )
    pause_signal = CooperativePauseSignal()

    async def _consolidation_side_effect(*args, **kwargs):
        # Simulate foreground activity interrupting right after consolidation completes
        pause_signal.request_pause("user_sent_message")
        return ConsolidationStats(merged=5, corrected=2, updated=1, errors=0)

    with patch(
        "myrm_agent_harness.toolkits.memory.strategies.consolidation.run_consolidation",
        side_effect=_consolidation_side_effect,
    ):
        report = await mgr.run_maintenance_cycle(force=True, pause_signal=pause_signal)

        assert report.skipped is True
        assert report.interrupted_by_pause is True
        assert "user_sent_message" in report.skip_reason
        # Completed phase stats must be retained
        assert report.consolidation_merged == 5
        assert report.consolidation_corrected == 2
        assert report.consolidation_updated == 1
        # Unreached phases should remain 0
        assert report.forgotten_count == 0
        assert report.blobs_swept == 0


@pytest.mark.asyncio
async def test_maintenance_completes_when_no_pause_requested(
    memory_config: MemoryConfig,
    mock_vector_store: AsyncMock,
    mock_embedding: AsyncMock,
) -> None:
    """When no pause signal is triggered, full maintenance executes normally."""
    mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)
    pause_signal = CooperativePauseSignal()

    report = await mgr.run_maintenance_cycle(pause_signal=pause_signal)

    assert report.skipped is False
    assert report.interrupted_by_pause is False
    assert report.skip_reason == ""


@pytest.mark.asyncio
async def test_cognitive_consolidator_delegates_pause_signal(
    memory_config: MemoryConfig,
    mock_vector_store: AsyncMock,
    mock_embedding: AsyncMock,
) -> None:
    """CognitiveConsolidator passes pause_signal to manager and exposes interrupted_by_pause."""
    mgr = _create_manager(memory_config, mock_vector_store, mock_embedding)
    pause_signal = CooperativePauseSignal()
    pause_signal.request_pause("cooperative_test")

    consolidator = CognitiveConsolidator(mgr)
    result = await consolidator.run_consolidation(pause_signal=pause_signal)

    assert result.skipped is True
    assert result.interrupted_by_pause is True
    assert "cooperative_test" in result.skip_reason
    # Cooperative pause should NOT be counted as an unhandled error
    assert len(result.errors) == 0
    res_dict = result.to_dict()
    assert res_dict["interrupted_by_pause"] is True
