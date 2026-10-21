"""
[INPUT]: MemoryBackendMetricsRecorder, MemoryBackendKind, MemoryOperationType, RecallPhaseType.
[OUTPUT]: Pytest test suite verifying memories_backend label dimension, opt-in toggle, recall-phase breakdowns, and latency percentiles.
[POS]: myrm-agent-harness/tests/observability/test_memory_backend_metrics.py
"""

import pytest
from myrm_agent_harness.observability.memory_backend_metrics import (
    MemoryBackendKind,
    MemoryBackendMetricsRecorder,
    MemoryOperationType,
    RecallPhaseType,
)


@pytest.fixture
def recorder() -> MemoryBackendMetricsRecorder:
    r = MemoryBackendMetricsRecorder(opt_in_enabled=True)
    r.reset()
    return r


def test_opt_in_toggle_controls_metric_ingestion(recorder: MemoryBackendMetricsRecorder) -> None:
    # 1. Disabled mode
    recorder.configure(opt_in_enabled=False)
    sample_disabled = recorder.record_sample(
        backend=MemoryBackendKind.SQLITE_FTS5,
        operation=MemoryOperationType.RECALL,
        duration_ms=12.5,
    )
    assert sample_disabled is None
    assert recorder.get_report().total_samples == 0

    # 2. Re-enable opt-in
    recorder.configure(opt_in_enabled=True)
    sample_enabled = recorder.record_sample(
        backend=MemoryBackendKind.SQLITE_FTS5,
        operation=MemoryOperationType.RECALL,
        duration_ms=12.5,
    )
    assert sample_enabled is not None
    assert sample_enabled.backend == MemoryBackendKind.SQLITE_FTS5
    assert recorder.get_report().total_samples == 1


def test_multi_backend_and_phase_percentiles(recorder: MemoryBackendMetricsRecorder) -> None:
    # Ingest samples for Qdrant RERANK
    for lat in [10.0, 20.0, 30.0, 40.0, 100.0]:
        recorder.record_sample(
            backend=MemoryBackendKind.QDRANT,
            operation=MemoryOperationType.RECALL,
            phase=RecallPhaseType.RERANK,
            duration_ms=lat,
            success=True,
        )

    # Ingest 1 degraded sample for SQLite FTS5 COLLECT
    recorder.record_sample(
        backend=MemoryBackendKind.SQLITE_FTS5,
        operation=MemoryOperationType.RECALL,
        phase=RecallPhaseType.COLLECT,
        duration_ms=8.0,
        success=True,
        degraded=True,
    )

    report = recorder.get_report()
    assert report.total_samples == 6
    assert len(report.backend_stats) == 2

    # Verify Qdrant RERANK stats
    qdrant_stat = next(
        s for s in report.backend_stats
        if s.backend == MemoryBackendKind.QDRANT and s.phase == RecallPhaseType.RERANK
    )
    assert qdrant_stat.total_operations == 5
    assert qdrant_stat.success_rate == 1.0
    assert qdrant_stat.degraded_count == 0
    assert qdrant_stat.avg_duration_ms == 40.0
    assert qdrant_stat.p50_duration_ms == 30.0
    assert qdrant_stat.p95_duration_ms == 100.0

    # Verify SQLite FTS5 COLLECT stats
    sqlite_stat = next(
        s for s in report.backend_stats
        if s.backend == MemoryBackendKind.SQLITE_FTS5 and s.phase == RecallPhaseType.COLLECT
    )
    assert sqlite_stat.total_operations == 1
    assert sqlite_stat.degraded_count == 1
    assert sqlite_stat.avg_duration_ms == 8.0


def test_reset_and_isolation(recorder: MemoryBackendMetricsRecorder) -> None:
    recorder.record_sample(MemoryBackendKind.IN_MEMORY, MemoryOperationType.RETAIN, 2.0)
    assert recorder.get_report().total_samples == 1

    recorder.reset()
    assert recorder.get_report().total_samples == 0
