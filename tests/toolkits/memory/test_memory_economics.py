"""Tests for memory system economics and Omri et al. 2026 telemetry models."""

from __future__ import annotations

from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.observability import (
    MemoryEconomicsSnapshot,
    MemoryPhaseLatency,
    MemoryRecallRoiGrade,
    MemoryTokenAccounting,
)


def test_memory_phase_latency_defaults() -> None:
    latency = MemoryPhaseLatency()
    assert latency.construction_ms == 0.0
    assert latency.retrieval_ms == 0.0
    assert latency.injection_overhead_ms == 0.0
    assert latency.total_wall_clock_ms == 0.0


def test_memory_phase_latency_values() -> None:
    latency = MemoryPhaseLatency(
        construction_ms=450.5,
        retrieval_ms=85.2,
        injection_overhead_ms=12.1,
        total_wall_clock_ms=547.8,
    )
    assert latency.construction_ms == 450.5
    assert latency.retrieval_ms == 85.2
    assert latency.injection_overhead_ms == 12.1
    assert latency.total_wall_clock_ms == 547.8


def test_memory_token_accounting_roi_calculation() -> None:
    accounting = MemoryTokenAccounting(
        injected_memory_tokens=1000,
        effective_cited_tokens=400,
        background_construction_tokens=250,
        cache_preservation_score=0.95,
        roi_percentage=40.0,
        roi_grade=MemoryRecallRoiGrade.HEALTHY,
    )
    assert accounting.injected_memory_tokens == 1000
    assert accounting.effective_cited_tokens == 400
    assert accounting.roi_percentage == 40.0
    assert accounting.roi_grade == MemoryRecallRoiGrade.HEALTHY
    assert accounting.cache_preservation_score == 0.95


def test_memory_economics_snapshot_serialization() -> None:
    now = datetime.now(UTC)
    snapshot = MemoryEconomicsSnapshot(
        id="econ_snap_001",
        correlation_id="corr_12345",
        timestamp=now,
        latency=MemoryPhaseLatency(
            construction_ms=300.0,
            retrieval_ms=50.0,
            injection_overhead_ms=5.0,
            total_wall_clock_ms=355.0,
        ),
        accounting=MemoryTokenAccounting(
            injected_memory_tokens=1200,
            effective_cited_tokens=720,
            background_construction_tokens=180,
            cache_preservation_score=0.88,
            roi_percentage=60.0,
            roi_grade=MemoryRecallRoiGrade.OPTIMAL,
        ),
        parasitic_memory_ids=["mem_stale_1", "mem_stale_2"],
        metadata={"session_id": "sess_abc", "turn_index": 15},
    )

    dumped = snapshot.model_dump(mode="json")
    assert dumped["id"] == "econ_snap_001"
    assert dumped["accounting"]["roi_grade"] == "optimal"
    assert len(dumped["parasitic_memory_ids"]) == 2
    assert dumped["metadata"]["turn_index"] == 15

    # Roundtrip validation
    restored = MemoryEconomicsSnapshot.model_validate(dumped)
    assert restored.id == snapshot.id
    assert restored.accounting.roi_grade == MemoryRecallRoiGrade.OPTIMAL
    assert restored.latency.total_wall_clock_ms == 355.0
