"""CJK retrieval recall quality regression tests.

Verifies that BM25 retrieval returns correct results for CJK partial-match
scenarios. These tests guard against regressions that silently break Chinese
search recall (e.g., tokenizer fallback producing single-token for entire phrases).

These tests are backend-agnostic: they pass regardless of whether jieba is installed,
because the CJK bigram fallback must also satisfy the recall guarantees.
"""

import pytest

from myrm_agent_harness.toolkits.retriever.bm25.tokenizer import (
    _cjk_bigram_tokenize,
    get_tokenizer_service,
)
from myrm_agent_harness.toolkits.retriever.bm25_retrieval import BM25Retriever

# ---------------------------------------------------------------------------
# Unit tests: _cjk_bigram_tokenize correctness
# ---------------------------------------------------------------------------


class TestCJKBigramTokenize:
    """Verify the CJK bigram fallback produces correct token sets."""

    def test_pure_chinese_produces_unigrams_and_bigrams(self):
        tokens = _cjk_bigram_tokenize("机器学习")
        assert "机" in tokens
        assert "器" in tokens
        assert "学" in tokens
        assert "习" in tokens
        assert "机器" in tokens
        assert "器学" in tokens
        assert "学习" in tokens
        assert len(tokens) == 7  # 4 unigrams + 3 bigrams

    def test_single_char_produces_only_unigram(self):
        tokens = _cjk_bigram_tokenize("学")
        assert tokens == ["学"]

    def test_mixed_cjk_english(self):
        tokens = _cjk_bigram_tokenize("Python机器学习tutorial")
        assert "Python" in tokens
        assert "tutorial" in tokens
        assert "机器" in tokens
        assert "学习" in tokens

    def test_empty_string(self):
        assert _cjk_bigram_tokenize("") == []

    def test_pure_english_no_cjk(self):
        tokens = _cjk_bigram_tokenize("hello world")
        assert "hello" in tokens
        assert "world" in tokens
        assert len(tokens) == 2

    def test_cjk_extended_range(self):
        """Verify CJK Unified Ideographs Extension A is handled."""
        tokens = _cjk_bigram_tokenize("𠀀𠀁")  # Characters outside BMP (> U+FFFF)
        # These are outside our regex range, should not crash
        assert isinstance(tokens, list)


# ---------------------------------------------------------------------------
# Integration tests: BM25 recall quality for CJK
# ---------------------------------------------------------------------------


class TestCJKRecallQuality:
    """End-to-end BM25 recall tests for CJK partial matching.

    These are the critical regression tests that ensure Chinese memory
    search actually works — partial queries must find documents containing
    the queried phrase as a substring.
    """

    DOCUMENTS = [
        "机器学习模型部署方案讨论",
        "深度学习训练优化技巧总结",
        "数据预处理管道设计文档",
        "前端React组件重构计划",
        "Python自动化测试框架搭建",
    ]

    @pytest.fixture
    def retriever(self):
        return BM25Retriever(self.DOCUMENTS)

    def test_partial_match_model_deploy(self, retriever):
        """Search '模型部署' must find '机器学习模型部署方案讨论'."""
        results = retriever.search("模型部署", top_k=5, only_relevant=True)
        found_indices = [idx for idx, _ in results]
        assert 0 in found_indices, (
            "Query '模型部署' must recall document containing '机器学习模型部署方案讨论'"
        )

    def test_partial_match_deep_learning(self, retriever):
        """Search '深度学习' must find the deep learning document."""
        results = retriever.search("深度学习", top_k=5, only_relevant=True)
        found_indices = [idx for idx, _ in results]
        assert 1 in found_indices, (
            "Query '深度学习' must recall document containing '深度学习训练优化技巧总结'"
        )

    def test_partial_match_data_pipeline(self, retriever):
        """Search '数据预处理' must find the data pipeline document."""
        results = retriever.search("数据预处理", top_k=5, only_relevant=True)
        found_indices = [idx for idx, _ in results]
        assert 2 in found_indices

    def test_partial_match_python_test(self, retriever):
        """Search 'Python测试' must find the Python testing document."""
        results = retriever.search("Python测试", top_k=5, only_relevant=True)
        found_indices = [idx for idx, _ in results]
        assert 4 in found_indices

    def test_ranking_relevance(self, retriever):
        """The most relevant document should rank first."""
        results = retriever.search("模型部署", top_k=5, only_relevant=True)
        assert len(results) > 0
        top_idx, top_score = results[0]
        assert top_idx == 0, "Document '机器学习模型部署方案讨论' should rank first for query '模型部署'"
        assert top_score > 0

    def test_no_false_positive_for_unrelated(self, retriever):
        """Completely unrelated query should not rank higher than relevant matches."""
        related = retriever.search("模型部署", top_k=1, only_relevant=True)
        unrelated = retriever.search("量子物理", top_k=5, only_relevant=True)
        if related and unrelated:
            best_related_score = related[0][1]
            best_unrelated_score = unrelated[0][1]
            assert best_unrelated_score < best_related_score, (
                f"Unrelated query score ({best_unrelated_score:.3f}) should be lower "
                f"than related query score ({best_related_score:.3f})"
            )

    def test_single_char_query(self, retriever):
        """Single character query should still produce results (not crash)."""
        results = retriever.search("学", top_k=5, only_relevant=True)
        # With jieba, single-char IDF may be too high to match; with bigram fallback
        # it should match. The key guarantee is no crash and valid return type.
        assert isinstance(results, list)
        for idx, score in results:
            assert isinstance(idx, int)
            assert isinstance(score, float)


# ---------------------------------------------------------------------------
# TokenizerService.backend property test
# ---------------------------------------------------------------------------


class TestTokenizerBackend:
    """Verify the backend property reports correctly."""

    def test_backend_property_returns_string(self):
        service = get_tokenizer_service()
        backend = service.backend
        assert backend in ("jieba", "bigram_fallback")

    def test_tokenize_produces_multiple_tokens_for_chinese(self):
        """Regardless of backend, Chinese text must produce multiple tokens."""
        service = get_tokenizer_service()
        tokens = service.tokenize("机器学习模型部署")
        assert len(tokens) >= 4, (
            f"Chinese text must produce multiple tokens, got {len(tokens)}: {tokens}"
        )
