"""Wiki corpus source emission for memory_search_tool."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.memory_search_execution import search_wiki_corpus
from myrm_agent_harness.toolkits.memory.memory_search_policy import MemorySearchBackends
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
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
        "myrm_agent_harness.toolkits.memory.agent_surface.memory_citations.emit_sources",
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
        "myrm_agent_harness.toolkits.memory.agent_surface.memory_citations.emit_sources",
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
        "myrm_agent_harness.toolkits.memory.agent_surface.memory_citations.emit_sources",
        new=AsyncMock(),
    ) as emit_mock:
        body = await search_wiki_corpus(backends, "missing")

    assert body == "No relevant wiki content found."
    emit_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_wiki_corpus_emits_resource_uri_with_wiki_structure(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    raw_file = structure.raw_dir / "notes.md"
    raw_bytes = b"Memory search wiki fallback"
    raw_file.write_bytes(raw_bytes)
    live_sha = hashlib.sha256(raw_bytes).hexdigest()

    result = QueryResult(
        question="notes",
        answer="Note from wiki corpus.",
        related_articles=[],
        confidence_score=0.7,
        source_snippets=[
            SourceSnippet(
                article_path="/concepts/notes.md",
                article_name="notes",
                snippet="Note from wiki corpus.",
                evidence_path="raw/notes.md",
                evidence_content_sha256="",
                evidence_snapshot_status="verified",
            )
        ],
    )
    backends = MemorySearchBackends(
        query_wiki=AsyncMock(return_value=result),
        wiki_structure=structure,
    )

    with patch(
        "myrm_agent_harness.toolkits.memory.agent_surface.memory_citations.emit_sources",
        new=AsyncMock(),
    ) as emit_mock:
        await search_wiki_corpus(backends, "notes")

    emitted = emit_mock.await_args.args[0]
    assert emitted[0]["resource_uri"] == f"raw/notes.md@sha256:{live_sha}"
