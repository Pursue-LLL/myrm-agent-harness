"""Tests for context_metrics instance-level monitoring."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.instance_metrics import (
    ContextMetrics,
    get_context_metrics,
    record_batch_query,
    record_cleanup,
    record_cleanup_active_sessions,
    record_cleanup_duration,
    record_cleanup_phase_duration,
    record_compression,
    record_decompression,
    record_file_access,
    record_offload_failure,
    record_offload_success,
    record_protection_rule_hit,
    record_quota_check,
    record_quota_exceeded,
    record_quota_usage,
    record_tracker_statistics,
    set_context_metrics,
)


class TestContextMetrics:
    """Test ContextMetrics instance-level data collection."""

    def test_initial_state(self) -> None:
        """Test metrics initial state is clean."""
        metrics = ContextMetrics()

        assert metrics.offload_operation_count == 0
        assert metrics.compression_count == 0
        assert metrics.decompression_operation_count == 0
        assert metrics.file_access_count == 0
        assert len(metrics.batch_query_count) == 0  # defaultdict, check empty

        # Properties
        assert metrics.offload_avg_duration_ms == 0.0
        assert metrics.offload_avg_bytes == 0.0
        assert metrics.compression_avg_ratio == 0.0
        assert metrics.decompression_success_rate == 1.0

    def test_record_offload_success(self) -> None:
        """Test recording successful offload operation."""
        metrics = ContextMetrics()

        metrics.record_offload_success(
            tool_name="web_fetch",
            content_bytes=10000,
            duration_ms=50.5,
        )

        assert metrics.offload_operation_count == 1
        assert metrics.offload_count[("web_fetch", "success")] == 1
        assert metrics.offload_count[("*", "success")] == 1
        assert metrics.offload_total_bytes == 10000
        assert metrics.offload_total_duration_ms == 50.5
        assert metrics.offload_avg_duration_ms == 50.5
        assert metrics.offload_avg_bytes == 10000.0

    def test_record_offload_failure(self) -> None:
        """Test recording failed offload operation."""
        metrics = ContextMetrics()

        metrics.record_offload_failure(tool_name="web_fetch")

        assert metrics.offload_operation_count == 1
        assert metrics.offload_count[("web_fetch", "failure")] == 1
        assert metrics.offload_count[("*", "failure")] == 1
        assert metrics.offload_total_bytes == 0
        assert metrics.offload_total_duration_ms == 0.0

    def test_record_compression(self) -> None:
        """Test recording compression operation."""
        metrics = ContextMetrics()

        metrics.record_compression(
            original_bytes=10000,
            compressed_bytes=2000,
            duration_ms=25.5,
        )

        assert metrics.compression_count == 1
        assert metrics.compression_total_duration_ms == 25.5
        assert len(metrics.compression_ratios) == 1
        assert metrics.compression_ratios[0] == 5.0  # 10000 / 2000
        assert metrics.compression_bytes_saved == 8000
        assert metrics.compression_avg_ratio == 5.0

    def test_record_decompression_success(self) -> None:
        """Test recording successful decompression."""
        metrics = ContextMetrics()

        metrics.record_decompression(
            duration_ms=15.0,
            success=True,
        )

        assert metrics.decompression_operation_count == 1
        assert metrics.decompression_count["success"] == 1
        assert metrics.decompression_total_duration_ms == 15.0
        assert metrics.decompression_success_rate == 1.0

    def test_record_decompression_failure(self) -> None:
        """Test recording failed decompression."""
        metrics = ContextMetrics()

        metrics.record_decompression(
            duration_ms=5.0,
            success=False,
        )

        assert metrics.decompression_operation_count == 1
        assert metrics.decompression_count["failure"] == 1
        # Failed decompression should NOT add to total_duration
        assert metrics.decompression_total_duration_ms == 0.0
        assert metrics.decompression_success_rate == 0.0

    def test_record_cleanup_basic(self) -> None:
        """Test recording basic cleanup operations."""
        metrics = ContextMetrics()

        metrics.record_cleanup(cleanup_type="lru", files_removed=10)
        metrics.record_cleanup(cleanup_type="orphan", files_removed=5)

        assert metrics.cleanup_count["lru"] == 1
        assert metrics.cleanup_count["orphan"] == 1
        assert metrics.cleanup_files_removed == [10, 5]

    def test_record_cleanup_duration(self) -> None:
        """Test recording cleanup duration accumulates total."""
        metrics = ContextMetrics()

        metrics.record_cleanup_duration("lru", 150.0)
        metrics.record_cleanup_duration("orphan", 80.0)

        # cleanup_total_duration_ms accumulates across all types
        assert metrics.cleanup_total_duration_ms == 230.0

    def test_record_cleanup_phase_duration(self) -> None:
        """Test recording cleanup phase durations."""
        metrics = ContextMetrics()

        metrics.record_cleanup_phase_duration("scan", 50.0)
        metrics.record_cleanup_phase_duration("remove", 100.0)
        metrics.record_cleanup_phase_duration("scan", 60.0)

        assert metrics.cleanup_phase_durations_ms["scan"] == [50.0, 60.0]
        assert metrics.cleanup_phase_durations_ms["remove"] == [100.0]

    def test_record_file_access(self) -> None:
        """Test recording file access operations."""
        metrics = ContextMetrics()

        metrics.record_file_access()
        metrics.record_file_access()
        metrics.record_file_access()

        assert metrics.file_access_count == 3

    def test_record_tracker_statistics(self) -> None:
        """Test recording tracker statistics."""
        metrics = ContextMetrics()

        metrics.record_tracker_statistics(access_tracker_records=100)

        assert metrics.file_access_tracker_records == [100]

    def test_record_quota_check_allowed(self) -> None:
        """Test recording quota check - allowed."""
        metrics = ContextMetrics()

        metrics.record_quota_check(allowed=True)

        assert metrics.quota_check_count["allowed"] == 1
        assert metrics.quota_check_count["denied"] == 0

    def test_record_quota_check_denied(self) -> None:
        """Test recording quota check - denied."""
        metrics = ContextMetrics()

        metrics.record_quota_check(allowed=False)

        assert metrics.quota_check_count["allowed"] == 0
        assert metrics.quota_check_count["denied"] == 1

    def test_record_quota_usage(self) -> None:
        """Test recording quota usage."""
        metrics = ContextMetrics()

        metrics.record_quota_usage(5000)
        metrics.record_quota_usage(8000)

        assert metrics.quota_usage_bytes == [5000, 8000]

    def test_record_quota_exceeded(self) -> None:
        """Test recording quota exceeded event."""
        metrics = ContextMetrics()

        metrics.record_quota_exceeded()
        metrics.record_quota_exceeded()

        assert metrics.quota_exceeded_count == 2

    def test_record_protection_rule_hit(self) -> None:
        """Test recording protection rule hits."""
        metrics = ContextMetrics()

        metrics.record_protection_rule_hit("session_active")
        metrics.record_protection_rule_hit("access_tracked")
        metrics.record_protection_rule_hit("session_active")

        assert metrics.protection_rule_hits["session_active"] == 2
        assert metrics.protection_rule_hits["access_tracked"] == 1

    def test_record_cleanup_active_sessions(self) -> None:
        """Test recording cleanup of active session list."""
        metrics = ContextMetrics()

        metrics.record_cleanup_active_sessions(count=50)
        metrics.record_cleanup_active_sessions(count=75)

        assert len(metrics.cleanup_active_sessions) == 2
        assert metrics.cleanup_active_sessions == [50, 75]

    def test_record_batch_query(self) -> None:
        """Test recording batch query operation."""
        metrics = ContextMetrics()

        metrics.record_batch_query(
            query_type="file_access",
            item_count=50,
            duration_ms=120.0,
        )

        assert metrics.batch_query_count["file_access"] == 1
        assert metrics.batch_query_sizes["file_access"] == [50]
        assert metrics.batch_query_durations_ms["file_access"] == [120.0]

    def test_to_dict_structure(self) -> None:
        """Test to_dict exports complete structure."""
        metrics = ContextMetrics()

        # Record various operations
        metrics.record_offload_success("tool1", 1000, 10.0)
        metrics.record_compression(5000, 1000, 20.0)
        metrics.record_decompression(5.0, True)
        metrics.record_cleanup("lru", 5)
        metrics.record_file_access()
        metrics.record_quota_check(True)
        metrics.record_batch_query("file_access", 20, 50.0)

        export = metrics.to_dict()

        # Validate top-level keys
        assert "offload" in export
        assert "compression" in export
        assert "decompression" in export
        assert "cleanup" in export
        assert "file_access" in export
        assert "quota" in export
        assert "batch_query" in export

        # Validate offload structure
        assert export["offload"]["total_operations"] == 1
        assert export["offload"]["success_count"] == 1
        assert export["offload"]["total_bytes"] == 1000

        # Validate compression structure
        assert export["compression"]["count"] == 1
        assert export["compression"]["bytes_saved"] == 4000

        # Validate other structures
        assert export["decompression"]["total_operations"] == 1
        assert export["cleanup"]["by_type"]["lru"] == 1
        assert export["file_access"]["count"] == 1
        assert export["quota"]["check_count"]["allowed"] == 1
        assert export["batch_query"]["by_type"]["file_access"]["count"] == 1

    def test_memory_limit_mechanism(self) -> None:
        """Test memory limit prevents unbounded list growth."""
        metrics = ContextMetrics()

        # Record 1100 compression operations (exceeds MAX_LIST_SIZE=1000)
        for i in range(1100):
            metrics.record_compression(
                original_bytes=10000 + i,
                compressed_bytes=2000,
                duration_ms=float(i % 100),
            )

        # List should be trimmed to around TRIM_TO_SIZE (500)
        assert len(metrics.compression_ratios) <= 1000
        assert len(metrics.compression_ratios) >= 400  # Should be close to TRIM_TO_SIZE

        # Most recent values should be preserved
        # Last compression had ratio: (10000 + 1099) / 2000 = ~5.55
        assert metrics.compression_ratios[-1] == pytest.approx((10000 + 1099) / 2000, rel=0.01)

    def test_quota_usage_list_memory_limit(self) -> None:
        """Test quota usage lists are memory-limited."""
        metrics = ContextMetrics()

        for i in range(1100):
            metrics.record_quota_usage(1000 + i)

        assert len(metrics.quota_usage_bytes) <= 1000
        assert len(metrics.quota_usage_bytes) >= 400

    def test_cleanup_files_removed_memory_limit(self) -> None:
        """Test cleanup files removed list is memory-limited."""
        metrics = ContextMetrics()

        for i in range(1100):
            metrics.record_cleanup(cleanup_type="lru", files_removed=i % 20)

        assert len(metrics.cleanup_files_removed) <= 1000
        assert len(metrics.cleanup_files_removed) >= 400


class TestContextMetricsContextvars:
    """Test contextvars propagation for async-safe metrics."""

    def test_set_and_get_context_metrics(self) -> None:
        """Test setting and getting metrics via contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        retrieved = get_context_metrics()
        assert retrieved is metrics

    def test_get_context_metrics_not_set(self) -> None:
        """Test getting metrics when not set returns None."""
        # Clear any existing context
        set_context_metrics(None)

        retrieved = get_context_metrics()
        assert retrieved is None

    async def test_contextvars_propagation_in_async(self) -> None:
        """Test metrics propagate correctly in async context."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        async def inner_function() -> ContextMetrics | None:
            return get_context_metrics()

        retrieved = await inner_function()
        assert retrieved is metrics


class TestModuleLevelWrappers:
    """Test backward-compatible module-level wrapper functions."""

    def test_record_offload_success_wrapper(self) -> None:
        """Test record_offload_success wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_offload_success("test_tool", 5000, 0.1)  # 0.1 seconds

        assert metrics.offload_operation_count == 1
        assert metrics.offload_count[("test_tool", "success")] == 1
        assert metrics.offload_total_duration_ms == pytest.approx(100.0, rel=0.01)

    def test_record_offload_failure_wrapper(self) -> None:
        """Test record_offload_failure wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_offload_failure("test_tool")

        assert metrics.offload_operation_count == 1
        assert metrics.offload_count[("test_tool", "failure")] == 1

    def test_record_compression_wrapper(self) -> None:
        """Test record_compression wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_compression(10000, 2000, 0.05)  # 0.05 seconds

        assert metrics.compression_count == 1
        assert metrics.compression_avg_ratio == 5.0
        assert metrics.compression_total_duration_ms == pytest.approx(50.0, rel=0.01)

    def test_record_decompression_wrapper(self) -> None:
        """Test record_decompression wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_decompression(0.02, True)  # 0.02 seconds

        assert metrics.decompression_operation_count == 1
        assert metrics.decompression_count["success"] == 1
        assert metrics.decompression_total_duration_ms == pytest.approx(20.0, rel=0.01)

    def test_record_cleanup_wrapper(self) -> None:
        """Test record_cleanup wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_cleanup("lru", 10)

        assert metrics.cleanup_count["lru"] == 1
        assert metrics.cleanup_files_removed == [10]

    def test_record_cleanup_duration_wrapper(self) -> None:
        """Test record_cleanup_duration wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_cleanup_duration("lru", 0.15)  # 0.15 seconds

        assert metrics.cleanup_total_duration_ms == pytest.approx(150.0, rel=0.01)

    def test_record_cleanup_phase_duration_wrapper(self) -> None:
        """Test record_cleanup_phase_duration wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_cleanup_phase_duration("scan", 0.05)  # 0.05 seconds

        assert metrics.cleanup_phase_durations_ms["scan"] == [pytest.approx(50.0, rel=0.01)]

    def test_record_file_access_wrapper(self) -> None:
        """Test record_file_access wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_file_access()
        record_file_access()

        assert metrics.file_access_count == 2

    def test_record_quota_check_wrapper(self) -> None:
        """Test record_quota_check wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_quota_check(True)

        assert metrics.quota_check_count["allowed"] == 1

    def test_record_quota_usage_wrapper(self) -> None:
        """Test record_quota_usage wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_quota_usage(5000)

        assert metrics.quota_usage_bytes == [5000]

    def test_record_quota_exceeded_wrapper(self) -> None:
        """Test record_quota_exceeded wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_quota_exceeded()

        assert metrics.quota_exceeded_count == 1

    def test_record_batch_query_wrapper(self) -> None:
        """Test record_batch_query wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_batch_query("file_access", 50, 0.1)  # 0.1 seconds

        assert metrics.batch_query_count["file_access"] == 1
        assert metrics.batch_query_sizes["file_access"] == [50]
        assert metrics.batch_query_durations_ms["file_access"] == [pytest.approx(100.0, rel=0.01)]

    def test_record_tracker_statistics_wrapper(self) -> None:
        """Test record_tracker_statistics wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_tracker_statistics(100)

        assert metrics.file_access_tracker_records == [100]

    def test_record_cleanup_active_sessions_wrapper(self) -> None:
        """Test record_cleanup_active_sessions wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_cleanup_active_sessions(50)

        assert len(metrics.cleanup_active_sessions) == 1
        assert metrics.cleanup_active_sessions == [50]

    def test_record_protection_rule_hit_wrapper(self) -> None:
        """Test record_protection_rule_hit wrapper uses contextvars."""
        metrics = ContextMetrics()
        set_context_metrics(metrics)

        record_protection_rule_hit("session_active")

        assert metrics.protection_rule_hits["session_active"] == 1

    def test_wrappers_no_metrics_graceful(self) -> None:
        """Test wrapper functions gracefully handle missing metrics."""
        set_context_metrics(None)

        # Should not raise exceptions
        record_offload_success("tool", 1000, 0.01)
        record_offload_failure("tool")
        record_compression(5000, 1000, 0.02)
        record_decompression(0.005, True)
        record_cleanup("lru", 5)
        record_cleanup_duration("lru", 0.15)
        record_cleanup_phase_duration("scan", 0.05)
        record_file_access()
        record_quota_check(True)
        record_quota_usage(5000)
        record_quota_exceeded()
        record_batch_query("file_access", 20, 0.05)
        record_tracker_statistics(100)
        record_cleanup_active_sessions(50)
        record_protection_rule_hit("session_active")


class TestMemoryLimits:
    """Test memory limit mechanism for unbounded lists."""

    def test_compression_ratios_trimming(self) -> None:
        """Test compression_ratios list is trimmed at MAX_LIST_SIZE."""
        metrics = ContextMetrics()

        # Record exactly MAX_LIST_SIZE operations
        for _i in range(1000):
            metrics.record_compression(10000, 2000, 10.0)

        assert len(metrics.compression_ratios) == 1000

        # Add one more to trigger trim
        metrics.record_compression(10000, 2000, 10.0)

        # Should be trimmed to around TRIM_TO_SIZE (500)
        assert len(metrics.compression_ratios) <= 1000
        assert len(metrics.compression_ratios) >= 400

    def test_quota_lists_trimming(self) -> None:
        """Test quota usage bytes list is trimmed at MAX_LIST_SIZE."""
        metrics = ContextMetrics()

        for i in range(1100):
            metrics.record_quota_usage(1000 + i)

        assert len(metrics.quota_usage_bytes) <= 1000
        assert len(metrics.quota_usage_bytes) >= 400

    def test_cleanup_lists_trimming(self) -> None:
        """Test cleanup lists are trimmed at MAX_LIST_SIZE."""
        metrics = ContextMetrics()

        for i in range(1100):
            metrics.record_cleanup("lru", i % 20)

        assert len(metrics.cleanup_files_removed) <= 1000
        assert len(metrics.cleanup_files_removed) >= 400

    def test_cleanup_phase_durations_trimming(self) -> None:
        """Test cleanup phase duration lists are trimmed at MAX_LIST_SIZE."""
        metrics = ContextMetrics()

        for i in range(1100):
            metrics.record_cleanup_phase_duration("scan", float(i % 50))

        assert len(metrics.cleanup_phase_durations_ms["scan"]) <= 1000
        assert len(metrics.cleanup_phase_durations_ms["scan"]) >= 400

    def test_batch_query_lists_trimming(self) -> None:
        """Test batch query lists are trimmed at MAX_LIST_SIZE."""
        metrics = ContextMetrics()

        for i in range(1100):
            metrics.record_batch_query("file_access", 50 + i, 100.0)

        assert len(metrics.batch_query_sizes["file_access"]) <= 1000
        assert len(metrics.batch_query_durations_ms["file_access"]) <= 1000

    def test_trim_preserves_most_recent(self) -> None:
        """Test trimming preserves most recent values."""
        metrics = ContextMetrics()

        # Add 1100 distinct values
        for i in range(1100):
            metrics.record_compression(10000 + i, 2000, 10.0)

        # Last value should be preserved
        expected_last_ratio = (10000 + 1099) / 2000
        assert metrics.compression_ratios[-1] == pytest.approx(expected_last_ratio, rel=0.01)

        # First values should be trimmed (oldest removed)
        # The list should contain recent 500-ish values
        # So the first value in list should be from iteration ~600 onwards
        first_ratio_in_list = metrics.compression_ratios[0]
        # This should NOT be from iteration 0 (ratio ~5.0)
        assert first_ratio_in_list > 5.1  # Should be from later iterations


class TestComputedProperties:
    """Test computed properties return correct values."""

    def test_offload_avg_duration_multiple_operations(self) -> None:
        """Test offload average duration with multiple operations."""
        metrics = ContextMetrics()

        metrics.record_offload_success("tool1", 1000, 10.0)
        metrics.record_offload_success("tool2", 2000, 30.0)
        metrics.record_offload_failure("tool3")  # No duration for failure

        # Average: (10.0 + 30.0) / 3 = 13.33ms
        assert metrics.offload_avg_duration_ms == pytest.approx(13.33, rel=0.01)

    def test_offload_avg_bytes_multiple_operations(self) -> None:
        """Test offload average bytes with multiple operations."""
        metrics = ContextMetrics()

        metrics.record_offload_success("tool1", 1000, 10.0)
        metrics.record_offload_success("tool2", 2000, 20.0)
        metrics.record_offload_success("tool3", 3000, 30.0)

        # Average: (1000 + 2000 + 3000) / 3 = 2000
        assert metrics.offload_avg_bytes == 2000.0

    def test_compression_avg_ratio_multiple_operations(self) -> None:
        """Test compression average ratio with multiple operations."""
        metrics = ContextMetrics()

        metrics.record_compression(10000, 2000, 10.0)  # ratio=5.0
        metrics.record_compression(8000, 4000, 15.0)  # ratio=2.0
        metrics.record_compression(6000, 3000, 12.0)  # ratio=2.0

        # Average: (5.0 + 2.0 + 2.0) / 3 = 3.0
        assert metrics.compression_avg_ratio == pytest.approx(3.0, rel=0.01)

    def test_decompression_success_rate_mixed(self) -> None:
        """Test decompression success rate with mixed results."""
        metrics = ContextMetrics()

        metrics.record_decompression(5.0, True)
        metrics.record_decompression(5.0, True)
        metrics.record_decompression(5.0, True)
        metrics.record_decompression(5.0, False)

        # 3 success / 4 total = 0.75
        assert metrics.decompression_success_rate == pytest.approx(0.75, rel=0.01)

    def test_cleanup_avg_files_removed_multiple(self) -> None:
        """Test cleanup average files removed with multiple operations."""
        metrics = ContextMetrics()

        metrics.record_cleanup("lru", 10)
        metrics.record_cleanup("orphan", 20)
        metrics.record_cleanup("lru", 30)

        # Average: (10 + 20 + 30) / 3 = 20.0
        assert metrics.cleanup_avg_files_removed == pytest.approx(20.0, rel=0.01)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_compression_zero_compressed_bytes(self) -> None:
        """Test compression with zero compressed bytes (avoids division by zero)."""
        metrics = ContextMetrics()

        metrics.record_compression(10000, 0, 20.0)

        # Should not add ratio (would be infinite)
        assert len(metrics.compression_ratios) == 0
        assert metrics.compression_bytes_saved == 10000

    def test_compression_negative_bytes_saved(self) -> None:
        """Test compression where compressed > original (expansion)."""
        metrics = ContextMetrics()

        metrics.record_compression(1000, 2000, 10.0)

        # Ratio is recorded (0.5 compression/expansion)
        assert len(metrics.compression_ratios) == 1
        assert metrics.compression_ratios[0] == 0.5

        # Bytes saved should be 0 (not negative)
        assert metrics.compression_bytes_saved == 0

    def test_multiple_offload_tools(self) -> None:
        """Test offload tracking across multiple tools."""
        metrics = ContextMetrics()

        metrics.record_offload_success("tool_a", 1000, 10.0)
        metrics.record_offload_success("tool_b", 2000, 20.0)
        metrics.record_offload_failure("tool_a")

        assert metrics.offload_operation_count == 3
        assert metrics.offload_count[("tool_a", "success")] == 1
        assert metrics.offload_count[("tool_a", "failure")] == 1
        assert metrics.offload_count[("tool_b", "success")] == 1
        assert metrics.offload_count[("*", "success")] == 2
        assert metrics.offload_count[("*", "failure")] == 1

    def test_cleanup_multiple_phase_durations(self) -> None:
        """Test cleanup records multiple phases correctly."""
        metrics = ContextMetrics()

        metrics.record_cleanup_phase_duration("scan", 50.0)
        metrics.record_cleanup_phase_duration("filter", 30.0)
        metrics.record_cleanup_phase_duration("remove", 100.0)
        metrics.record_cleanup_phase_duration("scan", 40.0)
        metrics.record_cleanup_phase_duration("remove", 80.0)

        assert len(metrics.cleanup_phase_durations_ms["scan"]) == 2
        assert len(metrics.cleanup_phase_durations_ms["filter"]) == 1
        assert len(metrics.cleanup_phase_durations_ms["remove"]) == 2
        assert metrics.cleanup_phase_durations_ms["scan"] == [50.0, 40.0]

    def test_decompression_failure_no_duration(self) -> None:
        """Test that failed decompression does not add to total duration."""
        metrics = ContextMetrics()

        metrics.record_decompression(100.0, success=False)

        assert metrics.decompression_operation_count == 1
        assert metrics.decompression_total_duration_ms == 0.0
