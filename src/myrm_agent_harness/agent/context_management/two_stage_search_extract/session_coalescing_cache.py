# [INPUT] SnippetTriageResult, DeepExtractResult
# [OUTPUT] SearchFetchSessionCache, CacheStats
# [POS] In-memory session search-fetch coalescing and deduplication cache with TTL management

"""Session-level coalescing cache for search triage snippets and deep extracted documents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from myrm_agent_harness.agent.context_management.two_stage_search_extract.search_extract_types import (
    DeepExtractResult,
    SnippetTriageResult,
)

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "fbclid"}


@dataclass(frozen=True)
class CacheStats:
    """Telemetry metrics for session search-fetch caching."""

    triage_hits: int
    triage_misses: int
    extract_hits: int
    extract_misses: int


class SearchFetchSessionCache:
    """Manages in-memory coalescing and deduplication for search and fetch queries."""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._ttl_seconds = ttl_seconds
        self._triage_cache: dict[str, tuple[float, SnippetTriageResult]] = {}
        self._extract_cache: dict[str, tuple[float, DeepExtractResult]] = {}
        self._triage_hits = 0
        self._triage_misses = 0
        self._extract_hits = 0
        self._extract_misses = 0

    @staticmethod
    def normalize_query(query: str) -> str:
        """Normalize query string for semantic coalescing."""
        lowered = query.lower().strip()
        cleaned = re.sub(r"[^\w\s]", "", lowered)
        return " ".join(cleaned.split())

    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize URL by stripping trailing slashes and marketing tracking params."""
        try:
            parsed = urlparse(url.strip())
            netloc = parsed.netloc.lower()
            path = parsed.path.rstrip("/")
            filtered_query = [
                (k, v)
                for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                if k.lower() not in _TRACKING_PARAMS
            ]
            new_query = urlencode(filtered_query)
            return urlunparse((parsed.scheme.lower(), netloc, path, parsed.params, new_query, ""))
        except Exception:
            return url.strip().rstrip("/").lower()

    def get_triage(self, query: str, bypass_cache: bool = False) -> SnippetTriageResult | None:
        """Lookup cached Stage 1 triage result by normalized query."""
        if bypass_cache:
            self._triage_misses += 1
            return None

        key = self.normalize_query(query)
        entry = self._triage_cache.get(key)
        now = datetime.now(timezone.utc).timestamp()

        if entry:
            created_at, result = entry
            if now - created_at <= self._ttl_seconds:
                self._triage_hits += 1
                # Return a copy with cached flag marked True
                return SnippetTriageResult(
                    query=result.query,
                    items=result.items,
                    total_estimated_tokens=result.total_estimated_tokens,
                    guidance_directive=result.guidance_directive,
                    cached=True,
                    timestamp_iso=result.timestamp_iso,
                )
            del self._triage_cache[key]

        self._triage_misses += 1
        return None

    def put_triage(self, query: str, result: SnippetTriageResult) -> None:
        """Store Stage 1 triage result into session cache."""
        key = self.normalize_query(query)
        now = datetime.now(timezone.utc).timestamp()
        self._triage_cache[key] = (now, result)

    def get_extract(self, url: str, bypass_cache: bool = False) -> DeepExtractResult | None:
        """Lookup cached Stage 2 deep extract by normalized URL."""
        if bypass_cache:
            self._extract_misses += 1
            return None

        key = self.normalize_url(url)
        entry = self._extract_cache.get(key)
        now = datetime.now(timezone.utc).timestamp()

        if entry:
            created_at, result = entry
            if now - created_at <= self._ttl_seconds:
                self._extract_hits += 1
                return DeepExtractResult(
                    url=result.url,
                    title=result.title,
                    cleaned_markdown=result.cleaned_markdown,
                    original_char_len=result.original_char_len,
                    cleaned_char_len=result.cleaned_char_len,
                    compression_ratio=result.compression_ratio,
                    fetch_turn=result.fetch_turn,
                    cached=True,
                    timestamp_iso=result.timestamp_iso,
                )
            del self._extract_cache[key]

        self._extract_misses += 1
        return None

    def put_extract(self, url: str, result: DeepExtractResult) -> None:
        """Store Stage 2 extract result into session cache."""
        key = self.normalize_url(url)
        now = datetime.now(timezone.utc).timestamp()
        self._extract_cache[key] = (now, result)

    def get_stats(self) -> CacheStats:
        """Retrieve telemetry metrics for session cache operations."""
        return CacheStats(
            triage_hits=self._triage_hits,
            triage_misses=self._triage_misses,
            extract_hits=self._extract_hits,
            extract_misses=self._extract_misses,
        )

    def clear(self) -> None:
        """Evict all entries from session cache."""
        self._triage_cache.clear()
        self._extract_cache.clear()
