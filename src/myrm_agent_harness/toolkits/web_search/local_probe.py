"""Local search service discovery probes (framework-level, business-agnostic)."""

from __future__ import annotations

import logging
import time
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.web_search.constants import SEARXNG_PROBE_CANDIDATE_URLS

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT_S = 3.0

SearchRegionPreset = Literal["global", "china", "code", "academic"]


class LocalSearchProbeResult(BaseModel):
    """Result of probing a local or self-hosted search endpoint."""

    provider: Literal["searxng"] = Field(..., description="Search backend identifier")
    base_url: str = Field(default="", description="Resolved api_base for SearXNG")
    available: bool = Field(default=False, description="Whether the service responded successfully")
    latency_ms: int = Field(default=0, description="Round-trip latency in milliseconds")
    error: str | None = Field(default=None, description="Error detail when unavailable")
    recommended_preset: SearchRegionPreset = Field(default="global", description="Suggested region preset")


async def _ping_url(url: str) -> tuple[bool, int, str | None]:
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S, follow_redirects=True) as client:
            resp = await client.get(url)
            elapsed = int((time.monotonic() - start) * 1000)
            if resp.status_code < 500:
                return True, elapsed, None
            return False, elapsed, f"HTTP {resp.status_code}"
    except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        return False, elapsed, f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.warning("Unexpected error probing %s: %s", url, exc)
        return False, elapsed, f"{type(exc).__name__}: {exc}"


async def _verify_searxng_search(base_url: str) -> tuple[bool, int, str | None]:
    """Confirm SearXNG can return HTML search results, not just respond on /."""
    search_url = f"{base_url.rstrip('/')}/search?q=probe&format=html"
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S, follow_redirects=True) as client:
            resp = await client.get(search_url)
            elapsed = int((time.monotonic() - start) * 1000)
            if resp.status_code >= 500:
                return False, elapsed, f"search HTTP {resp.status_code}"
            body = resp.text
            has_results = (
                'class="result"' in body or "class='result'" in body or 'id="results"' in body or "<article" in body
            )
            if has_results:
                return True, elapsed, None
            return False, elapsed, "SearXNG search returned no recognizable results"
    except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        return False, elapsed, f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.warning("Unexpected error verifying SearXNG search at %s: %s", base_url, exc)
        return False, elapsed, f"{type(exc).__name__}: {exc}"


async def probe_searxng_endpoints(
    candidate_urls: tuple[str, ...] | None = None,
) -> LocalSearchProbeResult:
    """Probe SearXNG at known URLs; return the first endpoint that passes search verification."""
    urls = candidate_urls or SEARXNG_PROBE_CANDIDATE_URLS
    for url in urls:
        base = url.rstrip("/")
        ok, latency_ms, error = await _ping_url(url)
        if not ok:
            logger.debug("SearXNG ping failed at %s: %s", url, error)
            continue

        search_ok, search_latency_ms, search_error = await _verify_searxng_search(base)
        if search_ok:
            return LocalSearchProbeResult(
                provider="searxng",
                base_url=base,
                available=True,
                latency_ms=latency_ms + search_latency_ms,
            )
        logger.debug("SearXNG search verify failed at %s: %s", url, search_error)

    last_url = urls[-1] if urls else SEARXNG_PROBE_CANDIDATE_URLS[0]
    return LocalSearchProbeResult(
        provider="searxng",
        base_url=last_url.rstrip("/"),
        available=False,
        error="SearXNG unreachable or search API unavailable at all candidate URLs",
    )


async def probe_local_search_services(
    searxng_candidates: tuple[str, ...] | None = None,
) -> list[LocalSearchProbeResult]:
    """Probe SearXNG (LiteLLM self-hosted backend)."""
    try:
        return [await probe_searxng_endpoints(searxng_candidates)]
    except Exception as exc:
        logger.warning("SearXNG probe failed unexpectedly: %s", exc)
        return [
            LocalSearchProbeResult(
                provider="searxng",
                available=False,
                error=str(exc),
            )
        ]


__all__ = [
    "LocalSearchProbeResult",
    "SearchRegionPreset",
    "probe_local_search_services",
    "probe_searxng_endpoints",
]
