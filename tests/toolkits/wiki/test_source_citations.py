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


def test_build_wiki_query_sources_skips_uri_without_evidence_path(tmp_path) -> None:
    """Concept-only snippets must not treat absolute article_path as raw evidence."""
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()

    result = QueryResult(
        question="Concept?",
        answer="Summary",
        related_articles=[],
        confidence_score=0.8,
        source_snippets=[
            SourceSnippet(
                article_path=str(structure.get_concept_file_path("test-concept")),
                article_name="test-concept",
                snippet="Summary",
                section="Compiled Truth",
                level="L2",
            )
        ],
    )

    sources = build_wiki_query_sources(result, structure=structure)
    assert len(sources) == 1
    assert "resource_uri" not in sources[0]


def test_build_wiki_query_sources_emits_superseded_from_uri_when_stale(tmp_path) -> None:
    import json

    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    previous_sha = "deadbeef" * 8
    metadata_path = structure.get_wiki_metadata_path()
    metadata_path.write_text(
        json.dumps(
            {
                "raw_supersede": {
                    "raw/notes.md": {
                        "previous_sha256": previous_sha,
                        "current_sha256": "feedface" * 8,
                        "reason": "supersede",
                        "superseded_at": "2020-01-01T00:00:00+00:00",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

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
                evidence_content_sha256=previous_sha,
                evidence_snapshot_status="stale",
            )
        ],
    )

    sources = build_wiki_query_sources(result, structure=structure)
    assert sources[0]["superseded_from_uri"] == f"raw/notes.md@sha256:{previous_sha}"


def test_build_wiki_query_sources_emits_claim_confidence_when_explicit() -> None:
    result = QueryResult(
        question="Budget?",
        answer="Budget fact",
        related_articles=[],
        confidence_score=0.82,
        source_snippets=[
            SourceSnippet(
                article_path="/concepts/budget.md",
                article_name="budget",
                snippet="Evidence excerpt",
                claim_id="claim.budget",
                claim_text="Budget fact",
                claim_confidence=0.91,
                evidence_path="raw/source.md",
            )
        ],
    )

    sources = build_wiki_query_sources(result)
    assert sources[0]["claim_confidence"] == 0.91


def test_build_wiki_query_sources_omits_fallback_claim_confidence() -> None:
    result = QueryResult(
        question="Budget?",
        answer="Budget fact",
        related_articles=[],
        confidence_score=0.82,
        source_snippets=[
            SourceSnippet(
                article_path="/concepts/budget.md",
                article_name="budget",
                snippet="Budget fact",
                claim_id="claim.budget",
                claim_confidence=0.5,
            )
        ],
    )

    sources = build_wiki_query_sources(result)
    assert "claim_confidence" not in sources[0]


def test_format_evidence_cards_context() -> None:
    from myrm_agent_harness.toolkits.wiki.retrieval.source_citations import (
        format_evidence_cards_context,
    )

    base_answer = "## Recent vault context\nSome activity"
    snippets = [
        SourceSnippet(
            article_path="/concepts/billing.md",
            article_name="billing",
            snippet="Exponential backoff retry is applied up to 5 times.",
            evidence_path="raw/billing.md",
            line_range="L40-L48",
            claim_text="Exponential backoff retry policy",
            claim_status="verified",
            claim_confidence=0.95,
        ),
        SourceSnippet(
            article_path="/concepts/legacy_billing.md",
            article_name="legacy_billing",
            snippet="Fixed interval 5s retry.",
            evidence_path="raw/legacy_billing.md",
            line_range="L12-L16",
            claim_status="stale",
            claim_confidence=0.70,
        ),
        SourceSnippet(
            article_path="wiki/assets/order_topology.png",
            article_name="order_topology",
            snippet="Order service microservices architecture diagram.",
            section="Image",
            hit_kind="asset",
            asset_filename="order_topology.png",
        ),
    ]

    formatted = format_evidence_cards_context(base_answer, snippets)

    assert "## Recent vault context" in formatted
    assert "## Evidence Snippets & Line Anchors" in formatted
    assert "--- [Evidence Card: source: raw/billing.md#L40-L48 | status: verified | confidence: 0.95] ---" in formatted
    assert "Claim: Exponential backoff retry policy" in formatted
    assert "Evidence: Exponential backoff retry is applied up to 5 times." in formatted
    assert "--- [Evidence Card: source: raw/legacy_billing.md#L12-L16 | status: stale | confidence: 0.70] ---" in formatted
    assert "--- [Evidence Card: source: wiki/assets/order_topology.png | asset: order_topology.png | section: Image] ---" in formatted
    assert "Caption: Order service microservices architecture diagram." in formatted
    assert "[Evidence-Card Answer Contract]" in formatted
    assert "disagree -> show both" in formatted


