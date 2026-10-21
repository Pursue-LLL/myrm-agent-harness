"""Evaluation Data Models

Defines data structures for search evaluation results.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class QueryResult:
    """Single query evaluation result

    Attributes:
        query: Original query string
        expected: List of expected skill names
        retrieved: List of retrieved skill names
        category: Query category
        success: Whether query succeeded (has relevant result in top-K)
        first_relevant_rank: Rank of first relevant result (None if no match)
        relevant_count: Number of relevant results in top-K
        average_precision: Average precision for this query (for MAP calculation)
    """

    query: str
    expected: list[str]
    retrieved: list[str]
    category: str
    success: bool
    first_relevant_rank: int | None
    relevant_count: int
    average_precision: float


@dataclass
class FailureAnalysis:
    """Failure analysis result

    Attributes:
        failed_queries: List of failed QueryResult objects
        failure_by_category: Dict mapping category to failure count
        failure_reasons: Dict mapping reason to query list
        total_failures: Total number of failures
        failure_rate: Overall failure rate
    """

    failed_queries: list[QueryResult]
    failure_by_category: dict[str, int]
    failure_reasons: dict[str, list[str]]
    total_failures: int
    failure_rate: float

    def print_report(self) -> None:
        """Print formatted failure analysis report"""
        print("\n" + "=" * 80)
        print("FAILURE ANALYSIS REPORT")
        print("=" * 80)

        print(f"\nTotal Failures: {self.total_failures}")
        print(f"Failure Rate: {self.failure_rate:.1%}")

        print("\nFAILURES BY CATEGORY:")
        for category, count in sorted(self.failure_by_category.items(), key=lambda x: x[1], reverse=True):
            print(f"  {category}: {count}")

        print("\nFAILURE REASONS:")
        for reason, queries in self.failure_reasons.items():
            print(f"\n  {reason} ({len(queries)} queries):")
            for query in queries[:5]:  # Show first 5
                print(f'    - "{query}"')
            if len(queries) > 5:
                print(f"    ... and {len(queries) - 5} more")

        print("\n" + "=" * 80 + "\n")


@dataclass
class SignificanceTest:
    """Statistical significance test result

    Attributes:
        metric_name: Name of the metric being tested
        baseline_mean: Baseline metric value
        improved_mean: Improved metric value
        difference: Absolute difference
        relative_change: Relative change percentage
        confidence_interval: 95% confidence interval for difference
        p_value: p-value from bootstrap test
        is_significant: Whether difference is statistically significant (p < 0.05)
    """

    metric_name: str
    baseline_mean: float
    improved_mean: float
    difference: float
    relative_change: float
    confidence_interval: tuple[float, float]
    p_value: float
    is_significant: bool

    def print_report(self) -> None:
        """Print formatted significance test report"""
        print(f"\n{self.metric_name}:")
        print(f"  Baseline: {self.baseline_mean:.4f}")
        print(f"  Improved: {self.improved_mean:.4f}")
        print(f"  Difference: {self.difference:+.4f} ({self.relative_change:+.1f}%)")
        print(f"  95% CI: [{self.confidence_interval[0]:.4f}, {self.confidence_interval[1]:.4f}]")
        print(f"  p-value: {self.p_value:.4f}")
        print(f"  Significant: {' YES' if self.is_significant else ' NO'}")


@dataclass
class EvaluationResult:
    """Complete evaluation result

    Attributes:
        metrics: Dictionary of metric name to value
        query_results: List of individual QueryResult objects
        dataset_size: Total number of queries evaluated
        k_values: K values used for Top-K metrics
    """

    metrics: dict[str, float]
    query_results: list[QueryResult]
    dataset_size: int
    k_values: list[int] = field(default_factory=lambda: [1, 3, 5, 10])

    def print_report(self, *, detailed: bool = False) -> None:
        """Print formatted evaluation report

        [INPUT]
        - detailed: If True, show Precision/Recall/F1/NDCG breakdown

        [OUTPUT]
        Formatted console output with metrics organized by category
        """
        print("\n" + "=" * 80)
        print("EVALUATION REPORT")
        print("=" * 80)
        print(f"Total Queries: {self.dataset_size}")

        print("\nRANKING METRICS:")
        print(f"  MRR: {self.metrics['mrr']:.3f}")
        print(f"  MAP: {self.metrics.get('map', 0.0):.3f}")

        print("\nTOP-K ACCURACY:")
        for k in self.k_values:
            if f"top{k}_accuracy" in self.metrics:
                print(f"  Top-{k}: {self.metrics[f'top{k}_accuracy']:.1%}")

        if detailed:
            print("\nPRECISION@K:")
            for k in self.k_values:
                if f"precision@{k}" in self.metrics:
                    print(f"  P@{k}: {self.metrics[f'precision@{k}']:.3f}")

            print("\nRECALL@K:")
            for k in self.k_values:
                if f"recall@{k}" in self.metrics:
                    print(f"  R@{k}: {self.metrics[f'recall@{k}']:.3f}")

            print("\nF1@K:")
            for k in self.k_values:
                if f"f1@{k}" in self.metrics:
                    print(f"  F1@{k}: {self.metrics[f'f1@{k}']:.3f}")

            print("\nNDCG@K:")
            for k in self.k_values:
                if f"ndcg@{k}" in self.metrics:
                    print(f"  NDCG@{k}: {self.metrics[f'ndcg@{k}']:.3f}")

        print("=" * 80 + "\n")

    def analyze_failures(self, top_k: int = 5) -> FailureAnalysis:
        """Analyze failed queries

        [INPUT]
        - top_k: Consider query failed if no relevant result in top-K

        [OUTPUT]
        FailureAnalysis object with detailed failure breakdown

        [POS]
        Identifies failure patterns and provides actionable insights for improvement.
        """
        failed_queries = [qr for qr in self.query_results if not qr.success]

        # Count failures by category
        failure_by_category: dict[str, int] = defaultdict(int)
        for qr in failed_queries:
            failure_by_category[qr.category] += 1

        # Classify failure reasons
        failure_reasons: dict[str, list[str]] = {
            "No matches found": [],
            "Relevant result beyond top-K": [],
            "Low ranking (position > 3)": [],
        }

        for qr in failed_queries:
            if qr.first_relevant_rank is None:
                failure_reasons["No matches found"].append(qr.query)
            elif qr.first_relevant_rank > top_k:
                failure_reasons["Relevant result beyond top-K"].append(qr.query)
            elif qr.first_relevant_rank > 3:
                failure_reasons["Low ranking (position > 3)"].append(qr.query)

        return FailureAnalysis(
            failed_queries=failed_queries,
            failure_by_category=dict(failure_by_category),
            failure_reasons=failure_reasons,
            total_failures=len(failed_queries),
            failure_rate=len(failed_queries) / self.dataset_size if self.dataset_size > 0 else 0.0,
        )
