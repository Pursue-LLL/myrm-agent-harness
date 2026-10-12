"""fetch_and_extract retrieves through one shared RetrieverManager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.retriever.engine import RetrieverManager
from myrm_agent_harness.toolkits.web_fetch.web_fetch_agent_tools import _fetch_and_extract
from myrm_agent_harness.utils.errors import ToolError

_Call = dict[str, object]


@pytest.fixture
def retrieval_calls(monkeypatch: pytest.MonkeyPatch) -> list[_Call]:
    """Stub the network-bound retrieval and the model services; record every call."""
    calls: list[_Call] = []
    result: tuple[list[dict[str, object]], str, str | None] = ([{"url": "https://a.test"}], "relevant snippet", "")

    async def fake_retrieve(
        self: RetrieverManager,
        urls: list[str],
        questions: str | list[str],
        reranker: object,
        embeddings: object,
        *,
        top_k: int = 10,
        use_raw_markdown: bool = False,
        allow_private_networks: bool = False,
    ) -> tuple[list[dict[str, object]], str, str | None]:
        calls.append({"manager": self, "urls": urls, "allow_private_networks": allow_private_networks})
        return result

    monkeypatch.setattr(RetrieverManager, "retrieve_from_urls", fake_retrieve)
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.retriever.embedding.factory.get_embedding_service", lambda config: MagicMock()
    )
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.retriever.reranker.factory.get_reranker_service", lambda config: MagicMock()
    )
    return calls


@pytest.mark.asyncio
async def test_extract_wraps_retrieved_snippets(retrieval_calls: list[_Call]) -> None:
    response = await _fetch_and_extract(["https://a.test"], ["what?"], MagicMock(), MagicMock())

    assert "relevant snippet" in str(response["content"])
    assert response["metadata"] == {
        "sources": [{"url": "https://a.test"}],
        "operation": "fetch_and_extract",
        "questions": ["what?"],
    }
    assert len(retrieval_calls) == 1


@pytest.mark.asyncio
async def test_manager_is_shared_so_the_bm25_index_cache_survives_calls(retrieval_calls: list[_Call]) -> None:
    await _fetch_and_extract(["https://a.test"], ["q1"], MagicMock(), MagicMock())
    await _fetch_and_extract(["https://b.test"], ["q2"], MagicMock(), MagicMock())

    assert retrieval_calls[0]["manager"] is retrieval_calls[1]["manager"]


@pytest.mark.asyncio
async def test_private_network_flag_is_forwarded(retrieval_calls: list[_Call]) -> None:
    await _fetch_and_extract(["http://10.0.0.1"], ["q"], MagicMock(), MagicMock(), allow_private_networks=True)

    assert retrieval_calls[0]["allow_private_networks"] is True


@pytest.mark.asyncio
async def test_retrieval_error_becomes_tool_error(
    monkeypatch: pytest.MonkeyPatch, retrieval_calls: list[_Call]
) -> None:
    async def failing(self: RetrieverManager, *args: object, **kwargs: object) -> tuple[list[object], str, str]:
        return [], "", "All URLs failed to crawl"

    monkeypatch.setattr(RetrieverManager, "retrieve_from_urls", failing)

    with pytest.raises(ToolError, match="Fetch failed: All URLs failed to crawl"):
        await _fetch_and_extract(["https://a.test"], ["q"], MagicMock(), MagicMock())
