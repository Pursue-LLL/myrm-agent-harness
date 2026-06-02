"""Unit tests for local_file_search.search."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.local_file_search.search import LocalFileSearchEngine
from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.collection_exists = AsyncMock(return_value=True)
    return store


@pytest.fixture
def mock_embeddings():
    svc = AsyncMock()
    svc.embed = AsyncMock(return_value=[0.1] * 1536)
    return svc


@pytest.fixture
def mock_reranker():
    reranker = AsyncMock()
    return reranker


@pytest.fixture
def engine(mock_store, mock_embeddings):
    return LocalFileSearchEngine(mock_store, mock_embeddings)


@pytest.fixture
def engine_with_reranker(mock_store, mock_embeddings, mock_reranker):
    return LocalFileSearchEngine(mock_store, mock_embeddings, reranker=mock_reranker)


def _make_search_result(
    content: str = "test content",
    source_path: str = "/docs/test.txt",
    relative_path: str = "test.txt",
    file_type: str = "txt",
    score: float = 0.9,
) -> SearchResult:
    return SearchResult(
        document=VectorDocument(
            content=content,
            metadata={
                "source_path": source_path,
                "relative_path": relative_path,
                "file_type": file_type,
                "directory_id": "d1",
                "section": "",
            },
        ),
        score=score,
    )


@pytest.mark.asyncio
class TestLocalFileSearchEngine:
    async def test_search_empty_collection(self, engine, mock_store):
        mock_store.collection_exists.return_value = False
        response = await engine.search("test query")
        assert response.hits == []
        assert response.query == "test query"

    async def test_search_no_results(self, engine, mock_store):
        mock_store.search = AsyncMock(return_value=[])
        response = await engine.search("no match query")
        assert response.hits == []
        assert response.total_hits == 0

    async def test_search_returns_results(self, engine, mock_store):
        mock_store.search = AsyncMock(return_value=[
            _make_search_result("Found content", "/docs/a.txt", "a.txt", "txt", 0.95),
            _make_search_result("Other content", "/docs/b.md", "b.md", "md", 0.85),
        ])

        response = await engine.search("test", top_k=5)
        assert response.total_hits == 2
        assert len(response.hits) == 2
        assert response.hits[0].score == 0.95
        assert response.hits[0].file_path == "/docs/a.txt"
        assert response.hits[0].relative_path == "a.txt"
        assert response.hits[1].file_type == "md"
        assert response.search_time_ms > 0

    async def test_search_with_file_type_filter(self, engine, mock_store):
        mock_store.search = AsyncMock(return_value=[])
        await engine.search("test", file_type_filter="pdf")
        call_kwargs = mock_store.search.call_args
        filters = call_kwargs.kwargs.get("filters") or call_kwargs[1].get("filters")
        assert filters is not None
        assert filters["file_type"] == "pdf"

    async def test_search_with_directory_filter(self, engine, mock_store):
        mock_store.search = AsyncMock(return_value=[])
        await engine.search("test", directory_id_filter="dir-1")
        call_kwargs = mock_store.search.call_args
        filters = call_kwargs.kwargs.get("filters") or call_kwargs[1].get("filters")
        assert filters is not None
        assert filters["directory_id"] == "dir-1"

    async def test_search_with_reranker(self, engine_with_reranker, mock_store, mock_reranker):
        mock_store.search = AsyncMock(return_value=[
            _make_search_result("Content A", "/a.txt", "a.txt", "txt", 0.7),
            _make_search_result("Content B", "/b.txt", "b.txt", "txt", 0.8),
            _make_search_result("Content C", "/c.txt", "c.txt", "txt", 0.6),
        ])

        reranked_doc = Document(
            page_content="Content B",
            metadata={
                "source_path": "/b.txt",
                "relative_path": "b.txt",
                "file_type": "txt",
                "rerank_score": 0.99,
                "section": "",
            },
        )
        mock_reranker.rerank = AsyncMock(return_value=[reranked_doc])

        response = await engine_with_reranker.search("test", top_k=1)
        mock_reranker.rerank.assert_called_once()
        assert len(response.hits) == 1
        assert response.hits[0].score == 0.99

    async def test_search_reranker_skipped_for_single_result(
        self, engine_with_reranker, mock_store, mock_reranker
    ):
        mock_store.search = AsyncMock(return_value=[
            _make_search_result("Only one", "/a.txt", "a.txt", "txt", 0.9),
        ])

        response = await engine_with_reranker.search("test")
        mock_reranker.rerank.assert_not_called()
        assert len(response.hits) == 1

    async def test_search_candidate_multiplier_with_reranker(
        self, engine_with_reranker, mock_store, mock_reranker
    ):
        mock_store.search = AsyncMock(return_value=[])
        mock_reranker.rerank = AsyncMock(return_value=[])

        await engine_with_reranker.search("test", top_k=5)
        call_kwargs = mock_store.search.call_args
        limit = call_kwargs.kwargs.get("limit") or call_kwargs[1].get("limit")
        assert limit == 15  # 5 * 3

    async def test_search_candidate_no_multiplier_without_reranker(self, engine, mock_store):
        mock_store.search = AsyncMock(return_value=[])
        await engine.search("test", top_k=5)
        call_kwargs = mock_store.search.call_args
        limit = call_kwargs.kwargs.get("limit") or call_kwargs[1].get("limit")
        assert limit == 5

    async def test_search_snippet_truncation(self, engine, mock_store):
        long_content = "x" * 600
        mock_store.search = AsyncMock(return_value=[
            _make_search_result(long_content, "/a.txt", "a.txt", "txt", 0.9),
        ])

        response = await engine.search("test")
        assert len(response.hits[0].snippet) == 500
