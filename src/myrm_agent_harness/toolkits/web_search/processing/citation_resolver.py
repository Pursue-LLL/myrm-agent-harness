"""Resolve citation redirect URLs to final destinations (SSRF-safe) and clean tracking parameters.

Follows provider redirect chains (e.g. Google url?q=...) via HEAD requests
using the shared secure_fetch redirect guard, strips marketing tracking parameters,
and provides canonical URL normalization.

[INPUT]
- core.security.http.secure_fetch::resolve_secure_http_target (POS: SSRF-safe redirect resolution)

[OUTPUT]
- strip_tracking_parameters: remove common marketing/analytics query parameters
- resolve_citation_url: single URL resolution with fallback to original
- enrich_sources_with_resolved_urls: batch resolve redirect chains, strip tracking, and deduplicate sources
  (`url` = final destination, `redirect_url` = original when different)
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

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

_KNOWN_TRACKING_KEYS: frozenset[str] = frozenset({
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "utm_name",
    "spm",
    "spm_id_from",
    "from_source",
    "ref",
    "ref_src",
    "ref_url",
    "fbclid",
    "gclid",
    "gbraid",
    "wbraid",
    "msclkid",
    "twclid",
    "igshid",
    "dclid",
    "_hsenc",
    "_hsmi",
    "mc_cid",
    "mc_eid",
    "yclid",
    "mkt_tok",
})


def strip_tracking_parameters(url: str) -> str:
    """Strip common marketing tracking query parameters while preserving meaningful query params."""
    if not url or not url.startswith(("http://", "https://")):
        return url
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        filtered_pairs = [
            (k, v)
            for k, v in query_pairs
            if k.lower() not in _KNOWN_TRACKING_KEYS and not k.lower().startswith("utm_")
        ]
        if len(filtered_pairs) == len(query_pairs):
            return url
        new_query = urlencode(filtered_pairs)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        return url


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
    return bool(path.rstrip("/").lower() == "/redirect" and "url=" in (parsed.query or "").lower())


async def resolve_citation_url(url: str) -> str:
    """Resolve a citation redirect URL and clean tracking parameters."""
    if not url or not url.startswith(("http://", "https://")):
        return url
    if not _needs_citation_redirect_resolution(url):
        return strip_tracking_parameters(url)
    try:
        timeout = httpx.Timeout(_REDIRECT_TIMEOUT_SECONDS)
        async with create_httpx_client(timeout=timeout, follow_redirects=False) as client:
            target = await resolve_secure_http_target(
                client,
                url,
                method="HEAD",
                max_redirects=5,
            )
            resolved = target.logical_url.strip()
            final_url = resolved or url
            return strip_tracking_parameters(final_url)
    except Exception as exc:
        logger.debug("Citation redirect resolution failed for %s: %s", url, exc)
        return strip_tracking_parameters(url)


def _normalize_source_url(source: dict[str, Any], raw_url: str, resolved: str) -> dict[str, Any]:
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
    """Resolve redirect chains, strip tracking query parameters, and normalize each source."""
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

    resolved_sources = list(await asyncio.gather(*(_resolve_one(item) for item in sources)))
    return resolved_sources
