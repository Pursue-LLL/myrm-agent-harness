from __future__ import annotations

"""[INPUT] AdaptiveTtlConfig, TimeSensitivityScenario
[OUTPUT] TimeSensitivityTtlAdvisor
[POS] Adaptive TTL scheduling and query time-sensitivity categorization engine
"""

import re
from urllib.parse import urlparse

from myrm_agent_harness.agent.context_management.two_stage_search_extract.search_extract_types import (
    AdaptiveTtlConfig,
    TimeSensitivityScenario,
)

_REALTIME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(realtime|live|crypto|stock|btc|eth|price|quote|breaking|news|weather|now|today)\b"),
    re.compile(r"(实时|行情|股价|大盘|币价|汇率|天气|今天|今日|最新|突发|快讯)"),
)

_ARCHIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(rfc|specification|whitepaper|history|origin|wiki|paper|handbook)\b"),
    re.compile(r"(历史|起源|沿革|规范|白皮书|维基|百科|原理|演进)"),
)

_ARCHIVE_DOMAINS: frozenset[str] = frozenset({
    "wikipedia.org",
    "wikimedia.org",
    "rfc-editor.org",
    "arxiv.org",
    "w3.org",
    "ietf.org",
    "archive.org",
})


class TimeSensitivityTtlAdvisor:
    """Evaluates query intent and URL domains to schedule scenario-adaptive TTLs."""

    def __init__(self, config: AdaptiveTtlConfig | None = None) -> None:
        self._config = config or AdaptiveTtlConfig()

    @property
    def config(self) -> AdaptiveTtlConfig:
        """Return the active adaptive TTL configuration."""
        return self._config

    def evaluate_query(
        self,
        query: str,
        explicit_scenario: TimeSensitivityScenario | str | None = None,
    ) -> tuple[TimeSensitivityScenario, int]:
        """Classify query intent and return (scenario, recommended_ttl_seconds)."""
        if explicit_scenario is not None:
            scenario = self._resolve_scenario(explicit_scenario)
            return scenario, self.get_ttl_for_scenario(scenario)

        cleaned = query.strip()
        # 1. Realtime check takes precedence (prevent stale stock/news hits)
        for pattern in _REALTIME_PATTERNS:
            if pattern.search(cleaned):
                return TimeSensitivityScenario.REALTIME, self._config.realtime_ttl_seconds

        # 2. Archive check for durable historical and specification content
        for pattern in _ARCHIVE_PATTERNS:
            if pattern.search(cleaned):
                return TimeSensitivityScenario.ARCHIVE, self._config.archive_ttl_seconds

        # 3. Standard fallback
        return TimeSensitivityScenario.STANDARD, self._config.standard_ttl_seconds

    def evaluate_url(
        self,
        url: str,
        explicit_scenario: TimeSensitivityScenario | str | None = None,
    ) -> tuple[TimeSensitivityScenario, int]:
        """Classify URL domain and path to return (scenario, recommended_ttl_seconds)."""
        if explicit_scenario is not None:
            scenario = self._resolve_scenario(explicit_scenario)
            return scenario, self.get_ttl_for_scenario(scenario)

        try:
            parsed = urlparse(url.strip())
            netloc = parsed.netloc.lower()
            path = parsed.path.lower()
        except Exception:
            return TimeSensitivityScenario.STANDARD, self._config.standard_ttl_seconds

        # 1. Check archive authority domains
        for domain in _ARCHIVE_DOMAINS:
            if netloc == domain or netloc.endswith("." + domain):
                return TimeSensitivityScenario.ARCHIVE, self._config.archive_ttl_seconds

        # 2. Check path keywords (e.g. /rfc/, /spec/, /docs/)
        if any(seg in path for seg in ("/rfc/", "/spec/", "/specs/", "/v1/historical/")):
            return TimeSensitivityScenario.ARCHIVE, self._config.archive_ttl_seconds

        # 3. Check realtime URL indicators (e.g. /quotes/, /live/, /stream/)
        if any(seg in path for seg in ("/quote/", "/quotes/", "/live/", "/tickers/")):
            return TimeSensitivityScenario.REALTIME, self._config.realtime_ttl_seconds

        return TimeSensitivityScenario.STANDARD, self._config.standard_ttl_seconds

    def get_ttl_for_scenario(self, scenario: TimeSensitivityScenario) -> int:
        """Retrieve configured TTL duration for a given scenario."""
        if scenario == TimeSensitivityScenario.REALTIME:
            return self._config.realtime_ttl_seconds
        if scenario == TimeSensitivityScenario.ARCHIVE:
            return self._config.archive_ttl_seconds
        return self._config.standard_ttl_seconds

    @staticmethod
    def _resolve_scenario(scenario: TimeSensitivityScenario | str) -> TimeSensitivityScenario:
        if isinstance(scenario, TimeSensitivityScenario):
            return scenario
        try:
            return TimeSensitivityScenario(str(scenario).lower().strip())
        except ValueError:
            return TimeSensitivityScenario.STANDARD
