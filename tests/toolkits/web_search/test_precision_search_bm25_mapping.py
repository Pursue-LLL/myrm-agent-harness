"""Precision mode: how the per-query BM25 candidate mapping feeds the reranker, and what happens when it fails."""

import logging
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.engine import RetrieverManager
from myrm_agent_harness.toolkits.retriever.reranker import RerankerConfig
from myrm_agent_harness.toolkits.web_search.engine import WebSearchTools
from myrm_agent_harness.toolkits.web_search.precision_search import _precision_mode_search
from myrm_agent_harness.toolkits.web_search.providers.web_searcher import SearchServiceConfig

_LOGGER_NAME = "myrm_agent_harness.toolkits.web_search.precision_search"
_CHUNK = Document(page_content="short chunk", metadata={"url": "https://example.com/a", "chunk_index": 0})


@pytest.fixture
def tools() -> Iterator[WebSearchTools]:
    with patch("myrm_agent_harness.toolkits.retriever.reranker.get_reranker_service", return_value=Mock()):
        yield WebSearchTools(
            config=SearchServiceConfig(search_service="perplexity", api_key="test-key"),
            reranker_config=RerankerConfig(model="cohere/rerank-v3.5", api_key="test-key"),
        )


def _retriever(mapping: AsyncMock) -> MagicMock:
    manager = MagicMock(spec=RetrieverManager)
    manager.bm25_retrieval_with_mapping = mapping
    manager.bm25_retrieval_only = AsyncMock(return_value=[_CHUNK])
    manager.rerank_with_mapping = AsyncMock(return_value=[_CHUNK])
    return manager


async def _run(tools: WebSearchTools, manager: MagicMock) -> list[Document]:
    return await _precision_mode_search(
        questions=["q"], unified_docs=[_CHUNK], reranker=Mock(), tools=tools, retriever_manager=manager
    )


@pytest.mark.asyncio
async def test_mapping_failure_falls_back_to_fused_bm25_and_is_logged_as_a_warning(
    tools: WebSearchTools, caplog: pytest.LogCaptureFixture
) -> None:
    manager = _retriever(AsyncMock(side_effect=RuntimeError("index build failed")))

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        result = await _run(tools, manager)

    assert result == [_CHUNK]
    manager.bm25_retrieval_only.assert_awaited_once()
    assert manager.rerank_with_mapping.await_args.kwargs["query_doc_mapping"] == {"q": [(_CHUNK, 1.0)]}
    warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and "bm25_retrieval_with_mapping" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert warnings[0].exc_info is not None


@pytest.mark.asyncio
async def test_mapping_is_passed_to_the_reranker_unchanged_when_it_has_hits(
    tools: WebSearchTools, caplog: pytest.LogCaptureFixture
) -> None:
    mapping = {"q": [(_CHUNK, 0.9)]}
    manager = _retriever(AsyncMock(return_value=mapping))

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        await _run(tools, manager)

    manager.bm25_retrieval_only.assert_not_awaited()
    assert manager.rerank_with_mapping.await_args.kwargs["query_doc_mapping"] == mapping
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.asyncio
async def test_mapping_without_any_hit_falls_back_to_fused_bm25_without_a_warning(
    tools: WebSearchTools, caplog: pytest.LogCaptureFixture
) -> None:
    manager = _retriever(AsyncMock(return_value={"q": []}))

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        await _run(tools, manager)

    manager.bm25_retrieval_only.assert_awaited_once()
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
