"""Unit tests for text_utils tokenization utilities."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.text_utils import (
    get_diversity_ratio,
    get_token_count,
    is_cjk_char,
    tokenize,
    tokenize_query,
)


class TestTokenizeQuery:
    """Tests for tokenize_query() - preserves order for adaptive logic."""

    def test_simple_english(self):
        """English text with whitespace separation."""
        assert tokenize_query("Python performance") == ["python", "performance"]

    def test_punctuation_separation(self):
        """Punctuation should separate tokens."""
        assert tokenize_query("hello,world") == ["hello", "world"]
        assert tokenize_query("foo.bar") == ["foo", "bar"]

    def test_chinese_tokenization(self):
        """Mixed alphanum+CJK treated as single token."""
        result = tokenize_query("Python性能优化")
        # Regex \w+ treats consecutive word chars as single token
        assert len(result) == 1  # ["python性能优化"]
        assert result[0] == "python性能优化"

    def test_mixed_language(self):
        """Mixed English and Chinese without separator."""
        result = tokenize_query("hello世界")
        # Without separator, forms single token
        assert len(result) == 1  # ["hello世界"]

    def test_empty_string(self):
        """Empty string returns empty list."""
        assert tokenize_query("") == []

    def test_lowercase_normalization(self):
        """Uppercase converted to lowercase."""
        assert tokenize_query("Python PYTHON") == ["python", "python"]

    def test_numbers_preserved(self):
        """Numbers treated as tokens."""
        assert tokenize_query("version 3.11") == ["version", "3", "11"]


class TestTokenize:
    """Tests for tokenize() - returns unique token set for keyword overlap."""

    def test_deduplication(self):
        """Duplicate tokens removed."""
        assert tokenize("Python Python bug") == frozenset({"python", "bug"})

    def test_simple_english(self):
        """Basic English tokenization."""
        assert tokenize("hello world") == frozenset({"hello", "world"})

    def test_punctuation_handling(self):
        """Punctuation separates tokens."""
        assert tokenize("hello,world!") == frozenset({"hello", "world"})

    def test_empty_string(self):
        """Empty string returns empty frozenset."""
        assert tokenize("") == frozenset()

    def test_chinese_text(self):
        """Chinese characters form single token."""
        result = tokenize("性能优化")
        assert len(result) == 1
        assert "性能优化" in result


class TestIsCjkChar:
    """Tests for CJK character detection."""

    def test_chinese_char(self):
        """Chinese characters detected."""
        assert is_cjk_char("中") is True
        assert is_cjk_char("国") is True

    def test_japanese_hiragana(self):
        """Japanese Hiragana detected."""
        assert is_cjk_char("あ") is True
        assert is_cjk_char("の") is True

    def test_japanese_katakana(self):
        """Japanese Katakana detected."""
        assert is_cjk_char("ア") is True
        assert is_cjk_char("ン") is True

    def test_korean_hangul(self):
        """Korean Hangul detected."""
        assert is_cjk_char("한") is True
        assert is_cjk_char("글") is True

    def test_english_char(self):
        """English letters not CJK."""
        assert is_cjk_char("a") is False
        assert is_cjk_char("Z") is False

    def test_empty_string(self):
        """Empty string returns False."""
        assert is_cjk_char("") is False


class TestGetTokenCount:
    """Tests for get_token_count() - fast token counting."""

    def test_simple_count(self):
        """Basic token counting."""
        assert get_token_count("hello world") == 2

    def test_punctuation_handling(self):
        """Punctuation creates separate tokens."""
        assert get_token_count("hello,world") == 2

    def test_chinese_count(self):
        """Consecutive Chinese forms single token."""
        assert get_token_count("性能优化") == 1

    def test_empty_string(self):
        """Empty string has zero tokens."""
        assert get_token_count("") == 0

    def test_mixed_language(self):
        """Mixed language without separator forms single token."""
        count = get_token_count("Python性能")
        assert count == 1  # ["python性能"]


class TestGetDiversityRatio:
    """Tests for get_diversity_ratio() - word variety metric."""

    def test_all_unique(self):
        """All unique words = 1.0 diversity."""
        assert get_diversity_ratio("hello world") == 1.0

    def test_partial_duplicates(self):
        """Partial duplicates = fractional diversity."""
        ratio = get_diversity_ratio("Python Python bug")
        assert 0.6 < ratio < 0.7  # 2 unique / 3 total

    def test_empty_string(self):
        """Empty string returns 0.0."""
        assert get_diversity_ratio("") == 0.0

    def test_single_word(self):
        """Single word = 1.0 diversity."""
        assert get_diversity_ratio("hello") == 1.0

    def test_chinese_diversity(self):
        """Chinese word diversity with space separation."""
        ratio = get_diversity_ratio("性能 性能")
        # "性能 性能" becomes ["性能", "性能"] (2 tokens, 1 unique)
        assert ratio == 0.5  # 1 unique / 2 total
