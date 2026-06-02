"""Ablation Study: Measure independent contribution of each optimization

消融实验：逐个移除优化项，测量每个的独立贡献
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add tests directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from agent.tools.skill_search.evaluator import SearchEvaluator
from agent.tools.skill_search.fixtures import create_comprehensive_mock_skills
from agent.tools.skill_search.golden_dataset import GOLDEN_DATASET

from myrm_agent_harness.agent.meta_tools.skills.search.engine import SkillSearchEngine


def run_ablation_study() -> None:
    """Run ablation study to measure each optimization's contribution"""

    print(" 消融实验：测量每个优化的独立贡献")
    print("=" * 80)

    skills = create_comprehensive_mock_skills()
    evaluator = SearchEvaluator(GOLDEN_DATASET)

    configurations = [
        ("Baseline (No Expansion)", False, None),
        ("Full Pipeline (All Optimizations)", True, None),
        # Note: To test individual components, would need to modify QueryExpander
        # to allow selective disabling of normalizer/typo/synonym components
    ]

    results_summary = []

    for name, enable_expansion, _ in configurations:
        print(f"\n Testing: {name}")
        print("-" * 80)

        engine = SkillSearchEngine(skills, enable_query_expansion=enable_expansion)

        results = evaluator.evaluate(lambda q: engine.search_bm25(q, top_k=10))

        mrr = results.metrics["mrr"]
        map_score = results.metrics["map"]
        top1 = results.metrics["top1_accuracy"] * 100
        top5 = results.metrics["top5_accuracy"] * 100

        print(f"  MRR: {mrr:.3f}")
        print(f"  MAP: {map_score:.3f}")
        print(f"  Top-1: {top1:.1f}%")
        print(f"  Top-5: {top5:.1f}%")

        results_summary.append({"name": name, "mrr": mrr, "map": map_score, "top1": top1, "top5": top5})

    # Calculate improvements
    print("\n 改进对比")
    print("=" * 80)

    baseline = results_summary[0]
    full = results_summary[1]

    print(
        f"MRR: {baseline['mrr']:.3f} -> {full['mrr']:.3f} ({(full['mrr'] - baseline['mrr']) / baseline['mrr'] * 100:+.1f}%)"
    )
    print(
        f"MAP: {baseline['map']:.3f} -> {full['map']:.3f} ({(full['map'] - baseline['map']) / baseline['map'] * 100:+.1f}%)"
    )
    print(f"Top-1: {baseline['top1']:.1f}% -> {full['top1']:.1f}% ({full['top1'] - baseline['top1']:+.1f}%)")
    print(f"Top-5: {baseline['top5']:.1f}% -> {full['top5']:.1f}% ({full['top5'] - baseline['top5']:+.1f}%)")

    print("\n 消融实验完成")
    print("\n 完整的消融实验需要:")
    print("  1. 可选禁用QueryNormalizer")
    print("  2. 可选禁用TypoCorrector")
    print("  3. 可选禁用SynonymExpander")
    print("  4. 逐个测试每个组件的独立贡献")


if __name__ == "__main__":
    run_ablation_study()
