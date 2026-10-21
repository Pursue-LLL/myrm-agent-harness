"""Qdrant sparse-mixin unit tests — capability lifecycle against a fake client.

Covers ensure idempotency (existing collection → no-op), the 409
"already exists" creation race treated as success, unexpected error
re-raise, sparse upsert struct building (named ``bm25`` vector + dense-layout
payload), named-vector sparse queries with result mapping, and document
conversion defaults — all against an in-memory fake client (no embedded
qdrant, no IO).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from qdrant_client import models

from myrm_agent_harness.toolkits.vector.base import FilterDict, SparsePoint
from myrm_agent_harness.toolkits.vector.qdrant.sparse import QdrantSparseMixin


class _FakeClient:
    """In-memory qdrant client double: collections plus call recording."""

    def __init__(self, *, collections: set[str] | None = None, create_error: Exception | None = None) -> None:
        self.collections: set[str] = collections if collections is not None else set()
        self.create_error = create_error
        self.create_calls: list[str] = []
        self.upserts: list[tuple[str, list[object]]] = []
        self.queries: list[dict[str, object]] = []

    def get_collection(self, *, collection_name: str) -> object:
        if collection_name not in self.collections:
            raise RuntimeError(f"Collection `{collection_name}` not found!")
        return SimpleNamespace(exists=True)

    def create_collection(self, *, collection_name: str, sparse_vectors_config: object) -> object:
        self.create_calls.append(collection_name)
        if self.create_error is not None:
            raise self.create_error
        self.collections.add(collection_name)
        return SimpleNamespace(ok=True)

    def upsert(self, *, collection_name: str, points: list[object]) -> object:
        self.upserts.append((collection_name, points))
        return SimpleNamespace(operation_id=1, status="completed")

    def query_points(
        self,
        *,
        collection_name: str,
        query: object,
        using: str,
        query_filter: object,
        limit: int,
        score_threshold: float | None,
        with_payload: bool,
    ) -> object:
        self.queries.append(
            {
                "collection": collection_name,
                "query": query,
                "using": using,
                "query_filter": query_filter,
                "limit": limit,
                "with_payload": with_payload,
            }
        )
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    id="pid-d1",
                    score=2.5,
                    payload={
                        "original_id": "d1",
                        "content": "litellm gateway outage",
                        "created_at": "2026-01-02T03:04:05+00:00",
                        "updated_at": "2026-01-02T03:04:05+00:00",
                        "user_id": "u1",
                    },
                )
            ]
        )


class _FakeHost(QdrantSparseMixin):
    """Minimal host supplying the collaborators the mixin expects."""

    def __init__(self, client: _FakeClient) -> None:
        self._client = client
        self.executed: list[str] = []
        self.retried: list[tuple[str, dict[str, object]]] = []

    async def _execute(self, operation: object, *args: object, **kwargs: object) -> object:
        self.executed.append(getattr(operation, "__name__", "<op>"))
        func = cast("Callable[..., object]", operation)
        return func(*args, **kwargs)

    async def _with_retry(self, operation: object, *args: object, **kwargs: object) -> object:
        self.retried.append((getattr(operation, "__name__", "<op>"), kwargs))
        func = cast("Callable[..., object]", operation)
        return func(*args, **kwargs)

    def point_id_for(self, id_str: str) -> str:
        return f"pid-{id_str}"


def make_point(pid: str, indices: list[int], values: list[float], content: str) -> SparsePoint:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    return SparsePoint(
        id=pid,
        indices=indices,
        values=values,
        content=content,
        metadata={"user_id": "u1"},
        created_at=ts,
        updated_at=ts,
    )


# ── Readiness & ensure lifecycle ──────────────────────────────────────


@pytest.mark.asyncio
async def test_ready_false_when_collection_absent() -> None:
    host = _FakeHost(_FakeClient())
    assert await host.sparse_collection_ready("gone_bm25") is False


@pytest.mark.asyncio
async def test_ready_true_when_present() -> None:
    host = _FakeHost(_FakeClient(collections={"sem_bm25"}))
    assert await host.sparse_collection_ready("sem_bm25") is True


@pytest.mark.asyncio
async def test_ensure_creates_named_bm25_sparse_collection_once() -> None:
    client = _FakeClient()
    host = _FakeHost(client)

    assert await host.ensure_sparse_collection("sem_bm25") is True
    assert client.create_calls == ["sem_bm25"]
    assert "sem_bm25" in client.collections

    # Idempotent: the second ensure is a no-op (already existed → False).
    assert await host.ensure_sparse_collection("sem_bm25") is False
    assert client.create_calls == ["sem_bm25"]


@pytest.mark.asyncio
async def test_ensure_treats_409_already_exists_race_as_success() -> None:
    client = _FakeClient(create_error=RuntimeError("Collection `sem_bm25` already exists!"))
    host = _FakeHost(client)

    # A concurrent creator raced past the readiness probe; Qdrant's 409 is
    # success for ensure — False (not created by us), and no exception.
    assert await host.ensure_sparse_collection("sem_bm25") is False


@pytest.mark.asyncio
async def test_ensure_reraises_unexpected_creation_errors() -> None:
    client = _FakeClient(create_error=RuntimeError("disk quota exceeded"))
    host = _FakeHost(client)

    with pytest.raises(RuntimeError, match="disk quota"):
        await host.ensure_sparse_collection("sem_bm25")


# ── Sparse upsert struct building ─────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_sparse_builds_named_vector_points() -> None:
    client = _FakeClient(collections={"sem_bm25"})
    host = _FakeHost(client)
    ts = datetime(2026, 1, 1, tzinfo=UTC)

    ids = await host.upsert_sparse(
        "sem_bm25",
        [
            make_point("d1", [10, 20], [1.0, 1.7], "hello litellm"),
            make_point("d2", [30], [2.0], "fastapi service"),
        ],
    )

    assert ids == ["d1", "d2"]
    assert host.retried[0][0] == "upsert"
    collection, structs = client.upserts[0]
    assert collection == "sem_bm25"
    assert len(structs) == 2

    first = cast("models.PointStruct", structs[0])
    assert first.id == "pid-d1"  # point_id_for applied
    vector = cast("dict[str, models.SparseVector]", first.vector)
    assert set(vector) == {"bm25"}  # named sparse vector
    assert vector["bm25"].indices == [10, 20]
    assert vector["bm25"].values == [1.0, 1.7]
    payload = cast("dict[str, object]", first.payload)
    assert payload["original_id"] == "d1"
    assert payload["content"] == "hello litellm"
    assert payload["created_at"] == ts.isoformat()
    assert payload["_created_ts"] == ts.timestamp()
    assert payload["user_id"] == "u1"


# ── Sparse query & result mapping ────────────────────────────────────


@pytest.mark.asyncio
async def test_search_sparse_queries_named_vector_and_maps_documents() -> None:
    client = _FakeClient(collections={"sem_bm25"})
    host = _FakeHost(client)

    results = await host.search_sparse("sem_bm25", [10, 30], [1.0, 1.0], limit=5)

    query = client.queries[0]
    assert query["using"] == "bm25"
    assert query["limit"] == 5
    sparse_query = cast("models.SparseVector", query["query"])
    assert sparse_query.indices == [10, 30]
    assert sparse_query.values == [1.0, 1.0]
    # filters=None builds no qdrant filter.
    assert query["query_filter"] is None

    assert len(results) == 1
    result = results[0]
    assert result.score == 2.5
    # original_id wins over the qdrant point id; iso timestamps round-trip.
    assert result.document.id == "d1"
    assert result.document.content == "litellm gateway outage"
    assert result.document.metadata["user_id"] == "u1"
    assert result.document.created_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.mark.asyncio
async def test_search_sparse_forwards_user_filters() -> None:
    client = _FakeClient(collections={"sem_bm25"})
    host = _FakeHost(client)
    filters: FilterDict = {"archived": {"not": True}, "primary_namespace": ["work"]}

    await host.search_sparse("sem_bm25", [10], [1.0], limit=3, filters=filters)

    query = client.queries[0]
    built = cast("models.Filter", query["query_filter"])
    assert built is not None  # real qdrant Filter built from FilterDict


def test_sparse_point_to_document_defaults_when_payload_sparse() -> None:
    host = _FakeHost(_FakeClient())

    # Missing timestamps fall back to now(); missing original_id falls back
    # to the qdrant point id.
    partial = models.ScoredPoint(id="pid-x", version=0, score=1.0, payload={"content": "only content"})
    doc = host._sparse_point_to_document(partial)
    assert doc.id == "pid-x"
    assert doc.content == "only content"
    assert doc.created_at.tzinfo is UTC
    assert doc.updated_at.tzinfo is UTC

    # Entirely absent payload → empty metadata and empty content.
    bare = models.ScoredPoint(id="pid-y", version=0, score=1.0, payload=None)
    empty = host._sparse_point_to_document(bare)
    assert empty.metadata == {}
    assert empty.content == ""
