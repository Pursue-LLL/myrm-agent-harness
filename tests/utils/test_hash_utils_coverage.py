"""Tests for hash_utils - covering all hash strategies and caching."""

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.utils.hash_utils import (
    _compute_hash,
    clear_hash_cache,
    get_cache_stats,
    get_content_hash,
    get_document_dedup_hash,
)


class TestComputeHash:
    def test_md5(self):
        result = _compute_hash("hello", "md5")
        assert len(result) == 32

    def test_sha256(self):
        result = _compute_hash("hello", "sha256")
        assert len(result) == 64

    def test_blake2b(self):
        result = _compute_hash("hello", "blake2b")
        assert len(result) == 32

    def test_builtin(self):
        result = _compute_hash("hello", "builtin")
        assert result == str(hash("hello"))

    def test_empty_content(self):
        assert _compute_hash("", "md5") == ""

    def test_unsupported_strategy(self):
        with pytest.raises(ValueError, match="Unsupported hash strategy"):
            _compute_hash("hello", "unknown")


class TestGetContentHash:
    def test_string_content_no_cache(self):
        result = get_content_hash("hello world", use_cache=False)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_document_content_no_cache(self):
        doc = Document(page_content="test content")
        result = get_content_hash(doc, use_cache=False)
        assert isinstance(result, str)

    def test_document_cached_in_metadata(self):
        doc = Document(page_content="test", metadata={"content_hash": "cached_hash"})
        result = get_content_hash(doc)
        assert result == "cached_hash"

    def test_no_cache(self):
        result = get_content_hash("test", use_cache=False)
        assert isinstance(result, str)

    def test_clean_content(self):
        result = get_content_hash("test content", clean_content=True, use_cache=False)
        assert isinstance(result, str)

    def test_different_strategies(self):
        results = set()
        for strategy in ["md5", "sha256", "blake2b"]:
            results.add(get_content_hash("hello", strategy=strategy, use_cache=False))
        assert len(results) == 3


class TestGetDocumentDedupHash:
    def test_basic(self):
        doc = Document(page_content="test content")
        result = get_document_dedup_hash(doc)
        assert isinstance(result, str)
        assert "original_content_hash" in doc.metadata

    def test_cached_hash(self):
        doc = Document(page_content="test", metadata={"original_content_hash": "pre_cached"})
        result = get_document_dedup_hash(doc)
        assert result == "pre_cached"


class TestCacheManagement:
    def test_clear_cache(self):
        clear_hash_cache()
        stats = get_cache_stats()
        assert stats["cache_size"] == 0

    def test_get_cache_stats(self):
        clear_hash_cache()
        stats = get_cache_stats()
        assert stats["max_size"] == 10000
        assert stats["ttl"] == 7200
        assert isinstance(stats["cache_keys"], list)
