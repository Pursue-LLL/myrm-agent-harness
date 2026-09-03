"""Unit tests for citation_resolver redirect resolution and tracking parameter stripping."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.core.security.http.secure_fetch import SecureHttpTarget
from myrm_agent_harness.toolkits.web_search.processing.citation_resolver import (
    _needs_citation_redirect_resolution,
    _normalize_source_url,
    enrich_sources_with_resolved_urls,
    resolve_citation_url,
    strip_tracking_parameters,
)


def test_strip_tracking_parameters() -> None:
    assert (
        strip_tracking_parameters("https://example.com/article?utm_source=twitter&utm_medium=social&page=2")
        == "https://example.com/article?page=2"
    )
    assert (
        strip_tracking_parameters("https://example.com/doc?spm=123.456&id=99")
        == "https://example.com/doc?id=99"
    )
    assert (
        strip_tracking_parameters("https://example.com/post?fbclid=xyz&gclid=abc")
        == "https://example.com/post"
    )
    assert (
        strip_tracking_parameters("https://example.com/path?utm_campaign=spring&utm_term=ai#section")
        == "https://example.com/path#section"
    )
    assert strip_tracking_parameters("https://example.com/clean") == "https://example.com/clean"
    assert strip_tracking_parameters("") == ""
    assert strip_tracking_parameters("not_a_valid_url") == "not_a_valid_url"


def test_needs_citation_redirect_resolution_detects_known_wrappers() -> None:
    assert _needs_citation_redirect_resolution("https://www.google.com/url?q=https://example.com/a")
    assert _needs_citation_redirect_resolution("https://duckduckgo.com/l/?uddg=https://example.com")
    assert _needs_citation_redirect_resolution("https://www.bing.com/ck/a?url=https://example.com")
    assert _needs_citation_redirect_resolution("https://googleusercontent.com/a/b")
    assert _needs_citation_redirect_resolution("https://searx.local/redirect?url=https://example.com")
    assert not _needs_citation_redirect_resolution("https://docs.python.org/3/")


def test_normalize_source_url_updates_link_field() -> None:
    source = {
        "link": "https://www.google.com/url?q=https://real.example/a",
        "title": "T",
    }
    normalized = _normalize_source_url(
        source,
        "https://www.google.com/url?q=https://real.example/a",
        "https://real.example/a",
    )
    assert normalized["link"] == "https://real.example/a"
    assert normalized["url"] == "https://real.example/a"


@pytest.mark.asyncio
async def test_resolve_citation_url_rejects_non_http_scheme() -> None:
    assert await resolve_citation_url("ftp://example.com/a") == "ftp://example.com/a"
    assert await resolve_citation_url("") == ""


@pytest.mark.asyncio
async def test_enrich_sources_handles_empty_and_missing_url() -> None:
    assert await enrich_sources_with_resolved_urls([]) == []
    enriched = await enrich_sources_with_resolved_urls([{"title": "No URL"}])
    assert enriched == [{"title": "No URL"}]


def test_normalize_source_url_sets_canonical_url_and_redirect_url() -> None:
    source = {"url": "https://redirect.example/r", "title": "T"}
    normalized = _normalize_source_url(source, "https://redirect.example/r", "https://real.example/article")
    assert normalized["url"] == "https://real.example/article"
    assert normalized["redirect_url"] == "https://redirect.example/r"
    assert normalized["title"] == "T"


def test_normalize_source_url_noop_when_unchanged() -> None:
    source = {"url": "https://example.com/a", "title": "T"}
    normalized = _normalize_source_url(source, "https://example.com/a", "https://example.com/a")
    assert normalized is source


@pytest.mark.asyncio
async def test_resolve_citation_url_skips_network_for_direct_links() -> None:
    with patch(
        "myrm_agent_harness.toolkits.web_search.processing.citation_resolver.resolve_secure_http_target",
        side_effect=RuntimeError("should not be called"),
    ):
        result = await resolve_citation_url("https://docs.python.org/3/?utm_source=test")
    assert result == "https://docs.python.org/3/"


@pytest.mark.asyncio
async def test_resolve_citation_url_returns_original_on_failure() -> None:
    with patch(
        "myrm_agent_harness.toolkits.web_search.processing.citation_resolver.resolve_secure_http_target",
        side_effect=RuntimeError("network"),
    ):
        result = await resolve_citation_url(
            "https://www.google.com/url?q=https://example.com/a",
        )
    assert result == "https://www.google.com/url?q=https://example.com/a"


@pytest.mark.asyncio
async def test_resolve_citation_url_follows_redirect_chain() -> None:
    target = SecureHttpTarget(
        logical_url="https://docs.python.org/3/?utm_source=google",
        request_url="https://docs.python.org/3/?utm_source=google",
        headers={},
        method="HEAD",
    )
    with patch(
        "myrm_agent_harness.toolkits.web_search.processing.citation_resolver.resolve_secure_http_target",
        new=AsyncMock(return_value=target),
    ):
        result = await resolve_citation_url("https://www.google.com/url?q=https://docs.python.org/3/")
    assert result == "https://docs.python.org/3/"


@pytest.mark.asyncio
async def test_enrich_sources_normalizes_url_for_frontend() -> None:
    target = SecureHttpTarget(
        logical_url="https://real.example/article?utm_medium=banner",
        request_url="https://real.example/article?utm_medium=banner",
        headers={},
        method="HEAD",
    )
    wrapper = "https://www.google.com/url?q=https://real.example/article"
    with patch(
        "myrm_agent_harness.toolkits.web_search.processing.citation_resolver.resolve_secure_http_target",
        new=AsyncMock(return_value=target),
    ) as mock_resolve:
        enriched = await enrich_sources_with_resolved_urls(
            [{"url": wrapper, "title": "T"}],
        )
    assert mock_resolve.await_count == 1
    assert enriched[0]["url"] == "https://real.example/article"
    assert enriched[0]["redirect_url"] == wrapper
    assert "resolved_url" not in enriched[0]


@pytest.mark.asyncio
async def test_enrich_sources_skips_head_for_direct_urls() -> None:
    direct = "https://docs.python.org/3/whatsnew/3.13.html?utm_source=direct"
    with patch(
        "myrm_agent_harness.toolkits.web_search.processing.citation_resolver.resolve_secure_http_target",
        new=AsyncMock(),
    ) as mock_resolve:
        enriched = await enrich_sources_with_resolved_urls(
            [{"url": direct, "title": "Docs"}],
        )
    mock_resolve.assert_not_awaited()
    assert enriched[0]["url"] == "https://docs.python.org/3/whatsnew/3.13.html"
    assert enriched[0]["redirect_url"] == direct
