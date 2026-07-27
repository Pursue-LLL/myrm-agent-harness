"""Tests for unified tokenizer service (CJK + English)."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.retriever.bm25.tokenizer import get_tokenizer_service


@pytest.fixture
def tokenizer():
    return get_tokenizer_service()


def test_simple_english_tokenization(tokenizer) -> None:
    text = "The quick brown fox is jumping over the lazy dog"
    tokens = tokenizer.tokenize(text)

    lower_tokens = [t.lower() for t in tokens]
    assert "quick" in lower_tokens or "the" in lower_tokens
    assert "jumping" in lower_tokens or "jump" in lower_tokens


def test_chinese_tokenization(tokenizer) -> None:
    text = "机器学习是人工智能的重要分支"
    tokens = tokenizer.tokenize(text)

    assert "机器学习" in tokens or "机器" in tokens
    assert "人工智能" in tokens or "人工" in tokens


def test_mixed_language_tokenization(tokenizer) -> None:
    text = "Python is a powerful programming language for 机器学习"
    tokens = tokenizer.tokenize(text)

    lower_tokens = [t.lower() for t in tokens]
    assert "python" in lower_tokens
    assert "机器学习" in tokens or "机器" in tokens


def test_tokenize_modes(tokenizer) -> None:
    text = "Python 机器学习"

    simple_tokens = tokenizer.tokenize(text, mode="simple")
    search_tokens = tokenizer.tokenize(text, mode="search")
    assert simple_tokens
    assert search_tokens


def test_empty_and_whitespace(tokenizer) -> None:
    assert tokenizer.tokenize("") == []
    assert tokenizer.tokenize("   ") == []
    assert tokenizer.tokenize("\n\t  \n") == []


@pytest.mark.asyncio
async def test_async_preload(tokenizer) -> None:
    await tokenizer.preload()
    tokens = tokenizer.tokenize("test preload")
    assert tokens


def test_real_world_query(tokenizer) -> None:
    queries = [
        "how to use Python for machine learning",
        "深度学习 deep learning tutorial",
        "自然语言处理 NLP techniques",
    ]

    for query in queries:
        tokens = tokenizer.tokenize(query)
        assert tokens
