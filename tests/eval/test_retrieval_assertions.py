"""Unit tests for RetrievalAssertion, collapse_retrieval_hits, and deep span evaluation."""

from __future__ import annotations

from myrm_agent_harness.eval.assertions import (
    collapse_retrieval_hits,
    evaluate_retrieval_assertions,
    normalize_retrieval_text,
    split_header_and_body,
)
from myrm_agent_harness.eval.protocols import RetrievalAssertion


def test_normalize_retrieval_text() -> None:
    raw = "  # Header [Link] `code_snippet` *bold*   and   text!  "
    normalized = normalize_retrieval_text(raw)
    assert normalized == "header link code snippet bold and text!"


def test_split_header_and_body_yaml() -> None:
    doc = """---
title: My Title
source: /path/to/file.md
---
This is the actual body content.
Line 2 of body."""
    header, body = split_header_and_body(doc)
    assert "title: My Title" in header
    assert "This is the actual body content." in body
    assert not body.startswith("---")


def test_split_header_and_body_markdown_prefixes() -> None:
    doc = """# /repo/owner/my-repo/file.py
Source: file.py
Blob: a1b2c3d4e5f6

def my_function():
    return 42"""
    header, body = split_header_and_body(doc)
    assert "Blob: a1b2c3d4e5f6" in header
    assert "def my_function():" in body


def test_collapse_retrieval_hits_deduplication() -> None:
    raw_hits = [
        {"doc_id": "doc_1", "content": "# Doc 1 Header\nChunk 1 text", "source_path": "a.md"},
        {"doc_id": "doc_1", "content": "Chunk 2 text from doc 1", "source_path": "a.md"},
        {"doc_id": "doc_2", "content": "# Doc 2 Header\nChunk 1 text doc 2", "source_path": "b.md"},
        {"doc_id": "doc_1", "content": "Chunk 3 text from doc 1", "source_path": "a.md"},
    ]
    collapsed = collapse_retrieval_hits(raw_hits)
    assert len(collapsed) == 2
    assert collapsed[0].identity == "a.md"
    assert collapsed[0].effective_rank == 1
    assert len(collapsed[0].bodies) == 3
    assert collapsed[1].identity == "b.md"
    assert collapsed[1].effective_rank == 2
    assert len(collapsed[1].bodies) == 1


def test_evaluate_retrieval_assertions_success() -> None:
    hits = [
        {"doc_id": "doc_main", "content": "# Header\nOverview and general info", "source_path": "main.md"},
        {"doc_id": "doc_main", "content": "Appendix D: user_id % 128 routing rule", "source_path": "main.md"},
        {"doc_id": "doc_other", "content": "Other service guidelines", "source_path": "other.md"},
    ]
    assertion = RetrievalAssertion(
        expected_spans=("user_id % 128 routing rule",),
        min_distinct_sources=2,
        max_duplicate_rate=0.5,
        top_k=5,
    )
    scores: dict[str, float] = {}
    passed, details = evaluate_retrieval_assertions([assertion], hits, scores_out=scores)
    assert passed is True
    assert "All retrieval assertions passed" in (details or "")
    assert scores["distinct_sources"] == 2.0
    assert scores["span_recall"] == 1.0


def test_evaluate_retrieval_assertions_missing_tail_span() -> None:
    hits = [
        {"doc_id": "doc_main", "content": "# Header\nOverview and general info", "source_path": "main.md"},
        {"doc_id": "doc_other", "content": "Other service guidelines", "source_path": "other.md"},
    ]
    assertion = RetrievalAssertion(
        expected_spans=("Appendix D: user_id % 128 routing rule",),
        top_k=5,
    )
    passed, details = evaluate_retrieval_assertions([assertion], hits)
    assert passed is False
    assert "span recall" in (details or "").lower()


def test_evaluate_retrieval_assertions_empty_hits() -> None:
    assertion = RetrievalAssertion(expected_spans=("some text",))
    passed, details = evaluate_retrieval_assertions([assertion], [])
    assert passed is False
    assert "No hits retrieved" in (details or "")


def test_evaluate_retrieval_assertions_empty_assertions() -> None:
    passed, details = evaluate_retrieval_assertions([], [{"content": "hit"}])
    assert passed is None
    assert details is None


def test_evaluate_retrieval_assertions_doc_id_mismatch() -> None:
    hits = [{"doc_id": "doc_A", "content": "Sample content", "source_path": "a.md"}]
    assertion = RetrievalAssertion(expected_doc_ids=("doc_B",))
    passed, details = evaluate_retrieval_assertions([assertion], hits)
    assert passed is False
    assert "missing expected doc_ids" in (details or "")


def test_evaluate_retrieval_assertions_duplicate_rate_exceeded() -> None:
    hits = [
        {"doc_id": "doc_A", "content": "Chunk 1", "source_path": "a.md"},
        {"doc_id": "doc_A", "content": "Chunk 2", "source_path": "a.md"},
        {"doc_id": "doc_A", "content": "Chunk 3", "source_path": "a.md"},
    ]
    # 3 hits, 1 unique source -> dup rate = 2/3 = 0.67 > 0.5
    assertion = RetrievalAssertion(max_duplicate_rate=0.5)
    passed, details = evaluate_retrieval_assertions([assertion], hits)
    assert passed is False
    assert "duplicate rate" in (details or "")


def test_evaluate_retrieval_assertions_distinct_sources_insufficient() -> None:
    hits = [
        {"doc_id": "doc_A", "content": "Chunk 1", "source_path": "a.md"},
        {"doc_id": "doc_A", "content": "Chunk 2", "source_path": "a.md"},
    ]
    assertion = RetrievalAssertion(min_distinct_sources=2)
    passed, details = evaluate_retrieval_assertions([assertion], hits)
    assert passed is False
    assert "distinct sources" in (details or "")

