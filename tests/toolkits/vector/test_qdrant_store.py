from unittest.mock import AsyncMock, MagicMock

import pytest
from qdrant_client.models import ScoredPoint

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
    mock_result.points = [
        ScoredPoint(id="1", version=1, score=0.9, payload={"content": "test"}, vector=[0.1, 0.2])
    ]
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
async def test_delete(store, mock_client):
    mock_client.retrieve.return_value = [MagicMock()]
    result = await store.delete("test_col", ["1"])
    assert result == 1
    mock_client.delete.assert_called_once()

@pytest.mark.asyncio
async def test_count(store, mock_client):
    mock_result = MagicMock()
    mock_result.count = 5
    mock_client.count.return_value = mock_result
    result = await store.count("test_col")
    assert result == 5

@pytest.mark.asyncio
async def test_scroll(store, mock_client):
    mock_client.scroll.return_value = ([
        ScoredPoint(id="1", version=1, score=1.0, payload={"content": "test"}, vector=[0.1, 0.2])
    ], "next_cursor")
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
    mock_client.collection_exists.side_effect = Exception("error")
    store.MAX_RETRIES = 1
    with pytest.raises(Exception):
        await store._with_retry(mock_client.collection_exists, collection_name="test")
