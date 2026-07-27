"""Tests for enhanced tokenization (CJK + native English normalization)."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.retriever.bm25.tokenizer import _ENGLISH_WORD_PATTERN, get_tokenizer_service


@pytest.fixture
def tokenizer():
    return get_tokenizer_service()


def test_english_word_detection() -> None:
    assert _ENGLISH_WORD_PATTERN.match("hello")
    assert _ENGLISH_WORD_PATTERN.match("machine-learning")
    assert _ENGLISH_WORD_PATTERN.match("don't")
    assert not _ENGLISH_WORD_PATTERN.match("你好")
    assert not _ENGLISH_WORD_PATTERN.match("123")
    assert not _ENGLISH_WORD_PATTERN.match("hello123")


def test_simple_english_tokenization(tokenizer) -> None:
    text = "The quick brown fox is jumping over the lazy dog"
    tokens = tokenizer.tokenize(text, enable_english_enhancement=True)

    lower_tokens = [t.lower() for t in tokens]
    assert "the" not in lower_tokens
    assert "over" not in lower_tokens
    assert "is" not in lower_tokens
    assert "jump" in tokens or "jump" in lower_tokens


def test_chinese_tokenization(tokenizer) -> None:
    text = "机器学习是人工智能的重要分支"
    tokens = tokenizer.tokenize(text, enable_english_enhancement=True)

    assert "机器学习" in tokens or "机器" in tokens
    assert "人工智能" in tokens or "人工" in tokens


def test_mixed_language_tokenization(tokenizer) -> None:
    text = "Python is a powerful programming language for 机器学习"
    tokens = tokenizer.tokenize(text, enable_english_enhancement=True)

    assert "is" not in tokens
    assert "a" not in tokens
    assert "for" not in tokens
    assert "python" in tokens
    assert "program" in tokens
    assert "机器学习" in tokens or "机器" in tokens


def test_suffix_normalization(tokenizer) -> None:
    test_cases = {
        "running": "run",
        "jumped": "jump",
        "flies": "fly",
        "learning": "learn",
        "studies": "study",
    }

    for original, expected_stem in test_cases.items():
        tokens = tokenizer.tokenize(original, enable_english_enhancement=True)
        assert tokens
        assert tokens[0] == expected_stem, f"{original} expected {expected_stem}, got {tokens[0]}"


def test_stopword_filtering(tokenizer) -> None:
    text = "The and is are was were been being have has had do does did"
    tokens = tokenizer.tokenize(text, enable_english_enhancement=True)

    for stopword in (
        "the",
        "and",
        "is",
        "are",
        "was",
        "were",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
    ):
        assert stopword not in tokens


def test_tokenize_modes_unchanged(tokenizer) -> None:
    text = "Python 机器学习"

    simple_tokens = tokenizer.tokenize(text, mode="simple", enable_english_enhancement=False)
    search_tokens = tokenizer.tokenize(text, mode="search", enable_english_enhancement=False)
    assert simple_tokens
    assert search_tokens


def test_special_characters(tokenizer) -> None:
    text = "hello-world, don't worry! machine_learning"
    tokens = tokenizer.tokenize(text, enable_english_enhancement=True)

    assert any("hello" in t or "world" in t for t in tokens)
    assert any("worry" in t or "worri" in t for t in tokens)


def test_empty_and_whitespace(tokenizer) -> None:
    assert tokenizer.tokenize("") == []
    assert tokenizer.tokenize("   ") == []
    assert tokenizer.tokenize("\n\t  \n") == []


@pytest.mark.asyncio
async def test_async_preload(tokenizer) -> None:
    await tokenizer.preload(enable_english_enhancement=True)
    tokens = tokenizer.tokenize("test preload", enable_english_enhancement=True)
    assert tokens


def test_real_world_query(tokenizer) -> None:
    queries = [
        "how to use Python for machine learning",
        "深度学习 deep learning tutorial",
        "自然语言处理 NLP techniques",
    ]

    for query in queries:
        tokens = tokenizer.tokenize(query, enable_english_enhancement=True)
        assert tokens
        assert "to" not in tokens
        assert "for" not in tokens
