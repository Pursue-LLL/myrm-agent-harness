"""Tests for search_results_processor description field completeness.

Verifies that search result snippets are NOT truncated when converted to
Document metadata — the [:100] truncation was removed as part of the
RAG traceability improvement.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.web_search.common import SearchResult
from myrm_agent_harness.toolkits.web_search.search_results_processor import (
    search_results_to_documents,
)


class TestDescriptionNotTruncated:
    """Verify that Document.metadata['description'] preserves full snippet."""

    def test_short_snippet_preserved(self) -> None:
        results = [
            SearchResult(title="T", link="https://a.com", snippet="Short snippet"),
        ]
        docs = search_results_to_documents(results)
        assert docs[0].metadata["description"] == "Short snippet"

    def test_long_snippet_not_truncated(self) -> None:
        long_snippet = "A" * 300
        results = [
            SearchResult(title="T", link="https://a.com", snippet=long_snippet),
        ]
        docs = search_results_to_documents(results)
        assert docs[0].metadata["description"] == long_snippet
        assert len(docs[0].metadata["description"]) == 300

    def test_snippet_over_100_chars_fully_preserved(self) -> None:
        snippet = "Word " * 30  # 150 chars
        results = [
            SearchResult(title="T", link="https://a.com", snippet=snippet),
        ]
        docs = search_results_to_documents(results)
        assert docs[0].metadata["description"] == snippet.strip()
        assert len(docs[0].metadata["description"]) > 100

    def test_page_content_matches_description(self) -> None:
        snippet = "The quick brown fox jumps over the lazy dog. " * 5
        results = [
            SearchResult(title="T", link="https://a.com", snippet=snippet),
        ]
        docs = search_results_to_documents(results)
        assert docs[0].page_content == docs[0].metadata["description"]

    def test_empty_snippet_handled(self) -> None:
        results = [
            SearchResult(title="T", link="https://a.com", snippet=""),
        ]
        docs = search_results_to_documents(results)
        assert docs[0].metadata["description"] == ""

    def test_unicode_snippet_preserved(self) -> None:
        snippet = "这是一段包含中文、日本語、한국어的长文本摘要。" * 5
        results = [
            SearchResult(title="T", link="https://a.com", snippet=snippet),
        ]
        docs = search_results_to_documents(results)
        assert docs[0].metadata["description"] == snippet

    def test_citations_included_in_metadata(self) -> None:
        from myrm_agent_harness.toolkits.web_search.common import Citation

        citations = [
            Citation(url="https://a.com/ref", title="Ref 1", start_index=0, end_index=10),
        ]
        results = [
            SearchResult(title="T", link="https://a.com", snippet="Has citations", citations=citations),
        ]
        docs = search_results_to_documents(results)
        assert "citations" in docs[0].metadata
        assert docs[0].metadata["citations"][0]["url"] == "https://a.com/ref"


class TestSearchResultsEdgeCases:
    """Edge cases for search_results_to_documents."""

    def test_whitespace_only_snippet_cleaned(self) -> None:
        results = [
            SearchResult(title="T", link="https://a.com", snippet="  \n\t  "),
        ]
        docs = search_results_to_documents(results)
        assert docs[0].metadata["description"] == docs[0].page_content

    def test_multiple_results_all_preserved(self) -> None:
        snippets = [f"Snippet {i} with more than one hundred characters " * 3 for i in range(5)]
        results = [
            SearchResult(title=f"T{i}", link=f"https://{i}.com", snippet=s)
            for i, s in enumerate(snippets)
        ]
        docs = search_results_to_documents(results)
        assert len(docs) == 5
        for i, doc in enumerate(docs):
            assert len(doc.metadata["description"]) > 100

    def test_metadata_url_preserved(self) -> None:
        results = [
            SearchResult(title="T", link="https://example.com/path?q=1", snippet="S"),
        ]
        docs = search_results_to_documents(results)
        assert docs[0].metadata["url"] == "https://example.com/path?q=1"

    def test_metadata_title_preserved(self) -> None:
        results = [
            SearchResult(title="A Very Long Title " * 10, link="https://a.com", snippet="S"),
        ]
        docs = search_results_to_documents(results)
        assert docs[0].metadata["title"] == "A Very Long Title " * 10


class TestSiteNameAndAuthorityPassthrough:
    """Verify site_name and authority_description are passed through."""

    def test_site_name_and_authority_in_metadata(self) -> None:
        results = [
            SearchResult(
                title="T",
                link="https://a.com",
                snippet="S",
                site_name="GitHub",
                authority_description="官方",
            ),
        ]
        docs = search_results_to_documents(results)
        assert docs[0].metadata["site_name"] == "GitHub"
        assert docs[0].metadata["authority_description"] == "官方"

    def test_none_site_name_omitted_from_metadata(self) -> None:
        results = [
            SearchResult(title="T", link="https://a.com", snippet="S"),
        ]
        docs = search_results_to_documents(results)
        assert "site_name" not in docs[0].metadata
        assert "authority_description" not in docs[0].metadata

    def test_full_chain_to_sources_metadata(self) -> None:
        """End-to-end: SearchResult → Document → format_documents_with_metadata → sources_metadata."""
        from myrm_agent_harness.utils.context_format import format_documents_with_metadata

        results = [
            SearchResult(
                title="GitHub Docs",
                link="https://docs.github.com",
                snippet="GitHub documentation",
                site_name="GitHub",
                authority_description="官方",
            ),
            SearchResult(
                title="Blog Post",
                link="https://blog.example.com",
                snippet="A blog post",
            ),
        ]
        docs = search_results_to_documents(results)
        sources, _context, _ = format_documents_with_metadata(docs)

        assert len(sources) == 2
        assert sources[0]["site_name"] == "GitHub"
        assert sources[0]["authority_description"] == "官方"
        assert "site_name" not in sources[1]
        assert "authority_description" not in sources[1]


class TestCombineSearchResultsMetadataPreservation:
    """Verify combine_search_results_unified preserves all metadata fields."""

    def test_date_and_summary_survive_combine(self) -> None:
        from langchain_core.documents import Document
        from myrm_agent_harness.toolkits.web_search.search_results_processor import (
            combine_search_results_unified,
        )

        doc = Document(
            page_content="Test content",
            metadata={
                "title": "T",
                "url": "https://example.com/page",
                "description": "Desc",
                "date": "2026-07-15",
                "summary": "Long summary",
                "site_name": "Example",
                "authority_description": "官方媒体",
            },
        )
        _, unified = combine_search_results_unified([("q1", [doc], None)])
        assert len(unified) == 1
        m = unified[0].metadata
        assert m["date"] == "2026-07-15"
        assert m["summary"] == "Long summary"
        assert m["site_name"] == "Example"
        assert m["authority_description"] == "官方媒体"

    def test_url_normalized_but_other_metadata_intact(self) -> None:
        from langchain_core.documents import Document
        from myrm_agent_harness.toolkits.web_search.search_results_processor import (
            combine_search_results_unified,
        )

        doc = Document(
            page_content="Content",
            metadata={
                "title": "T",
                "url": "https://example.com/page?utm_source=x",
                "description": "D",
                "date": "2026-01-01",
                "engines": ["volcengine"],
            },
        )
        _, unified = combine_search_results_unified([("q", [doc], None)])
        assert len(unified) == 1
        assert unified[0].metadata["date"] == "2026-01-01"
        assert unified[0].metadata["engines"] == ["volcengine"]
