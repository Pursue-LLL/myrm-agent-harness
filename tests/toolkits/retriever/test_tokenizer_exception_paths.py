"""Exception-path tests for tokenizer service."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


def test_jieba_import_error() -> None:
    tokenizer_path = (
        Path(__file__).parent.parent.parent.parent / "src/myrm_agent_harness/toolkits/retriever/bm25/tokenizer.py"
    )
    spec = importlib.util.spec_from_file_location("tokenizer_test", tokenizer_path)
    tokenizer_module = importlib.util.module_from_spec(spec)

    with patch.dict("sys.modules", {"jieba": None}):
        original_import = __import__

        def mock_import(name, *args, **kwargs):
            if name == "jieba":
                raise ImportError("jieba not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            spec.loader.exec_module(tokenizer_module)

            tokenizer = tokenizer_module.TokenizerService()
            result = tokenizer.tokenize("hello world")
            assert result == ["hello", "world"]


def test_enhance_english_applies_normalizer() -> None:
    tokenizer_path = (
        Path(__file__).parent.parent.parent.parent / "src/myrm_agent_harness/toolkits/retriever/bm25/tokenizer.py"
    )
    spec = importlib.util.spec_from_file_location("tokenizer_enhance", tokenizer_path)
    tokenizer_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tokenizer_module)

    tokenizer = tokenizer_module.TokenizerService()
    tokenizer._initialize()

    result = tokenizer._enhance_english(["running", "tests"])
    assert "run" in result
    assert "test" in result


@pytest.mark.asyncio
async def test_preload_exceptions() -> None:
    tokenizer_path = (
        Path(__file__).parent.parent.parent.parent / "src/myrm_agent_harness/toolkits/retriever/bm25/tokenizer.py"
    )
    spec = importlib.util.spec_from_file_location("tokenizer_preload", tokenizer_path)
    tokenizer_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tokenizer_module)

    tokenizer = tokenizer_module.TokenizerService()

    with patch.object(tokenizer, "_async_initialize") as mock_init:
        mock_init.side_effect = RuntimeError("Init failed")

        with pytest.raises(RuntimeError, match="Init failed"):
            await tokenizer.preload()
