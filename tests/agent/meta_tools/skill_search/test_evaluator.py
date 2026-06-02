"""Tests for unified SearchEvaluator framework"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.skills.search.engine import SkillSearchEngine

from .baselines import RandomSearchEngine, TFIDFSearchEngine
from .evaluator import SearchEvaluator
from .fixtures import create_comprehensive_mock_skills
from .golden_dataset import GOLDEN_DATASET


@pytest.fixture
def mock_skills():
    """Create mock skills for testing"""
    return create_comprehensive_mock_skills()


@pytest.fixture
def evaluator():
    """Create evaluator with golden dataset"""
    return SearchEvaluator(dataset=GOLDEN_DATASET, k_values=[1, 3, 5])


class TestSearchEvaluator:
    """Test SearchEvaluator class"""

    def test_init(self, evaluator):
        """Test evaluator initialization"""
        assert evaluator.dataset == GOLDEN_DATASET
        assert evaluator.k_values == [1, 3, 5]

    def test_evaluate_returns_result(self, evaluator, mock_skills):
        """Test evaluate returns EvaluationResult"""
        engine = SkillSearchEngine(skills=mock_skills)
        result = evaluator.evaluate(lambda q: engine.search_bm25(q, top_k=10))

        assert result.dataset_size == len(GOLDEN_DATASET)
        assert "mrr" in result.metrics
        assert "map" in result.metrics
        assert len(result.query_results) == len(GOLDEN_DATASET)

    def test_evaluate_metrics_range(self, evaluator, mock_skills):
        """Test metrics are in valid range"""
        engine = SkillSearchEngine(skills=mock_skills)
        result = evaluator.evaluate(lambda q: engine.search_bm25(q, top_k=10))

        # All metrics should be between 0 and 1
        assert 0.0 <= result.metrics["mrr"] <= 1.0
        assert 0.0 <= result.metrics["map"] <= 1.0
        assert 0.0 <= result.metrics["top1_accuracy"] <= 1.0
        assert 0.0 <= result.metrics["precision@5"] <= 1.0
        assert 0.0 <= result.metrics["recall@5"] <= 1.0
        assert 0.0 <= result.metrics["ndcg@5"] <= 1.0

    def test_analyze_failures(self, evaluator, mock_skills):
        """Test failure analysis"""
        engine = SkillSearchEngine(skills=mock_skills)
        result = evaluator.evaluate(lambda q: engine.search_bm25(q, top_k=10))

        failure_analysis = result.analyze_failures(top_k=5)

        assert failure_analysis.total_failures >= 0
        assert 0.0 <= failure_analysis.failure_rate <= 1.0
        assert len(failure_analysis.failed_queries) == failure_analysis.total_failures
        assert isinstance(failure_analysis.failure_by_category, dict)
        assert isinstance(failure_analysis.failure_reasons, dict)

    def test_analyze_by_category(self, evaluator, mock_skills):
        """Test category-level analysis"""
        engine = SkillSearchEngine(skills=mock_skills)
        category_results = evaluator.analyze_by_category(lambda q: engine.search_bm25(q, top_k=10))

        assert isinstance(category_results, dict)
        assert len(category_results) > 0

        for _category, metrics in category_results.items():
            assert "mrr" in metrics
            assert "top1" in metrics
            assert "top3" in metrics
            assert "top5" in metrics
            assert "total" in metrics
            assert metrics["total"] > 0

    def test_compare_with_significance(self, evaluator, mock_skills):
        """Test statistical significance testing"""
        bm25_engine = SkillSearchEngine(skills=mock_skills)
        tfidf_engine = TFIDFSearchEngine(skills=mock_skills)

        significance_tests = evaluator.compare_with_significance(
            baseline_func=lambda q: tfidf_engine.search(q, top_k=10),
            improved_func=lambda q: bm25_engine.search_bm25(q, top_k=10),
            n_bootstrap=100,  # Reduced for faster testing
        )

        assert len(significance_tests) == 4  # MRR, MAP, Top-1, Top-3
        for test in significance_tests:
            assert test.metric_name in ["MRR", "MAP", "TOP1_ACCURACY", "TOP3_ACCURACY"]
            assert isinstance(test.baseline_mean, float)
            assert isinstance(test.improved_mean, float)
            assert isinstance(test.p_value, float)
            assert 0.0 <= test.p_value <= 1.0
            assert isinstance(test.is_significant, bool)
            assert len(test.confidence_interval) == 2

    def test_query_result_structure(self, evaluator, mock_skills):
        """Test QueryResult structure"""
        engine = SkillSearchEngine(skills=mock_skills)
        result = evaluator.evaluate(lambda q: engine.search_bm25(q, top_k=10))

        for qr in result.query_results:
            assert isinstance(qr.query, str)
            assert isinstance(qr.expected, list)
            assert isinstance(qr.retrieved, list)
            assert isinstance(qr.category, str)
            assert isinstance(qr.success, bool)
            assert qr.first_relevant_rank is None or qr.first_relevant_rank > 0
            assert qr.relevant_count >= 0


class TestFailureAnalysis:
    """Test FailureAnalysis functionality"""

    def test_failure_analysis_with_random(self, evaluator, mock_skills):
        """Test failure analysis with Random baseline (should have many failures)"""
        random_engine = RandomSearchEngine(skills=mock_skills)
        result = evaluator.evaluate(lambda q: random_engine.search(q, top_k=10))

        failure_analysis = result.analyze_failures(top_k=5)

        # Random should have high failure rate
        assert failure_analysis.failure_rate > 0.5
        assert failure_analysis.total_failures > 50
        assert len(failure_analysis.failure_by_category) > 0

    def test_failure_reasons_classification(self, evaluator, mock_skills):
        """Test failure reasons are properly classified"""
        engine = SkillSearchEngine(skills=mock_skills)
        result = evaluator.evaluate(lambda q: engine.search_bm25(q, top_k=10))

        failure_analysis = result.analyze_failures(top_k=5)

        # Check all failure reasons are valid
        valid_reasons = {
            "No matches found",
            "Relevant result beyond top-K",
            "Low ranking (position > 3)",
        }
        for reason in failure_analysis.failure_reasons:
            assert reason in valid_reasons


class TestSignificanceTest:
    """Test statistical significance testing"""

    def test_significance_test_structure(self, evaluator, mock_skills):
        """Test SignificanceTest structure"""
        bm25_engine = SkillSearchEngine(skills=mock_skills)
        random_engine = RandomSearchEngine(skills=mock_skills)

        tests = evaluator.compare_with_significance(
            baseline_func=lambda q: random_engine.search(q, top_k=10),
            improved_func=lambda q: bm25_engine.search_bm25(q, top_k=10),
            n_bootstrap=100,
        )

        for test in tests:
            assert test.difference == test.improved_mean - test.baseline_mean
            assert test.confidence_interval[0] <= test.confidence_interval[1]

    def test_significance_bm25_vs_random(self, evaluator, mock_skills):
        """Test BM25 vs Random should be significant"""
        bm25_engine = SkillSearchEngine(skills=mock_skills)
        random_engine = RandomSearchEngine(skills=mock_skills)

        tests = evaluator.compare_with_significance(
            baseline_func=lambda q: random_engine.search(q, top_k=10),
            improved_func=lambda q: bm25_engine.search_bm25(q, top_k=10),
            n_bootstrap=100,
        )

        # BM25 should be significantly better than Random
        mrr_test = next(t for t in tests if t.metric_name == "MRR")
        assert mrr_test.is_significant
        assert mrr_test.difference > 0.5  # Large improvement
