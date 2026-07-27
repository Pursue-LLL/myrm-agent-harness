"""Unit tests for bm25_retrieval helpers and edge paths."""

from __future__ import annotations

from myrm_agent_harness.toolkits.retriever.bm25_retrieval import (
    BM25Retriever,
    extract_special_patterns,
    extract_url_keywords,
    extract_version_tokens,
    preprocess_text,
    split_camelcase,
)


def test_extract_version_tokens_empty() -> None:
    assert extract_version_tokens("") == []


def test_extract_version_tokens_with_suffix() -> None:
    tokens = extract_version_tokens("v1.77.0-alpha.1")
    assert "v1.77.0-alpha.1" in tokens
    assert "1.77.0" in tokens
    assert "1" in tokens
    assert "77" in tokens


def test_extract_url_keywords_domain_and_fragment() -> None:
    keywords = extract_url_keywords(
        "https://docs.litellm.ai/release_notes/v1-77-2#system-prompt"
    )
    assert "docs" in keywords
    assert "litellm" in keywords
    assert "release" in keywords
    assert "notes" in keywords
    assert "system" in keywords
    assert "prompt" in keywords


def test_split_camelcase_and_brands() -> None:
    tokens = split_camelcase("FastAPI")
    assert "FastAPI" in tokens
    assert "Fast" in tokens
    assert "API" in tokens

    github_tokens = split_camelcase("GitHub")
    assert "git" in github_tokens
    assert "hub" in github_tokens

    assert split_camelcase("") == []


def test_extract_special_patterns_version_and_url() -> None:
    tokens = extract_special_patterns(
        "litellm 1.77 release https://docs.litellm.ai/path"
    )
    assert any("1.77" in t for t in tokens)
    assert any("litellm" in t for t in tokens)


def test_preprocess_text_empty_and_mixed() -> None:
    assert preprocess_text("") == []
    tokens = preprocess_text("docs.litellm.ai/release_notes v1.77.2 机器学习")
    assert tokens
    assert any("机器" in t or "学习" in t for t in tokens)


def test_bm25_retriever_empty_documents() -> None:
    retriever = BM25Retriever(["", "   "])
    assert retriever.bm25 is None
    assert retriever.search("query") == []


def test_bm25_retriever_empty_query_and_only_relevant() -> None:
    retriever = BM25Retriever(["python machine learning tutorial"])
    assert retriever.search("") == []
    assert retriever.search("   ") == []

    hits = retriever.search("python machine learning tutorial", top_k=5)
    assert hits
    filtered = retriever.search(
        "python machine learning tutorial", top_k=5, only_relevant=True
    )
    assert len(filtered) <= len(hits)


def test_bm25_retriever_query_empty_after_preprocess() -> None:
    retriever = BM25Retriever(["valid document"])
    assert retriever.search("!!!") == []
