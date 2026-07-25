"""Bilibili search fast-path.

Direct search via Bilibili's public API, bypassing generic search engines.
Triggered by intent detection when user explicitly requests Bilibili search
(e.g., "搜B站上关于LLM的视频").

Returns structured results with play count, author, duration — data that
generic engines (Google, SearxNG) cannot provide for Bilibili content.

Scope limitation: This is one of only two platform-specific search fast-paths
(YouTube via SearxNG engine, Bilibili via direct API). Additional platforms
must use Skill/MCP — not toolkit built-ins.

[INPUT]
- web_search.common::SearchResult (POS: Unified search result dataclass)

[OUTPUT]
- search_bilibili: Async Bilibili keyword search returning SearchResult list or None

[POS]
Bilibili search fast-path. Returns structured SearchResult list via public API;
returns None on failure to trigger fallback to generic search engine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
import urllib.request

from myrm_agent_harness.toolkits.web_search.common import SearchResult

logger = logging.getLogger(__name__)

_SEARCH_API = "https://api.bilibili.com/x/web-interface/search/all/v2"
_REQUEST_TIMEOUT = 8
_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags (e.g., <em class="keyword">) from API response text."""
    return _HTML_TAG_RE.sub("", text)


def _format_play_count(count: int) -> str:
    if count >= 10000:
        return f"{count / 10000:.1f}万"
    return str(count)


async def search_bilibili(
    keyword: str,
    max_results: int = 10,
) -> list[SearchResult] | None:
    """Search Bilibili for videos matching keyword.

    Args:
        keyword: Search query string
        max_results: Maximum number of results to return (capped at 20, min 1)

    Returns:
        List of SearchResult on success, None on failure (triggers fallback).
    """
    if not keyword.strip():
        return None
    max_results = max(1, min(max_results, 20))

    def _do_search() -> list[SearchResult] | None:
        try:
            params = urllib.parse.urlencode({"keyword": keyword, "page": 1})
            url = f"{_SEARCH_API}?{params}"
            req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("code") != 0:
                logger.info("Bilibili search API returned code %s", data.get("code"))
                return None

            result_groups = (data.get("data") or {}).get("result", [])
            videos: list[dict] = []
            for group in result_groups:
                if group.get("result_type") == "video":
                    videos = group.get("data", [])
                    break

            if not videos:
                logger.info("Bilibili search returned 0 video results for: %s", keyword[:50])
                return None

            results: list[SearchResult] = []
            for v in videos[:max_results]:
                title = _strip_html(v.get("title", ""))
                author = v.get("author", "")
                play = v.get("play", 0)
                duration = v.get("duration", "")
                bvid = v.get("bvid", "")
                description = v.get("description", "")

                link = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
                snippet_parts = []
                if author:
                    snippet_parts.append(f"UP主: {author}")
                if play:
                    snippet_parts.append(f"播放: {_format_play_count(play)}")
                if duration:
                    snippet_parts.append(f"时长: {duration}")
                if description and description != "-":
                    snippet_parts.append(description[:100])

                results.append(
                    SearchResult(
                        title=title,
                        link=link,
                        snippet=" | ".join(snippet_parts) if snippet_parts else title,
                    )
                )

            logger.info("Bilibili search success: keyword=%s results=%d", keyword[:30], len(results))
            return results

        except Exception as exc:
            logger.warning("Bilibili search failed for '%s': %s", keyword[:30], exc)
            return None

    return await asyncio.to_thread(_do_search)
