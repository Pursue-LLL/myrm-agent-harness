"""Unit tests for memory health scoring (health.py).

Tests the pure `compute_health` function with various input scenarios:
- Empty system (new user)
- All-fresh / all-stale memories
- With / without graph backend
- Coverage calculation with active/stale memory types
- Retention health via ForgettingStrategy reuse
- Weight auto-adjustment based on graph availability
- Edge cases: single memory, all types empty, etc.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.health import (
    _COHERENCE_SAMPLE_LIMIT,
    _COVERAGE_WINDOW_DAYS,
    _FRESHNESS_WINDOW_DAYS,
    _WEIGHTS_NO_GRAPH,
    _WEIGHTS_WITH_GRAPH,
    _HealthInput,
    compute_health,
)
from myrm_agent_harness.toolkits.memory.strategies.forgetting import ForgettingConfig
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


def _make_memory(
    *, days_ago: int = 0, importance: float = 0.5, last_accessed_days_ago: int | None = None, access_count: int = 5
) -> SemanticMemory:
    now = datetime.now(UTC)
    created = now - timedelta(days=days_ago)
    last_accessed = now - timedelta(days=last_accessed_days_ago) if last_accessed_days_ago is not None else None
    return SemanticMemory(
        content=f"memory created {days_ago} days ago",
        importance=importance,
        created_at=created,
        updated_at=created,
        last_accessed_at=last_accessed,
        access_count=access_count,
    )


class TestEmptySystem:
    def test_empty_returns_100(self) -> None:
        result = compute_health(_HealthInput())
        assert result.total == 100
        assert result.dimensions == {}
        assert result.suggestions == []
        assert result.sample_size == 0

    def test_empty_with_graph(self) -> None:
        result = compute_health(_HealthInput(has_graph=True))
        assert result.total == 100
        assert result.has_graph is True


class TestFreshness:
    def test_all_fresh(self) -> None:
        memories = [_make_memory(days_ago=i) for i in range(10)]
        data = _HealthInput(memories=memories)
        result = compute_health(data)
        assert result.dimensions["freshness"] == 1.0

    def test_all_stale(self) -> None:
        memories = [_make_memory(days_ago=_FRESHNESS_WINDOW_DAYS + i + 1) for i in range(5)]
        data = _HealthInput(memories=memories)
        result = compute_health(data)
        assert result.dimensions["freshness"] == 0.0
        assert any("stale" in s.lower() for s in result.suggestions)

    def test_mixed_freshness(self) -> None:
        fresh = [_make_memory(days_ago=1) for _ in range(3)]
        stale = [_make_memory(days_ago=60) for _ in range(7)]
        data = _HealthInput(memories=fresh + stale)
        result = compute_health(data)
        assert result.dimensions["freshness"] == pytest.approx(0.3, abs=0.01)

    def test_last_accessed_takes_priority(self) -> None:
        mem = _make_memory(days_ago=90, last_accessed_days_ago=1)
        data = _HealthInput(memories=[mem])
        result = compute_health(data)
        assert result.dimensions["freshness"] == 1.0

    def test_naive_datetime_handled(self) -> None:
        mem = _make_memory(days_ago=1)
        mem.created_at = mem.created_at.replace(tzinfo=None)
        mem.last_accessed_at = None
        data = _HealthInput(memories=[mem])
        result = compute_health(data)
        assert result.dimensions["freshness"] == 1.0


class TestCoverage:
    def test_all_types_active(self) -> None:
        now = datetime.now(UTC)
        data = _HealthInput(
            memories=[_make_memory()],
            type_counts={"semantic": 10, "episodic": 5, "profile": 3},
            type_latest_update={
                "semantic": now,
                "episodic": now - timedelta(days=1),
                "profile": now - timedelta(days=3),
            },
        )
        result = compute_health(data)
        assert result.dimensions["coverage"] == 1.0

    def test_all_types_stale(self) -> None:
        old = datetime.now(UTC) - timedelta(days=_COVERAGE_WINDOW_DAYS + 10)
        data = _HealthInput(
            memories=[_make_memory()],
            type_counts={"semantic": 10, "episodic": 5},
            type_latest_update={"semantic": old, "episodic": old},
        )
        result = compute_health(data)
        assert result.dimensions["coverage"] == 0.0
        assert any("lacking recent updates" in s for s in result.suggestions)

    def test_no_type_counts_means_full_coverage(self) -> None:
        data = _HealthInput(memories=[_make_memory()])
        result = compute_health(data)
        assert result.dimensions["coverage"] == 1.0

    def test_partial_coverage(self) -> None:
        now = datetime.now(UTC)
        old = now - timedelta(days=_COVERAGE_WINDOW_DAYS + 5)
        data = _HealthInput(
            memories=[_make_memory()],
            type_counts={"semantic": 10, "episodic": 5},
            type_latest_update={"semantic": now, "episodic": old},
        )
        result = compute_health(data)
        assert result.dimensions["coverage"] == 0.5

    def test_empty_type_ignored(self) -> None:
        now = datetime.now(UTC)
        data = _HealthInput(
            memories=[_make_memory()], type_counts={"semantic": 10, "episodic": 0}, type_latest_update={"semantic": now}
        )
        result = compute_health(data)
        assert result.dimensions["coverage"] == 1.0


class TestRetentionHealth:
    def test_all_safe(self) -> None:
        memories = [_make_memory(importance=0.8, days_ago=5, access_count=10) for _ in range(5)]
        data = _HealthInput(memories=memories)
        result = compute_health(data)
        assert result.dimensions["retention_health"] == 1.0

    def test_all_at_risk(self) -> None:
        memories = [_make_memory(importance=0.01, days_ago=365, access_count=0) for _ in range(5)]
        data = _HealthInput(memories=memories)
        result = compute_health(data)
        assert result.dimensions["retention_health"] < 0.5
        assert any("at risk" in s for s in result.suggestions)

    def test_custom_forgetting_config(self) -> None:
        memories = [_make_memory(importance=0.3, days_ago=60, access_count=2)]
        strict_config = ForgettingConfig(retention_threshold=0.99)
        data = _HealthInput(memories=memories, forgetting_config=strict_config)
        result = compute_health(data)
        assert result.dimensions["retention_health"] == 0.0


class TestCoherence:
    def test_no_graph_skips_coherence(self) -> None:
        data = _HealthInput(memories=[_make_memory()], has_graph=False, coherent_count=5, coherence_sample_size=10)
        result = compute_health(data)
        assert "coherence" not in result.dimensions

    def test_graph_with_zero_sample(self) -> None:
        data = _HealthInput(memories=[_make_memory()], has_graph=True, coherent_count=0, coherence_sample_size=0)
        result = compute_health(data)
        assert "coherence" not in result.dimensions

    def test_full_coherence(self) -> None:
        data = _HealthInput(memories=[_make_memory()], has_graph=True, coherent_count=10, coherence_sample_size=10)
        result = compute_health(data)
        assert result.dimensions["coherence"] == 1.0

    def test_low_coherence_suggests(self) -> None:
        data = _HealthInput(memories=[_make_memory()], has_graph=True, coherent_count=1, coherence_sample_size=10)
        result = compute_health(data)
        assert result.dimensions["coherence"] == 0.1
        assert any("graph connectivity" in s.lower() for s in result.suggestions)


class TestWeightAutoAdjust:
    def test_no_graph_uses_3_weights(self) -> None:
        data = _HealthInput(memories=[_make_memory()], has_graph=False)
        result = compute_health(data)
        assert result.has_graph is False
        for dim in _WEIGHTS_NO_GRAPH:
            assert dim in result.dimensions

    def test_graph_uses_4_weights(self) -> None:
        data = _HealthInput(memories=[_make_memory()], has_graph=True, coherent_count=5, coherence_sample_size=10)
        result = compute_health(data)
        assert result.has_graph is True
        for dim in _WEIGHTS_WITH_GRAPH:
            assert dim in result.dimensions

    def test_weights_sum_to_one(self) -> None:
        assert sum(_WEIGHTS_NO_GRAPH.values()) == pytest.approx(1.0)
        assert sum(_WEIGHTS_WITH_GRAPH.values()) == pytest.approx(1.0)


class TestTotalScore:
    def test_perfect_system_scores_100(self) -> None:
        now = datetime.now(UTC)
        memories = [_make_memory(days_ago=1, importance=0.8, access_count=20) for _ in range(10)]
        data = _HealthInput(memories=memories, type_counts={"semantic": 10}, type_latest_update={"semantic": now})
        result = compute_health(data)
        assert result.total == 100

    def test_score_clamped_0_100(self) -> None:
        data = _HealthInput(memories=[_make_memory()])
        result = compute_health(data)
        assert 0 <= result.total <= 100

    def test_single_memory(self) -> None:
        data = _HealthInput(memories=[_make_memory(days_ago=1)])
        result = compute_health(data)
        assert result.total > 0
        assert result.sample_size == 1


class TestToDict:
    def test_to_dict_returns_new_objects(self) -> None:
        data = _HealthInput(memories=[_make_memory()])
        result = compute_health(data)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["total"] == result.total
        assert d["dimensions"] is not result.dimensions
        assert d["suggestions"] is not result.suggestions
        assert d["has_graph"] == result.has_graph
        assert d["sample_size"] == result.sample_size

    def test_frozen_immutable(self) -> None:
        result = compute_health(_HealthInput())
        with pytest.raises(AttributeError):
            result.total = 50  # type: ignore[misc]


class TestConstants:
    def test_coherence_sample_limit(self) -> None:
        assert _COHERENCE_SAMPLE_LIMIT == 100

    def test_freshness_window(self) -> None:
        assert _FRESHNESS_WINDOW_DAYS == 30

    def test_coverage_window(self) -> None:
        assert _COVERAGE_WINDOW_DAYS == 14
