"""Wiki corpus source emission for memory_search_tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.memory_search_execution import search_wiki_corpus
from myrm_agent_harness.toolkits.memory.memory_search_policy import MemorySearchBackends
from myrm_agent_harness.toolkits.wiki.core.types import QueryResult, SourceSnippet


@pytest.mark.asyncio
async def test_search_wiki_corpus_returns_answer_and_emits_asset_sources() -> None:
    result = QueryResult(
        question="diagram",
        answer="Found an architecture diagram.",
        related_articles=[],
        confidence_score=0.88,
        source_snippets=[
            SourceSnippet(
                article_path="wiki/assets/abc123_diagram.png",
                article_name="architecture",
                snippet="System overview diagram with three tiers.",
                section="Image",
                level="L2",
                hit_kind="asset",
                asset_filename="abc123_diagram.png",
            )
        ],
    )
    backends = MemorySearchBackends(
        query_wiki=AsyncMock(return_value=result),
        wiki_agent_id="agent-scope-1",
    )

    with patch(
        "myrm_agent_harness.toolkits.memory.memory_citations.emit_sources",
        new=AsyncMock(),
    ) as emit_mock:
        body = await search_wiki_corpus(backends, "diagram")

    assert "Found an architecture diagram." in body
    assert "UNTRUSTED_DATA" in body
    emit_mock.assert_awaited_once()
    emitted = emit_mock.await_args.args[0]
    assert len(emitted) == 1
    assert emitted[0]["index"] == 1
    assert emitted[0]["hit_kind"] == "asset"
    assert emitted[0]["asset_filename"] == "abc123_diagram.png"
    assert emitted[0]["type"] == "knowledge"
    assert emitted[0]["agent_id"] == "agent-scope-1"


@pytest.mark.asyncio
async def test_search_wiki_corpus_wraps_answer_with_untrusted_tag() -> None:
    result = QueryResult(
        question="diagram",
        answer="Found an architecture diagram.",
        related_articles=[],
        confidence_score=0.88,
        source_snippets=[],
    )
    backends = MemorySearchBackends(query_wiki=AsyncMock(return_value=result))

    with patch(
        "myrm_agent_harness.toolkits.memory.memory_citations.emit_sources",
        new=AsyncMock(),
    ):
        body = await search_wiki_corpus(backends, "diagram")

    assert "UNTRUSTED_DATA" in body
    assert "Found an architecture diagram." in body


@pytest.mark.asyncio
async def test_search_wiki_corpus_empty_answer_fallback() -> None:
    result = QueryResult(
        question="missing",
        answer="   ",
        related_articles=[],
        confidence_score=0.0,
        source_snippets=[],
    )
    backends = MemorySearchBackends(query_wiki=AsyncMock(return_value=result))

    with patch(
        "myrm_agent_harness.toolkits.memory.memory_citations.emit_sources",
        new=AsyncMock(),
    ) as emit_mock:
        body = await search_wiki_corpus(backends, "missing")

    assert body == "No relevant wiki content found."
    emit_mock.assert_not_awaited()
