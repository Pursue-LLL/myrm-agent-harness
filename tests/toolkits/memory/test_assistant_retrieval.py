"""Unit tests for Two-Pass Assistant Retrieval (MemPalace enhancement)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.memory._assistant_retrieval import search_conversation_two_pass
from myrm_agent_harness.toolkits.memory.config import MemoryConfig, RetrievalConfig
from myrm_agent_harness.toolkits.vector.base import SearchResult, VectorDocument, VectorStore


@pytest.fixture
def mock_config():
    """Create mock MemoryConfig with Two-Pass enabled."""
    return MemoryConfig(
        embedding_model="text-embedding-ada-002",
        collection_prefix="test_memory",
        retrieval=RetrievalConfig(
            enable_two_pass_assistant_retrieval=True,
            two_pass_first_stage_limit=10,
            enable_keyword_boost=True,
            enable_temporal_boost=True,
        ),
        similarity_threshold=0.7,
    )


@pytest.fixture
def mock_vector_store():
    """Create mock VectorStore."""
    store = MagicMock(spec=VectorStore)
    store.search = AsyncMock()
    store.search_multi_vector = AsyncMock(side_effect=NotImplementedError)
    return store


@pytest.mark.asyncio
async def test_two_pass_basic_flow(mock_vector_store, mock_config):
    """Test Two-Pass retrieval executes Pass 1 and Pass 2."""
    pass1_docs = [
        VectorDocument(
            id=f"conv_{i}",
            content=f"Summary {i}",
            vector=[0.1] * 768,
            metadata={
                "content": f"User: Test {i}",
                "summary": f"Summary {i}",
                "created_at": datetime.now(UTC).isoformat(),
                "archived": False,
            },
        )
        for i in range(5)
    ]

    pass2_docs = [pass1_docs[0], pass1_docs[2]]

    mock_vector_store.search.side_effect = [
        [SearchResult(document=d, score=0.9 - i * 0.05) for i, d in enumerate(pass1_docs)],
        [SearchResult(document=d, score=0.92 - i * 0.03) for i, d in enumerate(pass2_docs)],
    ]

    with patch("myrm_agent_harness.toolkits.memory._assistant_retrieval.boost_results") as mock_boost:
        mock_boost.side_effect = lambda r, *args, **kwargs: r

        results = await search_conversation_two_pass(
            query_raw=[0.5] * 768,
            query_summary=[0.5] * 768,
            query="What did you recommend for testing?",
            limit=5,
            vector=mock_vector_store,
            config=mock_config,
        )

    assert len(results) == 2
    assert mock_vector_store.search.call_count == 2
    call_args_list = mock_vector_store.search.call_args_list
    pass1_filters = call_args_list[0][1]["filters"]
    assert pass1_filters["archived"] is False


@pytest.mark.asyncio
async def test_two_pass_empty_pass1(mock_vector_store, mock_config):
    """Test Two-Pass handles empty Pass 1 results gracefully."""
    mock_vector_store.search.side_effect = [
        [],
        [],
    ]

    results = await search_conversation_two_pass(
        query_raw=[0.5] * 768,
        query_summary=[0.5] * 768,
        query="What did you tell me?",
        limit=5,
        vector=mock_vector_store,
        config=mock_config,
    )

    assert len(results) == 0
    assert mock_vector_store.search.call_count == 1


@pytest.mark.asyncio
async def test_two_pass_pass2_fallback(mock_vector_store, mock_config):
    """Test Two-Pass falls back to Pass 1 results if Pass 2 fails."""
    pass1_docs = [
        VectorDocument(
            id=f"conv_{i}",
            content=f"Summary {i}",
            vector=[0.1] * 768,
            metadata={
                "content": f"User: Fallback {i}",
                "summary": f"Summary {i}",
                "created_at": datetime.now(UTC).isoformat(),
                "archived": False,
            },
        )
        for i in range(3)
    ]

    mock_vector_store.search.side_effect = [
        [SearchResult(document=d, score=0.9) for d in pass1_docs],
        RuntimeError("Pass 2 failed"),
    ]

    with patch("myrm_agent_harness.toolkits.memory._assistant_retrieval.boost_results") as mock_boost:
        mock_boost.side_effect = lambda r, *args, **kwargs: r

        results = await search_conversation_two_pass(
            query_raw=[0.5] * 768,
            query_summary=[0.5] * 768,
            query="What did you say?",
            limit=5,
            vector=mock_vector_store,
            config=mock_config,
        )

    assert len(results) == 3


@pytest.mark.asyncio
async def test_two_pass_metrics_recording(mock_vector_store, mock_config):
    """Test Two-Pass records OTEL metrics."""
    pass1_docs = [
        VectorDocument(
            id="conv_1",
            content="Summary",
            vector=[0.1] * 768,
            metadata={
                "content": "User: Test",
                "summary": "Summary",
                "created_at": datetime.now(UTC).isoformat(),
                "archived": False,
            },
        )
    ]

    mock_vector_store.search.side_effect = [
        [SearchResult(document=pass1_docs[0], score=0.9)],
        [SearchResult(document=pass1_docs[0], score=0.92)],
    ]

    with (
        patch("myrm_agent_harness.toolkits.memory._assistant_retrieval.boost_results") as mock_boost,
        patch("myrm_agent_harness.toolkits.memory.metrics.get_search_metrics") as mock_metrics,
    ):
        mock_boost.side_effect = lambda r, *args, **kwargs: r
        mock_metrics_instance = MagicMock()
        mock_metrics.return_value = mock_metrics_instance

        await search_conversation_two_pass(
            query_raw=[0.5] * 768,
            query_summary=[0.5] * 768,
            query="What did you recommend?",
            limit=5,
            vector=mock_vector_store,
            config=mock_config,
        )

        mock_metrics_instance.record_two_pass_execution.assert_called_once()
        args = mock_metrics_instance.record_two_pass_execution.call_args[0]
        assert args[0] > 0


@pytest.mark.asyncio
async def test_two_pass_with_namespaces(mock_vector_store, mock_config):
    """Test Two-Pass applies namespace filters correctly."""
    pass1_docs = [
        VectorDocument(
            id="conv_shared_1",
            content="Shared summary",
            vector=[0.1] * 768,
            metadata={
                "namespaces": ["global", "shared:alpha"],
                "content": "Shared conversation",
                "summary": "Shared summary",
                "created_at": datetime.now(UTC).isoformat(),
                "archived": False,
            },
        )
    ]

    mock_vector_store.search.side_effect = [
        [SearchResult(document=pass1_docs[0], score=0.9)],
        [SearchResult(document=pass1_docs[0], score=0.92)],
    ]

    with patch("myrm_agent_harness.toolkits.memory._assistant_retrieval.boost_results") as mock_boost:
        mock_boost.side_effect = lambda r, *args, **kwargs: r

        results = await search_conversation_two_pass(
            query_raw=[0.5] * 768,
            query_summary=[0.5] * 768,
            query="What did you tell me?",
            limit=5,
            vector=mock_vector_store,
            config=mock_config,
            namespaces=["global", "shared:alpha"],
        )

    assert len(results) == 1
    call_args_list = mock_vector_store.search.call_args_list
    pass1_filters = call_args_list[0][1]["filters"]
    assert pass1_filters["namespaces"] == ["global", "shared:alpha"]
