"""Resolve citation redirect URLs to final destinations (SSRF-safe).

Follows provider redirect chains (e.g. Google url?q=...) via HEAD requests
using the shared secure_fetch redirect guard.

[INPUT]
- core.security.http.secure_fetch::resolve_secure_http_target (POS: SSRF-safe redirect resolution)

[OUTPUT]
- resolve_citation_url: single URL resolution with fallback to original
- enrich_sources_with_resolved_urls: batch resolve redirect chains and normalize sources
  (`url` = final destination, `redirect_url` = original when different)
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from myrm_agent_harness.core.security.http.secure_fetch import (
    resolve_secure_http_target,
)
from myrm_agent_harness.infra.tls_compat import create_httpx_client

logger = logging.getLogger(__name__)

_REDIRECT_TIMEOUT_SECONDS = 5.0
_MAX_CONCURRENT_RESOLUTIONS = 5

# Provider citation wrappers that require SSRF-safe HEAD resolution.
_GOOGLE_URL_PATH = re.compile(r"^/url/?$", re.IGNORECASE)
_DUCKDUCKGO_L_PATH = re.compile(r"^/l/?", re.IGNORECASE)
_BING_CK_PATH = re.compile(r"^/ck/", re.IGNORECASE)


def _needs_citation_redirect_resolution(url: str) -> bool:
    """Return True when URL is a known search-provider redirect wrapper."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if host == "googleusercontent.com":
        return True
    if host.endswith("google.com") or host.endswith("google.com.hk"):
        return bool(_GOOGLE_URL_PATH.match(path))
    if host.endswith("duckduckgo.com") or host == "duck.com":
        return bool(_DUCKDUCKGO_L_PATH.match(path))
    if host.endswith("bing.com"):
        return bool(_BING_CK_PATH.match(path))
    if (
        path.rstrip("/").lower() == "/redirect"
        and "url=" in (parsed.query or "").lower()
    ):
        return True
    return False


async def resolve_citation_url(url: str) -> str:
    """Resolve a citation redirect URL; return the original URL on failure or when not a wrapper."""
    if not url or not url.startswith(("http://", "https://")):
        return url
    if not _needs_citation_redirect_resolution(url):
        return url
    try:
        timeout = httpx.Timeout(_REDIRECT_TIMEOUT_SECONDS)
        async with create_httpx_client(
            timeout=timeout, follow_redirects=False
        ) as client:
            target = await resolve_secure_http_target(
                client,
                url,
                method="HEAD",
                max_redirects=5,
            )
            resolved = target.logical_url.strip()
            return resolved or url
    except Exception as exc:
        logger.debug("Citation redirect resolution failed for %s: %s", url, exc)
        return url


def _normalize_source_url(
    source: dict[str, Any], raw_url: str, resolved: str
) -> dict[str, Any]:
    """Apply resolved destination as canonical `url`; preserve original in `redirect_url`."""
    if resolved == raw_url:
        return source
    enriched = dict(source)
    enriched["redirect_url"] = raw_url
    enriched["url"] = resolved
    if "link" in enriched:
        enriched["link"] = resolved
    return enriched


async def enrich_sources_with_resolved_urls(
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve redirect chains and normalize each source for downstream SSE/UI.

    Sets ``url`` to the final clickable destination. When resolution changes the
    URL, the original value is stored in ``redirect_url`` for dedup audit trails.
    """
    if not sources:
        return sources

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_RESOLUTIONS)

    async def _resolve_one(source: dict[str, Any]) -> dict[str, Any]:
        raw_url = source.get("link") or source.get("url")
        if not isinstance(raw_url, str) or not raw_url:
            return source
        async with semaphore:
            resolved = await resolve_citation_url(raw_url)
        return _normalize_source_url(source, raw_url, resolved)

    return list(await asyncio.gather(*(_resolve_one(item) for item in sources)))
