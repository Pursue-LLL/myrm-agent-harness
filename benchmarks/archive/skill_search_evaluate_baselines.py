"""Baseline Comparison with Statistical Significance Testing

Compares BM25 against baseline methods with statistical significance testing:
- Random: Random shuffle (lower bound)
- TF-IDF: Classic information retrieval

Features:
- Side-by-side comparison
- Statistical significance testing (bootstrap)
- Confidence intervals and p-values

Usage:
    python -m tests.agent.meta_tools.skill_search.evaluate_baselines
"""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.skills.search.engine import SkillSearchEngine
from tests.agent.meta_tools.skill_search.baselines import RandomSearchEngine, TFIDFSearchEngine
from tests.agent.meta_tools.skill_search.evaluator import SearchEvaluator
from tests.agent.meta_tools.skill_search.fixtures import create_comprehensive_mock_skills
from tests.agent.meta_tools.skill_search.golden_dataset import GOLDEN_DATASET


def main() -> None:
    """Main evaluation function comparing BM25 against baselines with significance testing"""
    print("=" * 100)
    print("BASELINE COMPARISON WITH STATISTICAL SIGNIFICANCE TESTING")
    print("=" * 100)

    print("\nCreating mock skills...")
    skills = create_comprehensive_mock_skills()
    print(f"Created {len(skills)} mock skills")

    print("\nInitializing search engines...")
    bm25_engine = SkillSearchEngine(skills=skills)
    random_engine = RandomSearchEngine(skills=skills)
    tfidf_engine = TFIDFSearchEngine(skills=skills)

    print(f"\nEvaluating {len(GOLDEN_DATASET)} queries across 3 engines...")
    evaluator = SearchEvaluator(dataset=GOLDEN_DATASET, k_values=[1, 3, 5])

    # Evaluate each engine
    print("\n[1/3] Evaluating Random baseline...")
    random_result = evaluator.evaluate(lambda q: random_engine.search(q, top_k=10))

    print("[2/3] Evaluating TF-IDF baseline...")
    tfidf_result = evaluator.evaluate(lambda q: tfidf_engine.search(q, top_k=10))

    print("[3/3] Evaluating BM25 (production)...")
    bm25_result = evaluator.evaluate(lambda q: bm25_engine.search_bm25(q, top_k=10))

    # Print comparison table
    print("\n" + "=" * 100)
    print("COMPARISON RESULTS")
    print("=" * 100)

    print(f"\n{'Metric':<20} {'Random':<15} {'TF-IDF':<15} {'BM25':<15} {'Improvement':<15}")
    print("-" * 100)

    # MRR
    print(
        f"{'MRR':<20} {random_result.metrics['mrr']:<15.3f} "
        f"{tfidf_result.metrics['mrr']:<15.3f} {bm25_result.metrics['mrr']:<15.3f} "
        f"{(bm25_result.metrics['mrr'] - tfidf_result.metrics['mrr']):<+15.3f}"
    )

    # MAP
    print(
        f"{'MAP':<20} {random_result.metrics['map']:<15.3f} "
        f"{tfidf_result.metrics['map']:<15.3f} {bm25_result.metrics['map']:<15.3f} "
        f"{(bm25_result.metrics['map'] - tfidf_result.metrics['map']):<+15.3f}"
    )

    # Top-K Accuracy
    for k in [1, 3, 5]:
        metric_name = f"Top-{k} Acc"
        random_val = random_result.metrics[f"top{k}_accuracy"]
        tfidf_val = tfidf_result.metrics[f"top{k}_accuracy"]
        bm25_val = bm25_result.metrics[f"top{k}_accuracy"]
        improvement = bm25_val - tfidf_val
        print(f"{metric_name:<20} {random_val:<15.1%} {tfidf_val:<15.1%} {bm25_val:<15.1%} {improvement:<+15.1%}")

    # Precision@K
    for k in [1, 3, 5]:
        metric_name = f"Precision@{k}"
        random_val = random_result.metrics[f"precision@{k}"]
        tfidf_val = tfidf_result.metrics[f"precision@{k}"]
        bm25_val = bm25_result.metrics[f"precision@{k}"]
        improvement = bm25_val - tfidf_val
        print(f"{metric_name:<20} {random_val:<15.3f} {tfidf_val:<15.3f} {bm25_val:<15.3f} {improvement:<+15.3f}")

    # NDCG@K
    for k in [1, 3, 5]:
        metric_name = f"NDCG@{k}"
        random_val = random_result.metrics[f"ndcg@{k}"]
        tfidf_val = tfidf_result.metrics[f"ndcg@{k}"]
        bm25_val = bm25_result.metrics[f"ndcg@{k}"]
        improvement = bm25_val - tfidf_val
        print(f"{metric_name:<20} {random_val:<15.3f} {tfidf_val:<15.3f} {bm25_val:<15.3f} {improvement:<+15.3f}")

    print("-" * 100)

    # Statistical significance testing
    print("\n" + "=" * 100)
    print("STATISTICAL SIGNIFICANCE TESTING (BM25 vs TF-IDF)")
    print("=" * 100)
    print("\nRunning bootstrap test (1000 samples)...")

    significance_tests = evaluator.compare_with_significance(
        baseline_func=lambda q: tfidf_engine.search(q, top_k=10),
        improved_func=lambda q: bm25_engine.search_bm25(q, top_k=10),
        n_bootstrap=1000,
    )

    for test in significance_tests:
        test.print_report()

    # Summary insights
    print("\n" + "=" * 100)
    print("KEY INSIGHTS")
    print("=" * 100)

    mrr_vs_random = (
        bm25_result.metrics["mrr"] / random_result.metrics["mrr"] if random_result.metrics["mrr"] > 0 else float("inf")
    )
    mrr_vs_tfidf = (
        bm25_result.metrics["mrr"] / tfidf_result.metrics["mrr"] if tfidf_result.metrics["mrr"] > 0 else float("inf")
    )

    print("\n1. OVERALL PERFORMANCE:")
    print(f"   - BM25 is {mrr_vs_random:.1f}x better than Random baseline (MRR)")
    print(f"   - BM25 is {mrr_vs_tfidf:.2f}x better than TF-IDF baseline (MRR)")

    print("\n2. RANKING QUALITY:")
    print(
        f"   - BM25 MRR: {bm25_result.metrics['mrr']:.3f} "
        f"(first relevant at position {1 / bm25_result.metrics['mrr']:.1f})"
    )
    print(
        f"   - TF-IDF MRR: {tfidf_result.metrics['mrr']:.3f} "
        f"(first relevant at position {1 / tfidf_result.metrics['mrr']:.1f})"
    )

    print("\n3. TOP-1 ACCURACY:")
    print(f"   - BM25: {bm25_result.metrics['top1_accuracy']:.1%}")
    print(f"   - TF-IDF: {tfidf_result.metrics['top1_accuracy']:.1%}")
    print(f"   - Improvement: {(bm25_result.metrics['top1_accuracy'] - tfidf_result.metrics['top1_accuracy']):.1%}")

    print("\n4. STATISTICAL SIGNIFICANCE:")
    significant_count = sum(1 for test in significance_tests if test.is_significant)
    print(f"   - {significant_count}/{len(significance_tests)} metrics show significant improvement (p < 0.05)")
    if significant_count == len(significance_tests):
        print("   -  All improvements are statistically significant")
    elif significant_count > 0:
        print("   -  Some improvements are statistically significant")
    else:
        print("   -  No improvements are statistically significant")

    print("\n5. RECOMMENDATIONS:")
    if bm25_result.metrics["mrr"] < 0.7:
        print("   - Consider enabling Hybrid mode (BM25+Embedding) for better ranking")
    if bm25_result.metrics["top1_accuracy"] < 0.6:
        print("   - Top-1 accuracy could be improved with semantic search")
    if mrr_vs_tfidf < 1.2:
        print("   - BM25 advantage over TF-IDF is marginal, consider tuning parameters")
    if significant_count < len(significance_tests):
        print("   - Some improvements lack statistical significance, need more data or tuning")

    print("\n" + "=" * 100 + "\n")


if __name__ == "__main__":
    main()
