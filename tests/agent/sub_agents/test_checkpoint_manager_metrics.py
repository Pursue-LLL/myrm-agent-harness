"""Tests for checkpoint/checkpoint_manager.py — metrics integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.checkpoint.checkpoint_manager import SubagentCheckpointManager
from myrm_agent_harness.agent.sub_agents.checkpoint.metrics import CheckpointMetrics
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig


@pytest.fixture
def checkpoint_manager():
    """Create checkpoint manager instance."""
    return SubagentCheckpointManager()


class TestCheckpointManagerInit:
    """Test SubagentCheckpointManager initialization."""

    def test_init_creates_storage(self, checkpoint_manager):
        assert checkpoint_manager._storage is not None

    def test_init_creates_metrics(self, checkpoint_manager):
        assert checkpoint_manager._metrics is not None
        assert isinstance(checkpoint_manager._metrics, CheckpointMetrics)

    def test_metrics_property(self, checkpoint_manager):
        """Test metrics property returns CheckpointMetrics instance."""
        metrics = checkpoint_manager.metrics
        assert isinstance(metrics, CheckpointMetrics)
        assert metrics == checkpoint_manager._metrics


class TestMetricsIntegration:
    """Test metrics integration in checkpoint operations."""

    @pytest.mark.asyncio
    async def test_save_checkpoint_records_success_metrics(self, checkpoint_manager):
        """Test that successful save records metrics."""
        children_agents = {"test-task": MagicMock()}
        children_configs = {"test-task": SubagentConfig(system_prompt="worker", budget_tokens=10000)}

        # Mock the create_checkpoint_async and storage.save methods
        with patch.object(checkpoint_manager, "create_checkpoint_async", new_callable=AsyncMock) as mock_create:
            mock_checkpoint = MagicMock()
            mock_checkpoint.progress = 0.5
            mock_checkpoint.messages = ["test"]
            mock_create.return_value = mock_checkpoint

            with patch.object(checkpoint_manager._storage, "save", new_callable=AsyncMock):
                initial_save_count = checkpoint_manager.metrics.save_count
                initial_success_count = checkpoint_manager.metrics.save_success_count

                await checkpoint_manager.save_checkpoint_for_task("test-task", children_agents, children_configs)

                # Verify metrics were recorded
                assert checkpoint_manager.metrics.save_count == initial_save_count + 1
                assert checkpoint_manager.metrics.save_success_count == initial_success_count + 1
                assert checkpoint_manager.metrics.save_total_ms > 0
                assert checkpoint_manager.metrics.messages_extracted_count > 0

    @pytest.mark.asyncio
    async def test_save_checkpoint_records_failure_metrics(self, checkpoint_manager):
        """Test that failed save records failure metrics."""
        children_agents = {"test-task": MagicMock()}
        children_configs = {"test-task": SubagentConfig(system_prompt="worker", budget_tokens=10000)}

        # Mock create_checkpoint_async to raise exception
        with patch.object(checkpoint_manager, "create_checkpoint_async", new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = Exception("Test error")

            initial_save_count = checkpoint_manager.metrics.save_count
            initial_failure_count = checkpoint_manager.metrics.save_failure_count

            with pytest.raises(Exception, match="Test error"):
                await checkpoint_manager.save_checkpoint_for_task("test-task", children_agents, children_configs)

            # Verify failure metrics were recorded
            assert checkpoint_manager.metrics.save_count == initial_save_count + 1
            assert checkpoint_manager.metrics.save_failure_count == initial_failure_count + 1

    @pytest.mark.asyncio
    async def test_resume_checkpoint_records_success_metrics(self, checkpoint_manager):
        """Test that successful resume records metrics."""
        mock_checkpoint = MagicMock()
        mock_checkpoint.resumable = True
        mock_checkpoint.agent_type = "worker"
        mock_checkpoint.progress = 0.5
        mock_checkpoint.messages = ["msg1", "msg2"]
        mock_checkpoint.variables = {"key": "value"}
        mock_checkpoint.last_tool = "bash"
        mock_checkpoint.timestamp = 123456.0
        mock_checkpoint.accumulated_runtime_seconds = 0.0

        # Mock storage.load and storage.delete
        with patch.object(checkpoint_manager._storage, "load", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = mock_checkpoint

            with patch.object(checkpoint_manager._storage, "delete", new_callable=AsyncMock):
                initial_resume_count = checkpoint_manager.metrics.resume_count
                initial_success_count = checkpoint_manager.metrics.resume_success_count

                result = await checkpoint_manager.resume_from_checkpoint("test-task")

                # Verify metrics were recorded
                assert checkpoint_manager.metrics.resume_count == initial_resume_count + 1
                assert checkpoint_manager.metrics.resume_success_count == initial_success_count + 1
                assert checkpoint_manager.metrics.resume_total_ms > 0
                assert result.success is True

    @pytest.mark.asyncio
    async def test_resume_checkpoint_records_failure_metrics(self, checkpoint_manager):
        """Test that failed resume records failure metrics."""
        # Mock storage.load to return None (checkpoint not found)
        with patch.object(checkpoint_manager._storage, "load", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = None

            initial_resume_count = checkpoint_manager.metrics.resume_count
            initial_failure_count = checkpoint_manager.metrics.resume_failure_count

            with pytest.raises(ValueError, match="No checkpoint found"):
                await checkpoint_manager.resume_from_checkpoint("test-task")

            # Verify failure metrics were recorded
            assert checkpoint_manager.metrics.resume_count == initial_resume_count + 1
            assert checkpoint_manager.metrics.resume_failure_count == initial_failure_count + 1


class TestMetricsExport:
    """Test metrics export functionality."""

    def test_metrics_to_dict(self, checkpoint_manager):
        """Test metrics can be exported to dict."""
        # Set some metrics
        checkpoint_manager._metrics.save_count = 10
        checkpoint_manager._metrics.save_success_count = 9
        checkpoint_manager._metrics.save_failure_count = 1
        checkpoint_manager._metrics.save_total_ms = 5000.0

        metrics_dict = checkpoint_manager.metrics.to_dict()

        assert metrics_dict["save_count"] == 10
        assert metrics_dict["save_success_count"] == 9
        assert metrics_dict["save_failure_count"] == 1
        assert metrics_dict["save_success_rate"] == 0.9
        assert metrics_dict["save_avg_ms"] == 500.0
        assert metrics_dict["save_total_ms"] == 5000.0
