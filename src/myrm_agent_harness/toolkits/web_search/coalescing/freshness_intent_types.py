"""Data models and intent types for Dynamic Query Freshness and Cache Governance.

Provides freshness classification tiers, detection results, and governor
configuration settings for web search caching and single-flight coalescing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class QueryFreshnessTier(StrEnum):
    """Classification tier of query freshness requirements."""

    REALTIME_BYPASS = "realtime_bypass"
    DYNAMIC_SHORT_TTL = "dynamic_short_ttl"
    STANDARD_TTL = "standard_ttl"


@dataclass(frozen=True, slots=True)
class FreshnessDetectionResult:
    """Result payload evaluating a query's temporal freshness requirement."""

    tier: QueryFreshnessTier
    is_bypass_cache: bool
    effective_ttl_seconds: int
    matched_keywords: list[str] = field(default_factory=list)
    confidence: float = 1.0
    normalized_query: str = ""


@dataclass(frozen=True, slots=True)
class FreshnessGovernorConfig:
    """Settings controlling TTL thresholds and freshness keyword definitions."""

    default_ttl_seconds: int = 900
    short_ttl_seconds: int = 120
    bypass_ttl_seconds: int = 0
    enable_auto_detection: bool = True
    custom_realtime_keywords: list[str] = field(default_factory=list)
    custom_short_ttl_keywords: list[str] = field(default_factory=list)
