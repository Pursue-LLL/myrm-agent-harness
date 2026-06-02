"""Failure Case Root Cause Analysis

Analyzes failed queries to identify root causes and guide future optimizations.

Usage:
    python -m tests.agent.meta_tools.skill_search.analyze_failures
"""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.skills.search.engine import SkillSearchEngine
from tests.agent.meta_tools.skill_search.evaluator import SearchEvaluator
from tests.agent.meta_tools.skill_search.fixtures import create_comprehensive_mock_skills
from tests.agent.meta_tools.skill_search.golden_dataset import GOLDEN_DATASET


def analyze_bm25_failures() -> None:
    """Analyze BM25 failure cases"""
    print("=" * 100)
    print("FAILURE CASE ROOT CAUSE ANALYSIS")
    print("=" * 100)

    skills = create_comprehensive_mock_skills()
    engine = SkillSearchEngine(skills=skills)
    evaluator = SearchEvaluator(dataset=GOLDEN_DATASET)

    # Run evaluation to get failures
    result = evaluator.evaluate(lambda q: engine.search_bm25(q, top_k=10))
    failure_analysis = result.analyze_failures()

    print(f"\nTotal Failures: {failure_analysis.total_failures} / {len(GOLDEN_DATASET)}")
    print(f"Failure Rate: {failure_analysis.failure_rate:.1%}\n")

    # Get failed queries
    failed_queries = [qr for qr in result.query_results if not qr.success]

    print("=" * 100)
    print("DETAILED FAILURE ANALYSIS")
    print("=" * 100)

    # Analyze each failure
    for i, query_result in enumerate(failed_queries, 1):
        print(f"\n--- Failure #{i} ---")
        print(f"Query: '{query_result.query}'")
        print(f"Category: {query_result.category}")
        print(f"Expected: {query_result.expected}")
        print(f"Retrieved: {query_result.retrieved[:5]}")  # Top 5

        # Try to diagnose root cause
        query_lower = query_result.query.lower()
        [e.lower() for e in query_result.expected]

        # Check if expected skill exists
        skill_exists = any(s.name in query_result.expected for s in skills)
        print(f"Expected skill exists: {skill_exists}")

        # Check if query terms appear in expected skill
        if skill_exists:
            for skill in skills:
                if skill.name in query_result.expected:
                    skill_text = f"{skill.name} {skill.description}".lower()
                    query_terms = query_lower.split()
                    matching_terms = [term for term in query_terms if term in skill_text]
                    print(f"  Skill: {skill.name}")
                    print(f"  Description: {skill.description[:100]}...")
                    print(f"  Matching terms: {matching_terms}")
                    print(f"  Missing terms: {[t for t in query_terms if t not in skill_text]}")

        # Root cause classification
        causes = []

        if not skill_exists:
            causes.append("SKILL_MISSING: Expected skill not in dataset")
        elif len(query_result.expected) == 0:
            causes.append("NO_EXPECTED: No expected results defined")
        elif "/" in query_result.query:
            # Multilingual format - check if any variant matches
            variants = query_result.query.split()
            variant_matches = []
            for skill in skills:
                if skill.name in query_result.expected:
                    skill_text = f"{skill.name} {skill.description}".lower()
                    for variant in variants:
                        variant_terms = variant.split("/")
                        if any(term.lower() in skill_text for term in variant_terms):
                            variant_matches.append(variant)
            if not variant_matches:
                causes.append("SEMANTIC_GAP: No query variants match skill description")
            else:
                causes.append("SCORING_ISSUE: Terms match but score too low")
        elif len(query_lower) <= 2:
            causes.append("TOO_SHORT: Query too short for reliable matching")
        elif any(term in query_lower for term in ["票", "天", "piao"]):
            causes.append("AMBIGUOUS: Query too generic or ambiguous")
        else:
            causes.append("ALGORITHM_LIMITATION: BM25 scoring insufficient")

        print(f"Root causes: {causes}")

    # Summary by root cause
    print("\n" + "=" * 100)
    print("ROOT CAUSE SUMMARY")
    print("=" * 100)

    cause_categories = {
        "SKILL_MISSING": 0,
        "SEMANTIC_GAP": 0,
        "SCORING_ISSUE": 0,
        "TOO_SHORT": 0,
        "AMBIGUOUS": 0,
        "ALGORITHM_LIMITATION": 0,
        "NO_EXPECTED": 0,
    }

    for query_result in failed_queries:
        query_lower = query_result.query.lower()
        skill_exists = any(s.name in query_result.expected for s in skills)

        if not skill_exists:
            cause_categories["SKILL_MISSING"] += 1
        elif len(query_result.expected) == 0:
            cause_categories["NO_EXPECTED"] += 1
        elif "/" in query_result.query:
            # Check variant matching
            variants = query_result.query.split()
            has_match = False
            for skill in skills:
                if skill.name in query_result.expected:
                    skill_text = f"{skill.name} {skill.description}".lower()
                    for variant in variants:
                        variant_terms = variant.split("/")
                        if any(term.lower() in skill_text for term in variant_terms):
                            has_match = True
                            break
            if has_match:
                cause_categories["SCORING_ISSUE"] += 1
            else:
                cause_categories["SEMANTIC_GAP"] += 1
        elif len(query_lower) <= 2:
            cause_categories["TOO_SHORT"] += 1
        elif any(term in query_lower for term in ["票", "天", "piao"]):
            cause_categories["AMBIGUOUS"] += 1
        else:
            cause_categories["ALGORITHM_LIMITATION"] += 1

    print("\nFailure Distribution:")
    for cause, count in sorted(cause_categories.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            percentage = count / len(failed_queries) * 100 if failed_queries else 0
            print(f"  {cause}: {count} ({percentage:.1f}%)")

    print("\n" + "=" * 100)
    print("RECOMMENDATIONS")
    print("=" * 100)

    if cause_categories["SKILL_MISSING"] > 0:
        print("\n1. Expand skill coverage: Add missing skills to dataset")
    if cause_categories["SEMANTIC_GAP"] > 0:
        print("\n2. Enhance skill descriptions: Add more semantic keywords")
    if cause_categories["SCORING_ISSUE"] > 0:
        print("\n3. Tune BM25 scoring: Lower threshold or adjust term weights")
    if cause_categories["TOO_SHORT"] > 0:
        print("\n4. Improve short query handling: Enhanced synonym expansion or fuzzy matching")
    if cause_categories["AMBIGUOUS"] > 0:
        print("\n5. Query clarification: Detect ambiguous queries and request more context")
    if cause_categories["ALGORITHM_LIMITATION"] > 0:
        print("\n6. Consider hybrid mode: Embedding search for semantic understanding")

    print("\n" + "=" * 100 + "\n")


if __name__ == "__main__":
    analyze_bm25_failures()
