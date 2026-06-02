"""Tests for Golden Dataset evaluation

This test file demonstrates how to use the Golden Dataset to evaluate
search quality. It's designed to be run manually or as part of CI/CD
to track search quality over time.
"""

import pytest

from myrm_agent_harness.backends.skills.types import SkillMetadata

from .fixtures import create_comprehensive_mock_skills
from .golden_dataset import GOLDEN_DATASET, evaluate_search_quality, print_evaluation_report


@pytest.fixture
def mock_skills() -> list[SkillMetadata]:
    """Create comprehensive mock skills for testing"""
    return create_comprehensive_mock_skills()


def test_golden_dataset_structure():
    """Test that golden dataset has valid structure"""
    assert len(GOLDEN_DATASET) > 0, "Golden dataset should not be empty"

    for query in GOLDEN_DATASET:
        assert query.query, "Query should not be empty"
        assert query.expected_skills, "Expected skills should not be empty"
        assert query.description, "Description should not be empty"
        assert query.category, "Category should not be empty"


def test_golden_dataset_categories():
    """Test that golden dataset covers all important categories"""
    categories = {q.category for q in GOLDEN_DATASET}

    expected_categories = {
        "exact_match",
        "semantic_chinese",
        "semantic_english",
        "multilingual",
        "multilingual_format",
        "conceptual",
        "synonym",
        "short_query",
        "long_query",
        "fuzzy",
        "error_query",
    }

    assert categories == expected_categories, f"Missing categories: {expected_categories - categories}"


def test_golden_dataset_size():
    """Test that golden dataset has sufficient size for statistical significance"""
    assert len(GOLDEN_DATASET) >= 100, f"Golden dataset should have at least 100 queries, got {len(GOLDEN_DATASET)}"

    category_counts = {}
    for query in GOLDEN_DATASET:
        category_counts[query.category] = category_counts.get(query.category, 0) + 1

    for category, count in category_counts.items():
        assert count >= 5, f"Category '{category}' should have at least 5 queries, got {count}"


def test_evaluate_search_quality_bm25(mock_skills):
    """Test evaluation with BM25 search engine

    This test demonstrates how to evaluate BM25 search quality.
    """
    from myrm_agent_harness.agent.meta_tools.skills.search.engine import SkillSearchEngine

    engine = SkillSearchEngine(mock_skills)

    def search_func(query: str):
        return engine.search_bm25(query, top_k=5)

    results = evaluate_search_quality(search_func, GOLDEN_DATASET)

    print_evaluation_report(results)

    assert results["total_queries"] == len(GOLDEN_DATASET)
    assert 0.0 <= results["mrr"] <= 1.0
    assert 0.0 <= results["top1_accuracy"] <= 1.0
    assert 0.0 <= results["top3_accuracy"] <= 1.0
    assert 0.0 <= results["top5_accuracy"] <= 1.0

    assert results["top1_accuracy"] >= 0.3, "BM25 should have at least 30% top-1 accuracy"


@pytest.mark.skipif(
    True, reason="Hybrid search requires API access, skip by default. Run manually with --run-api-tests"
)
def test_evaluate_search_quality_hybrid(mock_skills):
    """Test evaluation with Hybrid search engine

    This test demonstrates how to evaluate Hybrid search quality.
    Requires API access and is skipped by default.
    """
    from myrm_agent_harness.agent.meta_tools.skills.search.hybrid_engine import HybridSkillSearchEngine
    from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig

    config = EmbeddingConfig(model="text-embedding-3-small")
    engine = HybridSkillSearchEngine(mock_skills, config)

    async def search_func(query: str):
        return await engine.search_bm25(query, top_k=5)

    import asyncio

    def sync_search_func(query: str):
        return asyncio.run(search_func(query))

    results = evaluate_search_quality(sync_search_func, GOLDEN_DATASET)

    print_evaluation_report(results)

    assert results["total_queries"] == len(GOLDEN_DATASET)

    assert results["top1_accuracy"] >= 0.5, "Hybrid should have at least 50% top-1 accuracy"
    assert results["top3_accuracy"] >= 0.7, "Hybrid should have at least 70% top-3 accuracy"


def test_evaluation_metrics_calculation():
    """Test that evaluation metrics are calculated correctly"""

    def mock_search_func(query: str):
        if query == "exact":
            return [
                type("Result", (), {"name": "expected_skill_1"}),
                type("Result", (), {"name": "other_skill"}),
            ]
        if query == "top3":
            return [
                type("Result", (), {"name": "other_skill_1"}),
                type("Result", (), {"name": "other_skill_2"}),
                type("Result", (), {"name": "expected_skill_2"}),
            ]
        return []

    dataset = [
        type(
            "Query",
            (),
            {
                "query": "exact",
                "expected_skills": ["expected_skill_1"],
                "description": "Test",
                "category": "test",
            },
        ),
        type(
            "Query",
            (),
            {
                "query": "top3",
                "expected_skills": ["expected_skill_2"],
                "description": "Test",
                "category": "test",
            },
        ),
        type(
            "Query",
            (),
            {
                "query": "miss",
                "expected_skills": ["expected_skill_3"],
                "description": "Test",
                "category": "test",
            },
        ),
    ]

    results = evaluate_search_quality(mock_search_func, dataset)

    assert results["total_queries"] == 3
    assert results["top1_accuracy"] == pytest.approx(1 / 3)
    assert results["top3_accuracy"] == pytest.approx(2 / 3)
    assert results["mrr"] == pytest.approx((1.0 + 1 / 3 + 0.0) / 3)
