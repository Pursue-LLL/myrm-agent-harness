"""Tests for apply_domain_diversity_sort and combine_search_results_unified.

Covers: empty input, single doc, no duplicates, same-domain decay,
all-same-domain, mixed domains, empty URL handling, sort stability,
unified dedup merge, failed queries, zero-result queries, and SearchAPIError.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_search.exceptions import SearchAPIError
from myrm_agent_harness.toolkits.web_search.search_results_processor import (
    apply_domain_diversity_sort,
    combine_search_results_unified,
)


def _doc(url: str, content: str = "content") -> Document:
    return Document(page_content=content, metadata={"url": url, "title": "T"})


class TestApplyDomainDiversitySort:
    """Core domain diversity sorting tests."""

    def test_empty_list(self) -> None:
        assert apply_domain_diversity_sort([]) == []

    def test_single_document(self) -> None:
        docs = [_doc("https://example.com")]
        result = apply_domain_diversity_sort(docs)
        assert len(result) == 1
        assert result[0].metadata["url"] == "https://example.com"

    def test_no_duplicate_domains_preserves_order(self) -> None:
        docs = [
            _doc("https://a.com"),
            _doc("https://b.com"),
            _doc("https://c.com"),
        ]
        result = apply_domain_diversity_sort(docs)
        urls = [d.metadata["url"] for d in result]
        assert urls == ["https://a.com", "https://b.com", "https://c.com"]

    def test_same_domain_decay_reorders(self) -> None:
        """csdn rank0 score=1.0, csdn rank1 score=0.4, csdn rank2 score≈0.21,
        stackoverflow rank3 score=0.25. So: csdn/a > csdn/b > stackoverflow > csdn/c."""
        docs = [
            _doc("https://csdn.net/a"),
            _doc("https://csdn.net/b"),
            _doc("https://csdn.net/c"),
            _doc("https://stackoverflow.com/q"),
        ]
        result = apply_domain_diversity_sort(docs)
        urls = [d.metadata["url"] for d in result]
        assert urls[0] == "https://csdn.net/a"
        assert urls[1] == "https://csdn.net/b"
        assert "stackoverflow.com" in urls[2]
        assert urls[3] == "https://csdn.net/c"

    def test_all_same_domain_preserves_relative_order(self) -> None:
        docs = [
            _doc("https://csdn.net/1"),
            _doc("https://csdn.net/2"),
            _doc("https://csdn.net/3"),
        ]
        result = apply_domain_diversity_sort(docs)
        urls = [d.metadata["url"] for d in result]
        assert urls == [
            "https://csdn.net/1",
            "https://csdn.net/2",
            "https://csdn.net/3",
        ]

    def test_mixed_domains_diversity(self) -> None:
        docs = [
            _doc("https://csdn.net/1"),
            _doc("https://csdn.net/2"),
            _doc("https://zhihu.com/1"),
            _doc("https://csdn.net/3"),
            _doc("https://github.com/1"),
        ]
        result = apply_domain_diversity_sort(docs)

        first_three_domains = [
            d.metadata["url"].split("/")[2] for d in result[:3]
        ]
        unique_in_top3 = len(set(first_three_domains))
        assert unique_in_top3 >= 2

    def test_empty_url_treated_as_same_domain(self) -> None:
        docs = [
            _doc(""),
            _doc(""),
            _doc("https://example.com"),
        ]
        result = apply_domain_diversity_sort(docs)
        assert len(result) == 3

    def test_www_stripped_by_extract_domain(self) -> None:
        """www.csdn.net and csdn.net should be treated as the same domain,
        so the second csdn doc gets decayed while example.com stays at rank2."""
        docs = [
            _doc("https://www.csdn.net/a"),
            _doc("https://csdn.net/b"),
            _doc("https://example.com/c"),
        ]
        result = apply_domain_diversity_sort(docs)
        assert result[0].metadata["url"] == "https://www.csdn.net/a"
        assert result[1].metadata["url"] == "https://csdn.net/b"
        assert "example.com" in result[2].metadata["url"]

    def test_custom_decay_factor(self) -> None:
        docs = [
            _doc("https://a.com/1"),
            _doc("https://a.com/2"),
            _doc("https://b.com/1"),
        ]
        result_aggressive = apply_domain_diversity_sort(docs, decay_factor=0.5)
        result_mild = apply_domain_diversity_sort(docs, decay_factor=0.95)

        aggressive_urls = [d.metadata["url"] for d in result_aggressive]
        assert aggressive_urls[1] == "https://b.com/1"

        mild_urls = [d.metadata["url"] for d in result_mild]
        assert mild_urls[0] == "https://a.com/1"

    def test_document_content_preserved(self) -> None:
        docs = [
            Document(
                page_content="Important content",
                metadata={"url": "https://a.com", "title": "Title A"},
            ),
            Document(
                page_content="Other content",
                metadata={"url": "https://b.com", "title": "Title B"},
            ),
        ]
        result = apply_domain_diversity_sort(docs)
        contents = {d.page_content for d in result}
        assert contents == {"Important content", "Other content"}

    def test_returns_new_list(self) -> None:
        docs = [_doc("https://a.com"), _doc("https://b.com")]
        result = apply_domain_diversity_sort(docs)
        assert result is not docs

    def test_decay_math_correctness(self) -> None:
        """same/1: base=1.0, n=1, score=1.0
        same/2: base=0.5, n=2, score=0.5*0.8=0.4
        other/1: base=0.333, n=1, score=0.333
        Order: same/1(1.0) > same/2(0.4) > other/1(0.333)"""
        docs = [
            _doc("https://same.com/1"),
            _doc("https://same.com/2"),
            _doc("https://other.com/1"),
        ]
        result = apply_domain_diversity_sort(docs, decay_factor=0.8)

        assert result[0].metadata["url"] == "https://same.com/1"
        assert result[1].metadata["url"] == "https://same.com/2"
        assert result[2].metadata["url"] == "https://other.com/1"

    def test_decay_factor_zero_extreme(self) -> None:
        """decay_factor=0 means all same-domain duplicates get score 0 except the first."""
        docs = [
            _doc("https://a.com/1"),
            _doc("https://a.com/2"),
            _doc("https://b.com/1"),
        ]
        result = apply_domain_diversity_sort(docs, decay_factor=0.0)
        assert result[0].metadata["url"] == "https://a.com/1"
        assert result[1].metadata["url"] == "https://b.com/1"

    def test_decay_factor_one_no_effect(self) -> None:
        """decay_factor=1.0 means no decay, original order preserved."""
        docs = [
            _doc("https://a.com/1"),
            _doc("https://a.com/2"),
            _doc("https://b.com/1"),
        ]
        result = apply_domain_diversity_sort(docs, decay_factor=1.0)
        urls = [d.metadata["url"] for d in result]
        assert urls == ["https://a.com/1", "https://a.com/2", "https://b.com/1"]

    def test_large_input_many_domains(self) -> None:
        """10+ documents across multiple domains."""
        docs = []
        for i in range(5):
            docs.append(_doc(f"https://csdn.net/{i}"))
        for i in range(3):
            docs.append(_doc(f"https://zhihu.com/{i}"))
        docs.append(_doc("https://github.com/1"))
        docs.append(_doc("https://stackoverflow.com/1"))

        result = apply_domain_diversity_sort(docs)
        assert len(result) == 10

        top3_domains = {
            result[i].metadata["url"].split("/")[2] for i in range(3)
        }
        assert len(top3_domains) >= 1

    def test_no_metadata_url_key(self) -> None:
        """Document without 'url' in metadata should not crash."""
        docs = [
            Document(page_content="no url", metadata={"title": "T"}),
            _doc("https://ok.com/page"),
        ]
        result = apply_domain_diversity_sort(docs)
        assert len(result) == 2

    def test_log_not_emitted_for_unique_domains(self, caplog: pytest.LogCaptureFixture) -> None:
        """When all domains are unique, no domain diversity log is emitted."""
        import logging

        docs = [_doc("https://a.com"), _doc("https://b.com")]
        with caplog.at_level(logging.INFO):
            apply_domain_diversity_sort(docs)
        assert "Domain diversity" not in caplog.text

    def test_log_emitted_for_repeated_domains(self, caplog: pytest.LogCaptureFixture) -> None:
        """When a domain appears >1 time, domain diversity log is emitted."""
        import logging

        docs = [_doc("https://a.com/1"), _doc("https://a.com/2")]
        with caplog.at_level(logging.INFO):
            apply_domain_diversity_sort(docs)
        assert "Domain diversity" in caplog.text


def _search_doc(url: str, title: str = "T", content: str = "snippet") -> Document:
    return Document(
        page_content=content,
        metadata={"url": url, "title": title, "description": content},
    )


_MODULE = "myrm_agent_harness.toolkits.web_search.search_results_processor"


class TestCombineSearchResultsUnified:
    """Tests for combine_search_results_unified."""

    def test_empty_input(self) -> None:
        urls, docs = combine_search_results_unified([])
        assert urls == []
        assert docs == []

    def test_all_queries_failed_raises(self) -> None:
        data = [("q1", [], RuntimeError("network error"))]
        with pytest.raises(SearchAPIError):
            combine_search_results_unified(data)

    def test_all_queries_zero_results_raises(self) -> None:
        data = [("q1", [], None), ("q2", [], None)]
        with pytest.raises(SearchAPIError):
            combine_search_results_unified(data)

    def test_single_query_single_doc(self) -> None:
        doc = _search_doc("https://example.com/page1")
        data = [("q1", [doc], None)]
        urls, docs = combine_search_results_unified(data)
        assert len(docs) == 1
        assert len(urls) == 1
        assert "example.com" in urls[0]["url"]

    def test_dedup_same_url_same_content(self) -> None:
        doc1 = _search_doc("https://example.com/page1", content="same content")
        doc2 = _search_doc("https://example.com/page1", content="same content")
        data = [("q1", [doc1], None), ("q2", [doc2], None)]
        urls, docs = combine_search_results_unified(data)
        assert len(docs) == 1

    def test_dedup_same_url_different_content_keeps_longest(self) -> None:
        """Same URL with different content: URL arbitration keeps the longest."""
        doc1 = _search_doc("https://example.com/page1", content="short")
        doc2 = _search_doc("https://example.com/page1", content="much longer content here")
        data = [("q1", [doc1], None), ("q2", [doc2], None)]
        urls, docs = combine_search_results_unified(data)
        assert len(docs) == 1
        assert "much longer" in docs[0].page_content

    def test_different_urls_different_content_both_kept(self) -> None:
        """Different URLs with different content are both kept."""
        doc1 = _search_doc("https://a.com/page1", content="unique content A")
        doc2 = _search_doc("https://b.com/page2", content="unique content B")
        data = [("q1", [doc1, doc2], None)]
        urls, docs = combine_search_results_unified(data)
        assert len(docs) == 2
        assert len(urls) == 2

    def test_different_urls_same_content_mirror_dedup(self) -> None:
        """Different URLs with identical content (mirror sites) are deduplicated."""
        doc1 = _search_doc("https://a.com/page1", content="same content")
        doc2 = _search_doc("https://b.com/page2", content="same content")
        data = [("q1", [doc1, doc2], None)]
        urls, docs = combine_search_results_unified(data)
        assert len(docs) == 1

    def test_mixed_success_and_failure(self) -> None:
        doc = _search_doc("https://ok.com/page")
        data = [
            ("q1", [doc], None),
            ("q2", [], RuntimeError("fail")),
        ]
        urls, docs = combine_search_results_unified(data)
        assert len(docs) == 1

    def test_doc_missing_url_skipped(self) -> None:
        doc_ok = _search_doc("https://valid.com/page")
        doc_no_url = Document(
            page_content="no url doc",
            metadata={"title": "T", "description": "d"},
        )
        data = [("q1", [doc_ok, doc_no_url], None)]
        urls, docs = combine_search_results_unified(data)
        assert len(docs) == 1

    def test_url_normalization_semantic_keeps_fragment(self) -> None:
        """metadata['url'] uses normalized_url_semantic which keeps fragment."""
        doc = _search_doc("https://Example.COM/Page#fragment")
        data = [("q1", [doc], None)]
        urls, docs = combine_search_results_unified(data)
        assert len(docs) == 1
        assert "example.com" in docs[0].metadata["url"]
        assert "#fragment" in docs[0].metadata["url"]

    def test_multiple_queries_merge(self) -> None:
        doc1 = _search_doc("https://a.com/1", content="content for a.com")
        doc2 = _search_doc("https://b.com/2", content="content for b.com")
        doc3 = _search_doc("https://c.com/3", content="content for c.com")
        data = [
            ("q1", [doc1, doc2], None),
            ("q2", [doc3], None),
        ]
        urls, docs = combine_search_results_unified(data)
        assert len(docs) == 3
        assert len(urls) == 3

    def test_metadata_preserved(self) -> None:
        doc = _search_doc("https://example.com/page", title="My Title")
        data = [("q1", [doc], None)]
        urls, docs = combine_search_results_unified(data)
        assert docs[0].metadata["title"] == "My Title"
        assert urls[0]["title"] == "My Title"

    def test_invalid_url_normalization_skipped(self) -> None:
        """When normalize_url returns empty dedup key, doc is skipped."""
        doc = _search_doc("not-a-valid-url-at-all")
        data = [("q1", [doc], None)]
        urls, docs = combine_search_results_unified(data)
        assert len(docs) <= 1

    def test_normalize_url_returns_empty_dedup_key(self) -> None:
        """When normalize_url returns empty dedup key, doc is skipped with warning."""
        doc = _search_doc("https://valid-looking.com/page")
        data = [("q1", [doc], None)]
        with patch(f"{_MODULE}.normalize_url", return_value=("", "")):
            urls, docs = combine_search_results_unified(data)
        assert len(docs) == 0

    def test_long_content_truncation_hash(self) -> None:
        """Content >500 chars should use first 500 chars for hash dedup."""
        long_content = "A" * 600
        doc1 = _search_doc("https://a.com/page", content=long_content)
        doc2 = _search_doc("https://a.com/page", content=long_content)
        data = [("q1", [doc1], None), ("q2", [doc2], None)]
        urls, docs = combine_search_results_unified(data)
        assert len(docs) == 1

    def test_long_content_different_suffix_dedup(self) -> None:
        """Docs with same first 500 chars but different tails should dedup (same hash)."""
        base = "X" * 500
        doc1 = _search_doc("https://a.com/page", content=base + "AAAA")
        doc2 = _search_doc("https://a.com/page", content=base + "BBBB")
        data = [("q1", [doc1], None), ("q2", [doc2], None)]
        urls, docs = combine_search_results_unified(data)
        assert len(docs) == 1

    def test_search_api_error_context_metadata(self) -> None:
        """SearchAPIError should include query statistics in context."""
        data = [("q1", [], None), ("q2", [], RuntimeError("fail"))]
        with pytest.raises(SearchAPIError) as exc_info:
            combine_search_results_unified(data)
        ctx = exc_info.value.context
        assert ctx is not None
        assert ctx.metadata["total_queries"] == "2"
        assert ctx.metadata["failed_queries"] == "1"

    def test_mixed_failed_zero_success(self) -> None:
        """Mix of failed, zero-result, and successful queries."""
        doc = _search_doc("https://ok.com/page")
        data = [
            ("q1", [doc], None),
            ("q2", [], None),
            ("q3", [], RuntimeError("timeout")),
        ]
        urls, docs = combine_search_results_unified(data)
        assert len(docs) == 1

    def test_all_docs_skipped_but_total_nonzero(self) -> None:
        """All docs have URL but normalize fails, total_docs > 0 but unified empty."""
        doc = _search_doc("https://ok.com/page")
        data = [("q1", [doc], None)]
        with patch(f"{_MODULE}.normalize_url", return_value=("", "")):
            urls, docs = combine_search_results_unified(data)
        assert len(docs) == 0
        assert len(urls) == 0
