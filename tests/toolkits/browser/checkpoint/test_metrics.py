"""Tests for checkpoint metrics."""

from myrm_agent_harness.toolkits.browser.checkpoint import CheckpointMetrics


class TestCheckpointMetrics:
    """Test checkpoint metrics computation and export."""

    def test_initial_state(self) -> None:
        """Should initialize with zero values."""
        metrics = CheckpointMetrics()

        assert metrics.save_count == 0
        assert metrics.save_total_ms == 0.0
        assert metrics.save_skipped_count == 0
        assert metrics.recovery_count == 0

    def test_save_avg_ms(self) -> None:
        """Should compute average save duration."""
        metrics = CheckpointMetrics()
        metrics.save_count = 10
        metrics.save_total_ms = 500.0

        assert metrics.save_avg_ms == 50.0

    def test_save_avg_ms_zero_division(self) -> None:
        """Should handle zero division for avg_ms."""
        metrics = CheckpointMetrics()

        assert metrics.save_avg_ms == 0.0

    def test_incremental_ratio(self) -> None:
        """Should compute incremental save ratio."""
        metrics = CheckpointMetrics()
        metrics.vault_save_count = 2  # 2 actual SessionVault saves
        metrics.save_skipped_count = 8  # 8 skipped saves

        assert metrics.incremental_ratio == 0.8  # 80% skipped

    def test_incremental_ratio_zero_division(self) -> None:
        """Should handle zero division for ratio."""
        metrics = CheckpointMetrics()

        assert metrics.incremental_ratio == 0.0

    def test_recovery_success_rate(self) -> None:
        """Should compute recovery success rate."""
        metrics = CheckpointMetrics()
        metrics.recovery_count = 7
        metrics.recovery_failures = 3

        assert metrics.recovery_success_rate == 0.7  # 70% success

    def test_recovery_success_rate_zero_division(self) -> None:
        """Should handle zero division for success rate."""
        metrics = CheckpointMetrics()

        assert metrics.recovery_success_rate == 1.0  # 100% when no attempts

    def test_vault_save_avg_ms(self) -> None:
        """Should compute average vault save duration."""
        metrics = CheckpointMetrics()
        metrics.vault_save_count = 5
        metrics.vault_save_total_ms = 150.0

        assert metrics.vault_save_avg_ms == 30.0

    def test_to_dict_complete(self) -> None:
        """Should export complete metrics dictionary."""
        metrics = CheckpointMetrics()
        metrics.save_count = 10
        metrics.save_total_ms = 500.0
        metrics.save_skipped_count = 8
        metrics.recovery_count = 3
        metrics.recovery_total_ms = 600.0
        metrics.recovery_failures = 1
        metrics.vault_save_count = 2
        metrics.vault_save_total_ms = 60.0
        metrics.hash_computations = 10
        metrics.hash_total_ms = 5.0
        metrics.metadata_extractions = 3
        metrics.metadata_extraction_total_ms = 15.0
        metrics.hash_collision_count = 1
        metrics.metadata_missing_count = 2

        result = metrics.to_dict()

        assert result["save_count"] == 10
        assert result["save_avg_ms"] == 50.0
        assert result["save_skipped_count"] == 8
        assert result["incremental_ratio"] == 0.8  # 8/(2+8)
        assert result["recovery_count"] == 3
        assert result["recovery_avg_ms"] == 200.0
        assert result["recovery_success_rate"] == 0.75  # 3/4
        assert result["vault_save_count"] == 2
        assert result["vault_save_avg_ms"] == 30.0
        assert result["hash_avg_ms"] == 0.5
        assert result["metadata_extraction_avg_ms"] == 5.0
        assert result["warnings"]["hash_collisions"] == 1
        assert result["warnings"]["metadata_missing"] == 2

    def test_to_dict_with_zeros(self) -> None:
        """Should handle zero values gracefully."""
        metrics = CheckpointMetrics()

        result = metrics.to_dict()

        assert result["save_avg_ms"] == 0.0
        assert result["recovery_avg_ms"] == 0.0
        assert result["incremental_ratio"] == 0.0
        assert result["recovery_success_rate"] == 1.0
