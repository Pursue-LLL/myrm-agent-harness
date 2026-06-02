"""Analyze how Hybrid mode improves BM25 failures

Compares BM25 vs Hybrid performance on queries that failed in BM25-only mode.

Usage:
    export EMBEDDING_MODEL="openai/BAAI/bge-m3"
    export EMBEDDING_API_KEY="..."
    export EMBEDDING_API_BASE="https://api.siliconflow.cn/v1"
    python -m tests.agent.meta_tools.skill_search.analyze_failure_improvement
"""

from __future__ import annotations

import asyncio
import logging
import os

from myrm_agent_harness.agent.meta_tools.skills.search.engine import SkillSearchEngine
from myrm_agent_harness.agent.meta_tools.skills.search.hybrid_engine import HybridSkillSearchEngine
from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig
from tests.agent.meta_tools.skill_search.evaluator import SearchEvaluator
from tests.agent.meta_tools.skill_search.fixtures import create_comprehensive_mock_skills
from tests.agent.meta_tools.skill_search.golden_dataset import GOLDEN_DATASET

logger = logging.getLogger(__name__)


async def main() -> None:
    """Compare BM25 vs Hybrid on failed queries"""
    if not os.getenv("EMBEDDING_API_KEY"):
        print("ERROR: No API key found. Set EMBEDDING_API_KEY environment variable.")
        return

    print("=" * 100)
    print("FAILURE IMPROVEMENT ANALYSIS: BM25 vs Hybrid")
    print("=" * 100)

    skills = create_comprehensive_mock_skills()

    # Setup engines
    bm25_engine = SkillSearchEngine(skills=skills)
    config = EmbeddingConfig(
        model=os.getenv("EMBEDDING_MODEL", "openai/BAAI/bge-m3"),
        api_key=os.getenv("EMBEDDING_API_KEY"),
        api_base=os.getenv("EMBEDDING_API_BASE"),
    )
    hybrid_engine = HybridSkillSearchEngine(skills, config)

    # Get BM25 failures
    evaluator = SearchEvaluator(dataset=GOLDEN_DATASET)
    bm25_result = evaluator.evaluate(lambda q: bm25_engine.search_bm25(q, top_k=10))
    bm25_failures = [qr for qr in bm25_result.query_results if not qr.success]

    print(f"\nBM25 Failed Queries: {len(bm25_failures)} / {len(GOLDEN_DATASET)}")
    print(f"Failure Rate: {len(bm25_failures) / len(GOLDEN_DATASET):.1%}\n")

    # Test each failure with Hybrid
    print("=" * 100)
    print("TESTING HYBRID MODE ON BM25 FAILURES")
    print("=" * 100)

    improvements = []
    still_failed = []

    for i, bm25_failed in enumerate(bm25_failures, 1):
        query = bm25_failed.query
        expected_set = set(bm25_failed.expected)

        try:
            hybrid_results = await hybrid_engine.search_bm25(query, top_k=10)
            hybrid_names = [r.name if hasattr(r, "name") else r for r in hybrid_results]

            # Check if Hybrid found the expected skill
            first_relevant_rank = None
            for rank, name in enumerate(hybrid_names, start=1):
                if name in expected_set:
                    first_relevant_rank = rank
                    break

            print(f"\n--- Failure #{i} ---")
            print(f"Query: '{query}'")
            print(f"Category: {bm25_failed.category}")
            print(f"Expected: {bm25_failed.expected}")
            print(f"BM25 Top-3: {bm25_failed.retrieved[:3]}")
            print(f"Hybrid Top-3: {hybrid_names[:3]}")

            if first_relevant_rank is not None:
                improvements.append((query, bm25_failed.category, first_relevant_rank))
                print(f" IMPROVED: Found at rank {first_relevant_rank}")
            else:
                still_failed.append((query, bm25_failed.category))
                print(" STILL FAILED: Not found in top-10")

        except Exception as e:
            logger.warning("Hybrid search failed for %r: %s", query, e)
            still_failed.append((query, bm25_failed.category))
            print(f" ERROR: {e}")

    # Summary
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)

    print(f"\nBM25 Failures: {len(bm25_failures)}")
    print(f"Hybrid Improvements: {len(improvements)} ({len(improvements) / len(bm25_failures) * 100:.1f}%)")
    print(f"Still Failed: {len(still_failed)} ({len(still_failed) / len(bm25_failures) * 100:.1f}%)")

    if improvements:
        print("\n IMPROVED QUERIES:")
        for query, category, rank in improvements:
            print(f"  [{category}] '{query}' → rank {rank}")

    if still_failed:
        print("\n STILL FAILED QUERIES:")
        for query, category in still_failed:
            print(f"  [{category}] '{query}'")

    # Calculate overall improvement
    print("\n" + "=" * 100)
    print("IMPACT ANALYSIS")
    print("=" * 100)

    rescued_rate = len(improvements) / len(bm25_failures) if bm25_failures else 0
    final_failure_rate = len(still_failed) / len(GOLDEN_DATASET)

    print(f"\nBM25 Failure Rate: {len(bm25_failures) / len(GOLDEN_DATASET):.1%}")
    print(f"Hybrid Rescue Rate: {rescued_rate:.1%}")
    print(f"Final Failure Rate: {final_failure_rate:.1%}")
    print(
        f"Overall Improvement: {(len(bm25_failures) - len(still_failed)) / len(GOLDEN_DATASET) * 100:.1f} percentage points"
    )

    print("\n" + "=" * 100 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
