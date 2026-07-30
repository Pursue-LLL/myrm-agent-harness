"""Tests for raw evidence excerpt reads used by wiki query citations."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock

from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
    clear_raw_bytes_lru_cache,
    read_evidence_excerpt,
    resolve_evidence_snapshot_and_excerpt,
)
from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import QueryResult, SourceSnippet
from myrm_agent_harness.toolkits.wiki.retrieval.query import WikiQueryEngine
from myrm_agent_harness.toolkits.wiki.retrieval.source_citations import build_wiki_query_sources


def test_read_evidence_excerpt_returns_line_range_text(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    raw_file = structure.raw_dir / "email.md"
    raw_file.write_text("line one\nline two\nline three\n", encoding="utf-8")

    excerpt = read_evidence_excerpt("raw/email.md", "2-3", structure)

    assert excerpt == "line two\nline three"


def test_read_evidence_excerpt_falls_back_empty_when_file_missing(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()

    excerpt = read_evidence_excerpt("raw/missing.md", "1-2", structure)

    assert excerpt == ""


def test_read_evidence_excerpt_returns_empty_for_invalid_line_range(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    raw_file = structure.raw_dir / "email.md"
    raw_file.write_text("line one\nline two\nline three\n", encoding="utf-8")

    assert read_evidence_excerpt("raw/email.md", "abc", structure) == ""
    assert read_evidence_excerpt("raw/email.md", "", structure) == ""


def test_resolve_evidence_snapshot_and_excerpt_single_read(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    raw_file = structure.raw_dir / "budget.md"
    raw_bytes = b"line one\nBudget fact line\nline three\n"
    raw_file.write_bytes(raw_bytes)
    pinned = hashlib.sha256(raw_bytes).hexdigest()

    cache: dict[str, bytes] = {}
    status, excerpt = resolve_evidence_snapshot_and_excerpt(
        "raw/budget.md",
        "2-2",
        pinned,
        structure,
        cache=cache,
    )

    assert status == "verified"
    assert excerpt == "Budget fact line"
    assert len(cache) == 1


def test_claim_snippets_from_content_uses_raw_excerpt_not_claim_text(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    raw_file = structure.raw_dir / "source.md"
    raw_file.write_text("header\nEvidence excerpt line\nfooter\n", encoding="utf-8")
    raw_bytes = raw_file.read_bytes()
    pinned = hashlib.sha256(raw_bytes).hexdigest()

    concept_path = structure.get_concept_file_path("budget")
    concept_path.parent.mkdir(parents=True, exist_ok=True)
    concept_path.write_text(
        f"""---
type: concept
claims:
  - id: claim.budget
    text: Budget fact
    status: supported
    confidence: 0.9
    evidence:
      - kind: raw-note
        sourceId: source.budget
        path: raw/source.md
        lines: "2-2"
        weight: 1.0
        confidence: 0.9
        contentSha256: {pinned}
---

## Compiled Truth
Budget details.
""",
        encoding="utf-8",
    )

    engine = WikiQueryEngine(llm=MagicMock(), structure=structure, config=WikiConfig())
    snippets = engine._claim_snippets_from_content(concept_path.read_text(encoding="utf-8"), concept_path)

    assert len(snippets) == 1
    assert snippets[0].snippet == "Evidence excerpt line"
    assert snippets[0].claim_text == "Budget fact"
    assert snippets[0].snippet != snippets[0].claim_text


def test_load_raw_bytes_lru_cache_avoids_second_disk_read(tmp_path, monkeypatch) -> None:
    clear_raw_bytes_lru_cache()
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    raw_file = structure.raw_dir / "email.md"
    raw_file.write_text("line one\n", encoding="utf-8")

    call_count = 0
    original_read_bytes = Path.read_bytes

    def counting_read_bytes(self: Path) -> bytes:
        nonlocal call_count
        call_count += 1
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", counting_read_bytes)

    assert read_evidence_excerpt("raw/email.md", "1-1", structure) == "line one"
    assert read_evidence_excerpt("raw/email.md", "1-1", structure) == "line one"
    assert call_count == 1
    clear_raw_bytes_lru_cache()


def test_build_wiki_query_sources_skips_empty_related_article_ghost(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()

    result = QueryResult(
        question="Budget?",
        answer="Budget fact",
        related_articles=["Budget"],
        confidence_score=0.8,
        source_snippets=[
            SourceSnippet(
                article_path="/concepts/budget.md",
                article_name="budget",
                snippet="Evidence excerpt",
                section="Claim",
                level="L2",
                claim_id="claim.budget",
                claim_text="Budget fact",
                evidence_path="raw/source.md",
                line_range="1-2",
            )
        ],
    )

    sources = build_wiki_query_sources(result, structure=structure)

    assert len(sources) == 1
    assert sources[0]["snippet"] == "Evidence excerpt"
    assert sources[0]["claim_text"] == "Budget fact"
