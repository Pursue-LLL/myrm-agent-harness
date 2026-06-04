"""Hybrid Mode Quality Evaluation Script

Evaluates Hybrid (BM25+Embedding+RRF) search quality and compares with BM25-only mode.
Requires embedding API access.

Usage:
    python -m tests.agent.meta_tools.skill_search.evaluate_hybrid
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from collections import defaultdict

import numpy as np

from myrm_agent_harness.agent.meta_tools.skills.search.engine import SkillSearchEngine
from myrm_agent_harness.agent.meta_tools.skills.search.hybrid_engine import HybridSkillSearchEngine
from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig
from tests.agent.meta_tools.skill_search.evaluation_models import EvaluationResult, QueryResult
from tests.agent.meta_tools.skill_search.evaluator import SearchEvaluator
from tests.agent.meta_tools.skill_search.fixtures import create_comprehensive_mock_skills
from tests.agent.meta_tools.skill_search.golden_dataset import GOLDEN_DATASET

logger = logging.getLogger(__name__)


async def evaluate_async_engine(
    engine: HybridSkillSearchEngine, dataset: list, k_values: list[int]
) -> EvaluationResult:
    """Evaluate async hybrid engine"""
    reciprocal_ranks = []
    average_precisions = []
    query_results = []
    metrics_at_k = {k: {"hits": 0, "precision": [], "recall": [], "ndcg": []} for k in k_values}

    for golden_query in dataset:
        try:
            results = await engine.search_bm25(golden_query.query, top_k=10)
        except Exception as e:
            logger.warning("Search failed for query %r: %s", golden_query.query, e)
            results = []

        result_names = [r.name if hasattr(r, "name") else r for r in results]
        expected_set = set(golden_query.expected_skills)
        num_expected = len(expected_set)

        # MRR
        first_relevant_rank = None
        for rank, result_name in enumerate(result_names, start=1):
            if result_name in expected_set:
                first_relevant_rank = rank
                reciprocal_ranks.append(1.0 / rank)
                break
        if first_relevant_rank is None:
            reciprocal_ranks.append(0.0)
            first_relevant_rank = None

        # MAP
        relevant_ranks = [rank for rank, result_name in enumerate(result_names, start=1) if result_name in expected_set]
        if relevant_ranks:
            precisions_at_relevant = [
                sum(1 for r in result_names[:rank] if r in expected_set) / rank for rank in relevant_ranks
            ]
            query_ap = sum(precisions_at_relevant) / num_expected
            average_precisions.append(query_ap)
        else:
            average_precisions.append(0.0)

        # Metrics at each K
        relevant_in_top_k_count = 0
        for k in k_values:
            top_k_results = result_names[:k]
            relevant_in_top_k = [r for r in top_k_results if r in expected_set]
            num_relevant_in_top_k = len(relevant_in_top_k)

            if k == k_values[0]:  # Store for QueryResult
                relevant_in_top_k_count = num_relevant_in_top_k

            if num_relevant_in_top_k > 0:
                metrics_at_k[k]["hits"] += 1

            precision = num_relevant_in_top_k / k if k > 0 else 0.0
            metrics_at_k[k]["precision"].append(precision)

            recall = num_relevant_in_top_k / num_expected if num_expected > 0 else 0.0
            metrics_at_k[k]["recall"].append(recall)

            # NDCG@K
            dcg = sum(
                1.0 / math.log2(rank + 1)
                for rank, result_name in enumerate(top_k_results, start=1)
                if result_name in expected_set
            )
            ideal_dcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(k, num_expected) + 1))
            ndcg = dcg / ideal_dcg if ideal_dcg > 0 else 0.0
            metrics_at_k[k]["ndcg"].append(ndcg)

        query_results.append(
            QueryResult(
                query=golden_query.query,
                expected=golden_query.expected_skills,
                retrieved=result_names,
                category=golden_query.category,
                success=bool(first_relevant_rank),
                first_relevant_rank=first_relevant_rank,
                relevant_count=relevant_in_top_k_count,
                average_precision=average_precisions[-1],
            )
        )

    # Build metrics dict
    hybrid_metrics = {
        "mrr": float(np.mean(reciprocal_ranks)) if reciprocal_ranks else 0.0,
        "map": float(np.mean(average_precisions)) if average_precisions else 0.0,
    }
    for k in k_values:
        hybrid_metrics[f"top{k}_accuracy"] = metrics_at_k[k]["hits"] / len(dataset)
        hybrid_metrics[f"precision_at_{k}"] = float(np.mean(metrics_at_k[k]["precision"]))
        hybrid_metrics[f"recall_at_{k}"] = float(np.mean(metrics_at_k[k]["recall"]))
        hybrid_metrics[f"f1_at_{k}"] = (
            2
            * hybrid_metrics[f"precision_at_{k}"]
            * hybrid_metrics[f"recall_at_{k}"]
            / (hybrid_metrics[f"precision_at_{k}"] + hybrid_metrics[f"recall_at_{k}"])
            if (hybrid_metrics[f"precision_at_{k}"] + hybrid_metrics[f"recall_at_{k}"]) > 0
            else 0.0
        )
        hybrid_metrics[f"ndcg_at_{k}"] = float(np.mean(metrics_at_k[k]["ndcg"]))

    return EvaluationResult(
        metrics=hybrid_metrics, query_results=query_results, dataset_size=len(dataset), k_values=k_values
    )


async def analyze_by_category_async(engine: HybridSkillSearchEngine, dataset: list) -> dict[str, dict[str, float]]:
    """Analyze async engine performance by category"""
    category_results = defaultdict(lambda: {"reciprocal_ranks": []})

    for golden_query in dataset:
        category = golden_query.category
        try:
            results = await engine.search_bm25(golden_query.query, top_k=10)
        except Exception as e:
            logger.warning("Search failed for query %r: %s", golden_query.query, e)
            results = []

        result_names = [r.name if hasattr(r, "name") else r for r in results]
        expected_set = set(golden_query.expected_skills)

        # Calculate MRR for this query
        for rank, result_name in enumerate(result_names, start=1):
            if result_name in expected_set:
                category_results[category]["reciprocal_ranks"].append(1.0 / rank)
                break
        else:
            category_results[category]["reciprocal_ranks"].append(0.0)

    # Compute MRR for each category
    return {
        category: {"mrr": float(np.mean(data["reciprocal_ranks"])) if data["reciprocal_ranks"] else 0.0}
        for category, data in category_results.items()
    }


async def main() -> None:
    """Main evaluation function"""
    if not os.getenv("EMBEDDING_API_KEY"):
        print("ERROR: No API key found. Set EMBEDDING_API_KEY environment variable.")
        print("Hybrid evaluation requires embedding API access.")
        return

    print("=" * 100)
    print("HYBRID MODE EVALUATION (BM25+Embedding+RRF)")
    print("=" * 100)

    print("\nCreating mock skills...")
    skills = create_comprehensive_mock_skills()
    print(f"Created {len(skills)} mock skills")

    print("\nInitializing search engines...")
    bm25_engine = SkillSearchEngine(skills=skills)
    config = EmbeddingConfig(
        model=os.getenv("EMBEDDING_MODEL", "openai/BAAI/bge-m3"),
        api_key=os.getenv("EMBEDDING_API_KEY"),
        api_base=os.getenv("EMBEDDING_API_BASE"),
    )
    hybrid_engine = HybridSkillSearchEngine(skills, config)

    print(f"\nEvaluating {len(GOLDEN_DATASET)} queries...")
    print("(This will take a few minutes due to embedding API calls...)\n")

    evaluator = SearchEvaluator(dataset=GOLDEN_DATASET)

    print("=" * 100)
    print("STEP 1: BM25 Mode Evaluation")
    print("=" * 100)
    bm25_result = evaluator.evaluate(lambda q: bm25_engine.search_bm25(q, top_k=10))
    print("\nBM25 Results:")
    bm25_result.print_report(detailed=False)

    print("\n" + "=" * 100)
    print("STEP 2: Hybrid Mode Evaluation")
    print("=" * 100)

    hybrid_result = await evaluate_async_engine(hybrid_engine, GOLDEN_DATASET, evaluator.k_values)
    print("\nHybrid Results:")
    hybrid_result.print_report(detailed=False)

    print("\n" + "=" * 100)
    print("STEP 3: Comparison Analysis")
    print("=" * 100)

    # Simple comparison (statistical significance test requires sync function, skip for now)
    bm25_mrr = bm25_result.metrics["mrr"]
    hybrid_mrr = hybrid_result.metrics["mrr"]
    improvement = (hybrid_mrr - bm25_mrr) / bm25_mrr if bm25_mrr > 0 else 0.0

    print(f"\nBM25 MRR: {bm25_mrr:.3f}")
    print(f"Hybrid MRR: {hybrid_mrr:.3f}")
    print(f"Improvement: {improvement:+.1%}")

    print("\n" + "=" * 100)
    print("STEP 4: Category-Level Analysis")
    print("=" * 100)
    print("\nAnalyzing performance by category...\n")

    bm25_by_category = evaluator.analyze_by_category(lambda q: bm25_engine.search_bm25(q, top_k=10))
    hybrid_by_category = await analyze_by_category_async(hybrid_engine, GOLDEN_DATASET)

    print(f"{'Category':<20} {'BM25 MRR':>12} {'Hybrid MRR':>12} {'Improvement':>12}")
    print("-" * 100)

    improvements = []
    for category in sorted(bm25_by_category.keys()):
        bm25_cat_mrr = bm25_by_category[category]["mrr"]
        hybrid_cat_mrr = hybrid_by_category.get(category, {}).get("mrr", 0.0)
        cat_improvement = (hybrid_cat_mrr - bm25_cat_mrr) / bm25_cat_mrr if bm25_cat_mrr > 0 else 0.0
        improvements.append((category, cat_improvement, bm25_cat_mrr, hybrid_cat_mrr))
        print(f"{category:<20} {bm25_cat_mrr:>12.3f} {hybrid_cat_mrr:>12.3f} {cat_improvement:>11.1%}")

    print("\nBIGGEST IMPROVEMENTS:")
    improvements.sort(key=lambda x: x[1], reverse=True)
    for category, cat_improvement, bm25_cat_mrr, hybrid_cat_mrr in improvements[:5]:
        if cat_improvement > 0:
            print(f"  {category}: {bm25_cat_mrr:.3f} → {hybrid_cat_mrr:.3f} (+{cat_improvement:.1%})")

    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(f"\nBM25 MRR: {bm25_mrr:.3f}")
    print(f"Hybrid MRR: {hybrid_mrr:.3f}")
    print(f"Overall Improvement: {improvement:+.1%}\n")

    # Determine significance based on improvement magnitude
    if improvement > 0.05:
        print(" Hybrid mode provides meaningful improvements (>5%)")
    elif improvement > 0.01:
        print(" Hybrid mode provides marginal improvements (1-5%)")
    else:
        print(" Hybrid mode shows minimal improvements (<1%)")

    print("\n" + "=" * 100 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
