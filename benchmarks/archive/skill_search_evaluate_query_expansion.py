"""Query Expansion Quality Evaluation Script

Evaluates the impact of query expansion on search quality.
Compares BM25 with and without query expansion.

Usage:
    python -m tests.agent.meta_tools.skill_search.evaluate_query_expansion
"""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.skills.search.engine import SkillSearchEngine
from tests.agent.meta_tools.skill_search.evaluator import SearchEvaluator
from tests.agent.meta_tools.skill_search.fixtures import create_comprehensive_mock_skills
from tests.agent.meta_tools.skill_search.golden_dataset import GOLDEN_DATASET


def main() -> None:
    """Main evaluation function"""
    print("=" * 100)
    print("QUERY EXPANSION EVALUATION")
    print("=" * 100)

    print("\nCreating mock skills...")
    skills = create_comprehensive_mock_skills()
    print(f"Created {len(skills)} mock skills")

    print("\nInitializing search engines...")
    engine_no_expand = SkillSearchEngine(skills, enable_query_expansion=False)
    engine_with_expand = SkillSearchEngine(skills, enable_query_expansion=True)

    print(f"\nEvaluating {len(GOLDEN_DATASET)} queries...\n")

    evaluator = SearchEvaluator(dataset=GOLDEN_DATASET)

    print("=" * 100)
    print("STEP 1: BM25 Without Query Expansion")
    print("=" * 100)
    baseline_result = evaluator.evaluate(lambda q: engine_no_expand.search_bm25(q, top_k=10))
    print("\nBaseline Results (No Expansion):")
    baseline_result.print_report(detailed=False)

    print("\n" + "=" * 100)
    print("STEP 2: BM25 With Query Expansion")
    print("=" * 100)
    improved_result = evaluator.evaluate(lambda q: engine_with_expand.search_bm25(q, top_k=10))
    print("\nImproved Results (With Expansion):")
    improved_result.print_report(detailed=False)

    print("\n" + "=" * 100)
    print("STEP 3: Statistical Significance Testing")
    print("=" * 100)
    print("\nComparing with statistical significance testing...")
    print("(Running 1000 bootstrap samples...)\n")

    significance_tests = evaluator.compare_with_significance(
        baseline_func=lambda q: engine_no_expand.search_bm25(q, top_k=10),
        improved_func=lambda q: engine_with_expand.search_bm25(q, top_k=10),
    )

    for test in significance_tests:
        test.print_report()

    print("\n" + "=" * 100)
    print("STEP 4: Failure Analysis Comparison")
    print("=" * 100)

    baseline_failures = baseline_result.analyze_failures()
    improved_failures = improved_result.analyze_failures()

    print("\nFailure Rate Comparison:")
    print(f"  Without Expansion: {baseline_failures.failure_rate:.1%} ({baseline_failures.total_failures} failures)")
    print(f"  With Expansion: {improved_failures.failure_rate:.1%} ({improved_failures.total_failures} failures)")
    print(f"  Reduction: {baseline_failures.total_failures - improved_failures.total_failures} queries fixed")

    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)

    mrr_improvement = improved_result.metrics["mrr"] - baseline_result.metrics["mrr"]
    map_improvement = improved_result.metrics["map"] - baseline_result.metrics["map"]
    top1_improvement = improved_result.metrics["top1_accuracy"] - baseline_result.metrics["top1_accuracy"]

    print(
        f"\nMRR: {baseline_result.metrics['mrr']:.3f} → {improved_result.metrics['mrr']:.3f} "
        f"({mrr_improvement:+.3f}, {mrr_improvement / baseline_result.metrics['mrr']:+.1%})"
    )
    print(
        f"MAP: {baseline_result.metrics['map']:.3f} → {improved_result.metrics['map']:.3f} "
        f"({map_improvement:+.3f}, {map_improvement / baseline_result.metrics['map']:+.1%})"
    )
    print(
        f"Top-1: {baseline_result.metrics['top1_accuracy']:.1%} → {improved_result.metrics['top1_accuracy']:.1%} "
        f"({top1_improvement:+.1%})"
    )

    sig_count = sum(1 for test in significance_tests if test.is_significant)
    print(f"\nStatistically Significant Improvements: {sig_count}/{len(significance_tests)} metrics")

    if sig_count > 0:
        print(" Query expansion provides statistically significant improvements")
    else:
        print(" Improvements not statistically significant")

    print(f"\nFailure Reduction: {baseline_failures.total_failures - improved_failures.total_failures} queries")

    print("\n" + "=" * 100 + "\n")


if __name__ == "__main__":
    main()
