"""Tests for unified tokenizer service (CJK + English)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.retriever.bm25 import tokenizer as tokenizer_module
from myrm_agent_harness.toolkits.retriever.bm25.tokenizer import (
    TokenizerService,
    get_tokenizer_service,
    preload_tokenizer,
)


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


def test_backend_bigram_fallback(tokenizer) -> None:
    if tokenizer.backend == "jieba":
        pytest.skip("jieba installed in environment")
    assert tokenizer.backend == "bigram_fallback"


def test_jieba_tokenize_paths_with_mock() -> None:
    service = TokenizerService()
    mock_jieba = MagicMock()
    mock_jieba.cut.return_value = ["hello", " ", "world"]
    mock_jieba.cut_for_search.return_value = ["hello", "world"]
    service._jieba = mock_jieba
    service._initialized = True

    assert service.backend == "jieba"
    assert service.tokenize("hello world") == ["hello", "world"]
    assert service.tokenize("hello world", mode="search") == ["hello", "world"]

    service._init_jieba_sync()
    mock_jieba.initialize.assert_not_called()


@pytest.mark.asyncio
async def test_module_preload_tokenizer() -> None:
    await preload_tokenizer()


@pytest.mark.asyncio
async def test_preload_failure_raises() -> None:
    service = TokenizerService()
    with patch.object(service, "_async_initialize", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            await service.preload()


def test_jieba_init_success_path() -> None:
    service = TokenizerService()
    mock_jieba = MagicMock()
    with patch.dict("sys.modules", {"jieba": mock_jieba}):
        service._jieba = None
        service._initialized = False
        service._init_jieba_sync()
    assert service._jieba is mock_jieba
    mock_jieba.initialize.assert_called_once()


@pytest.mark.asyncio
async def test_async_initialize_runs_in_executor() -> None:
    service = TokenizerService()
    service._initialized = False
    with patch.object(service, "_init_jieba_sync") as init_mock:
        await service._async_initialize()
        init_mock.assert_called_once()
    assert service._initialized is True


def test_jieba_import_failure_uses_fallback() -> None:
    service = TokenizerService()
    with patch.dict("sys.modules", {"jieba": None}), patch.object(tokenizer_module, "logger"):
        service._jieba = None
        service._initialized = False
        with patch("builtins.__import__", side_effect=ImportError("no jieba")):
            service._init_jieba_sync()
    assert service._jieba is None
