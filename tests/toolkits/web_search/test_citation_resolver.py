"""Unit tests for citation_resolver module (SSRF-safe redirects, tracking parameter stripping, strong typing)."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.web_search.processing.citation_resolver import (
    SearchSourcePayload,
    enrich_sources_with_resolved_urls,
    resolve_citation_url,
    strip_tracking_parameters,
)


def test_strip_tracking_parameters() -> None:
    """Test removing UTM and analytics tracking parameters while preserving query content."""
    raw_url = "https://example.com/article?id=42&utm_source=twitter&utm_medium=social&utm_campaign=launch"
    cleaned = strip_tracking_parameters(raw_url)
    assert cleaned == "https://example.com/article?id=42"


def test_strip_tracking_parameters_preserves_anchor() -> None:
    """Test preserving fragment anchors while stripping tracking params."""
    raw_url = "https://example.com/docs?utm_content=button#installation"
    cleaned = strip_tracking_parameters(raw_url)
    assert cleaned == "https://example.com/docs#installation"


@pytest.mark.asyncio
async def test_resolve_citation_url_non_redirect() -> None:
    """Test standard direct URL returns stripped parameters without network calls."""
    direct_url = "https://docs.python.org/3/whatsnew/3.13.html?utm_source=newsletter"
    resolved = await resolve_citation_url(direct_url)
    assert resolved == "https://docs.python.org/3/whatsnew/3.13.html"


@pytest.mark.asyncio
async def test_enrich_sources_with_resolved_urls_typed() -> None:
    """Test batch resolving sources with strong SearchSourcePayload typing."""
    sources: list[SearchSourcePayload] = [
        {
            "index": 1,
            "title": "Python 3.13 Release Notes",
            "url": "https://docs.python.org/3/whatsnew/3.13.html?utm_source=blog",
            "snippet": "Python 3.13 details...",
        },
        {
            "index": 2,
            "title": "No URL source",
            "snippet": "Local note...",
        },
    ]

    enriched = await enrich_sources_with_resolved_urls(sources)

    assert len(enriched) == 2
    assert enriched[0]["url"] == "https://docs.python.org/3/whatsnew/3.13.html"
    assert enriched[0]["redirect_url"] == "https://docs.python.org/3/whatsnew/3.13.html?utm_source=blog"
    assert enriched[1]["title"] == "No URL source"
