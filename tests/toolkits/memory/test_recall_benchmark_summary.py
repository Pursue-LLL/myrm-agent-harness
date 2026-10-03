"""Tests for enhanced MemoryRecallBenchmarkSummary with IR metrics."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.reliability import (
    MemoryRecallBenchmarkResult,
    summarize_recall_benchmark,
)


class TestSummarizeRecallBenchmark:
    def test_empty_results(self) -> None:
        summary = summarize_recall_benchmark([])
        assert summary.case_count == 0
        assert summary.status == "missing"

    def test_all_cases_pass_rank1(self) -> None:
        results = [
            MemoryRecallBenchmarkResult(
                case_id="c1", expected_found=True, best_rank=1, top_k=5, hit_count=5, score=1.0, latency_ms=10.0
            ),
            MemoryRecallBenchmarkResult(
                case_id="c2", expected_found=True, best_rank=1, top_k=5, hit_count=5, score=1.0, latency_ms=20.0
            ),
        ]
        summary = summarize_recall_benchmark(results)
        assert summary.recall_at_k == 1.0
        assert summary.ndcg_at_k == pytest.approx(1.0, abs=0.01)
        assert summary.mrr_score == pytest.approx(1.0, abs=0.01)
        assert summary.precision_at_k == pytest.approx(0.2, abs=0.01)
        assert summary.status == "ready"
        assert summary.latency_p50_ms > 0
        assert summary.latency_p95_ms > 0

    def test_mixed_results(self) -> None:
        results = [
            MemoryRecallBenchmarkResult(
                case_id="c1", expected_found=True, best_rank=1, top_k=5, hit_count=3, score=1.0, latency_ms=15.0
            ),
            MemoryRecallBenchmarkResult(
                case_id="c2", expected_found=True, best_rank=3, top_k=5, hit_count=5, score=0.33, latency_ms=25.0
            ),
            MemoryRecallBenchmarkResult(
                case_id="c3", expected_found=False, best_rank=None, top_k=5, hit_count=5, score=0.0, latency_ms=30.0
            ),
        ]
        summary = summarize_recall_benchmark(results)
        assert summary.case_count == 3
        assert summary.passed_count == 2
        assert 0.0 < summary.recall_at_k < 1.0
        assert 0.0 < summary.ndcg_at_k < 1.0
        assert 0.0 < summary.mrr_score < 1.0
        assert summary.status == "critical"

    def test_all_cases_fail(self) -> None:
        results = [
            MemoryRecallBenchmarkResult(case_id="c1", expected_found=False, top_k=5, hit_count=0, score=0.0),
        ]
        summary = summarize_recall_benchmark(results)
        assert summary.recall_at_k == 0.0
        assert summary.ndcg_at_k == 0.0
        assert summary.mrr_score == 0.0
        assert summary.precision_at_k == 0.0
        assert summary.status == "critical"

    def test_latency_percentiles_with_no_latency(self) -> None:
        results = [
            MemoryRecallBenchmarkResult(case_id="c1", expected_found=True, best_rank=1, top_k=5, score=1.0),
        ]
        summary = summarize_recall_benchmark(results)
        assert summary.latency_p50_ms == 0.0
        assert summary.latency_p95_ms == 0.0
        assert summary.latency_p99_ms == 0.0

    def test_latency_percentiles_p99(self) -> None:
        """P99 tail latency is surfaced for SLO gating at scale."""
        results = [
            MemoryRecallBenchmarkResult(case_id=f"c{i}", expected_found=True, best_rank=1, top_k=5, score=1.0, latency_ms=10.0)
            for i in range(99)
        ]
        # One extreme outlier defines the tail beyond p95.
        results.append(
            MemoryRecallBenchmarkResult(case_id="c_outlier", expected_found=True, best_rank=1, top_k=5, score=1.0, latency_ms=900.0)
        )
        summary = summarize_recall_benchmark(results)
        # Linear interpolation at k=98.01 lands between idx 98 (10ms) and
        # idx 99 (900ms): 10 + 0.01 * 890 = 18.9 — the outlier drags the tail.
        assert summary.latency_p99_ms == 18.9
        assert summary.latency_p99_ms > summary.latency_p95_ms
        assert summary.latency_p95_ms >= summary.latency_p50_ms
