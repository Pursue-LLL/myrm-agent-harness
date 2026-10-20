from __future__ import annotations

"""[INPUT] SnippetTriageResult, DeepExtractResult
[OUTPUT] SearchFetchSessionCache, CacheStats
[POS] In-memory session search-fetch coalescing and deduplication cache with adaptive TTL management
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Generic, TypeVar
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from myrm_agent_harness.agent.context_management.two_stage_search_extract.search_extract_types import (
    DeepExtractResult,
    SnippetTriageResult,
)

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "fbclid"}

T = TypeVar("T", SnippetTriageResult, DeepExtractResult)


@dataclass(frozen=True)
class _CacheEntry(Generic[T]):
    created_at: float
    ttl_seconds: int
    scenario: str
    result: T
    estimated_tokens: int


@dataclass(frozen=True)
class CacheStats:
    """Telemetry metrics for session search-fetch caching."""

    triage_hits: int
    triage_misses: int
    extract_hits: int
    extract_misses: int
    total_saved_tokens: int = 0
    realtime_hits: int = 0
    standard_hits: int = 0
    archive_hits: int = 0


class SearchFetchSessionCache:
    """Manages in-memory coalescing and deduplication for search and fetch queries with adaptive TTL."""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._default_ttl_seconds = ttl_seconds
        self._triage_cache: dict[str, _CacheEntry[SnippetTriageResult]] = {}
        self._extract_cache: dict[str, _CacheEntry[DeepExtractResult]] = {}
        self._triage_hits = 0
        self._triage_misses = 0
        self._extract_hits = 0
        self._extract_misses = 0
        self._total_saved_tokens = 0
        self._realtime_hits = 0
        self._standard_hits = 0
        self._archive_hits = 0

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

    def _record_hit_metrics(self, scenario: str, saved_tokens: int) -> None:
        self._total_saved_tokens += saved_tokens
        if scenario == "realtime":
            self._realtime_hits += 1
        elif scenario == "archive":
            self._archive_hits += 1
        else:
            self._standard_hits += 1

    def get_triage(self, query: str, bypass_cache: bool = False) -> SnippetTriageResult | None:
        """Lookup cached Stage 1 triage result by normalized query with adaptive TTL check."""
        if bypass_cache:
            self._triage_misses += 1
            return None

        key = self.normalize_query(query)
        entry = self._triage_cache.get(key)
        now = datetime.now(timezone.utc).timestamp()

        if entry:
            if now - entry.created_at <= entry.ttl_seconds:
                self._triage_hits += 1
                age_seconds = max(0, int(now - entry.created_at))
                self._record_hit_metrics(entry.scenario, entry.estimated_tokens)
                return SnippetTriageResult(
                    query=entry.result.query,
                    items=entry.result.items,
                    total_estimated_tokens=entry.result.total_estimated_tokens,
                    guidance_directive=entry.result.guidance_directive,
                    cached=True,
                    cache_age_seconds=age_seconds,
                    saved_tokens=entry.estimated_tokens,
                    scenario=entry.scenario,
                    timestamp_iso=entry.result.timestamp_iso,
                )
            del self._triage_cache[key]

        self._triage_misses += 1
        return None

    def put_triage(
        self,
        query: str,
        result: SnippetTriageResult,
        ttl_seconds: int | None = None,
        scenario: str = "standard",
        estimated_tokens: int | None = None,
    ) -> None:
        """Store Stage 1 triage result into session cache with adaptive TTL."""
        key = self.normalize_query(query)
        now = datetime.now(timezone.utc).timestamp()
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        tokens = estimated_tokens if estimated_tokens is not None else max(100, result.total_estimated_tokens)
        self._triage_cache[key] = _CacheEntry(
            created_at=now,
            ttl_seconds=ttl,
            scenario=scenario,
            result=result,
            estimated_tokens=tokens,
        )

    def get_extract(self, url: str, bypass_cache: bool = False) -> DeepExtractResult | None:
        """Lookup cached Stage 2 deep extract by normalized URL with adaptive TTL check."""
        if bypass_cache:
            self._extract_misses += 1
            return None

        key = self.normalize_url(url)
        entry = self._extract_cache.get(key)
        now = datetime.now(timezone.utc).timestamp()

        if entry:
            if now - entry.created_at <= entry.ttl_seconds:
                self._extract_hits += 1
                age_seconds = max(0, int(now - entry.created_at))
                self._record_hit_metrics(entry.scenario, entry.estimated_tokens)
                return DeepExtractResult(
                    url=entry.result.url,
                    title=entry.result.title,
                    cleaned_markdown=entry.result.cleaned_markdown,
                    original_char_len=entry.result.original_char_len,
                    cleaned_char_len=entry.result.cleaned_char_len,
                    compression_ratio=entry.result.compression_ratio,
                    fetch_turn=entry.result.fetch_turn,
                    cached=True,
                    cache_age_seconds=age_seconds,
                    saved_tokens=entry.estimated_tokens,
                    scenario=entry.scenario,
                    timestamp_iso=entry.result.timestamp_iso,
                )
            del self._extract_cache[key]

        self._extract_misses += 1
        return None

    def put_extract(
        self,
        url: str,
        result: DeepExtractResult,
        ttl_seconds: int | None = None,
        scenario: str = "standard",
        estimated_tokens: int | None = None,
    ) -> None:
        """Store Stage 2 extract result into session cache with adaptive TTL."""
        key = self.normalize_url(url)
        now = datetime.now(timezone.utc).timestamp()
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        tokens = estimated_tokens if estimated_tokens is not None else max(500, result.original_char_len // 4)
        self._extract_cache[key] = _CacheEntry(
            created_at=now,
            ttl_seconds=ttl,
            scenario=scenario,
            result=result,
            estimated_tokens=tokens,
        )

    def get_stats(self) -> CacheStats:
        """Retrieve telemetry metrics for session cache operations."""
        return CacheStats(
            triage_hits=self._triage_hits,
            triage_misses=self._triage_misses,
            extract_hits=self._extract_hits,
            extract_misses=self._extract_misses,
            total_saved_tokens=self._total_saved_tokens,
            realtime_hits=self._realtime_hits,
            standard_hits=self._standard_hits,
            archive_hits=self._archive_hits,
        )

    def clear(self) -> None:
        """Evict all entries from session cache."""
        self._triage_cache.clear()
        self._extract_cache.clear()

