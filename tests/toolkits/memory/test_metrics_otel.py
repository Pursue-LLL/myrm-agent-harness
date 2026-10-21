"""Tests for SearchMetrics OTEL integration and snapshot/reset logic."""

from __future__ import annotations

from unittest.mock import MagicMock

from myrm_agent_harness.toolkits.memory.metrics import SearchMetrics, get_search_metrics
from myrm_agent_harness.toolkits.memory.types import MemoryType


class TestSearchMetricsOTEL:
    def test_otel_initialized_or_none(self) -> None:
        metrics = SearchMetrics()
        assert metrics._otel_search_total is None or hasattr(metrics._otel_search_total, "add")

    def test_push_otel_noop_when_none(self) -> None:
        metrics = SearchMetrics()
        metrics._otel_search_total = None
        metrics._push_otel(0, [], 10.0)

    def test_push_otel_with_mock_instruments(self) -> None:
        metrics = SearchMetrics()
        counter = MagicMock()
        histogram = MagicMock()
        metrics._otel_search_total = counter
        metrics._otel_zero_result_total = counter
        metrics._otel_latency_ms = histogram
        metrics._otel_result_score = histogram

        metrics._push_otel(2, [(0.8, "semantic"), (0.6, "episodic")], 15.5)

        counter.add.assert_any_call(1)
        histogram.record.assert_any_call(15.5)
        histogram.record.assert_any_call(0.8, attributes={"memory_type": "semantic"})
        histogram.record.assert_any_call(0.6, attributes={"memory_type": "episodic"})

    def test_push_otel_zero_results(self) -> None:
        metrics = SearchMetrics()
        search_counter = MagicMock()
        zero_counter = MagicMock()
        metrics._otel_search_total = search_counter
        metrics._otel_zero_result_total = zero_counter
        metrics._otel_latency_ms = MagicMock()
        metrics._otel_result_score = MagicMock()

        metrics._push_otel(0, [], 5.0)

        search_counter.add.assert_called_once_with(1)
        zero_counter.add.assert_called_once_with(1)

    def test_push_otel_exception_swallowed(self) -> None:
        metrics = SearchMetrics()
        counter = MagicMock()
        counter.add.side_effect = RuntimeError("OTEL failure")
        metrics._otel_search_total = counter

        metrics._push_otel(1, [(0.5, "semantic")], 10.0)

    def test_init_otel_failure_leaves_none(self) -> None:
        metrics = SearchMetrics()
        metrics._otel_search_total = None
        metrics._otel_zero_result_total = None
        metrics._otel_latency_ms = None
        metrics._otel_result_score = None
        metrics._push_otel(1, [(0.5, "semantic")], 10.0)


class TestSearchMetricsSnapshot:
    def test_snapshot_empty(self) -> None:
        metrics = SearchMetrics()
        snap = metrics.snapshot()
        assert snap.total_searches == 0
        assert snap.zero_result_rate == 0.0
        assert snap.avg_score == 0.0
        assert snap.avg_result_count == 0.0

    def test_snapshot_after_records(self) -> None:
        metrics = SearchMetrics()
        metrics._record(
            result_count=2,
            scored_types=[(0.8, "semantic"), (0.6, "episodic")],
            latency_ms=15.0,
            searched_types=[MemoryType.SEMANTIC, MemoryType.EPISODIC],
            hit_types={"semantic", "episodic"},
        )
        snap = metrics.snapshot()
        assert snap.total_searches == 1
        assert snap.zero_result_count == 0
        assert snap.avg_score == 0.7
        assert snap.min_score == 0.6
        assert snap.max_score == 0.8
        assert snap.avg_result_count == 2.0
        assert "semantic" in snap.hit_rate_by_type
        assert "episodic" in snap.hit_rate_by_type

    def test_snapshot_zero_result(self) -> None:
        metrics = SearchMetrics()
        metrics._record(
            result_count=0, scored_types=[], latency_ms=5.0, searched_types=[MemoryType.SEMANTIC], hit_types=set()
        )
        snap = metrics.snapshot()
        assert snap.zero_result_count == 1
        assert snap.zero_result_rate == 1.0


class TestSearchMetricsReset:
    def test_reset_clears_all(self) -> None:
        metrics = SearchMetrics()
        metrics._record(
            result_count=3,
            scored_types=[(0.9, "semantic")],
            latency_ms=10.0,
            searched_types=[MemoryType.SEMANTIC],
            hit_types={"semantic"},
        )
        metrics.reset()
        snap = metrics.snapshot()
        assert snap.total_searches == 0
        assert snap.zero_result_count == 0
        assert snap.avg_score == 0.0


class TestSearchTracker:
    def test_track_search_records_results(self) -> None:
        metrics = SearchMetrics()
        result = MagicMock()
        result.score = 0.85
        result.memory_type = MemoryType.SEMANTIC

        with metrics.track_search([MemoryType.SEMANTIC]) as tracker:
            tracker.record([result])

        snap = metrics.snapshot()
        assert snap.total_searches == 1
        assert snap.avg_score == 0.85

    def test_track_search_no_record(self) -> None:
        metrics = SearchMetrics()
        with metrics.track_search([MemoryType.SEMANTIC]):
            pass

        snap = metrics.snapshot()
        assert snap.total_searches == 1
        assert snap.zero_result_count == 1

    def test_track_search_double_record_ignored(self) -> None:
        metrics = SearchMetrics()
        result = MagicMock()
        result.score = 0.5
        result.memory_type = MemoryType.SEMANTIC

        with metrics.track_search() as tracker:
            tracker.record([result])
            tracker.record([result])

        snap = metrics.snapshot()
        assert snap.total_searches == 1

    def test_latency_ring_buffer(self) -> None:
        metrics = SearchMetrics(latency_buffer_size=3)
        for i in range(5):
            metrics._record(
                result_count=1,
                scored_types=[(0.5, "semantic")],
                latency_ms=float(i * 10),
                searched_types=[MemoryType.SEMANTIC],
                hit_types={"semantic"},
            )
        snap = metrics.snapshot()
        assert snap.total_searches == 5


class TestCrossSessionHits:
    """Cross-session knowledge transfer hit tracking."""

    def _make_result(self, source_chat_id: str | None = None) -> MagicMock:
        memory = MagicMock()
        memory.source_chat_id = source_chat_id
        result = MagicMock()
        result.score = 0.8
        result.memory_type = MemoryType.SEMANTIC
        result.memory = memory
        return result

    def test_cross_session_hits_counted(self) -> None:
        metrics = SearchMetrics()
        r1 = self._make_result(source_chat_id="chat_A")
        r2 = self._make_result(source_chat_id="chat_B")
        r3 = self._make_result(source_chat_id="chat_B")

        with metrics.track_search([MemoryType.SEMANTIC], current_chat_id="chat_B") as tracker:
            tracker.record([r1, r2, r3])

        snap = metrics.snapshot()
        assert snap.cross_session_hits == 1
        assert snap.total_sourced_hits == 3
        assert snap.cross_session_hit_rate == round(1 / 3, 4)

    def test_no_current_chat_id_skips_tracking(self) -> None:
        metrics = SearchMetrics()
        r1 = self._make_result(source_chat_id="chat_A")

        with metrics.track_search([MemoryType.SEMANTIC]) as tracker:
            tracker.record([r1])

        snap = metrics.snapshot()
        assert snap.cross_session_hits == 0
        assert snap.total_sourced_hits == 0
        assert snap.cross_session_hit_rate == 0.0

    def test_no_source_chat_id_not_counted(self) -> None:
        metrics = SearchMetrics()
        r1 = self._make_result(source_chat_id=None)
        r2 = self._make_result(source_chat_id="chat_A")

        with metrics.track_search([MemoryType.SEMANTIC], current_chat_id="chat_B") as tracker:
            tracker.record([r1, r2])

        snap = metrics.snapshot()
        assert snap.cross_session_hits == 1
        assert snap.total_sourced_hits == 1

    def test_all_same_session_zero_cross(self) -> None:
        metrics = SearchMetrics()
        r1 = self._make_result(source_chat_id="chat_X")
        r2 = self._make_result(source_chat_id="chat_X")

        with metrics.track_search([MemoryType.SEMANTIC], current_chat_id="chat_X") as tracker:
            tracker.record([r1, r2])

        snap = metrics.snapshot()
        assert snap.cross_session_hits == 0
        assert snap.total_sourced_hits == 2
        assert snap.cross_session_hit_rate == 0.0

    def test_accumulates_across_searches(self) -> None:
        metrics = SearchMetrics()
        r1 = self._make_result(source_chat_id="chat_A")
        r2 = self._make_result(source_chat_id="chat_B")

        with metrics.track_search([MemoryType.SEMANTIC], current_chat_id="chat_B") as tracker:
            tracker.record([r1, r2])

        with metrics.track_search([MemoryType.SEMANTIC], current_chat_id="chat_C") as tracker:
            tracker.record([r1, r2])

        snap = metrics.snapshot()
        assert snap.cross_session_hits == 3
        assert snap.total_sourced_hits == 4

    def test_reset_clears_cross_session(self) -> None:
        metrics = SearchMetrics()
        r1 = self._make_result(source_chat_id="chat_A")

        with metrics.track_search([MemoryType.SEMANTIC], current_chat_id="chat_B") as tracker:
            tracker.record([r1])

        metrics.reset()
        snap = metrics.snapshot()
        assert snap.cross_session_hits == 0
        assert snap.total_sourced_hits == 0
        assert snap.cross_session_hit_rate == 0.0

    def test_finish_without_record_does_not_affect_cross_session(self) -> None:
        """If record() is never called, finish() auto-fires with 0 cross_session."""
        metrics = SearchMetrics()
        with metrics.track_search([MemoryType.SEMANTIC], current_chat_id="chat_X"):
            pass

        snap = metrics.snapshot()
        assert snap.cross_session_hits == 0
        assert snap.total_sourced_hits == 0
        assert snap.total_searches == 1

    def test_concurrent_searches_accumulate_correctly(self) -> None:
        """Multiple parallel searches should safely accumulate counters."""
        import threading

        metrics = SearchMetrics()

        def do_search(chat_id: str) -> None:
            r = MagicMock()
            r.score = 0.7
            r.memory_type = MemoryType.SEMANTIC
            r.memory = MagicMock()
            r.memory.source_chat_id = "chat_origin"
            with metrics.track_search([MemoryType.SEMANTIC], current_chat_id=chat_id) as tracker:
                tracker.record([r])

        threads = [threading.Thread(target=do_search, args=(f"chat_{i}",)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = metrics.snapshot()
        assert snap.cross_session_hits == 20
        assert snap.total_sourced_hits == 20
        assert snap.total_searches == 20

    def test_empty_results_list(self) -> None:
        """Empty results list should not affect cross_session counters."""
        metrics = SearchMetrics()
        with metrics.track_search([MemoryType.SEMANTIC], current_chat_id="chat_A") as tracker:
            tracker.record([])

        snap = metrics.snapshot()
        assert snap.cross_session_hits == 0
        assert snap.total_sourced_hits == 0

    def test_memory_attribute_missing_graceful(self) -> None:
        """Results without .memory attribute should not crash."""
        metrics = SearchMetrics()
        r = MagicMock()
        r.score = 0.5
        r.memory_type = MemoryType.SEMANTIC
        r.memory = None

        with metrics.track_search([MemoryType.SEMANTIC], current_chat_id="chat_X") as tracker:
            tracker.record([r])

        snap = metrics.snapshot()
        assert snap.cross_session_hits == 0
        assert snap.total_sourced_hits == 0


class TestRecordBoostMethods:
    """OTEL recording methods for MemPalace boost counters."""

    def test_record_assistant_reference_query_noop_when_none(self) -> None:
        metrics = SearchMetrics()
        metrics._otel_assistant_reference_query_count = None
        metrics.record_assistant_reference_query()

    def test_record_assistant_reference_query_with_counter(self) -> None:
        metrics = SearchMetrics()
        counter = MagicMock()
        metrics._otel_assistant_reference_query_count = counter
        metrics.record_assistant_reference_query()
        counter.add.assert_called_once_with(1)

    def test_record_two_pass_execution_with_counters(self) -> None:
        metrics = SearchMetrics()
        counter = MagicMock()
        histogram = MagicMock()
        metrics._otel_two_pass_execution_count = counter
        metrics._otel_two_pass_latency_ms = histogram
        metrics.record_two_pass_execution(42.5)
        counter.add.assert_called_once_with(1)
        histogram.record.assert_called_once_with(42.5)

    def test_record_two_pass_execution_noop_when_none(self) -> None:
        metrics = SearchMetrics()
        metrics._otel_two_pass_execution_count = None
        metrics._otel_two_pass_latency_ms = None
        metrics.record_two_pass_execution(10.0)

    def test_record_keyword_boost(self) -> None:
        metrics = SearchMetrics()
        counter = MagicMock()
        metrics._otel_keyword_boost_count = counter
        metrics.record_keyword_boost(3)
        counter.add.assert_called_once_with(3)

    def test_record_keyword_boost_zero_skipped(self) -> None:
        metrics = SearchMetrics()
        counter = MagicMock()
        metrics._otel_keyword_boost_count = counter
        metrics.record_keyword_boost(0)
        counter.add.assert_not_called()

    def test_record_temporal_boost(self) -> None:
        metrics = SearchMetrics()
        counter = MagicMock()
        metrics._otel_temporal_boost_count = counter
        metrics.record_temporal_boost(2)
        counter.add.assert_called_once_with(2)

    def test_record_preference_boost(self) -> None:
        metrics = SearchMetrics()
        counter = MagicMock()
        metrics._otel_preference_boost_count = counter
        metrics.record_preference_boost(5)
        counter.add.assert_called_once_with(5)


class TestStorageMetrics:
    """StorageMetrics accumulation and snapshot."""

    def test_snapshot_empty(self) -> None:
        from myrm_agent_harness.toolkits.memory.metrics import StorageMetrics

        sm = StorageMetrics()
        snap = sm.snapshot()
        assert snap.total_collections == 0
        assert snap.total_documents == 0
        assert snap.total_size_bytes == 0
        assert snap.alert_triggered is False

    def test_record_collection_size(self) -> None:
        from myrm_agent_harness.toolkits.memory.metrics import StorageMetrics

        sm = StorageMetrics()
        sm.record_collection_size("semantic_text-ada-002", 50_000_000, 1000)
        snap = sm.snapshot()
        assert snap.total_collections == 1
        assert snap.total_documents == 1000
        assert snap.total_size_bytes == 50_000_000
        assert "semantic_text-ada-002" in snap.size_by_collection

    def test_record_user_storage(self) -> None:
        from myrm_agent_harness.toolkits.memory.metrics import StorageMetrics

        sm = StorageMetrics()
        sm.record_user_storage("user_123", 120_000_000)
        snap = sm.snapshot()
        assert snap.user_storage_bytes["user_123"] == 120_000_000

    def test_alert_triggers_on_threshold(self) -> None:
        from myrm_agent_harness.toolkits.memory.metrics import StorageMetrics

        sm = StorageMetrics(alert_threshold_gb=0.001)
        sm.record_collection_size("big_collection", 2_000_000, 500)
        snap = sm.snapshot()
        assert snap.alert_triggered is True

    def test_alert_clears_below_threshold(self) -> None:
        from myrm_agent_harness.toolkits.memory.metrics import StorageMetrics

        sm = StorageMetrics(alert_threshold_gb=0.001)
        sm.record_collection_size("big", 2_000_000, 500)
        assert sm.snapshot().alert_triggered is True
        sm.record_collection_size("big", 100, 1)
        assert sm.snapshot().alert_triggered is False

    def test_reset_clears_all(self) -> None:
        from myrm_agent_harness.toolkits.memory.metrics import StorageMetrics

        sm = StorageMetrics()
        sm.record_collection_size("coll", 1000, 10)
        sm.record_user_storage("user", 500)
        sm.reset()
        snap = sm.snapshot()
        assert snap.total_collections == 0
        assert snap.total_documents == 0
        assert snap.user_storage_bytes == {}

    def test_user_storage_alert_warning(self) -> None:
        from myrm_agent_harness.toolkits.memory.metrics import StorageMetrics

        sm = StorageMetrics(alert_threshold_gb=0.001)
        sm.record_user_storage("heavy_user", 2_000_000)


class TestGetStorageMetrics:
    def test_singleton(self) -> None:
        import myrm_agent_harness.toolkits.memory.metrics as mod
        from myrm_agent_harness.toolkits.memory.metrics import get_storage_metrics

        mod._global_storage_metrics = None
        m1 = get_storage_metrics()
        m2 = get_storage_metrics()
        assert m1 is m2
        mod._global_storage_metrics = None


class TestGetSearchMetrics:
    def test_singleton(self) -> None:
        import myrm_agent_harness.toolkits.memory.metrics as mod

        mod._global_metrics = None
        m1 = get_search_metrics()
        m2 = get_search_metrics()
        assert m1 is m2
        mod._global_metrics = None
