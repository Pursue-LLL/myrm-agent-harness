"""Tests for wiki query source citation metadata builder."""

from __future__ import annotations

import hashlib

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import QueryResult, SourceSnippet
from myrm_agent_harness.toolkits.wiki.retrieval.source_citations import build_wiki_query_sources


def test_build_wiki_query_sources_uses_live_digest_when_pin_missing(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    raw_file = structure.raw_dir / "notes.md"
    raw_bytes = b"Live digest fallback"
    raw_file.write_bytes(raw_bytes)
    live_sha = hashlib.sha256(raw_bytes).hexdigest()

    result = QueryResult(
        question="Notes?",
        answer="Note fact",
        related_articles=[],
        confidence_score=0.8,
        source_snippets=[
            SourceSnippet(
                article_path="/concepts/notes.md",
                article_name="notes",
                snippet="Note fact",
                evidence_path="raw/notes.md",
                evidence_content_sha256="",
                evidence_snapshot_status="verified",
            )
        ],
    )

    sources = build_wiki_query_sources(result, structure=structure)
    assert len(sources) == 1
    assert sources[0]["resource_uri"] == f"raw/notes.md@sha256:{live_sha}"


def test_build_wiki_query_sources_prefers_compile_pin_over_live_digest(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    raw_file = structure.raw_dir / "notes.md"
    raw_file.write_bytes(b"Live changed")

    pinned_sha = "deadbeef" * 8
    result = QueryResult(
        question="Notes?",
        answer="Note fact",
        related_articles=[],
        confidence_score=0.8,
        source_snippets=[
            SourceSnippet(
                article_path="/concepts/notes.md",
                article_name="notes",
                snippet="Note fact",
                evidence_path="raw/notes.md",
                evidence_content_sha256=pinned_sha,
                evidence_snapshot_status="stale",
            )
        ],
    )

    sources = build_wiki_query_sources(result, structure=structure)
    assert sources[0]["resource_uri"] == f"raw/notes.md@sha256:{pinned_sha}"
