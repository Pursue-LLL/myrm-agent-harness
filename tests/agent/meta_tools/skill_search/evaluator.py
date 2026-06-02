"""Unified Search Evaluation Framework

Provides a comprehensive evaluation framework with:
- Core metrics calculation (MRR, MAP, Top-K, P/R/F1, NDCG)
- Failure analysis (identify and analyze failed queries)
- Statistical significance testing (bootstrap, confidence intervals)
- Baseline comparison (Random, TF-IDF)
- Category-level analysis

Usage:
    evaluator = SearchEvaluator(dataset=GOLDEN_DATASET)
    result = evaluator.evaluate(search_func)
    result.print_report(detailed=True)
    result.analyze_failures()
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np

from .evaluation_models import EvaluationResult, QueryResult, SignificanceTest

if TYPE_CHECKING:
    from collections.abc import Callable

    from .skill_search_golden_dataset import GoldenQuery

logger = logging.getLogger(__name__)


class SearchEvaluator:
    """Unified search evaluation framework

    Provides comprehensive evaluation capabilities including:
    - Core metrics calculation
    - Failure analysis
    - Statistical significance testing
    - Baseline comparison
    - Category-level analysis

    Usage:
        evaluator = SearchEvaluator(dataset=GOLDEN_DATASET)
        result = evaluator.evaluate(search_func)
        result.print_report(detailed=True)
    """

    def __init__(self, dataset: list[GoldenQuery], k_values: list[int] | None = None):
        """Initialize evaluator

        [INPUT]
        - dataset: List of GoldenQuery objects
        - k_values: K values for Top-K metrics (defaults to [1, 3, 5, 10])
        """
        self.dataset = dataset
        self.k_values = k_values or [1, 3, 5, 10]

    def evaluate(self, search_func: Callable[[str], list]) -> EvaluationResult:
        """Evaluate search function with comprehensive metrics

        [INPUT]
        - search_func: Function(query: str) -> list[SkillMetadata | str]

        [OUTPUT]
        EvaluationResult object with metrics and query-level results

        [POS]
        Core evaluation method that calculates all standard metrics and tracks
        individual query results for detailed analysis.
        """
        total_queries = len(self.dataset)
        reciprocal_ranks: list[float] = []
        average_precisions: list[float] = []
        query_results: list[QueryResult] = []

        # Initialize metrics for each K
        metrics_at_k = {k: {"hits": 0, "precision": [], "recall": [], "ndcg": []} for k in self.k_values}

        for golden_query in self.dataset:
            try:
                results = search_func(golden_query.query)
            except Exception as e:
                logger.warning("Search failed for query %r: %s", golden_query.query, e)
                results = []

            result_names = [r.name if hasattr(r, "name") else r for r in results]
            expected_set = set(golden_query.expected_skills)
            num_expected = len(expected_set)

            # MRR: Find first relevant result
            first_relevant_rank = None
            for rank, result_name in enumerate(result_names, start=1):
                if result_name in expected_set:
                    if first_relevant_rank is None:
                        first_relevant_rank = rank
                        reciprocal_ranks.append(1.0 / rank)
                    break
            if first_relevant_rank is None:
                reciprocal_ranks.append(0.0)

            # MAP: Average precision across all relevant results
            relevant_ranks = [
                rank for rank, result_name in enumerate(result_names, start=1) if result_name in expected_set
            ]
            if relevant_ranks:
                precisions_at_relevant = [
                    sum(1 for r in result_names[:rank] if r in expected_set) / rank for rank in relevant_ranks
                ]
                query_ap = sum(precisions_at_relevant) / num_expected
                average_precisions.append(query_ap)
            else:
                query_ap = 0.0
                average_precisions.append(0.0)

            # Metrics at each K
            for k in self.k_values:
                top_k_results = result_names[:k]
                relevant_in_top_k = [r for r in top_k_results if r in expected_set]
                num_relevant_in_top_k = len(relevant_in_top_k)

                # Top-K Accuracy
                if num_relevant_in_top_k > 0:
                    metrics_at_k[k]["hits"] += 1

                # Precision@K
                precision = num_relevant_in_top_k / k if k > 0 else 0.0
                metrics_at_k[k]["precision"].append(precision)

                # Recall@K
                recall = num_relevant_in_top_k / num_expected if num_expected > 0 else 0.0
                metrics_at_k[k]["recall"].append(recall)

                # NDCG@K
                dcg = sum(
                    (1.0 if result_names[i] in expected_set else 0.0) / math.log2(i + 2)
                    for i in range(min(k, len(result_names)))
                )
                ideal_dcg = sum(1.0 / math.log2(i + 2) for i in range(min(k, num_expected)))
                ndcg = dcg / ideal_dcg if ideal_dcg > 0 else 0.0
                metrics_at_k[k]["ndcg"].append(ndcg)

            # Store query result
            query_results.append(
                QueryResult(
                    query=golden_query.query,
                    expected=golden_query.expected_skills,
                    retrieved=result_names[:10],  # Store top-10
                    category=golden_query.category,
                    success=first_relevant_rank is not None and first_relevant_rank <= 5,
                    first_relevant_rank=first_relevant_rank,
                    relevant_count=len([r for r in result_names[:5] if r in expected_set]),
                    average_precision=query_ap,
                )
            )

        # Aggregate metrics
        metrics = {
            "mrr": sum(reciprocal_ranks) / total_queries if total_queries > 0 else 0.0,
            "map": sum(average_precisions) / total_queries if total_queries > 0 else 0.0,
            "total_queries": total_queries,
        }

        # Add metrics for each K
        for k in self.k_values:
            metrics[f"top{k}_accuracy"] = metrics_at_k[k]["hits"] / total_queries if total_queries > 0 else 0.0
            metrics[f"precision@{k}"] = sum(metrics_at_k[k]["precision"]) / total_queries if total_queries > 0 else 0.0
            metrics[f"recall@{k}"] = sum(metrics_at_k[k]["recall"]) / total_queries if total_queries > 0 else 0.0
            metrics[f"ndcg@{k}"] = sum(metrics_at_k[k]["ndcg"]) / total_queries if total_queries > 0 else 0.0

            # F1@K
            precision = metrics[f"precision@{k}"]
            recall = metrics[f"recall@{k}"]
            metrics[f"f1@{k}"] = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        return EvaluationResult(
            metrics=metrics, query_results=query_results, dataset_size=total_queries, k_values=self.k_values
        )

    def compare_with_significance(
        self,
        baseline_func: Callable[[str], list],
        improved_func: Callable[[str], list],
        n_bootstrap: int = 1000,
        alpha: float = 0.05,
    ) -> list[SignificanceTest]:
        """Compare two search functions with statistical significance testing

        [INPUT]
        - baseline_func: Baseline search function
        - improved_func: Improved search function
        - n_bootstrap: Number of bootstrap samples (default: 1000)
        - alpha: Significance level (default: 0.05 for 95% confidence)

        [OUTPUT]
        List of SignificanceTest objects for key metrics (MRR, MAP, Top-1, Top-3)

        [POS]
        Uses bootstrap resampling to compute confidence intervals and p-values,
        providing scientific evidence for whether improvements are statistically significant.
        """
        # Evaluate both functions
        baseline_result = self.evaluate(baseline_func)
        improved_result = self.evaluate(improved_func)

        # Metrics to test
        test_metrics = ["mrr", "map", "top1_accuracy", "top3_accuracy"]
        results = []

        for metric_name in test_metrics:
            baseline_mean = baseline_result.metrics[metric_name]
            improved_mean = improved_result.metrics[metric_name]
            difference = improved_mean - baseline_mean
            relative_change = (difference / baseline_mean * 100) if baseline_mean > 0 else 0.0

            # Bootstrap resampling
            baseline_scores = self._extract_metric_scores(baseline_result, metric_name)
            improved_scores = self._extract_metric_scores(improved_result, metric_name)

            bootstrap_diffs = []
            rng = np.random.default_rng(42)  # Fixed seed for reproducibility

            for _ in range(n_bootstrap):
                # Resample with replacement
                baseline_sample = rng.choice(baseline_scores, size=len(baseline_scores), replace=True)
                improved_sample = rng.choice(improved_scores, size=len(improved_scores), replace=True)

                bootstrap_diffs.append(np.mean(improved_sample) - np.mean(baseline_sample))

            # Confidence interval
            ci_lower = float(np.percentile(bootstrap_diffs, alpha / 2 * 100))
            ci_upper = float(np.percentile(bootstrap_diffs, (1 - alpha / 2) * 100))

            # p-value: proportion of bootstrap samples where difference <= 0
            p_value = float(np.mean(np.array(bootstrap_diffs) <= 0))

            results.append(
                SignificanceTest(
                    metric_name=metric_name.upper(),
                    baseline_mean=baseline_mean,
                    improved_mean=improved_mean,
                    difference=difference,
                    relative_change=relative_change,
                    confidence_interval=(ci_lower, ci_upper),
                    p_value=p_value,
                    is_significant=(p_value < alpha),
                )
            )

        return results

    def _extract_metric_scores(self, result: EvaluationResult, metric_name: str) -> np.ndarray:
        """Extract per-query scores for a given metric

        [INPUT]
        - result: EvaluationResult object
        - metric_name: Name of metric to extract

        [OUTPUT]
        NumPy array of per-query scores
        """
        if metric_name == "mrr":
            scores = [1.0 / qr.first_relevant_rank if qr.first_relevant_rank else 0.0 for qr in result.query_results]
        elif metric_name == "map":
            scores = [qr.average_precision for qr in result.query_results]
        elif metric_name == "top1_accuracy":
            scores = [1.0 if qr.first_relevant_rank == 1 else 0.0 for qr in result.query_results]
        elif metric_name == "top3_accuracy":
            scores = [
                1.0 if qr.first_relevant_rank and qr.first_relevant_rank <= 3 else 0.0 for qr in result.query_results
            ]
        else:
            scores = [0.0] * len(result.query_results)

        return np.array(scores)

    def analyze_by_category(self, search_func: Callable[[str], list]) -> dict[str, dict[str, float]]:
        """Evaluate search quality by category

        [INPUT]
        - search_func: Function(query: str) -> list[SkillMetadata | str]

        [OUTPUT]
        Dictionary mapping category to metrics (mrr, top1, top3, top5, total)

        [POS]
        Breaks down overall performance by query category to identify strengths and weaknesses.
        """
        category_queries: dict[str, list[GoldenQuery]] = defaultdict(list)
        for query in self.dataset:
            category_queries[query.category].append(query)

        results = {}
        for category, queries in category_queries.items():
            category_evaluator = SearchEvaluator(queries, self.k_values)
            category_result = category_evaluator.evaluate(search_func)

            results[category] = {
                "mrr": category_result.metrics["mrr"],
                "top1": category_result.metrics["top1_accuracy"],
                "top3": category_result.metrics["top3_accuracy"],
                "top5": category_result.metrics["top5_accuracy"],
                "total": len(queries),
            }

        return results
