"""Tests for IR metric functions in eval.metrics."""

from __future__ import annotations

import pytest

from myrm_agent_harness.eval.metrics import (
    hit_rate,
    latency_percentile,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


class TestRecallAtK:
    def test_full_recall(self) -> None:
        assert recall_at_k(["a", "b", "c"], {"a", "b"}, k=3) == 1.0

    def test_partial_recall(self) -> None:
        assert recall_at_k(["a", "x", "y"], {"a", "b"}, k=3) == 0.5

    def test_zero_recall(self) -> None:
        assert recall_at_k(["x", "y", "z"], {"a", "b"}, k=3) == 0.0

    def test_truncated_at_k(self) -> None:
        assert recall_at_k(["a", "b", "c", "d"], {"c", "d"}, k=2) == 0.0

    def test_empty_gold(self) -> None:
        assert recall_at_k(["a"], set(), k=1) == 0.0

    def test_empty_retrieved(self) -> None:
        assert recall_at_k([], {"a"}, k=3) == 0.0


class TestPrecisionAtK:
    def test_full_precision(self) -> None:
        assert precision_at_k(["a", "b"], {"a", "b", "c"}, k=2) == 1.0

    def test_half_precision(self) -> None:
        assert precision_at_k(["a", "x"], {"a", "b"}, k=2) == 0.5

    def test_zero_precision(self) -> None:
        assert precision_at_k(["x", "y"], {"a"}, k=2) == 0.0

    def test_truncated_at_k(self) -> None:
        assert precision_at_k(["x", "a", "b"], {"a", "b"}, k=1) == 0.0

    def test_k_zero(self) -> None:
        assert precision_at_k(["a"], {"a"}, k=0) == 0.0

    def test_k_negative(self) -> None:
        assert precision_at_k(["a"], {"a"}, k=-1) == 0.0


class TestNdcgAtK:
    def test_perfect_ranking(self) -> None:
        result = ndcg_at_k(["a", "b", "c"], {"a", "b"}, k=3)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_imperfect_ranking(self) -> None:
        result = ndcg_at_k(["x", "a", "b"], {"a", "b"}, k=3)
        assert 0.0 < result < 1.0

    def test_no_relevant(self) -> None:
        assert ndcg_at_k(["x", "y"], {"a"}, k=2) == 0.0

    def test_k_zero(self) -> None:
        assert ndcg_at_k(["a"], {"a"}, k=0) == 0.0

    def test_k_negative(self) -> None:
        assert ndcg_at_k(["a"], {"a"}, k=-1) == 0.0


class TestMRR:
    def test_first_hit(self) -> None:
        assert mrr(["a", "b", "c"], {"a"}) == 1.0

    def test_second_hit(self) -> None:
        assert mrr(["x", "a", "c"], {"a"}) == 0.5

    def test_no_hit(self) -> None:
        assert mrr(["x", "y", "z"], {"a"}) == 0.0


class TestHitRate:
    def test_hit_exists(self) -> None:
        assert hit_rate(["x", "a"], {"a"}, k=2) == 1.0

    def test_no_hit(self) -> None:
        assert hit_rate(["x", "y"], {"a"}, k=2) == 0.0

    def test_hit_beyond_k(self) -> None:
        assert hit_rate(["x", "y", "a"], {"a"}, k=2) == 0.0

    def test_k_zero(self) -> None:
        assert hit_rate(["a"], {"a"}, k=0) == 0.0

    def test_k_negative(self) -> None:
        assert hit_rate(["a"], {"a"}, k=-1) == 0.0


class TestLatencyPercentile:
    def test_median(self) -> None:
        result = latency_percentile([10, 20, 30, 40, 50], 50.0)
        assert result == pytest.approx(30.0, abs=1.0)

    def test_p95(self) -> None:
        values = list(range(1, 101))
        result = latency_percentile(values, 95.0)
        assert result == pytest.approx(95.05, abs=1.0)

    def test_empty(self) -> None:
        assert latency_percentile([], 50.0) == 0.0

    def test_single_value(self) -> None:
        assert latency_percentile([42.0], 99.0) == 42.0
