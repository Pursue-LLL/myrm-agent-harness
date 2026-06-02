"""Information Retrieval metrics — pure functions for scoring ranked results.

[INPUT]
None (zero-dependency pure functions)

[OUTPUT]
- recall_at_k: fraction of gold items found in top-K
- precision_at_k: fraction of top-K that are gold items
- ndcg_at_k: Normalized Discounted Cumulative Gain
- mrr: Mean Reciprocal Rank (reciprocal rank of first gold hit)
- hit_rate: whether ANY gold item appears in top-K (binary 0/1)
- latency_percentile: compute p-th percentile from latency list

[POS]
Generic IR scoring utilities reusable by memory retrieval eval,
search quality benchmarks, or any ranked-result evaluation scenario.
"""

from __future__ import annotations

import math


def recall_at_k(retrieved_ids: list[str], gold_ids: set[str], k: int) -> float:
    """Fraction of gold items found in top-K retrieved results."""
    if not gold_ids or k <= 0:
        return 0.0
    top_k = set(retrieved_ids[:k])
    return len(top_k & gold_ids) / len(gold_ids)


def precision_at_k(retrieved_ids: list[str], gold_ids: set[str], k: int) -> float:
    """Fraction of top-K retrieved results that are gold items."""
    if k <= 0:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for rid in top_k if rid in gold_ids)
    return hits / k


def _dcg(relevances: list[bool], k: int) -> float:
    """Discounted Cumulative Gain for binary relevance."""
    total = 0.0
    for i in range(min(k, len(relevances))):
        if relevances[i]:
            total += 1.0 / math.log2(i + 2)
    return total


def ndcg_at_k(retrieved_ids: list[str], gold_ids: set[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain at K."""
    if not gold_ids or k <= 0:
        return 0.0
    relevances = [rid in gold_ids for rid in retrieved_ids[:k]]
    actual_dcg = _dcg(relevances, k)
    ideal_count = min(k, len(gold_ids))
    ideal_relevances = [True] * ideal_count
    ideal_dcg = _dcg(ideal_relevances, k)
    if ideal_dcg == 0.0:
        return 0.0
    return actual_dcg / ideal_dcg


def mrr(retrieved_ids: list[str], gold_ids: set[str]) -> float:
    """Reciprocal rank of the first gold item in retrieved results."""
    for i, rid in enumerate(retrieved_ids):
        if rid in gold_ids:
            return 1.0 / (i + 1)
    return 0.0


def hit_rate(retrieved_ids: list[str], gold_ids: set[str], k: int) -> float:
    """Binary: 1.0 if ANY gold item appears in top-K, else 0.0."""
    if not gold_ids or k <= 0:
        return 0.0
    top_k = set(retrieved_ids[:k])
    return 1.0 if top_k & gold_ids else 0.0


def latency_percentile(latencies_ms: list[float], percentile: float) -> float:
    """Compute the p-th percentile from a list of latency values (ms).

    Uses nearest-rank method. percentile should be in [0, 100].
    """
    if not latencies_ms:
        return 0.0
    sorted_lat = sorted(latencies_ms)
    idx = max(0, min(len(sorted_lat) - 1, math.ceil(percentile / 100.0 * len(sorted_lat)) - 1))
    return sorted_lat[idx]
