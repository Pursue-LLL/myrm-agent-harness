"""Unit tests for IntegrationFetcher — validates resilience mechanisms.

Covers:
- Timeout handling (provider fetch exceeds deadline)
- Idempotent dedup (same external_object_id not ingested twice)
- Batch processing (correct splitting and aggregation)
- Concurrent semaphore limiting
- Error isolation (one batch failure doesn't corrupt overall state)
- Provider not found graceful error
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.integration.fetcher import (
    _EMBED_BATCH_SIZE,
    _MAX_CONCURRENT_PROVIDERS,
    IntegrationFetcher,
)
from myrm_agent_harness.toolkits.memory.integration.types import (
    IntegrationLeaf,
    IntegrationTree,
)


def _make_leaf(provider: str = "github", ext_id: str = "obj-1", title: str = "test") -> IntegrationLeaf:
    return IntegrationLeaf(
        provider=provider,
        external_object_id=ext_id,
        title=title,
        content=f"Content for {ext_id}",
    )


def _make_tree(provider: str = "github") -> IntegrationTree:
    return IntegrationTree(provider=provider)


def _make_fetcher(
    vector_store: AsyncMock | None = None,
    embedding: AsyncMock | None = None,
    tree_manager: AsyncMock | None = None,
) -> IntegrationFetcher:
    vs = vector_store or AsyncMock()
    if not vs.upsert._mock_name:
        vs.upsert = AsyncMock()

    emb = embedding or AsyncMock()
    if not hasattr(emb.embed_batch, "_mock_name") or emb.embed_batch._mock_name:
        emb.embed_batch = AsyncMock(
            side_effect=lambda texts: [[0.1] * 128 for _ in texts]
        )

    tm = tree_manager or AsyncMock()
    tm.get_or_create_tree = AsyncMock(return_value=_make_tree())
    tm.attach_leaf = AsyncMock()
    return IntegrationFetcher(vector_store=vs, embedding=emb, tree_manager=tm)


def _make_provider(
    leaves: list[IntegrationLeaf] | None = None,
    fetch_delay: float = 0,
    cursor: str | None = "cursor-1",
) -> MagicMock:
    provider = MagicMock()
    provider.provider_id = "test-provider"

    async def _fetch(**kwargs):
        if fetch_delay > 0:
            await asyncio.sleep(fetch_delay)
        return leaves or []

    provider.fetch = AsyncMock(side_effect=_fetch)
    provider.get_sync_cursor = AsyncMock(return_value=cursor)
    provider.validate_connection = AsyncMock(return_value=True)
    return provider


class TestFetcherTimeout:
    """Verify timeout protection works correctly."""

    @pytest.mark.asyncio
    async def test_fetch_timeout_returns_failed_result(self):
        fetcher = _make_fetcher()
        provider = _make_provider(fetch_delay=200)
        fetcher.register_provider(provider)

        with patch(
            "myrm_agent_harness.toolkits.memory.integration.fetcher._PROVIDER_FETCH_TIMEOUT_S",
            0.01,
        ):
            result = await fetcher.sync_provider("test-provider")

        assert result.failed == 1
        assert "timed out" in result.errors[0]
        assert result.created == 0

    @pytest.mark.asyncio
    async def test_timeout_does_not_update_cursor(self):
        fetcher = _make_fetcher()
        provider = _make_provider(fetch_delay=200)
        fetcher.register_provider(provider)

        with patch(
            "myrm_agent_harness.toolkits.memory.integration.fetcher._PROVIDER_FETCH_TIMEOUT_S",
            0.01,
        ):
            await fetcher.sync_provider("test-provider")

        assert fetcher._cursors.get("test-provider::") is None


class TestFetcherIdempotent:
    """Verify deduplication prevents double ingestion."""

    @pytest.mark.asyncio
    async def test_same_leaf_not_ingested_twice(self):
        vs = AsyncMock()
        vs.upsert = AsyncMock()
        emb = AsyncMock()
        emb.embed_batch = AsyncMock(return_value=[[0.1] * 128])
        tm = AsyncMock()
        tm.get_or_create_tree = AsyncMock(return_value=_make_tree())
        tm.attach_leaf = AsyncMock()

        fetcher = IntegrationFetcher(vector_store=vs, embedding=emb, tree_manager=tm)

        leaf = _make_leaf(ext_id="unique-1")
        provider = _make_provider(leaves=[leaf])
        fetcher.register_provider(provider)

        r1 = await fetcher.sync_provider("test-provider")
        assert r1.created == 1

        r2 = await fetcher.sync_provider("test-provider")
        assert r2.skipped == 1
        assert r2.created == 0


class TestFetcherBatching:
    """Verify batch processing splits correctly."""

    @pytest.mark.asyncio
    async def test_large_dataset_split_into_batches(self):
        count = _EMBED_BATCH_SIZE * 2 + 5
        leaves = [_make_leaf(ext_id=f"obj-{i}") for i in range(count)]

        vs = AsyncMock()
        vs.upsert = AsyncMock()
        emb = AsyncMock()
        emb.embed_batch = AsyncMock(
            side_effect=lambda texts: [[0.1] * 128 for _ in texts]
        )
        tm = AsyncMock()
        tm.get_or_create_tree = AsyncMock(return_value=_make_tree())
        tm.attach_leaf = AsyncMock()

        fetcher = IntegrationFetcher(vector_store=vs, embedding=emb, tree_manager=tm)
        provider = _make_provider(leaves=leaves)
        fetcher.register_provider(provider)

        result = await fetcher.sync_provider("test-provider")

        assert result.created == count
        assert emb.embed_batch.call_count == 3
        assert vs.upsert.call_count == 3


class TestFetcherErrorIsolation:
    """Verify errors in one batch don't corrupt the entire sync."""

    @pytest.mark.asyncio
    async def test_embedding_failure_marks_batch_failed(self):
        vs = AsyncMock()
        vs.upsert = AsyncMock()
        emb = AsyncMock()
        emb.embed_batch = AsyncMock(side_effect=RuntimeError("API quota exceeded"))
        tm = AsyncMock()
        tm.get_or_create_tree = AsyncMock(return_value=_make_tree())
        tm.attach_leaf = AsyncMock()

        fetcher = IntegrationFetcher(vector_store=vs, embedding=emb, tree_manager=tm)
        leaves = [_make_leaf(ext_id=f"obj-{i}") for i in range(3)]
        provider = _make_provider(leaves=leaves)
        fetcher.register_provider(provider)

        result = await fetcher.sync_provider("test-provider")

        assert result.failed == 3
        assert "Embedding error" in result.errors[0]

    @pytest.mark.asyncio
    async def test_vector_upsert_failure_does_not_mark_known(self):
        vs = AsyncMock()
        vs.upsert = AsyncMock(side_effect=RuntimeError("DB connection lost"))
        emb = AsyncMock()
        emb.embed_batch = AsyncMock(return_value=[[0.1] * 128])
        tm = AsyncMock()
        tm.get_or_create_tree = AsyncMock(return_value=_make_tree())
        tm.attach_leaf = AsyncMock()

        fetcher = IntegrationFetcher(vector_store=vs, embedding=emb, tree_manager=tm)
        leaf = _make_leaf(ext_id="retry-me")
        provider = _make_provider(leaves=[leaf])
        fetcher.register_provider(provider)

        r1 = await fetcher.sync_provider("test-provider")
        assert r1.failed == 1

        assert not fetcher._is_known("github", "retry-me")


class TestFetcherProviderNotFound:
    """Verify graceful handling of unregistered provider."""

    @pytest.mark.asyncio
    async def test_unknown_provider_returns_error(self):
        fetcher = _make_fetcher()
        result = await fetcher.sync_provider("nonexistent")

        assert result.failed == 1
        assert "not registered" in result.errors[0]


class TestFetcherConcurrency:
    """Verify semaphore-based concurrency control."""

    @pytest.mark.asyncio
    async def test_sync_all_respects_semaphore(self):
        active = {"count": 0, "max": 0}

        async def _tracked_fetch(**kwargs):
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
            await asyncio.sleep(0.01)
            active["count"] -= 1
            return [_make_leaf(ext_id=f"leaf-{kwargs.get('account_key', '')}")]

        vs = AsyncMock()
        vs.upsert = AsyncMock()
        emb = AsyncMock()
        emb.embed_batch = AsyncMock(return_value=[[0.1] * 128])
        tm = AsyncMock()
        tm.get_or_create_tree = AsyncMock(return_value=_make_tree())
        tm.attach_leaf = AsyncMock()

        fetcher = IntegrationFetcher(vector_store=vs, embedding=emb, tree_manager=tm)

        for i in range(_MAX_CONCURRENT_PROVIDERS + 3):
            p = MagicMock()
            p.provider_id = f"provider-{i}"
            p.fetch = AsyncMock(side_effect=_tracked_fetch)
            p.get_sync_cursor = AsyncMock(return_value=None)
            fetcher.register_provider(p)

        results = await fetcher.sync()

        assert len(results) == _MAX_CONCURRENT_PROVIDERS + 3
        assert active["max"] <= _MAX_CONCURRENT_PROVIDERS
