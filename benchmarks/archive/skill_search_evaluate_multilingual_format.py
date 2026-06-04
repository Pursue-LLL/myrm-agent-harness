"""Evaluate multilingual format queries vs single-keyword queries

This script compares search quality on:
1. Single-keyword queries (e.g., "火车票")
2. Multilingual format queries (e.g., "火车票/railway ticket/train booking")

Goal: Verify whether query expansion adds significant value when LLM
already provides multilingual format as instructed by the prompt.
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from myrm_agent_harness.agent.meta_tools.skills.search.engine import SkillSearchEngine
from tests.agent.meta_tools.skill_search.evaluator import SearchEvaluator
from tests.agent.meta_tools.skill_search.fixtures import create_comprehensive_mock_skills
from tests.agent.meta_tools.skill_search.golden_dataset import GOLDEN_DATASET


def run_evaluation() -> None:
    """Run multilingual format evaluation"""
    print("=" * 80)
    print("Multilingual Format Query Evaluation")
    print("=" * 80)
    print()

    skills = create_comprehensive_mock_skills()

    # Filter datasets
    single_keyword_queries = [q for q in GOLDEN_DATASET if q.category != "multilingual_format"]
    multilingual_queries = [q for q in GOLDEN_DATASET if q.category == "multilingual_format"]

    print("Dataset sizes:")
    print(f"- Single-keyword queries: {len(single_keyword_queries)}")
    print(f"- Multilingual format queries: {len(multilingual_queries)}")
    print()

    # Evaluate both scenarios with and without query expansion
    scenarios = [
        ("Single-keyword WITHOUT expansion", single_keyword_queries, False),
        ("Single-keyword WITH expansion", single_keyword_queries, True),
        ("Multilingual WITHOUT expansion", multilingual_queries, False),
        ("Multilingual WITH expansion", multilingual_queries, True),
    ]

    results_table = []

    for scenario_name, dataset, enable_expansion in scenarios:
        print(f"\n{'=' * 80}")
        print(f"Scenario: {scenario_name}")
        print(f"{'=' * 80}\n")

        engine = SkillSearchEngine(skills, enable_query_expansion=enable_expansion)
        evaluator = SearchEvaluator(dataset=dataset)

        result = evaluator.evaluate(lambda q: engine.search_bm25(q, top_k=10))
        metrics = result.metrics

        print("Results:")
        print(f"  MRR:                {metrics['mrr']:.3f}")
        print(f"  MAP:                {metrics['map']:.3f}")
        print(f"  Top-1 Accuracy:     {metrics['top1_accuracy'] * 100:.1f}%")
        print(f"  Top-3 Accuracy:     {metrics['top3_accuracy'] * 100:.1f}%")
        print(f"  Top-5 Accuracy:     {metrics['top5_accuracy'] * 100:.1f}%")
        print(f"  Failure Rate:       {(1 - metrics['top5_accuracy']) * 100:.1f}%")

        results_table.append(
            {
                "scenario": scenario_name,
                "dataset_size": len(dataset),
                "mrr": metrics["mrr"],
                "map": metrics["map"],
                "top1": metrics["top1_accuracy"],
                "top3": metrics["top3_accuracy"],
                "top5": metrics["top5_accuracy"],
            }
        )

    # Comparison analysis
    print("\n" + "=" * 80)
    print("COMPARATIVE ANALYSIS")
    print("=" * 80)

    single_no_exp = results_table[0]
    single_with_exp = results_table[1]
    multi_no_exp = results_table[2]
    multi_with_exp = results_table[3]

    print("\n1. Query Expansion Contribution:")
    print("-" * 80)

    # Single-keyword scenario
    single_mrr_gain = (single_with_exp["mrr"] - single_no_exp["mrr"]) / single_no_exp["mrr"] * 100
    single_top1_gain = (single_with_exp["top1"] - single_no_exp["top1"]) / single_no_exp["top1"] * 100

    print("\nSingle-keyword queries:")
    print(f"  MRR improvement:    {single_mrr_gain:+.1f}%  ({single_no_exp['mrr']:.3f} → {single_with_exp['mrr']:.3f})")
    print(
        f"  Top-1 improvement:  {single_top1_gain:+.1f}%  ({single_no_exp['top1'] * 100:.1f}% → {single_with_exp['top1'] * 100:.1f}%)"
    )

    # Multilingual format scenario
    if multi_no_exp["mrr"] > 0:
        multi_mrr_gain = (multi_with_exp["mrr"] - multi_no_exp["mrr"]) / multi_no_exp["mrr"] * 100
    else:
        multi_mrr_gain = 0.0

    if multi_no_exp["top1"] > 0:
        multi_top1_gain = (multi_with_exp["top1"] - multi_no_exp["top1"]) / multi_no_exp["top1"] * 100
    else:
        multi_top1_gain = 0.0

    print("\nMultilingual format queries:")
    print(f"  MRR improvement:    {multi_mrr_gain:+.1f}%  ({multi_no_exp['mrr']:.3f} → {multi_with_exp['mrr']:.3f})")
    print(
        f"  Top-1 improvement:  {multi_top1_gain:+.1f}%  ({multi_no_exp['top1'] * 100:.1f}% → {multi_with_exp['top1'] * 100:.1f}%)"
    )

    print("\n2. Multilingual Format Effect:")
    print("-" * 80)

    # Compare baseline performance (without expansion)
    baseline_mrr_diff = (multi_no_exp["mrr"] - single_no_exp["mrr"]) / single_no_exp["mrr"] * 100
    baseline_top1_diff = (multi_no_exp["top1"] - single_no_exp["top1"]) / single_no_exp["top1"] * 100

    print("\nWithout query expansion:")
    print(f"  MRR (Multi vs Single):   {baseline_mrr_diff:+.1f}%")
    print(f"  Top-1 (Multi vs Single): {baseline_top1_diff:+.1f}%")
    print(f"  → Multilingual format {'improves' if baseline_mrr_diff > 0 else 'degrades'} baseline performance")

    # Compare with expansion
    expanded_mrr_diff = (multi_with_exp["mrr"] - single_with_exp["mrr"]) / single_with_exp["mrr"] * 100
    expanded_top1_diff = (multi_with_exp["top1"] - single_with_exp["top1"]) / single_with_exp["top1"] * 100

    print("\nWith query expansion:")
    print(f"  MRR (Multi vs Single):   {expanded_mrr_diff:+.1f}%")
    print(f"  Top-1 (Multi vs Single): {expanded_top1_diff:+.1f}%")
    print(f"  → Multilingual format {'improves' if expanded_mrr_diff > 0 else 'degrades'} performance")

    print("\n3. Key Findings:")
    print("-" * 80)

    # Determine query expansion's real-world value
    if multi_mrr_gain < 5.0:
        expansion_verdict = "LOW VALUE (< 5% improvement in realistic scenario)"
    elif multi_mrr_gain < 15.0:
        expansion_verdict = "MODERATE VALUE (5-15% improvement)"
    else:
        expansion_verdict = "HIGH VALUE (> 15% improvement)"

    print(f"\n Query Expansion in realistic scenario: {expansion_verdict}")
    print(f"  - Single-keyword: +{single_mrr_gain:.1f}% MRR (idealized test)")
    print(f"  - Multilingual:   +{multi_mrr_gain:.1f}% MRR (realistic production)")

    if baseline_mrr_diff > 10:
        print(f"\n Multilingual format SIGNIFICANTLY improves baseline (+{baseline_mrr_diff:.1f}%)")
        print("  → LLM's multilingual expansion is highly effective")
    elif baseline_mrr_diff > 0:
        print(f"\n Multilingual format modestly improves baseline (+{baseline_mrr_diff:.1f}%)")
    else:
        print(f"\n Multilingual format DEGRADES baseline ({baseline_mrr_diff:.1f}%)")
        print("  → Potential issue with '/' separator handling")

    print("\n" + "=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)

    if multi_mrr_gain < 5.0 and baseline_mrr_diff > 10:
        print("\n→ Consider SIMPLIFYING query expansion:")
        print("  - LLM already provides effective multilingual keywords")
        print("  - Query expansion adds minimal value in realistic scenario")
        print("  - Could reduce to just normalization + typo correction")
    elif multi_mrr_gain >= 15:
        print("\n→ KEEP current query expansion design:")
        print("  - Still provides significant value even with multilingual input")
        print("  - Adds domain-specific synonyms LLM might miss")
    else:
        print("\n→ Current design is REASONABLE but could be optimized")
        print("  - Moderate value in realistic scenario")
        print("  - Consider cost/complexity vs benefit trade-off")

    print()


if __name__ == "__main__":
    run_evaluation()
