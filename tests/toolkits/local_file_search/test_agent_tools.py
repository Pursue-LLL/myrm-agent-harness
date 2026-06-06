"""Unit tests for local_file_search.local_file_search_agent_tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, PropertyMock

import pytest
from myrm_agent_harness.toolkits.local_file_search.local_file_search_agent_tools import (
    create_local_file_search_tools,
)
from myrm_agent_harness.toolkits.local_file_search.models import (
    IndexStats,
    IndexStatus,
    SearchHit,
    SearchResponse,
)


@pytest.fixture
def mock_search_engine():
    engine = AsyncMock()
    return engine


@pytest.fixture
def mock_indexer():
    indexer = AsyncMock()
    type(indexer).stats = PropertyMock(return_value=IndexStats(total_files=10, total_chunks=50))
    return indexer


@pytest.fixture
def tools(mock_search_engine, mock_indexer):
    return create_local_file_search_tools(mock_search_engine, mock_indexer)


class TestCreateTools:
    def test_creates_two_tools(self, tools):
        assert len(tools) == 2

    def test_tool_names(self, tools):
        names = {t.name for t in tools}
        assert "search_local_files_tool" in names
        assert "get_local_file_index_status_tool" in names


@pytest.mark.asyncio
class TestSearchTool:
    async def test_empty_query(self, tools):
        search_tool = next(t for t in tools if t.name == "search_local_files_tool")
        result = await search_tool.ainvoke({"query": "", "top_k": 10, "file_type": ""})
        assert "provide a search query" in result.lower()

    async def test_no_results_with_no_indexed_files(self, tools, mock_search_engine, mock_indexer):
        type(mock_indexer).stats = PropertyMock(return_value=IndexStats(total_files=0))
        mock_search_engine.search = AsyncMock(return_value=SearchResponse(query="test"))

        search_tool = next(t for t in tools if t.name == "search_local_files_tool")
        result = await search_tool.ainvoke({"query": "test query", "top_k": 10, "file_type": ""})
        assert "no files have been indexed" in result.lower()

    async def test_no_results_with_indexed_files(self, tools, mock_search_engine, mock_indexer):
        type(mock_indexer).stats = PropertyMock(return_value=IndexStats(total_files=100))
        mock_search_engine.search = AsyncMock(return_value=SearchResponse(query="test"))

        search_tool = next(t for t in tools if t.name == "search_local_files_tool")
        result = await search_tool.ainvoke({"query": "test query", "top_k": 10, "file_type": ""})
        assert "no results found" in result.lower()
        assert "100" in result

    async def test_returns_formatted_results(self, tools, mock_search_engine):
        hits = [
            SearchHit(
                file_path="/docs/report.pdf",
                relative_path="report.pdf",
                snippet="Important findings about...",
                score=0.95,
                file_type="pdf",
                section="## Results",
            ),
        ]
        mock_search_engine.search = AsyncMock(
            return_value=SearchResponse(hits=hits, total_hits=1, query="findings", search_time_ms=12.5)
        )

        search_tool = next(t for t in tools if t.name == "search_local_files_tool")
        result = await search_tool.ainvoke({"query": "findings", "top_k": 10, "file_type": ""})
        assert "report.pdf" in result
        assert "0.950" in result
        assert "/docs/report.pdf" in result
        assert "Results" in result
        assert "Important findings" in result

    async def test_top_k_clamped(self, tools, mock_search_engine):
        mock_search_engine.search = AsyncMock(return_value=SearchResponse(query="test"))

        search_tool = next(t for t in tools if t.name == "search_local_files_tool")
        await search_tool.ainvoke({"query": "test", "top_k": 100, "file_type": ""})
        call_kwargs = mock_search_engine.search.call_args
        assert call_kwargs.kwargs["top_k"] == 50

    async def test_file_type_filter_passed(self, tools, mock_search_engine):
        mock_search_engine.search = AsyncMock(return_value=SearchResponse(query="test"))

        search_tool = next(t for t in tools if t.name == "search_local_files_tool")
        await search_tool.ainvoke({"query": "test", "top_k": 10, "file_type": "pdf"})
        call_kwargs = mock_search_engine.search.call_args
        assert call_kwargs.kwargs["file_type_filter"] == "pdf"


@pytest.mark.asyncio
class TestStatusTool:
    async def test_returns_stats(self, tools, mock_indexer):
        from datetime import UTC, datetime

        type(mock_indexer).stats = PropertyMock(
            return_value=IndexStats(
                total_files=42,
                total_chunks=256,
                total_directories=3,
                status=IndexStatus.IDLE,
                error_count=1,
                last_indexed_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        status_tool = next(t for t in tools if t.name == "get_local_file_index_status_tool")
        result = await status_tool.ainvoke({})
        assert "42" in result
        assert "256" in result
        assert "idle" in result
        assert "2026" in result

    async def test_shows_progress_when_indexing(self, tools, mock_indexer):
        type(mock_indexer).stats = PropertyMock(
            return_value=IndexStats(
                status=IndexStatus.INDEXING,
                indexing_progress=0.65,
                current_file="/docs/big.pdf",
            )
        )

        status_tool = next(t for t in tools if t.name == "get_local_file_index_status_tool")
        result = await status_tool.ainvoke({})
        assert "65.0%" in result
        assert "/docs/big.pdf" in result
