from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qdrant_client.models import Filter, ScoredPoint

from myrm_agent_harness.toolkits.vector.base import VectorDocument
from myrm_agent_harness.toolkits.vector.config import DeploymentMode, VectorStoreConfig
from myrm_agent_harness.toolkits.vector.qdrant.store import QdrantVectorStore


@pytest.fixture
def mock_client():
    client = AsyncMock()
    return client


@pytest.fixture
def store(mock_client):
    config = VectorStoreConfig(mode=DeploymentMode.REMOTE, url="http://localhost:6333", api_key="test")
    return QdrantVectorStore(client=mock_client, config=config, is_async=True)


@pytest.mark.asyncio
async def test_create_collection(store, mock_client):
    mock_client.collection_exists.return_value = False
    mock_client.create_collection.return_value = True

    result = await store.create_collection("test_col", dimension=128, distance="cosine")
    assert result is True
    mock_client.create_collection.assert_called_once()


@pytest.mark.asyncio
async def test_create_collection_exists(store, mock_client):
    mock_client.collection_exists.return_value = True
    result = await store.create_collection("test_col")
    assert result is False
    mock_client.create_collection.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_collection_creates_when_missing(store, mock_client):
    mock_client.collection_exists.return_value = False
    mock_client.create_collection.return_value = True

    await store.ensure_collection("test_col", dimension=128, distance="cosine")
    mock_client.create_collection.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_collection_skips_when_exists(store, mock_client):
    mock_client.collection_exists.return_value = True

    await store.ensure_collection("test_col", dimension=128)
    mock_client.create_collection.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_collection_refuses_a_collection_of_another_model(store, mock_client):
    """A size mismatch means another embedding model's vectors: reusing it would fail every write."""
    mock_client.collection_exists.return_value = True
    info = MagicMock()
    info.config.params.vectors.size = 768
    info.config.params.vectors.distance.name = "cosine"
    info.points_count = 0
    mock_client.get_collection.return_value = info

    with pytest.raises(ValueError, match="belongs to another embedding model"):
        await store.ensure_collection("test_col", dimension=1024)


@pytest.mark.asyncio
async def test_ensure_collection_accepts_a_matching_size(store, mock_client):
    mock_client.collection_exists.return_value = True
    info = MagicMock()
    info.config.params.vectors.size = 768
    info.config.params.vectors.distance.name = "cosine"
    info.points_count = 5
    mock_client.get_collection.return_value = info

    await store.ensure_collection("test_col", dimension=768)
    mock_client.create_collection.assert_not_called()


@pytest.mark.asyncio
async def test_create_named_vector_collection_configures_every_channel(store, mock_client):
    mock_client.collection_exists.return_value = False

    created = await store.create_named_vector_collection("conv", 768, names=("raw", "summary"))

    assert created is True
    vectors_config = mock_client.create_collection.call_args.kwargs["vectors_config"]
    assert set(vectors_config) == {"raw", "summary"}
    assert all(params.size == 768 for params in vectors_config.values())


@pytest.mark.asyncio
async def test_delete_collection(store, mock_client):
    mock_client.collection_exists.return_value = True
    result = await store.delete_collection("test_col")
    assert result is True
    mock_client.delete_collection.assert_called_once_with(collection_name="test_col")


@pytest.mark.asyncio
async def test_upsert(store, mock_client):
    doc = VectorDocument(id="1", content="test", vector=[0.1, 0.2])
    result = await store.upsert("test_col", [doc])
    assert result == ["1"]
    mock_client.upsert.assert_called_once()


@pytest.mark.asyncio
async def test_search(store, mock_client):
    mock_result = MagicMock()
    mock_result.points = [ScoredPoint(id="1", version=1, score=0.9, payload={"content": "test"}, vector=[0.1, 0.2])]
    mock_client.query_points.return_value = mock_result

    results = await store.search("test_col", [0.1, 0.2], limit=1)
    assert len(results) == 1
    assert results[0].document.id == "1"
    assert results[0].score == 0.9


@pytest.mark.asyncio
async def test_get(store, mock_client):
    mock_client.retrieve.return_value = [
        ScoredPoint(id="1", version=1, score=1.0, payload={"content": "test"}, vector=[0.1, 0.2])
    ]
    results = await store.get("test_col", ["1"])
    assert len(results) == 1
    assert results[0].id == "1"


@pytest.mark.asyncio
async def test_upsert_non_uuid_id_survives_round_trip(store, mock_client):
    """A non-UUID id remapped to a qdrant point UUID must read back unchanged."""
    doc = VectorDocument(id="mem-pinned", content="test", vector=[0.1, 0.2])
    await store.upsert("test_col", [doc])

    point = mock_client.upsert.call_args.kwargs["points"][0]
    assert point.payload["original_id"] == "mem-pinned"
    assert str(point.id) != "mem-pinned"

    mock_client.retrieve.return_value = [
        ScoredPoint(id=point.id, version=1, score=1.0, payload=point.payload, vector=[0.1, 0.2])
    ]
    results = await store.get("test_col", ["mem-pinned"])
    assert results[0].id == "mem-pinned"
    assert "original_id" not in results[0].metadata


@pytest.mark.asyncio
async def test_upsert_uuid_id_stays_authoritative(store, mock_client):
    """A payload id must never override an already-UUID point id."""
    point_uuid = "3f1c9d2e-6b74-4a51-9c0e-2f5a7b8d1e44"
    doc = VectorDocument(id="other-id", content="test", vector=[0.1, 0.2])
    await store.upsert("test_col", [doc])

    mock_client.retrieve.return_value = [
        ScoredPoint(id=point_uuid, version=1, score=1.0, payload={"content": "test"}, vector=[0.1, 0.2])
    ]
    results = await store.get("test_col", [point_uuid])
    assert results[0].id == point_uuid


@pytest.mark.asyncio
async def test_delete(store, mock_client):
    mock_client.retrieve.return_value = [MagicMock()]
    result = await store.delete("test_col", ["1"])
    assert result == 1
    mock_client.delete.assert_called_once()


@pytest.mark.asyncio
async def test_delete_by_filter_without_conditions_selects_every_point(store, mock_client):
    """An empty filter is "everything" (as in search/count); the SDK rejects a bare None selector."""
    mock_client.count.return_value = MagicMock(count=3)

    deleted = await store.delete_by_filter("test_col", {})

    assert deleted == 3
    selector = mock_client.delete.call_args.kwargs["points_selector"]
    assert isinstance(selector, Filter)
    assert not (selector.must or selector.should or selector.must_not)


@pytest.mark.asyncio
async def test_delete_by_filter_keeps_the_callers_conditions(store, mock_client):
    mock_client.count.return_value = MagicMock(count=1)

    await store.delete_by_filter("test_col", {"tree_id": "t1"})

    selector = mock_client.delete.call_args.kwargs["points_selector"]
    assert selector.must[0].key == "tree_id"


@pytest.mark.asyncio
async def test_delete_by_filter_skips_the_delete_when_nothing_matches(store, mock_client):
    mock_client.count.return_value = MagicMock(count=0)

    assert await store.delete_by_filter("test_col", {}) == 0
    mock_client.delete.assert_not_called()


@pytest.mark.asyncio
async def test_count(store, mock_client):
    mock_result = MagicMock()
    mock_result.count = 5
    mock_client.count.return_value = mock_result
    result = await store.count("test_col")
    assert result == 5


@pytest.mark.asyncio
async def test_scroll(store, mock_client):
    mock_client.scroll.return_value = (
        [ScoredPoint(id="1", version=1, score=1.0, payload={"content": "test"}, vector=[0.1, 0.2])],
        "next_cursor",
    )
    docs, cursor = await store.scroll("test_col")
    assert len(docs) == 1
    assert cursor == "next_cursor"


@pytest.mark.asyncio
async def test_health_check(store, mock_client):
    mock_client.get_collections.return_value = MagicMock()
    assert await store.health_check() is True


@pytest.mark.asyncio
async def test_get_server_info(store, mock_client):
    mock_collections = MagicMock()
    mock_collections.collections = ["1", "2"]
    mock_client.get_collections.return_value = mock_collections
    info = await store.get_server_info()
    assert info["collections_count"] == 2
    assert info["mode"] == DeploymentMode.REMOTE.value


@pytest.mark.asyncio
async def test_close(store, mock_client):
    await store.close()
    mock_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_with_retry_failure(store, mock_client):
    mock_client.collection_exists.side_effect = ValueError("error")
    store.MAX_RETRIES = 1
    with pytest.raises(ValueError):
        await store._with_retry(mock_client.collection_exists, collection_name="test")


@pytest.mark.asyncio
async def test_with_retry_recovers_from_transient_error(store, mock_client):
    store.RETRY_BASE_DELAY = 0
    mock_client.collection_exists.side_effect = [ConnectionError("reset"), True]

    assert await store._with_retry(mock_client.collection_exists, collection_name="test") is True
    assert mock_client.collection_exists.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Collection `notes_bm25` not found!",
        "Unexpected Response: 404 (Not Found)\nRaw response content: Not found: Collection `notes_bm25` doesn't exist!",
    ],
)
async def test_with_retry_does_not_back_off_for_a_missing_collection(store, mock_client, message):
    """Waiting never creates the collection; backing off would stall fail-open callers such as the BM25 mirror."""
    mock_client.upsert.side_effect = RuntimeError(message)

    with (
        patch("myrm_agent_harness.toolkits.vector.qdrant.store.asyncio.sleep", new=AsyncMock()) as sleep,
        pytest.raises(RuntimeError, match="notes_bm25"),
    ):
        await store._with_retry(mock_client.upsert, collection_name="notes_bm25")

    assert mock_client.upsert.call_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_reads_of_a_missing_collection_are_empty_not_errors(store, mock_client):
    """Collections are created by their first write, so a fresh install reads them before they exist."""
    missing = ValueError("Collection notes not found")
    mock_client.query_points.side_effect = missing
    mock_client.retrieve.side_effect = missing
    mock_client.count.side_effect = missing
    mock_client.scroll.side_effect = missing

    assert await store.search("notes", [0.1] * 4) == []
    assert await store.get("notes", ["a"]) == []
    assert await store.count("notes") == 0
    assert await store.scroll("notes") == ([], None)


@pytest.mark.asyncio
async def test_a_read_failure_that_is_not_a_missing_collection_still_raises(store, mock_client):
    mock_client.query_points.side_effect = ConnectionError("qdrant down")

    with pytest.raises(ConnectionError):
        await store.search("notes", [0.1] * 4)


# --- Edge-case coverage for evict / close / health & remaining branches ---


@pytest.mark.asyncio
async def test_deployment_mode_property(store):
    assert store.deployment_mode == DeploymentMode.REMOTE.value


@pytest.mark.asyncio
async def test_delete_collection_missing(store, mock_client):
    mock_client.collection_exists.return_value = False
    result = await store.delete_collection("missing_col")
    assert result is False
    mock_client.delete_collection.assert_not_called()


@pytest.mark.asyncio
async def test_collection_exists_exception(store, mock_client):
    mock_client.collection_exists.side_effect = RuntimeError("boom")
    assert await store.collection_exists("test") is False


@pytest.mark.asyncio
async def test_get_collection_info_success(store, mock_client):
    info = MagicMock()
    info.config.params.vectors.size = 128
    info.config.params.vectors.distance.name = "cosine"
    info.points_count = 3
    mock_client.get_collection.return_value = info
    result = await store.get_collection_info("test")
    assert result is not None
    assert result.name == "test"
    assert result.dimension == 128
    assert result.distance == "cosine"
    assert result.count == 3


@pytest.mark.asyncio
async def test_get_collection_info_failure(store, mock_client):
    mock_client.get_collection.side_effect = RuntimeError("boom")
    assert await store.get_collection_info("test") is None


@pytest.mark.asyncio
async def test_list_collections(store, mock_client):
    c1 = MagicMock()
    c1.name = "a"
    c2 = MagicMock()
    c2.name = "b"
    mock_client.get_collections.return_value = MagicMock(collections=[c1, c2])
    assert await store.list_collections() == ["a", "b"]


@pytest.mark.asyncio
async def test_health_check_failure(store, mock_client):
    mock_client.get_collections.side_effect = RuntimeError("qdrant down")
    assert await store.health_check() is False


@pytest.mark.asyncio
async def test_get_server_info_failure(store, mock_client):
    mock_client.get_collections.side_effect = RuntimeError("qdrant down")
    assert await store.get_server_info() == {}


@pytest.mark.asyncio
async def test_close_skips_embedded(store, mock_client):
    store._config = VectorStoreConfig(mode=DeploymentMode.EMBEDDED, local_path=":memory:")
    await store.close()
    mock_client.close.assert_not_called()


@pytest.mark.asyncio
async def test_close_sync_client():
    client = MagicMock()
    config = VectorStoreConfig(mode=DeploymentMode.REMOTE, url="http://localhost:6333", api_key="test")
    store = QdrantVectorStore(client=client, config=config, is_async=False)
    await store.close()
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_hard_close_async_client(store, mock_client):
    await store.hard_close()
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_hard_close_sync_client():
    client = MagicMock()
    config = VectorStoreConfig(mode=DeploymentMode.REMOTE, url="http://localhost:6333", api_key="test")
    store = QdrantVectorStore(client=client, config=config, is_async=False)
    await store.hard_close()
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_hard_close_embedded_singleton():
    """hard_close must force-close even for EMBEDDED (eviction path)."""
    client = MagicMock()
    config = VectorStoreConfig(mode=DeploymentMode.EMBEDDED, local_path="/tmp/vec")
    store = QdrantVectorStore(client=client, config=config, is_async=False)
    await store.hard_close()
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_missing_collection_no_vector(store, mock_client):
    mock_client.get_collection.side_effect = RuntimeError("not found")
    doc = VectorDocument(id="1", content="test", vector=None)
    with pytest.raises(ValueError, match="cannot infer dimension"):
        await store.upsert("missing", [doc])


@pytest.mark.asyncio
async def test_upsert_document_missing_vector(store, mock_client):
    mock_client.get_collection.return_value = MagicMock()
    doc = VectorDocument(id="1", content="test", vector=None)
    with pytest.raises(ValueError, match="missing vector"):
        await store.upsert("test", [doc])


@pytest.mark.asyncio
async def test_upsert_non_uuid_id(store, mock_client):
    """Non-UUID doc ids are deterministically mapped via uuid5."""
    mock_client.get_collection.return_value = MagicMock()
    doc = VectorDocument(id="plain-text-id", content="test", vector=[0.1, 0.2])
    result = await store.upsert("test", [doc])
    assert result == ["plain-text-id"]
    mock_client.upsert.assert_called_once()


@pytest.mark.asyncio
async def test_upsert_valid_uuid_passthrough(store, mock_client):
    """A valid UUID doc id is passed through unchanged."""
    import uuid

    mock_client.get_collection.return_value = MagicMock()
    valid_id = str(uuid.uuid4())
    doc = VectorDocument(id=valid_id, content="test", vector=[0.1, 0.2])
    result = await store.upsert("test", [doc])
    assert result == [valid_id]
    mock_client.upsert.assert_called_once()


@pytest.mark.asyncio
async def test_search_multi_named_vectors(store, mock_client):
    from qdrant_client.models import ScoredPoint

    mock_result = MagicMock()
    mock_result.points = [ScoredPoint(id="1", version=1, score=0.9, payload={"content": "multi"}, vector=[0.1, 0.2])]
    mock_client.query_points.return_value = mock_result
    results = await store.search_multi_vector("test", {"dense": [0.1, 0.2]}, limit=5)
    assert len(results) == 1
    assert results[0].document.id == "1"
    mock_client.query_points.assert_called_once()
    assert mock_client.query_points.call_args.kwargs["query"] is not None


@pytest.mark.asyncio
async def test_point_to_document_dict_vector(store, mock_client):
    """A dict vector (named vectors) is discarded from VectorDocument."""
    from qdrant_client.models import ScoredPoint

    point = ScoredPoint(
        id="1",
        version=1,
        score=0.5,
        payload={"content": "dict-vec", "created_at": "2026-01-01T00:00:00+00:00"},
        vector={"dense": [0.1, 0.2]},
    )
    doc = store._point_to_document(point)
    assert doc.content == "dict-vec"
    assert doc.vector is None


@pytest.mark.asyncio
async def test_backfill_epoch_timestamps_missing_and_bad_dates(store, mock_client):
    """Backfill tolerates missing/invalid ISO dates and paginates to completion."""

    def make_point(point_id: str, created: str | None, updated: str | None) -> MagicMock:
        payload = {}
        if created is not None:
            payload["created_at"] = created
        if updated is not None:
            payload["updated_at"] = updated
        return MagicMock(id=point_id, payload=payload)

    page1 = [make_point("1", "not-a-date", "also-bad"), make_point("2", None, None)]
    mock_client.scroll.return_value = (page1, "cursor2")
    mock_client.set_payload.return_value = None

    # Second iteration returns empty points -> loop breaks.
    def scroll_side_effect(*args, **kwargs):
        offset = kwargs.get("offset")
        if offset is None:
            return (page1, "cursor2")
        return ([], None)

    mock_client.scroll.side_effect = scroll_side_effect

    updated = await store.backfill_epoch_timestamps("test", batch_size=10)
    assert updated == 2
    assert mock_client.set_payload.call_count == 2
