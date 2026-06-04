"""Category-Level Quality Analysis

Evaluates search quality with detailed breakdown by query category using the
unified SearchEvaluator framework. Identifies strengths and weaknesses across
different types of queries.

Usage:
    python -m tests.agent.meta_tools.skill_search.evaluate_quality
"""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.skills.search.engine import SkillSearchEngine
from tests.agent.meta_tools.skill_search.evaluator import SearchEvaluator
from tests.agent.meta_tools.skill_search.fixtures import create_comprehensive_mock_skills
from tests.agent.meta_tools.skill_search.golden_dataset import GOLDEN_DATASET


def print_category_report(results: dict[str, dict[str, float]]) -> None:
    """Print category breakdown report

    [INPUT]
    - results: Category metrics from evaluate_by_category

    [OUTPUT]
    Formatted console output with overall metrics, category breakdown, and strengths/weaknesses
    """
    print("\n" + "=" * 80)
    print("CATEGORY BREAKDOWN REPORT")
    print("=" * 80)

    overall_mrr = sum(r["mrr"] * r["total"] for r in results.values()) / sum(r["total"] for r in results.values())
    overall_top1 = sum(r["top1"] * r["total"] for r in results.values()) / sum(r["total"] for r in results.values())
    overall_top3 = sum(r["top3"] * r["total"] for r in results.values()) / sum(r["total"] for r in results.values())
    overall_top5 = sum(r["top5"] * r["total"] for r in results.values()) / sum(r["total"] for r in results.values())

    print("\nOVERALL METRICS:")
    print(f"  MRR:            {overall_mrr:.3f}")
    print(f"  Top-1 Accuracy: {overall_top1:.1%}")
    print(f"  Top-3 Accuracy: {overall_top3:.1%}")
    print(f"  Top-5 Accuracy: {overall_top5:.1%}")

    print("\nCATEGORY BREAKDOWN:")
    print(f"{'Category':<20} {'Queries':>7} {'MRR':>7} {'Top-1':>7} {'Top-3':>7} {'Top-5':>7}")
    print("-" * 80)

    for category in sorted(results.keys()):
        metrics = results[category]
        print(
            f"{category:<20} {metrics['total']:>7} {metrics['mrr']:>7.3f} "
            f"{metrics['top1']:>6.1%} {metrics['top3']:>6.1%} {metrics['top5']:>6.1%}"
        )

    print("\nSTRENGTHS (Top-1 > 70%):")
    strong_categories = [(cat, metrics["top1"]) for cat, metrics in results.items() if metrics["top1"] > 0.70]
    if strong_categories:
        for cat, score in sorted(strong_categories, key=lambda x: x[1], reverse=True):
            print(f"  - {cat}: {score:.1%}")
    else:
        print("  None")

    print("\nWEAKNESSES (Top-1 < 40%):")
    weak_categories = [(cat, metrics["top1"]) for cat, metrics in results.items() if metrics["top1"] < 0.40]
    if weak_categories:
        for cat, score in sorted(weak_categories, key=lambda x: x[1]):
            print(f"  - {cat}: {score:.1%}")
    else:
        print("  None")

    print("\n" + "=" * 80 + "\n")


def main() -> None:
    """Main evaluation function with category-level analysis"""
    print("=" * 100)
    print("CATEGORY-LEVEL QUALITY ANALYSIS")
    print("=" * 100)

    print("\nCreating mock skills...")
    skills = create_comprehensive_mock_skills()
    print(f"Created {len(skills)} mock skills")

    print("\nInitializing BM25 search engine...")
    engine = SkillSearchEngine(skills=skills)

    print(f"\nEvaluating {len(GOLDEN_DATASET)} queries by category...")
    evaluator = SearchEvaluator(dataset=GOLDEN_DATASET)
    category_results = evaluator.analyze_by_category(lambda q: engine.search_bm25(q, top_k=10))
    print_category_report(category_results)

    print("\n" + "=" * 100)
    print("RECOMMENDATIONS")
    print("=" * 100)

    weak_categories = [(cat, metrics["top1"]) for cat, metrics in category_results.items() if metrics["top1"] < 0.40]

    if weak_categories:
        print("\nWeak categories detected. Consider:")
        print("  1. Expanding Golden Dataset for weak categories")
        print("  2. Tuning BM25 parameters (k1, b) for specific query types")
        print("  3. Enabling Hybrid mode (BM25+Embedding) for semantic queries")
    else:
        print("\nAll categories performing well (Top-1 >= 40%)")

    print("\n" + "=" * 100 + "\n")


if __name__ == "__main__":
    main()
