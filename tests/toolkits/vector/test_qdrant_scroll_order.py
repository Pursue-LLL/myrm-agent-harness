"""Tests for QdrantVectorStore scroll order_by, ensure_payload_indexes, and epoch timestamps."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from qdrant_client.models import ScoredPoint

from myrm_agent_harness.toolkits.vector.base import VectorDocument
from myrm_agent_harness.toolkits.vector.config import DeploymentMode, VectorStoreConfig
from myrm_agent_harness.toolkits.vector.qdrant.store import QdrantVectorStore


@pytest.fixture
def mock_client():
    return AsyncMock()


@pytest.fixture
def store(mock_client):
    config = VectorStoreConfig(mode=DeploymentMode.REMOTE, url="http://localhost:6333", api_key="test")
    return QdrantVectorStore(client=mock_client, config=config, is_async=True)


class TestScrollOrderBy:
    @pytest.mark.asyncio
    async def test_scroll_without_order_by(self, store, mock_client):
        mock_client.scroll.return_value = ([], None)
        await store.scroll("col", limit=10)
        call_kwargs = mock_client.scroll.call_args[1]
        assert "order_by" not in call_kwargs
        assert call_kwargs["offset"] is None

    @pytest.mark.asyncio
    async def test_scroll_with_order_by_desc(self, store, mock_client):
        from qdrant_client.http.models import Direction, OrderBy

        mock_client.scroll.return_value = ([], None)
        await store.scroll("col", limit=10, order_by=("_created_ts", "desc"))
        call_kwargs = mock_client.scroll.call_args[1]
        ob = call_kwargs["order_by"]
        assert isinstance(ob, OrderBy)
        assert ob.key == "_created_ts"
        assert ob.direction == Direction.DESC

    @pytest.mark.asyncio
    async def test_scroll_with_order_by_asc(self, store, mock_client):
        from qdrant_client.http.models import Direction, OrderBy

        mock_client.scroll.return_value = ([], None)
        await store.scroll("col", limit=5, order_by=("importance", "asc"))
        call_kwargs = mock_client.scroll.call_args[1]
        ob = call_kwargs["order_by"]
        assert ob.key == "importance"
        assert ob.direction == Direction.ASC

    @pytest.mark.asyncio
    async def test_scroll_order_by_with_offset(self, store, mock_client):
        mock_client.scroll.return_value = ([], None)
        await store.scroll("col", limit=10, offset="uuid-123", order_by=("_updated_ts", "desc"))
        call_kwargs = mock_client.scroll.call_args[1]
        assert call_kwargs["offset"] == "uuid-123"
        assert "order_by" in call_kwargs


class TestEnsurePayloadIndexes:
    @pytest.mark.asyncio
    async def test_creates_four_indexes(self, store, mock_client):
        mock_client.create_payload_index.return_value = True
        await store.ensure_payload_indexes("test_col")
        assert mock_client.create_payload_index.call_count == 4
        created_fields = [c[1]["field_name"] for c in mock_client.create_payload_index.call_args_list]
        assert set(created_fields) == {"_created_ts", "_updated_ts", "importance", "tags"}

    @pytest.mark.asyncio
    async def test_swallows_errors_gracefully(self, store, mock_client):
        mock_client.create_payload_index.side_effect = Exception("already exists")
        await store.ensure_payload_indexes("test_col")


class TestUpsertEpochTimestamps:
    @pytest.mark.asyncio
    async def test_upsert_includes_epoch_timestamps(self, store, mock_client):
        now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        doc = VectorDocument(id="doc1", content="test", vector=[0.1, 0.2], created_at=now, updated_at=now)
        await store.upsert("test_col", [doc])
        call_args = mock_client.upsert.call_args
        point = call_args[1]["points"][0]
        assert "_created_ts" in point.payload
        assert "_updated_ts" in point.payload
        assert isinstance(point.payload["_created_ts"], float)
        assert point.payload["_created_ts"] == now.timestamp()


class TestBackfillEpochTimestamps:
    @pytest.mark.asyncio
    async def test_backfill_no_missing_points(self, store, mock_client):
        mock_client.scroll.return_value = ([], None)
        count = await store.backfill_epoch_timestamps("test_col")
        assert count == 0
        mock_client.set_payload.assert_not_called()

    @pytest.mark.asyncio
    async def test_backfill_updates_missing_points(self, store, mock_client):
        point = MagicMock()
        point.id = "point-1"
        point.payload = {"created_at": "2026-01-15T12:00:00+00:00", "updated_at": "2026-01-15T13:00:00+00:00"}
        mock_client.scroll.side_effect = [([point], None)]
        count = await store.backfill_epoch_timestamps("test_col")
        assert count == 1
        set_call = mock_client.set_payload.call_args[1]
        assert "_created_ts" in set_call["payload"]
        assert "_updated_ts" in set_call["payload"]

    @pytest.mark.asyncio
    async def test_backfill_handles_malformed_dates(self, store, mock_client):
        point = MagicMock()
        point.id = "point-2"
        point.payload = {"created_at": "not-a-date"}
        mock_client.scroll.side_effect = [([point], None)]
        count = await store.backfill_epoch_timestamps("test_col")
        assert count == 1
        set_call = mock_client.set_payload.call_args[1]
        assert isinstance(set_call["payload"]["_created_ts"], float)
