"""Tests for CloudEmbedding batch splitting logic."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.retriever.embedding.cloud_embedding import (
    CloudEmbedding,
    _MAX_CHARS_PER_BATCH,
    _MAX_TEXTS_PER_BATCH,
)


def _make_mock_response(count: int, dim: int = 1536) -> MagicMock:
    mock = MagicMock()
    mock.data = [{"embedding": [0.1] * dim} for _ in range(count)]
    return mock


@pytest.fixture()
def service() -> CloudEmbedding:
    return CloudEmbedding(model="text-embedding-3-small", api_key="test-key")


class TestSplitIntoBatches:
    """Unit tests for _split_into_batches static method."""

    def test_small_batch_no_split(self) -> None:
        texts = ["hello"] * 10
        batches = CloudEmbedding._split_into_batches(texts)
        assert batches == [texts]

    def test_split_by_count(self) -> None:
        texts = ["short"] * 100
        batches = CloudEmbedding._split_into_batches(texts)
        assert len(batches) == 4  # 32 + 32 + 32 + 4
        assert sum(len(b) for b in batches) == 100
        assert all(len(b) <= _MAX_TEXTS_PER_BATCH for b in batches)

    def test_split_by_chars(self) -> None:
        texts = ["x" * 40_000] * 10  # 400K total, exceeds 100K limit
        batches = CloudEmbedding._split_into_batches(texts)
        assert len(batches) > 1
        assert sum(len(b) for b in batches) == 10
        for batch in batches:
            total_chars = sum(len(t) for t in batch)
            assert total_chars <= _MAX_CHARS_PER_BATCH + 40_000  # single text can exceed

    def test_single_oversized_text(self) -> None:
        texts = ["x" * 200_000]  # Single text exceeds char limit
        batches = CloudEmbedding._split_into_batches(texts)
        assert len(batches) == 1
        assert batches[0] == texts

    def test_empty_input(self) -> None:
        batches = CloudEmbedding._split_into_batches([])
        assert batches == [[]]  # greedy packing returns one empty batch

    def test_exactly_at_count_limit(self) -> None:
        texts = ["hi"] * _MAX_TEXTS_PER_BATCH
        batches = CloudEmbedding._split_into_batches(texts)
        assert len(batches) == 1

    def test_one_over_count_limit(self) -> None:
        texts = ["hi"] * (_MAX_TEXTS_PER_BATCH + 1)
        batches = CloudEmbedding._split_into_batches(texts)
        assert len(batches) == 2
        assert len(batches[0]) == _MAX_TEXTS_PER_BATCH
        assert len(batches[1]) == 1

    def test_mixed_lengths_split_by_chars(self) -> None:
        texts = ["short"] * 20 + ["x" * 80_000] * 2
        batches = CloudEmbedding._split_into_batches(texts)
        assert sum(len(b) for b in batches) == 22
        assert len(batches) >= 2


class TestEmbedBatchWithSplit:
    """Integration tests for embed_batch with batch splitting."""

    @pytest.mark.asyncio()
    async def test_large_batch_splits_api_calls(self, service: CloudEmbedding) -> None:
        call_sizes: list[int] = []

        async def mock_aembedding(**kwargs: object) -> MagicMock:
            inputs = kwargs.get("input", [])
            assert isinstance(inputs, list)
            call_sizes.append(len(inputs))
            return _make_mock_response(len(inputs))

        with patch("litellm.aembedding", side_effect=mock_aembedding):
            result = await service.embed_batch(["text"] * 100)

        assert len(result) == 100
        assert len(call_sizes) == 4  # 32+32+32+4
        assert all(size <= _MAX_TEXTS_PER_BATCH for size in call_sizes)

    @pytest.mark.asyncio()
    async def test_small_batch_single_call(self, service: CloudEmbedding) -> None:
        call_count = 0

        async def mock_aembedding(**kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            inputs = kwargs.get("input", [])
            assert isinstance(inputs, list)
            return _make_mock_response(len(inputs))

        with patch("litellm.aembedding", side_effect=mock_aembedding):
            result = await service.embed_batch(["hello"] * 5)

        assert len(result) == 5
        assert call_count == 1

    @pytest.mark.asyncio()
    async def test_long_texts_split_by_chars(self, service: CloudEmbedding) -> None:
        call_sizes: list[int] = []

        async def mock_aembedding(**kwargs: object) -> MagicMock:
            inputs = kwargs.get("input", [])
            assert isinstance(inputs, list)
            call_sizes.append(len(inputs))
            return _make_mock_response(len(inputs))

        long_texts = ["y" * 60_000] * 5  # 5 texts x 60K = 300K chars
        with patch("litellm.aembedding", side_effect=mock_aembedding):
            result = await service.embed_batch(long_texts)

        assert len(result) == 5
        assert len(call_sizes) > 1  # Must split due to chars
        assert sum(call_sizes) == 5

    @pytest.mark.asyncio()
    async def test_empty_batch(self, service: CloudEmbedding) -> None:
        result = await service.embed_batch([])
        assert result == []

    @pytest.mark.asyncio()
    async def test_preserves_order(self, service: CloudEmbedding) -> None:
        """Verify vectors match input text order across splits."""
        counter = 0

        async def mock_aembedding(**kwargs: object) -> MagicMock:
            nonlocal counter
            inputs = kwargs.get("input", [])
            assert isinstance(inputs, list)
            mock = MagicMock()
            mock.data = []
            for _ in inputs:
                mock.data.append({"embedding": [float(counter)] * 1536})
                counter += 1
            return mock

        with patch("litellm.aembedding", side_effect=mock_aembedding):
            result = await service.embed_batch(["t"] * 70)

        assert len(result) == 70
        for i, vec in enumerate(result):
            assert vec[0] == float(i), f"Order mismatch at index {i}"
