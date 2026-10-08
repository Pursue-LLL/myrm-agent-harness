"""
[POS] src/myrm_agent_harness/core/security/browser_human_handoff/zero_content_watchdog.py
[INPUT] re, time, typing
[OUTPUT] ZeroContentDOMWatchdog

Zero-Content DOM Corruption Watchdog.
Detects stealthy browser whiteouts, anti-bot silent freezing, and 0-character DOM corruptions
where HTTP status is 200 but page content is entirely absent.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import re
import time

from .types import DOMContentHealthInspection

logger = logging.getLogger(__name__)


class ZeroContentDOMWatchdog:
    """Watchdog inspecting extracted DOM trees for deceptive 0-character corruptions and silent blank states."""

    STRIP_TAGS_REGEX: re.Pattern[str] = re.compile(r"<[^>]+>")
    TAG_COUNT_REGEX: re.Pattern[str] = re.compile(r"<[a-zA-Z0-9]+(?:\s|>|/)")

    def __init__(self, min_healthy_chars: int = 10, min_healthy_nodes: int = 3) -> None:
        self._min_healthy_chars = min_healthy_chars
        self._min_healthy_nodes = min_healthy_nodes

    def inspect_dom_health(self, html_or_dom: str, url: str = "") -> DOMContentHealthInspection:
        """Inspect visible text length and node count to catch empty DOM whiteouts."""
        now = time.time()
        normalized_url = url.strip().lower()

        # Legitimate blank pages
        if normalized_url in ("about:blank", "chrome://newtab", "edge://newtab"):
            return DOMContentHealthInspection(
                url=url,
                content_length=0,
                node_count=0,
                is_corrupted_zero_content=False,
                diagnosis="Intentional blank page target.",
                timestamp=now,
            )

        # Extract visible text by stripping tags
        visible_text = self.STRIP_TAGS_REGEX.sub(" ", html_or_dom).strip()
        visible_length = len(visible_text)
        tag_matches = self.TAG_COUNT_REGEX.findall(html_or_dom)
        node_count = len(tag_matches)

        if visible_length == 0:
            diagnosis = (
                f"Catastrophic 0-character DOM corruption detected on '{url or 'unknown'}'. "
                "Page returned markup without visible text, indicating stealth anti-bot freezing or silent whiteout."
            )
            logger.warning(diagnosis)
            return DOMContentHealthInspection(
                url=url,
                content_length=0,
                node_count=node_count,
                is_corrupted_zero_content=True,
                diagnosis=diagnosis,
                timestamp=now,
            )

        if visible_length < self._min_healthy_chars and node_count < self._min_healthy_nodes:
            diagnosis = (
                f"Degraded DOM content detected (chars={visible_length}, nodes={node_count}). "
                "Page appears stunted or incompletely hydrated."
            )
            logger.warning(diagnosis)
            return DOMContentHealthInspection(
                url=url,
                content_length=visible_length,
                node_count=node_count,
                is_corrupted_zero_content=True,
                diagnosis=diagnosis,
                timestamp=now,
            )

        return DOMContentHealthInspection(
            url=url,
            content_length=visible_length,
            node_count=node_count,
            is_corrupted_zero_content=False,
            diagnosis="DOM content healthy and adequately hydrated.",
            timestamp=now,
        )
