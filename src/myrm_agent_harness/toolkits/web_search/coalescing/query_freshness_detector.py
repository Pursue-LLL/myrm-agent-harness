"""Query freshness detector for web search and request caching.

Inspects prompt directives and temporal domain terms to classify incoming
queries into realtime bypass, short TTL, or standard cached tiers.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from myrm_agent_harness.toolkits.web_search.coalescing.freshness_intent_types import (
    FreshnessDetectionResult,
    FreshnessGovernorConfig,
    QueryFreshnessTier,
)

_PROMPT_BYPASS_PATTERNS: tuple[str, ...] = (
    "no-cache",
    "nocache",
    "force_refresh",
    "不要用缓存",
    "跳过缓存",
    "无需缓存",
    "获取最新",
    "最新实时",
    "实时最新",
    "fresh:true",
    "fresh: true",
)

_DEFAULT_REALTIME_KEYWORDS: tuple[str, ...] = (
    "股价",
    "开盘价",
    "收盘价",
    "盘前",
    "盘后",
    "汇率",
    "stock price",
    "btc",
    "eth",
    "加密货币现价",
    "突发",
    "热搜",
    "实时新闻",
    "最新突发",
    "breaking news",
)

_DEFAULT_SHORT_TTL_KEYWORDS: tuple[str, ...] = (
    "今日",
    "今天",
    "实时气温",
    "天气",
    "气象预警",
    "今日热点",
    "实时路况",
    "today",
    "weather",
)


class QueryFreshnessDetector:
    """High-speed heuristic detector for query temporal sensitivity."""

    def __init__(self, config: FreshnessGovernorConfig | None = None) -> None:
        self._config = config or FreshnessGovernorConfig()
        self._realtime_keywords: list[str] = [
            *map(str.lower, _DEFAULT_REALTIME_KEYWORDS),
            *map(str.lower, self._config.custom_realtime_keywords),
        ]
        self._short_ttl_keywords: list[str] = [
            *map(str.lower, _DEFAULT_SHORT_TTL_KEYWORDS),
            *map(str.lower, self._config.custom_short_ttl_keywords),
        ]

    def detect(
        self,
        query: str,
        *,
        explicit_bypass: bool = False,
        prompt_hint: str | None = None,
    ) -> FreshnessDetectionResult:
        """Classify temporal tier and cache bypass requirements of the query."""
        normalized = re.sub(r"\s+", " ", query.strip().lower())
        combined_text = (
            f"{normalized} {prompt_hint.strip().lower()}"
            if prompt_hint
            else normalized
        )

        # 1. Explicit caller bypass flag
        if explicit_bypass:
            return FreshnessDetectionResult(
                tier=QueryFreshnessTier.REALTIME_BYPASS,
                is_bypass_cache=True,
                effective_ttl_seconds=self._config.bypass_ttl_seconds,
                matched_keywords=["explicit_flag"],
                confidence=1.0,
                normalized_query=normalized,
            )

        # 2. Natural language Prompt bypass directives
        matched_bypass = [
            pat for pat in _PROMPT_BYPASS_PATTERNS if pat in combined_text
        ]
        if matched_bypass:
            return FreshnessDetectionResult(
                tier=QueryFreshnessTier.REALTIME_BYPASS,
                is_bypass_cache=True,
                effective_ttl_seconds=self._config.bypass_ttl_seconds,
                matched_keywords=matched_bypass,
                confidence=0.99,
                normalized_query=normalized,
            )

        if not self._config.enable_auto_detection:
            return FreshnessDetectionResult(
                tier=QueryFreshnessTier.STANDARD_TTL,
                is_bypass_cache=False,
                effective_ttl_seconds=self._config.default_ttl_seconds,
                confidence=1.0,
                normalized_query=normalized,
            )

        # 3. Realtime sensitive keywords (stocks, currency, breaking news)
        matched_realtime = self._find_matches(combined_text, self._realtime_keywords)
        if matched_realtime:
            return FreshnessDetectionResult(
                tier=QueryFreshnessTier.REALTIME_BYPASS,
                is_bypass_cache=True,
                effective_ttl_seconds=self._config.bypass_ttl_seconds,
                matched_keywords=matched_realtime,
                confidence=0.92,
                normalized_query=normalized,
            )

        # 4. Short-lived dynamic keywords (today, weather, morning briefs)
        matched_short = self._find_matches(combined_text, self._short_ttl_keywords)
        if matched_short:
            return FreshnessDetectionResult(
                tier=QueryFreshnessTier.DYNAMIC_SHORT_TTL,
                is_bypass_cache=False,
                effective_ttl_seconds=self._config.short_ttl_seconds,
                matched_keywords=matched_short,
                confidence=0.88,
                normalized_query=normalized,
            )

        # 5. Default standard TTL
        return FreshnessDetectionResult(
            tier=QueryFreshnessTier.STANDARD_TTL,
            is_bypass_cache=False,
            effective_ttl_seconds=self._config.default_ttl_seconds,
            confidence=0.80,
            normalized_query=normalized,
        )

    def _find_matches(self, text: str, keywords: Sequence[str]) -> list[str]:
        """Collect keywords present in the target string."""
        return [kw for kw in keywords if kw in text]
