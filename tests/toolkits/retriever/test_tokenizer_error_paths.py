"""Error-path tests for tokenizer service."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest


def load_tokenizer_module():
    tokenizer_path = (
        Path(__file__).parent.parent.parent.parent / "src/myrm_agent_harness/toolkits/retriever/bm25/tokenizer.py"
    )
    spec = importlib.util.spec_from_file_location("_tokenizer", tokenizer_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_jieba_import_failure_fallback() -> None:
    mod = load_tokenizer_module()
    tokenizer = mod.TokenizerService()
    tokenizer._jieba = None
    tokenizer._initialized = True

    result = tokenizer.tokenize("hello world 测试")
    assert "hello" in result and "world" in result and "测试" in result


@pytest.mark.asyncio
async def test_preload_exception_handling() -> None:
    mod = load_tokenizer_module()
    tokenizer = mod.TokenizerService()

    async def mock_async_init() -> None:
        raise RuntimeError("Async init failed")

    tokenizer._async_initialize = mock_async_init

    with pytest.raises(RuntimeError, match="Async init failed"):
        await tokenizer.preload()
