"""Tests for time-range filtering across the memory search pipeline.

Covers:
- Qdrant filter builder DatetimeRange detection
- _user_filter since/until parameter
- _parse_time_bound relative + ISO 8601 parsing
- memory_recall tool since/until passthrough
- MemoryManager.search since/until passthrough
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import _user_filter
from myrm_agent_harness.toolkits.memory.memory_agent_tools import _parse_time_bound
from myrm_agent_harness.toolkits.memory.types import MemoryScope, MemorySearchResult, MemoryType, SemanticMemory
from myrm_agent_harness.toolkits.vector.qdrant.filters import (
    _is_datetime_range,
    _is_datetime_value,
    build_qdrant_filter,
)


class TestQdrantDatetimeRange:
    """Verify filter builder auto-detects datetime values and uses DatetimeRange."""

    def test_is_datetime_value_iso_string(self):
        assert _is_datetime_value("2026-04-18T12:00:00") is True

    def test_is_datetime_value_datetime_obj(self):
        assert _is_datetime_value(datetime(2026, 4, 18, tzinfo=UTC)) is True

    def test_is_datetime_value_integer(self):
        assert _is_datetime_value(42) is False

    def test_is_datetime_value_plain_string(self):
        assert _is_datetime_value("hello") is False

    def test_is_datetime_value_empty_string(self):
        assert _is_datetime_value("") is False

    def test_is_datetime_range_with_iso(self):
        assert _is_datetime_range({"gte": "2026-01-01T00:00:00", "lte": "2026-12-31T23:59:59"}) is True

    def test_is_datetime_range_with_numbers(self):
        assert _is_datetime_range({"gte": 0, "lte": 100}) is False

    def test_is_datetime_range_mixed(self):
        assert _is_datetime_range({"gte": "2026-01-01T00:00:00", "lte": 100}) is True

    @pytest.mark.skip(reason="Needs qdrant_client to be installed")
    def test_build_filter_datetime_range(self):
        f = build_qdrant_filter({"created_at": {"gte": "2026-01-01T00:00:00", "lte": "2026-12-31T00:00:00"}})
        assert f is not None
        assert len(f.must) == 1
        cond = f.must[0]
        assert cond.key == "created_at"
        from qdrant_client.models import DatetimeRange

        assert isinstance(cond.range, DatetimeRange)

    @pytest.mark.skip(reason="Needs qdrant_client to be installed")
    def test_build_filter_numeric_range(self):
        f = build_qdrant_filter({"importance": {"gte": 0.5, "lte": 1.0}})
        assert f is not None
        cond = f.must[0]
        from qdrant_client.models import Range

        assert isinstance(cond.range, Range)

    def test_build_filter_none_returns_none(self):
        assert build_qdrant_filter(None) is None

    def test_build_filter_empty_returns_none(self):
        assert build_qdrant_filter({}) is None

    @pytest.mark.skip(reason="Needs qdrant_client to be installed")
    def test_build_filter_simple_match(self):
        f = build_qdrant_filter({"archived": False})
        assert f is not None
        assert len(f.must) == 1
        assert f.must[0].key == "archived"

    @pytest.mark.skip(reason="Needs qdrant_client to be installed")
    def test_build_filter_list_match(self):
        f = build_qdrant_filter({"tags": ["a", "b"]})
        assert f is not None
        assert len(f.must) == 1

    @pytest.mark.skip(reason="Needs qdrant_client to be installed")
    def test_build_filter_combined_datetime_and_match(self):
        f = build_qdrant_filter(
            {
                "created_at": {"gte": "2026-01-01T00:00:00"},
            }
        )
        assert f is not None
        assert len(f.must) == 1


class TestUserFilter:
    """Verify _user_filter produces correct time-range entries."""

    def test_no_time_filter(self):
        f = _user_filter()
        assert "created_at" not in f
        assert f["archived"] is False

    def test_since_only(self):
        since = datetime(2026, 4, 1, tzinfo=UTC)
        f = _user_filter(since=since)
        assert "created_at" in f
        time_range = f["created_at"]
        assert isinstance(time_range, dict)
        assert "gte" in time_range
        assert "lte" not in time_range
        assert time_range["gte"] == since.isoformat()

    def test_until_only(self):
        until = datetime(2026, 4, 30, tzinfo=UTC)
        f = _user_filter(until=until)
        assert "created_at" in f
        time_range = f["created_at"]
        assert isinstance(time_range, dict)
        assert "lte" in time_range
        assert "gte" not in time_range

    def test_since_and_until(self):
        since = datetime(2026, 4, 1, tzinfo=UTC)
        until = datetime(2026, 4, 30, tzinfo=UTC)
        f = _user_filter(since=since, until=until)
        time_range = f["created_at"]
        assert isinstance(time_range, dict)
        assert "gte" in time_range
        assert "lte" in time_range

    def test_time_filter_with_namespaces(self):
        since = datetime(2026, 4, 1, tzinfo=UTC)
        f = _user_filter(namespaces=["ns1"], since=since)
        assert f["namespaces"] == ["ns1"]
        assert "created_at" in f

    def test_time_filter_preserves_archived_exclusion(self):
        since = datetime(2026, 4, 1, tzinfo=UTC)
        f = _user_filter(since=since)
        assert f["archived"] is False

    def test_time_filter_with_include_archived(self):
        since = datetime(2026, 4, 1, tzinfo=UTC)
        f = _user_filter(include_archived=True, since=since)
        assert "archived" not in f
        assert "created_at" in f


class TestParseTimeBound:
    """Verify _parse_time_bound handles relative and ISO 8601 inputs."""

    def test_none_returns_none(self):
        assert _parse_time_bound(None) is None

    def test_empty_returns_none(self):
        assert _parse_time_bound("") is None

    def test_whitespace_only_returns_none(self):
        assert _parse_time_bound("   ") is None

    def test_relative_days(self):
        result = _parse_time_bound("7d")
        assert result is not None
        delta = datetime.now(UTC) - result
        assert 6.9 < delta.total_seconds() / 86400 < 7.1

    def test_relative_hours(self):
        result = _parse_time_bound("24h")
        assert result is not None
        delta = datetime.now(UTC) - result
        assert 23.9 < delta.total_seconds() / 3600 < 24.1

    def test_relative_weeks(self):
        result = _parse_time_bound("2w")
        assert result is not None
        delta = datetime.now(UTC) - result
        assert 13.9 < delta.total_seconds() / 86400 < 14.1

    def test_relative_months(self):
        result = _parse_time_bound("1m")
        assert result is not None
        delta = datetime.now(UTC) - result
        assert 29 < delta.total_seconds() / 86400 < 31

    def test_relative_years(self):
        result = _parse_time_bound("1y")
        assert result is not None
        delta = datetime.now(UTC) - result
        assert 364 < delta.total_seconds() / 86400 < 366

    def test_iso_with_timezone(self):
        result = _parse_time_bound("2026-04-01T00:00:00+00:00")
        assert result is not None
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 1

    def test_iso_naive_gets_utc(self):
        result = _parse_time_bound("2026-04-01T12:00:00")
        assert result is not None
        assert result.tzinfo == UTC

    def test_invalid_returns_none(self):
        assert _parse_time_bound("not-a-date") is None

    def test_case_insensitive(self):
        result = _parse_time_bound("7D")
        assert result is not None

    def test_with_spaces(self):
        result = _parse_time_bound("  7d  ")
        assert result is not None


class TestMemoryRecallTimePassing:
    """Verify memory_recall tool passes since/until through to MemoryManager.search."""

    @pytest.mark.asyncio
    async def test_recall_passes_since_and_until(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager
        from myrm_agent_harness.toolkits.memory.memory_agent_tools import create_memory_tools

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        search_mock = AsyncMock(
            return_value=[
                MemorySearchResult(
                    memory=SemanticMemory(
                        content="Test memory", scope=MemoryScope(primary_namespace="global", namespaces=["global"])
                    ),
                    score=0.9,
                    memory_type=MemoryType.SEMANTIC,
                )
            ]
        )

        with patch.object(MemoryManager, "search", search_mock):
            recall_tool = next(t for t in create_memory_tools(manager) if t.name == "memory_search_tool")
            await recall_tool.ainvoke({"query": "test", "since": "7d", "until": "1d"})

        search_mock.assert_called_once()
        call_kwargs = search_mock.call_args
        assert call_kwargs.kwargs.get("since") is not None
        assert call_kwargs.kwargs.get("until") is not None

    @pytest.mark.asyncio
    async def test_recall_without_time_params(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager
        from myrm_agent_harness.toolkits.memory.memory_agent_tools import create_memory_tools

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        search_mock = AsyncMock(return_value=[])
        with patch.object(MemoryManager, "search", search_mock):
            recall_tool = next(t for t in create_memory_tools(manager) if t.name == "memory_search_tool")
            await recall_tool.ainvoke({"query": "test"})

        search_mock.assert_called_once()
        call_kwargs = search_mock.call_args
        assert call_kwargs.kwargs.get("since") is None
        assert call_kwargs.kwargs.get("until") is None

    @pytest.mark.asyncio
    async def test_recall_iso_since(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager
        from myrm_agent_harness.toolkits.memory.memory_agent_tools import create_memory_tools

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        search_mock = AsyncMock(return_value=[])
        with patch.object(MemoryManager, "search", search_mock):
            recall_tool = next(t for t in create_memory_tools(manager) if t.name == "memory_search_tool")
            await recall_tool.ainvoke({"query": "test", "since": "2026-04-01T00:00:00"})

        call_kwargs = search_mock.call_args
        since_val = call_kwargs.kwargs.get("since")
        assert since_val is not None
        assert since_val.year == 2026
        assert since_val.month == 4

    @pytest.mark.asyncio
    async def test_recall_invalid_since_ignored(self, mock_vector_store, mock_embedding, memory_config):
        from myrm_agent_harness.toolkits.memory.manager import MemoryManager
        from myrm_agent_harness.toolkits.memory.memory_agent_tools import create_memory_tools

        manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)

        search_mock = AsyncMock(return_value=[])
        with patch.object(MemoryManager, "search", search_mock):
            recall_tool = next(t for t in create_memory_tools(manager) if t.name == "memory_search_tool")
            await recall_tool.ainvoke({"query": "test", "since": "not-a-date"})

        call_kwargs = search_mock.call_args
        assert call_kwargs.kwargs.get("since") is None
