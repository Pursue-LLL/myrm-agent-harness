"""Tests for list_by_type sort_by/tag_filter and tag normalization in converters."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import (
    _SORT_FIELD_MAP,
    count_by_type,
    list_by_type,
)
from myrm_agent_harness.toolkits.memory._internal.storage_converters import (
    episodic_to_doc,
    semantic_to_doc,
)
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemoryType,
    SemanticMemory,
)
from myrm_agent_harness.toolkits.vector.base import VectorDocument


class TestSortFieldMap:
    def test_maps_created_at(self):
        assert _SORT_FIELD_MAP["created_at"] == "_created_ts"

    def test_maps_updated_at(self):
        assert _SORT_FIELD_MAP["updated_at"] == "_updated_ts"

    def test_maps_importance(self):
        assert _SORT_FIELD_MAP["importance"] == "importance"


class TestListByTypeSortAndFilter:
    @pytest.fixture
    def config(self):
        return MemoryConfig(embedding_model="test-model")

    @pytest.fixture
    def mock_vector(self):
        vec = AsyncMock()
        vec.scroll.return_value = ([], None)
        vec.count.return_value = 0
        return vec

    @pytest.mark.asyncio
    async def test_passes_order_by_to_scroll(self, mock_vector, config):
        await list_by_type(
            MemoryType.SEMANTIC,
            limit=10,
            offset=0,
            relational=None,
            vector=mock_vector,
            config=config,
            sort_by="created_at",
            sort_order="desc",
        )
        call_kwargs = mock_vector.scroll.call_args[1]
        assert call_kwargs["order_by"] == ("_created_ts", "desc")

    @pytest.mark.asyncio
    async def test_passes_tag_filter_to_scroll(self, mock_vector, config):
        await list_by_type(
            MemoryType.SEMANTIC,
            limit=10,
            offset=0,
            relational=None,
            vector=mock_vector,
            config=config,
            tag_filter="MyTag",
        )
        call_kwargs = mock_vector.scroll.call_args[1]
        assert call_kwargs["filters"]["tags"] == "mytag"

    @pytest.mark.asyncio
    async def test_no_order_by_when_sort_by_none(self, mock_vector, config):
        await list_by_type(
            MemoryType.SEMANTIC,
            limit=10,
            offset=0,
            relational=None,
            vector=mock_vector,
            config=config,
        )
        call_kwargs = mock_vector.scroll.call_args[1]
        assert call_kwargs["order_by"] is None

    @pytest.mark.asyncio
    async def test_invalid_sort_by_ignored(self, mock_vector, config):
        await list_by_type(
            MemoryType.SEMANTIC,
            limit=10,
            offset=0,
            relational=None,
            vector=mock_vector,
            config=config,
            sort_by="nonexistent_field",
        )
        call_kwargs = mock_vector.scroll.call_args[1]
        assert call_kwargs["order_by"] is None


class TestCountByTypeTagFilter:
    @pytest.fixture
    def config(self):
        return MemoryConfig(embedding_model="test-model")

    @pytest.fixture
    def mock_vector(self):
        vec = AsyncMock()
        vec.count.return_value = 5
        return vec

    @pytest.mark.asyncio
    async def test_passes_tag_filter_to_count(self, mock_vector, config):
        result = await count_by_type(
            MemoryType.SEMANTIC,
            relational=None,
            vector=mock_vector,
            config=config,
            tag_filter="TestTag",
        )
        assert result == 5
        call_kwargs = mock_vector.count.call_args[1]
        assert call_kwargs["filters"]["tags"] == "testtag"


class TestTagNormalization:
    def test_semantic_to_doc_lowercases_tags(self):
        mem = SemanticMemory(
            content="test",
            importance=0.5,
            tags=["Python", "AI", "MachineLearning"],
        )
        doc = semantic_to_doc(mem)
        assert doc.metadata["tags"] == ["python", "ai", "machinelearning"]

    def test_episodic_to_doc_defaults_empty_tags(self):
        mem = EpisodicMemory(
            content="test event",
            event_type="observation",
            importance=0.5,
        )
        doc = episodic_to_doc(mem)
        assert doc.metadata["tags"] == []

    def test_empty_tags_preserved(self):
        mem = SemanticMemory(content="test", importance=0.5, tags=[])
        doc = semantic_to_doc(mem)
        assert doc.metadata["tags"] == []
