"""Tests for IncrementalSessionCheckpointer."""

import pytest
from langgraph.checkpoint.base import Checkpoint
from langgraph.checkpoint.memory import MemorySaver

from myrm_agent_harness.toolkits.browser.checkpoint import (
    CheckpointMetrics,
    IncrementalSessionCheckpointer,
)


@pytest.fixture
def base_saver() -> MemorySaver:
    """Create base MemorySaver for testing."""
    return MemorySaver()


@pytest.fixture
def incremental_saver(base_saver: MemorySaver) -> IncrementalSessionCheckpointer:
    """Create IncrementalSessionCheckpointer for testing."""
    return IncrementalSessionCheckpointer(base_saver)


class TestIncrementalCheckpointer:
    """Test IncrementalSessionCheckpointer decorator."""

    def test_initialization(self, incremental_saver: IncrementalSessionCheckpointer) -> None:
        """Should initialize with wrapped checkpointer."""
        assert incremental_saver._wrapped is not None
        assert isinstance(incremental_saver.metrics, CheckpointMetrics)

    @pytest.mark.asyncio
    async def test_delegates_aget(self, incremental_saver: IncrementalSessionCheckpointer) -> None:
        """Should delegate aget to wrapped checkpointer."""
        config = {"configurable": {"thread_id": "test-1"}}

        # Should not raise (delegates to MemorySaver)
        result = await incremental_saver.aget(config)

        assert result is None  # Empty checkpoint

    @pytest.mark.asyncio
    async def test_aput_with_no_browser_metadata(self, incremental_saver: IncrementalSessionCheckpointer) -> None:
        """Should save checkpoint without browser metadata."""

        config = {"configurable": {"thread_id": "test-1", "checkpoint_ns": ""}}
        checkpoint = Checkpoint(
            v=1,
            id="checkpoint-1",
            ts="2026-03-23T00:00:00Z",
            channel_values={"messages": []},
        )
        metadata = {}
        new_versions = {}

        result = await incremental_saver.aput(config, checkpoint, metadata, new_versions)

        assert result is not None
        assert incremental_saver.metrics.save_count == 1
        assert incremental_saver.metrics.save_skipped_count == 0

    @pytest.mark.asyncio
    async def test_aput_with_browser_metadata_tracks_hash(
        self, incremental_saver: IncrementalSessionCheckpointer
    ) -> None:
        """Should track hash changes in browser metadata."""

        config = {"configurable": {"thread_id": "test-1", "checkpoint_ns": ""}}
        checkpoint = Checkpoint(
            v=1,
            id="checkpoint-1",
            ts="2026-03-23T00:00:00Z",
            channel_values={"messages": []},
        )

        # First save with hash1
        metadata1 = {
            "browser": {
                "session_hash": "abc123",
                "session_domain": "example.com",
            }
        }

        await incremental_saver.aput(config, checkpoint, metadata1, {})

        assert incremental_saver.metrics.save_count == 1
        assert incremental_saver.metrics.vault_save_count == 1
        assert incremental_saver.metrics.save_skipped_count == 0

        # Second save with same hash (should skip)
        metadata2 = {
            "browser": {
                "session_hash": "abc123",  # Same hash
                "session_domain": "example.com",
            }
        }

        checkpoint2 = Checkpoint(
            v=1,
            id="checkpoint-2",
            ts="2026-03-23T00:00:01Z",
            channel_values={"messages": []},
        )
        await incremental_saver.aput(config, checkpoint2, metadata2, {})

        assert incremental_saver.metrics.save_count == 2
        assert incremental_saver.metrics.vault_save_count == 1  # Not incremented
        assert incremental_saver.metrics.save_skipped_count == 1  # Skipped

        # Third save with different hash (should not skip)
        metadata3 = {
            "browser": {
                "session_hash": "xyz789",  # Different hash
                "session_domain": "example.com",
            }
        }

        checkpoint3 = Checkpoint(
            v=1,
            id="checkpoint-3",
            ts="2026-03-23T00:00:02Z",
            channel_values={"messages": []},
        )
        await incremental_saver.aput(config, checkpoint3, metadata3, {})

        assert incremental_saver.metrics.save_count == 3
        assert incremental_saver.metrics.vault_save_count == 2  # Incremented
        assert incremental_saver.metrics.save_skipped_count == 1  # Still 1

    @pytest.mark.asyncio
    async def test_aput_tracks_save_duration(self, incremental_saver: IncrementalSessionCheckpointer) -> None:
        """Should track checkpoint save duration."""

        config = {"configurable": {"thread_id": "test-1", "checkpoint_ns": ""}}
        checkpoint = Checkpoint(
            v=1,
            id="checkpoint-1",
            ts="2026-03-23T00:00:00Z",
            channel_values={"messages": []},
        )

        await incremental_saver.aput(config, checkpoint, {}, {})

        assert incremental_saver.metrics.save_count == 1
        assert incremental_saver.metrics.save_total_ms > 0
        assert incremental_saver.metrics.save_avg_ms > 0

    @pytest.mark.asyncio
    async def test_different_threads_tracked_separately(
        self, incremental_saver: IncrementalSessionCheckpointer
    ) -> None:
        """Should track hash changes per thread independently."""

        checkpoint = Checkpoint(
            v=1,
            id="checkpoint-1",
            ts="2026-03-23T00:00:00Z",
            channel_values={"messages": []},
        )

        metadata = {
            "browser": {
                "session_hash": "abc123",
            }
        }

        # Save for thread-1
        config1 = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}
        await incremental_saver.aput(config1, checkpoint, metadata, {})

        # Save for thread-2 with same hash (should NOT skip, different thread)
        config2 = {"configurable": {"thread_id": "thread-2", "checkpoint_ns": ""}}
        checkpoint2 = Checkpoint(
            v=1,
            id="checkpoint-2",
            ts="2026-03-23T00:00:01Z",
            channel_values={"messages": []},
        )
        await incremental_saver.aput(config2, checkpoint2, metadata, {})

        assert incremental_saver.metrics.vault_save_count == 2  # Both saved
        assert incremental_saver.metrics.save_skipped_count == 0

    @pytest.mark.asyncio
    async def test_thread_store_integration(self, base_saver: MemorySaver) -> None:
        """Should register thread and update activity when ThreadStore is enabled."""
        from unittest.mock import AsyncMock, MagicMock

        # Create mock ThreadStore
        mock_store = MagicMock()
        mock_store.register = AsyncMock()
        mock_store.update_activity = AsyncMock()

        # Create checkpointer with ThreadStore
        saver = IncrementalSessionCheckpointer(
            base_saver,
            thread_store=mock_store,
        )

        config = {"configurable": {"thread_id": "test-thread-store", "checkpoint_ns": ""}}
        checkpoint = Checkpoint(
            v=1,
            id="checkpoint-1",
            ts="2026-03-23T00:00:00Z",
            channel_values={"messages": []},
        )
        metadata = {
            "browser": {
                "session_hash": "hash1",
                "current_url": "https://example.com",
            }
        }

        # First checkpoint: register + update_activity
        await saver.aput(config, checkpoint, metadata, {})
        assert mock_store.register.call_count == 1
        assert mock_store.update_activity.call_count == 1  # Called after register

        # Second checkpoint: update_activity only
        checkpoint2 = Checkpoint(
            v=1,
            id="checkpoint-2",
            ts="2026-03-23T00:00:01Z",
            channel_values={"messages": []},
        )
        metadata2 = {"browser": {"session_hash": "hash2"}}
        await saver.aput(config, checkpoint2, metadata2, {})
        assert mock_store.register.call_count == 1  # Still 1 (not re-registered)
        assert mock_store.update_activity.call_count == 2  # Incremented


class TestMetricsComputation:
    """Test metrics computation and properties."""

    def test_incremental_ratio_calculation(self) -> None:
        """Should calculate incremental ratio correctly."""
        metrics = CheckpointMetrics()

        # 80% skipped (8 skipped out of 10 vault attempts)
        metrics.vault_save_count = 2
        metrics.save_skipped_count = 8

        assert metrics.incremental_ratio == 0.8

    def test_recovery_success_rate_calculation(self) -> None:
        """Should calculate recovery success rate correctly."""
        metrics = CheckpointMetrics()

        # 75% success (3 success, 1 failure)
        metrics.recovery_count = 3
        metrics.recovery_failures = 1

        assert metrics.recovery_success_rate == 0.75

    def test_to_dict_structure(self) -> None:
        """Should export metrics with expected structure."""
        metrics = CheckpointMetrics()
        metrics.save_count = 5
        metrics.save_total_ms = 100.0

        result = metrics.to_dict()

        assert "save_count" in result
        assert "save_avg_ms" in result
        assert "incremental_ratio" in result
        assert "recovery_success_rate" in result
        assert "warnings" in result
        assert "hash_collisions" in result["warnings"]


class TestCacheMetrics:
    """Test cache observability metrics."""

    @pytest.mark.asyncio
    async def test_cache_metrics_exposed(self, base_saver: MemorySaver) -> None:
        """Verify cache metrics are accessible."""
        checkpointer = IncrementalSessionCheckpointer(wrapped=base_saver)

        metrics = checkpointer.get_cache_metrics()

        assert "hash_cache" in metrics

        hash_metrics = metrics["hash_cache"]
        assert "hits" in hash_metrics
        assert "misses" in hash_metrics
        assert "hit_rate" in hash_metrics
        assert "size" in hash_metrics

    @pytest.mark.asyncio
    async def test_metrics_structure(self, base_saver: MemorySaver) -> None:
        """Verify metrics structure is complete."""
        checkpointer = IncrementalSessionCheckpointer(wrapped=base_saver)

        cache_metrics = checkpointer.get_cache_metrics()

        assert "hash_cache" in cache_metrics

        hash_metrics = cache_metrics["hash_cache"]
        assert "hits" in hash_metrics
        assert "misses" in hash_metrics
        assert "hit_rate" in hash_metrics
        assert "size" in hash_metrics
        assert "maxsize" in hash_metrics
