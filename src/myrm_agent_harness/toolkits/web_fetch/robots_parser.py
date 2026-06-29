"""Robots.txt parser for responsible deep_crawl operations.

Fetches and parses robots.txt to filter disallowed paths and
extract Crawl-Delay directives for rate limiting.

[INPUT]
- myrm_agent_harness.core.security.http.secure_fetch::secure_get (POS: SSRF-protected outbound HTTP)

[OUTPUT]
- RobotsParser: Async robots.txt fetcher and path filter

[POS]
Robots.txt compliance layer. Ensures deep_crawl respects site
rules, preventing IP bans and legal issues in production.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from myrm_agent_harness.core.security.http.secure_fetch import secure_get

logger = logging.getLogger(__name__)

_DISALLOW_RE = re.compile(r"^Disallow:\s*(.+)", re.IGNORECASE)
_ALLOW_RE = re.compile(r"^Allow:\s*(.+)", re.IGNORECASE)
_CRAWL_DELAY_RE = re.compile(r"^Crawl-Delay:\s*(\d+\.?\d*)", re.IGNORECASE)
_USER_AGENT_RE = re.compile(r"^User-Agent:\s*(.+)", re.IGNORECASE)
_SITEMAP_RE = re.compile(r"^Sitemap:\s*(.+)", re.IGNORECASE)


class RobotsRules:
    """Parsed robots.txt rules for a specific domain."""

    def __init__(
        self,
        disallowed: list[str],
        allowed: list[str],
        crawl_delay: float | None,
        sitemaps: list[str],
    ):
        self.disallowed = disallowed
        self.allowed = allowed
        self.crawl_delay = crawl_delay
        self.sitemaps = sitemaps

    def is_path_allowed(self, path: str) -> bool:
        """Check if a path is allowed by robots.txt rules.

        Allow rules take precedence over Disallow when both match.
        """
        for allow_pattern in self.allowed:
            if self._matches(path, allow_pattern):
                return True
        for disallow_pattern in self.disallowed:
            if self._matches(path, disallow_pattern):
                return False
        return True

    @staticmethod
    def _matches(path: str, pattern: str) -> bool:
        """Simple robots.txt pattern matching (prefix match with * wildcard)."""
        if not pattern:
            return False
        if pattern == "/":
            return True
        if "*" in pattern:
            parts = pattern.split("*")
            pos = 0
            for part in parts:
                if not part:
                    continue
                idx = path.find(part, pos)
                if idx == -1:
                    return False
                pos = idx + len(part)
            return True
        return path.startswith(pattern)


class RobotsParser:
    """Async robots.txt fetcher and parser."""

    def __init__(self, user_agent: str = "*"):
        self._user_agent = user_agent
        self._cache: dict[str, RobotsRules] = {}

    async def fetch_and_parse(self, base_url: str) -> RobotsRules:
        """Fetch and parse robots.txt for the given URL's domain.

        Returns cached result if already fetched. On failure, returns
        permissive rules (allow all) to avoid blocking crawl.
        """
        parsed = urlparse(base_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        if domain in self._cache:
            return self._cache[domain]

        robots_url = urljoin(domain, "/robots.txt")
        rules = await self._fetch_robots(robots_url)
        self._cache[domain] = rules
        return rules

    async def _fetch_robots(self, robots_url: str) -> RobotsRules:
        """Fetch robots.txt content and parse it."""
        try:
            response = await secure_get(robots_url, timeout=10.0)
            if response.status_code != 200:
                logger.info("robots.txt not found (HTTP %d): %s", response.status_code, robots_url)
                return RobotsRules([], [], None, [])
            return self._parse_content(response.text)
        except Exception as e:
            logger.warning("Failed to fetch robots.txt: %s — %s", robots_url, e)
            return RobotsRules([], [], None, [])

    def _parse_content(self, content: str) -> RobotsRules:
        """Parse robots.txt content into rules."""
        disallowed: list[str] = []
        allowed: list[str] = []
        crawl_delay: float | None = None
        sitemaps: list[str] = []
        in_relevant_section = False

        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            sitemap_match = _SITEMAP_RE.match(line)
            if sitemap_match:
                sitemaps.append(sitemap_match.group(1).strip())
                continue

            ua_match = _USER_AGENT_RE.match(line)
            if ua_match:
                agent = ua_match.group(1).strip().lower()
                in_relevant_section = agent == "*" or self._user_agent.lower() in agent
                continue

            if not in_relevant_section:
                continue

            disallow_match = _DISALLOW_RE.match(line)
            if disallow_match:
                path = disallow_match.group(1).strip()
                if path:
                    disallowed.append(path)
                continue

            allow_match = _ALLOW_RE.match(line)
            if allow_match:
                path = allow_match.group(1).strip()
                if path:
                    allowed.append(path)
                continue

            delay_match = _CRAWL_DELAY_RE.match(line)
            if delay_match:
                crawl_delay = float(delay_match.group(1))
                continue

        return RobotsRules(disallowed, allowed, crawl_delay, sitemaps)
