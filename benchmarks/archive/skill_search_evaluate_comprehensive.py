"""Comprehensive Quality Evaluation

Evaluates search quality with all metrics and failure analysis using the unified
SearchEvaluator framework.

Features:
- All standard metrics (MRR, MAP, Top-K, P/R/F1, NDCG)
- Failure analysis (identify problematic queries)
- Actionable recommendations

Usage:
    python -m tests.agent.meta_tools.skill_search.evaluate_comprehensive
"""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.skills.search.engine import SkillSearchEngine
from tests.agent.meta_tools.skill_search.evaluator import SearchEvaluator
from tests.agent.meta_tools.skill_search.fixtures import create_comprehensive_mock_skills
from tests.agent.meta_tools.skill_search.golden_dataset import GOLDEN_DATASET


def main() -> None:
    """Main evaluation function with comprehensive metrics and failure analysis"""
    print("=" * 100)
    print("COMPREHENSIVE QUALITY EVALUATION")
    print("=" * 100)

    print("\nCreating mock skills...")
    skills = create_comprehensive_mock_skills()
    print(f"Created {len(skills)} mock skills")

    print("\nInitializing BM25 search engine...")
    engine = SkillSearchEngine(skills=skills)

    print(f"\nEvaluating {len(GOLDEN_DATASET)} queries with all metrics...")
    evaluator = SearchEvaluator(dataset=GOLDEN_DATASET, k_values=[1, 3, 5, 10])
    result = evaluator.evaluate(lambda q: engine.search_bm25(q, top_k=10))

    # Print detailed report with all metrics
    result.print_report(detailed=True)

    # Failure analysis
    print("\n" + "=" * 100)
    print("FAILURE ANALYSIS")
    print("=" * 100)
    failure_analysis = result.analyze_failures(top_k=5)
    failure_analysis.print_report()

    # Print summary insights
    print("=" * 100)
    print("KEY INSIGHTS")
    print("=" * 100)

    mrr = result.metrics["mrr"]
    map_score = result.metrics["map"]
    top1 = result.metrics["top1_accuracy"]
    top3 = result.metrics["top3_accuracy"]
    top5 = result.metrics["top5_accuracy"]

    print("\n1. RANKING QUALITY:")
    print(f"   - MRR {mrr:.3f} indicates first relevant result at position {1 / mrr:.1f}")
    print(f"   - MAP {map_score:.3f} shows overall precision across all relevant results")

    print("\n2. RETRIEVAL EFFECTIVENESS:")
    print(f"   - Top-1 Accuracy {top1:.1%}: Immediate success rate")
    print(f"   - Top-3 Accuracy {top3:.1%}: Success within 3 results")
    print(f"   - Top-5 Accuracy {top5:.1%}: Success within 5 results")

    print("\n3. PRECISION vs RECALL TRADE-OFF:")
    for k in [1, 3, 5, 10]:
        p = result.metrics[f"precision@{k}"]
        r = result.metrics[f"recall@{k}"]
        f1 = result.metrics[f"f1@{k}"]
        print(f"   - @{k}: P={p:.3f}, R={r:.3f}, F1={f1:.3f}")

    print("\n4. RANKING QUALITY (NDCG):")
    for k in [1, 3, 5, 10]:
        ndcg = result.metrics[f"ndcg@{k}"]
        print(f"   - NDCG@{k}: {ndcg:.3f} (1.0 = perfect ranking)")

    print("\n5. FAILURE PATTERNS:")
    if failure_analysis.total_failures > 0:
        print(f"   - {failure_analysis.total_failures} queries failed ({failure_analysis.failure_rate:.1%})")
        top_failure_category = max(failure_analysis.failure_by_category.items(), key=lambda x: x[1])[0]
        print(f"   - Worst category: {top_failure_category}")
        print("   - See FAILURE ANALYSIS section above for details")
    else:
        print("   - No failures detected!")

    print("\n6. RECOMMENDATIONS:")
    if mrr < 0.7:
        print("   - Consider enabling Hybrid mode (BM25+Embedding) to improve MRR")
    if top1 < 0.6:
        print("   - Top-1 accuracy could be improved with better ranking")
    if map_score < 0.6:
        print("   - MAP indicates room for improvement in overall precision")
    if result.metrics["ndcg@5"] < 0.7:
        print("   - NDCG suggests ranking quality could be enhanced")
    if failure_analysis.total_failures > 0:
        print(f"   - Focus on improving {top_failure_category} queries")

    print("\n" + "=" * 100 + "\n")


if __name__ == "__main__":
    main()
