"""Vector store ABC default-implementation tests.

Covers the optional methods with default implementations on ``VectorStore``
so backends (Qdrant, future ones) can rely on them without re-testing.
"""

from collections.abc import Sequence
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.vector.base import (
    CollectionInfo,
    SearchResult,
    VectorDocument,
    VectorStore,
)


class _StubVectorStore(VectorStore):
    """Minimal concrete store exercising the ABC default implementations."""

    async def create_collection(
        self,
        name: str,
        dimension: int | None = None,
        distance: str = "cosine",
    ) -> bool:
        return True

    async def delete_collection(self, name: str) -> bool:
        return True

    async def collection_exists(self, name: str) -> bool:
        return True

    async def get_collection_info(self, name: str) -> CollectionInfo | None:
        return CollectionInfo(name=name, dimension=3)

    async def list_collections(self) -> list[str]:
        return ["stub"]

    async def upsert(
        self,
        collection: str,
        documents: Sequence[VectorDocument],
    ) -> list[str]:
        return [doc.id for doc in documents]

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        limit: int = 10,
        filters: dict[str, str | int | float | bool | list[str] | dict[str, str | int | float]] | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        return []

    async def get(self, collection: str, ids: list[str]) -> list[VectorDocument]:
        return []

    async def delete(self, collection: str, ids: list[str]) -> int:
        return len(ids)

    async def delete_by_filter(
        self,
        collection: str,
        filters: dict[str, str | int | float | bool | list[str] | dict[str, str | int | float]],
    ) -> int:
        return 0

    async def count(
        self,
        collection: str,
        filters: dict[str, str | int | float | bool | list[str] | dict[str, str | int | float]] | None = None,
    ) -> int:
        return 0

    async def scroll(
        self,
        collection: str,
        limit: int = 100,
        offset: str | None = None,
        filters: dict[str, str | int | float | bool | list[str] | dict[str, str | int | float]] | None = None,
        order_by: tuple[str, str] | None = None,
    ) -> tuple[list[VectorDocument], str | None]:
        return [], None

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_default_is_persistent_true() -> None:
    """Backends that don't override report persistent storage by default."""
    assert _StubVectorStore().is_persistent is True


@pytest.mark.asyncio
async def test_default_health_check_success() -> None:
    """health_check defaults to listing collections and reporting healthy."""
    store = _StubVectorStore()
    assert await store.health_check() is True


@pytest.mark.asyncio
async def test_default_health_check_propagates_failure() -> None:
    """health_check defaults to False when the underlying probe raises."""
    store = _StubVectorStore()
    store.list_collections = AsyncMock(side_effect=RuntimeError("unreachable"))
    assert await store.health_check() is False


@pytest.mark.asyncio
async def test_default_batch_upsert_chunks_and_fans_out() -> None:
    """batch_upsert splits into bounded batches and gathers all results."""
    store = _StubVectorStore()
    upserted: list[list[str]] = []

    async def counting_upsert(collection: str, documents: Sequence[VectorDocument]) -> list[str]:
        upserted.append([doc.id for doc in documents])
        return [doc.id for doc in documents]

    store.upsert = counting_upsert  # type: ignore[method-assign]
    docs = [VectorDocument(id=f"d{i}", content=f"doc-{i}") for i in range(6)]

    ids = await store.batch_upsert("col", docs, batch_size=4, max_concurrent=2)

    assert ids == [f"d{i}" for i in range(6)]
    assert [chunk for chunk in upserted] == [["d0", "d1", "d2", "d3"], ["d4", "d5"]]


@pytest.mark.asyncio
async def test_default_batch_upsert_single_batch() -> None:
    """Small batches don't chunk and hit upsert once."""
    store = _StubVectorStore()
    upserted: list[list[str]] = []

    async def counting_upsert(collection: str, documents: Sequence[VectorDocument]) -> list[str]:
        upserted.append([doc.id for doc in documents])
        return [doc.id for doc in documents]

    store.upsert = counting_upsert  # type: ignore[method-assign]
    docs = [VectorDocument(id="d0", content="only")]

    ids = await store.batch_upsert("col", docs)

    assert ids == ["d0"]
    assert upserted == [["d0"]]


@pytest.mark.asyncio
async def test_default_search_multi_vector_raises() -> None:
    """Unsupported backends fail loudly with the fallback hint."""
    store = _StubVectorStore()
    with pytest.raises(NotImplementedError, match="doesn't support search_multi_vector"):
        await store.search_multi_vector("col", {"raw": [0.1, 0.2, 0.3]})
